"""Monthly BI auto-report (bi-report feature, increment #1).

매월 1일 06:00(KST) beat가 직전 달치 운영 BI를 집계 → bi_monthly_reports에
이력 저장(idempotent upsert) → admin 알림. 관리자 즉시 생성도 지원(run-monthly).

수신=study_provenance(전체·미판독 포함), 판독/TAT=reports. reports.signed_at IS NOT NULL
이 완료 판정(enum NAME 함정 회피). 동기 엔진은 캐싱(_get_sync_db, 연결 누수 방지).

★기간 경계는 반드시 기관 로컬시간(settings.timezone)으로 계산한다. celery beat는
KST 06:00에 뜨지만 앱의 DB 세션 TimeZone은 UTC라, SQL의 CURRENT_DATE/date_trunc에
맡기면 KST 00~09시 실행분이 UTC 전날로 평가되어 **직전 달이 한 달 더 밀린다**
(라이브 실측: 2026-08-01 실행분이 7월이 아닌 6월치를 생성). 경계를 파이썬에서
tz-aware datetime으로 만들어 bind 파라미터로 넘겨 세션 TZ 의존을 제거.
"""
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app
from app.services.dicom_auto_validate import _get_sync_db

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS bi_monthly_reports (
    id UUID PRIMARY KEY,
    period_month DATE NOT NULL UNIQUE,
    received INT NOT NULL DEFAULT 0,
    reported INT NOT NULL DEFAULT 0,
    read_done INT NOT NULL DEFAULT 0,
    avg_tat_h NUMERIC,
    p90_tat_h NUMERIC,
    modality_breakdown JSONB,
    origin_breakdown JSONB,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _local_tz() -> ZoneInfo:
    """기관 로컬 타임존. 잘못된 설정값이 월간 집계를 조용히 UTC로 되돌리지 않도록
    폴백 시 경고를 남긴다."""
    try:
        return ZoneInfo(settings.timezone)
    except Exception:
        logger.warning("invalid settings.timezone=%r — falling back to Asia/Seoul",
                       settings.timezone)
        return ZoneInfo("Asia/Seoul")


def month_bounds(period: date) -> tuple[datetime, datetime]:
    """period(그 달의 임의 날짜) → 로컬시각 기준 [해당 월 1일 00:00, 다음 달 1일 00:00).
    반환은 tz-aware라 timestamptz 컬럼과 직접 비교해도 세션 TZ에 영향받지 않는다."""
    tz = _local_tz()
    start = datetime(period.year, period.month, 1, tzinfo=tz)
    nxt_y, nxt_m = (period.year + 1, 1) if period.month == 12 else (period.year, period.month + 1)
    return start, datetime(nxt_y, nxt_m, 1, tzinfo=tz)


def previous_month(now: datetime | None = None) -> date:
    """로컬 '지금' 기준 직전 달의 1일. now 미지정 시 로컬 현재시각."""
    tz = _local_tz()
    local_now = (now or datetime.now(tz)).astimezone(tz)
    return (local_now.date().replace(day=1) - timedelta(days=1)).replace(day=1)


def _compute(db, start: datetime, end: datetime) -> dict:
    """start/end: tz-aware datetime으로 [start, end) 구간을 한정."""
    bounds = {"start": start, "end": end}

    recv = db.execute(text("""
        SELECT count(*) AS received,
               count(*) FILTER (WHERE r.study_instance_uid IS NOT NULL) AS reported,
               count(*) FILTER (WHERE r.signed_at IS NOT NULL) AS read_done
        FROM study_provenance sp
        LEFT JOIN reports r ON r.study_instance_uid = sp.study_instance_uid
        WHERE sp.received_at >= :start AND sp.received_at < :end
    """), bounds).mappings().first()

    tat = db.execute(text("""
        SELECT round(avg(EXTRACT(EPOCH FROM (signed_at - created_at)) / 3600.0)::numeric, 1) AS avg_tat_h,
               round((percentile_cont(0.9) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (signed_at - created_at)) / 3600.0))::numeric, 1) AS p90_tat_h
        FROM reports
        WHERE signed_at >= :start AND signed_at < :end
    """), bounds).mappings().first()

    modality = db.execute(text("""
        SELECT COALESCE(NULLIF(modality, ''), '미상') AS modality, count(*) AS n
        FROM reports WHERE created_at >= :start AND created_at < :end
        GROUP BY 1 ORDER BY 2 DESC
    """), bounds).mappings().all()

    origin = db.execute(text("""
        SELECT origin, count(*) AS n
        FROM study_provenance WHERE received_at >= :start AND received_at < :end
        GROUP BY 1 ORDER BY 2 DESC
    """), bounds).mappings().all()

    return {
        "received": recv["received"] or 0,
        "reported": recv["reported"] or 0,
        "read_done": recv["read_done"] or 0,
        "avg_tat_h": float(tat["avg_tat_h"]) if tat["avg_tat_h"] is not None else None,
        "p90_tat_h": float(tat["p90_tat_h"]) if tat["p90_tat_h"] is not None else None,
        "modality_breakdown": {m["modality"]: m["n"] for m in modality},
        "origin_breakdown": {o["origin"]: o["n"] for o in origin},
    }


def _notify_admin(db, title: str, msg: str):
    db.execute(text("""
        INSERT INTO notifications (id, type, title, message, urgency, target_role,
            study_instance_uid, action_url, is_read, acknowledged, created_at)
        VALUES (:id, 'bi_monthly', :title, :msg, 'normal', 'admin', NULL,
                '/pacs-admin/bi', false, false, NOW())
    """), {"id": str(uuid.uuid4()), "title": title, "msg": msg})


@celery_app.task(name="app.services.bi_report.monthly_bi_report",
                 bind=True, max_retries=1)
def monthly_bi_report(self, period: str | None = None):
    """직전 달 운영 BI 집계 → 이력 저장 → admin 알림.

    period: "YYYY-MM" 지정 시 그 달을 재집계(백필/재생성). 미지정=직전 달.
    """
    db = _get_sync_db()
    try:
        db.execute(text(_DDL))
        db.commit()

        # 직전 달 경계 [전월1일 00:00 KST, 당월1일 00:00 KST)
        if period:
            try:
                y, m = period.split("-")
                target = date(int(y), int(m), 1)
            except (ValueError, AttributeError):
                raise ValueError(f"period must be 'YYYY-MM', got {period!r}")
        else:
            target = previous_month()
        start, end = month_bounds(target)
        data = _compute(db, start, end)
        period_month = target

        db.execute(text("""
            INSERT INTO bi_monthly_reports (id, period_month, received, reported, read_done,
                avg_tat_h, p90_tat_h, modality_breakdown, origin_breakdown, generated_at)
            VALUES (:id, :period, :received, :reported, :read_done, :avg, :p90,
                    CAST(:mod AS jsonb), CAST(:org AS jsonb), NOW())
            ON CONFLICT (period_month) DO UPDATE SET
                received = EXCLUDED.received, reported = EXCLUDED.reported,
                read_done = EXCLUDED.read_done, avg_tat_h = EXCLUDED.avg_tat_h,
                p90_tat_h = EXCLUDED.p90_tat_h, modality_breakdown = EXCLUDED.modality_breakdown,
                origin_breakdown = EXCLUDED.origin_breakdown, generated_at = NOW()
        """), {
            "id": str(uuid.uuid4()), "period": period_month,
            "received": data["received"], "reported": data["reported"],
            "read_done": data["read_done"], "avg": data["avg_tat_h"], "p90": data["p90_tat_h"],
            "mod": json.dumps(data["modality_breakdown"], ensure_ascii=False),
            "org": json.dumps(data["origin_breakdown"], ensure_ascii=False),
        })
        db.commit()

        ym = period_month.strftime("%Y년 %m월")
        unread = data["received"] - data["read_done"]
        rate = (data["read_done"] / data["received"] * 100) if data["received"] else 0
        tat = f"{data['avg_tat_h']}시간" if data["avg_tat_h"] is not None else "—"
        msg = (f"{ym} 운영 요약 — 수신 {data['received']}건 · 판독완료 {data['read_done']}건"
               f"(판독률 {rate:.0f}%) · 미판독 {unread}건 · 평균 TAT {tat}. "
               f"상세는 경영BI에서 확인하세요.")
        _notify_admin(db, f"{ym} 월간 BI 리포트", msg)
        db.commit()
        logger.info("monthly_bi_report generated for %s [%s, %s): %s",
                    period_month, start, end, data)
        return {"period": str(period_month), "window_start": start.isoformat(),
                "window_end": end.isoformat(), **data}
    except Exception as e:
        db.rollback()
        logger.exception("monthly_bi_report failed: %s", e)
        raise
    finally:
        db.close()
