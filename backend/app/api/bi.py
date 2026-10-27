"""Operational BI API (bi-report feature).

경영/운영 BI — 판독 운영 지표 + 수신(접수) 검사량.
- 판독 관점(reports): KPI·모달리티·판독의 생산성. 완료=signed_at IS NOT NULL(enum 무관).
- 수신 관점(study_provenance): 전체 접수량(미판독 포함)·유입 경로·판독률 격차.
단일 호출(operational)로 대시보드 한 화면 분량을 반환. 월간 이력은 monthly-history.
"""
import csv
import io
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bi", tags=["경영/운영 BI"])

_TAT_H = "EXTRACT(EPOCH FROM (signed_at - created_at)) / 3600.0"

ORIGIN_LABEL = {
    "internal": "원내", "external": "전원", "patient_upload": "환자업로드",
    "kiosk": "키오스크", "test_data": "테스트", "ai_generated": "AI생성",
    "research": "연구", "migration": "이관", "unknown": "미상",
}


async def _aggregate(db: AsyncSession, days: int, months: int) -> dict:
    # 판독 KPI 요약 (reports)
    summary = (await db.execute(text(f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE signed_at IS NOT NULL) AS completed,
               count(DISTINCT signed_by_name) FILTER (WHERE signed_at IS NOT NULL) AS readers,
               count(*) FILTER (WHERE urgency = 'urgent') AS urgent,
               round(avg({_TAT_H}) FILTER (WHERE signed_at IS NOT NULL)::numeric, 1) AS avg_tat_h,
               round((percentile_cont(0.9) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (signed_at - created_at)) / 3600.0)
                   FILTER (WHERE signed_at IS NOT NULL))::numeric, 1) AS p90_tat_h
        FROM reports WHERE created_at > now() - make_interval(days => :d)
    """), {"d": days})).mappings().first()
    total = summary["total"] or 0
    completed = summary["completed"] or 0

    # 수신(접수) 요약 — 전체 study(미판독 포함) vs 판독 격차 (study_provenance ⟕ reports)
    recv = (await db.execute(text("""
        SELECT count(*) AS received,
               count(*) FILTER (WHERE r.study_instance_uid IS NOT NULL) AS reported,
               count(*) FILTER (WHERE r.signed_at IS NOT NULL) AS read_done
        FROM study_provenance sp
        LEFT JOIN reports r ON r.study_instance_uid = sp.study_instance_uid
        WHERE sp.received_at > now() - make_interval(days => :d)
    """), {"d": days})).mappings().first()
    received = recv["received"] or 0
    read_done = recv["read_done"] or 0

    # 월별 수신량 추이 (수신 기준 + 판독완료 오버레이)
    # ★월 버킷은 기관 로컬시간 기준. DB 세션 TZ가 UTC라 date_trunc에 timestamptz를
    # 그대로 넘기면 KST 00~09시 수신분이 전월로 밀린다(월간 리포트와 동일 결함).
    trend = (await db.execute(text("""
        SELECT to_char(date_trunc('month', sp.received_at AT TIME ZONE :tz), 'YYYY-MM') AS month,
               count(*) AS received,
               count(*) FILTER (WHERE r.signed_at IS NOT NULL) AS completed
        FROM study_provenance sp
        LEFT JOIN reports r ON r.study_instance_uid = sp.study_instance_uid
        WHERE sp.received_at > now() - make_interval(months => :m)
        GROUP BY 1 ORDER BY 1
    """), {"m": months, "tz": settings.timezone})).mappings().all()

    # 유입 경로별 (origin)
    origins = (await db.execute(text("""
        SELECT origin, count(*) AS count
        FROM study_provenance WHERE received_at > now() - make_interval(days => :d)
        GROUP BY 1 ORDER BY 2 DESC
    """), {"d": days})).mappings().all()

    # 모달리티 가동률 (판독 기준)
    modality = (await db.execute(text(f"""
        SELECT COALESCE(NULLIF(modality, ''), '미상') AS modality,
               count(*) AS total,
               count(*) FILTER (WHERE signed_at IS NOT NULL) AS completed,
               round(avg({_TAT_H}) FILTER (WHERE signed_at IS NOT NULL)::numeric, 1) AS avg_tat_h
        FROM reports WHERE created_at > now() - make_interval(days => :d)
        GROUP BY 1 ORDER BY total DESC
    """), {"d": days})).mappings().all()

    # 판독의 생산성 (서명 기준)
    readers = (await db.execute(text(f"""
        SELECT COALESCE(signed_by_name, '미상') AS reader,
               count(*) AS signed,
               round(avg({_TAT_H})::numeric, 1) AS avg_tat_h
        FROM reports
        WHERE signed_at IS NOT NULL AND signed_at > now() - make_interval(days => :d)
        GROUP BY 1 ORDER BY signed DESC LIMIT 20
    """), {"d": days})).mappings().all()

    return {
        "period_days": days, "trend_months": months,
        "summary": {
            "total": total, "completed": completed,
            "completion_rate": round(completed / total, 3) if total else None,
            "readers": summary["readers"] or 0,
            "urgent": summary["urgent"] or 0,
            "avg_tat_h": float(summary["avg_tat_h"]) if summary["avg_tat_h"] is not None else None,
            "p90_tat_h": float(summary["p90_tat_h"]) if summary["p90_tat_h"] is not None else None,
        },
        "reception": {
            "received": received,
            "reported": recv["reported"] or 0,
            "read_done": read_done,
            "unread": received - read_done,
            "read_rate": round(read_done / received, 3) if received else None,
            "by_origin": [dict(r) for r in origins],
        },
        "volume_trend": [dict(r) for r in trend],
        "modality": [dict(r) for r in modality],
        "readers": [dict(r) for r in readers],
    }


@router.get("/operational", summary="운영 BI 대시보드 (판독 KPI·수신량·모달리티·판독의)")
async def operational_bi(
    db: Annotated[AsyncSession, Depends(get_db)],
    # 경영/운영 BI는 관리 데이터 — 응급 임상열람(BTG) 대상 아님(S10)
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
    days: int = Query(30, ge=1, le=365, description="KPI·모달리티·판독의·경로 기간(일)"),
    months: int = Query(6, ge=1, le=24, description="추이 기간(월)"),
):
    return await _aggregate(db, days, months)


@router.get("/export", summary="운영 BI CSV 내보내기 (경영진 배포용)")
async def export_bi(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
    days: int = Query(90, ge=1, le=365),
    months: int = Query(12, ge=1, le=24),
):
    d = await _aggregate(db, days, months)
    s, rc = d["summary"], d["reception"]
    buf = io.StringIO()
    w = csv.writer(buf)

    def rate(n, total):
        return f"{n / total * 100:.0f}%" if total else "—"

    w.writerow([f"OpenPACS 운영 BI 리포트 (최근 {days}일, 추이 {months}개월)"])
    w.writerow([])
    w.writerow(["[수신 요약]"])
    w.writerow(["수신검사", "판독완료", "미판독", "판독률"])
    w.writerow([rc["received"], rc["read_done"], rc["unread"],
                rate(rc["read_done"], rc["received"])])
    w.writerow([])
    w.writerow(["[판독 KPI]"])
    w.writerow(["총판독", "완료", "완료율", "평균TAT(시간)", "P90TAT(시간)", "활성판독의", "긴급"])
    w.writerow([s["total"], s["completed"],
                rate(s["completed"], s["total"]),
                s["avg_tat_h"] if s["avg_tat_h"] is not None else "—",
                s["p90_tat_h"] if s["p90_tat_h"] is not None else "—",
                s["readers"], s["urgent"]])
    w.writerow([])
    w.writerow(["[월별 수신량 추이]"])
    w.writerow(["월", "수신", "판독완료"])
    for t in d["volume_trend"]:
        w.writerow([t["month"], t["received"], t["completed"]])
    w.writerow([])
    w.writerow(["[유입 경로별]"])
    w.writerow(["경로", "건수"])
    for o in rc["by_origin"]:
        w.writerow([ORIGIN_LABEL.get(o["origin"], o["origin"]), o["count"]])
    w.writerow([])
    w.writerow(["[모달리티별 판독]"])
    w.writerow(["모달리티", "판독건수", "완료", "평균TAT(시간)"])
    for m in d["modality"]:
        w.writerow([m["modality"], m["total"], m["completed"],
                    m["avg_tat_h"] if m["avg_tat_h"] is not None else "—"])
    w.writerow([])
    w.writerow(["[판독의 생산성]"])
    w.writerow(["판독의", "서명건수", "평균TAT(시간)"])
    for r in d["readers"]:
        w.writerow([r["reader"], r["signed"],
                    r["avg_tat_h"] if r["avg_tat_h"] is not None else "—"])

    # UTF-8 BOM → Excel 한글 정상 표시
    content = "﻿" + buf.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="openpacs-bi-report.csv"'},
    )


@router.get("/monthly-history", summary="월간 자동 리포트 이력")
async def monthly_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    limit: int = Query(12, ge=1, le=60),
):
    # 테이블 부재(월간 작업 미실행) 시 빈 목록
    exists = (await db.execute(text(
        "SELECT to_regclass('public.bi_monthly_reports') IS NOT NULL"
    ))).scalar()
    if not exists:
        return {"reports": []}
    rows = (await db.execute(text("""
        SELECT to_char(period_month, 'YYYY-MM') AS month, received, reported, read_done,
               avg_tat_h, p90_tat_h, modality_breakdown, origin_breakdown,
               generated_at
        FROM bi_monthly_reports ORDER BY period_month DESC LIMIT :l
    """), {"l": limit})).mappings().all()
    return {"reports": [dict(r) for r in rows]}


@router.post("/run-monthly", summary="월간 리포트 즉시 생성(관리자)")
async def run_monthly(
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$",
                               description="YYYY-MM 지정 시 해당 월 재집계(백필). 미지정=직전 달"),
):
    from app.services.bi_report import monthly_bi_report
    monthly_bi_report.delay(period=period)
    target = period or "직전 달"
    return {"status": "queued", "period": period,
            "message": f"월간 BI 리포트({target}) 생성을 큐에 등록했습니다."}
