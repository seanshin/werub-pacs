"""Reading Statistics API — radiologist performance and TAT analytics."""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports/statistics", tags=["판독 통계"])


@router.get("", summary="판독 통계 조회")
async def get_reading_statistics(
    from_date: str = Query(None, description="시작일 (YYYY-MM-DD)"),
    to_date: str = Query(None, description="종료일 (YYYY-MM-DD)"),
    group_by: str = Query("daily", description="그룹 기준 (daily|weekly|monthly|reader)"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """판독 통계를 조회합니다.

    - 판독의별 판독 건수
    - 일/주/월별 추이
    - 평균 TAT (Turn Around Time)
    - 모달리티별 분포
    """
    now = datetime.now(timezone.utc)
    if not from_date:
        from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = now.strftime("%Y-%m-%d")
    # date 객체 바인딩 — text()의 :param::date 캐스트는 SQLAlchemy가 오파싱($1:date)해 구문오류.
    from_d = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_d_excl = datetime.strptime(to_date, "%Y-%m-%d").date() + timedelta(days=1)

    stats = {}

    # Total counts
    result = await db.execute(text("""
        SELECT
            count(*) as total,
            count(CASE WHEN signed_at IS NOT NULL THEN 1 END) as signed,
            count(CASE WHEN signed_at IS NULL THEN 1 END) as pending
        FROM reports
        WHERE created_at >= :from_date AND created_at < :to_date_excl
    """), {"from_date": from_d, "to_date_excl": to_d_excl})
    row = result.mappings().first()
    stats["summary"] = dict(row) if row else {"total": 0, "signed": 0, "pending": 0}

    # By reader
    result = await db.execute(text("""
        SELECT author_name as reader, count(*) as count,
            count(CASE WHEN signed_at IS NOT NULL THEN 1 END) as signed
        FROM reports
        WHERE created_at >= :from_date AND created_at < :to_date_excl
        GROUP BY author_name
        ORDER BY count DESC
    """), {"from_date": from_d, "to_date_excl": to_d_excl})
    stats["by_reader"] = [dict(r._mapping) for r in result]

    # Daily trend
    result = await db.execute(text("""
        SELECT DATE(created_at) as date, count(*) as count
        FROM reports
        WHERE created_at >= :from_date AND created_at < :to_date_excl
        GROUP BY DATE(created_at)
        ORDER BY date
    """), {"from_date": from_d, "to_date_excl": to_d_excl})
    stats["daily_trend"] = [{"date": str(r._mapping["date"]), "count": r._mapping["count"]} for r in result]

    # By modality (from study_instance_uid → Orthanc lookup would be expensive, use report data)
    result = await db.execute(text("""
        SELECT urgency, count(*) as count
        FROM reports
        WHERE created_at >= :from_date AND created_at < :to_date_excl
        GROUP BY urgency
    """), {"from_date": from_d, "to_date_excl": to_d_excl})
    stats["by_urgency"] = [dict(r._mapping) for r in result]

    stats["period"] = {"from": from_date, "to": to_date}

    return stats


@router.get("/tat", summary="판독 소요시간 (TAT) 분석")
async def get_tat_analysis(
    days: int = Query(30, le=365, description="분석 기간 (일)"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """판독 소요시간 (Turn Around Time) 상세 분석.

    - 판독의별 평균/중앙/최대 TAT
    - 모달리티별 평균 TAT
    - 시간대별 판독 분포
    - 일별 평균 TAT 트렌드
    """
    now = datetime.now(timezone.utc)
    from_dt = (now - timedelta(days=days)).date()

    result = {}

    # Overall TAT (created_at → signed_at)
    row = await db.execute(text("""
        SELECT
            COUNT(*) as total_signed,
            ROUND(AVG(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as avg_min,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as median_min,
            ROUND(MAX(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as max_min,
            ROUND(MIN(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as min_min,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as p95_min
        FROM reports
        WHERE signed_at IS NOT NULL AND created_at >= :from_dt
    """), {"from_dt": from_dt})
    r = row.mappings().first()
    result["overall"] = dict(r) if r else {}

    # By reader
    rows = await db.execute(text("""
        SELECT
            COALESCE(signed_by_name, author_name) as reader,
            COUNT(*) as count,
            ROUND(AVG(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as avg_min,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as median_min,
            ROUND(MAX(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as max_min
        FROM reports
        WHERE signed_at IS NOT NULL AND created_at >= :from_dt
        GROUP BY COALESCE(signed_by_name, author_name)
        ORDER BY count DESC
    """), {"from_dt": from_dt})
    result["by_reader"] = [dict(r._mapping) for r in rows]

    # By modality (approximate from study_description)
    rows = await db.execute(text("""
        SELECT
            CASE
                WHEN modality IS NOT NULL AND modality != '' THEN modality
                WHEN study_description ILIKE '%CT%' THEN 'CT'
                WHEN study_description ILIKE '%MR%' OR study_description ILIKE '%MRI%' THEN 'MR'
                WHEN study_description ILIKE '%CR%' OR study_description ILIKE '%X-ray%' THEN 'CR'
                WHEN study_description ILIKE '%US%' OR study_description ILIKE '%Ultrasound%' THEN 'US'
                ELSE 'Other'
            END as modality,
            COUNT(*) as count,
            ROUND(AVG(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as avg_min
        FROM reports
        WHERE signed_at IS NOT NULL AND created_at >= :from_dt
        GROUP BY 1
        ORDER BY count DESC
    """), {"from_dt": from_dt})
    result["by_modality"] = [dict(r._mapping) for r in rows]

    # Hourly distribution (which hours are reports signed)
    rows = await db.execute(text("""
        SELECT
            EXTRACT(HOUR FROM signed_at AT TIME ZONE 'Asia/Seoul') as hour,
            COUNT(*) as count
        FROM reports
        WHERE signed_at IS NOT NULL AND created_at >= :from_dt
        GROUP BY 1
        ORDER BY 1
    """), {"from_dt": from_dt})
    result["hourly_distribution"] = [{"hour": int(r._mapping["hour"]), "count": r._mapping["count"]} for r in rows]

    # Daily average TAT trend
    rows = await db.execute(text("""
        SELECT
            DATE(signed_at) as date,
            COUNT(*) as count,
            ROUND(AVG(EXTRACT(EPOCH FROM (signed_at - created_at)) / 60)) as avg_min
        FROM reports
        WHERE signed_at IS NOT NULL AND created_at >= :from_dt
        GROUP BY DATE(signed_at)
        ORDER BY date
    """), {"from_dt": from_dt})
    result["daily_trend"] = [{"date": str(r._mapping["date"]), "count": r._mapping["count"], "avg_min": r._mapping["avg_min"]} for r in rows]

    result["period_days"] = days

    return result


@router.get("/residents", summary="레지던트(예비판독) 성과 통계")
async def get_resident_performance(
    days: int = Query(90, le=365, description="분석 기간 (일)"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """레지던트 예비판독 성과 분석.

    예비판독(resident → attending)을 수행한 리포트를 대상으로:
    - 예비판독 건수 / 전문의 최종확정 건수 / 대기 건수
    - 전문의 최종 **수정률** (preliminary_content 원본 vs 최종 findings/impression 텍스트 차이로 근사)
    - **일치율** (최종본에서 결론(impression)이 바뀌지 않은 비율)
    - 평균 예비판독 소요시간 (created_at → preliminary_at)

    NOTE: report_status_enum 은 DB에 **대문자**(FINAL/PRELIMINARY)로 저장됨.
    """
    now = datetime.now(timezone.utc)
    from_dt = (now - timedelta(days=days)).date()

    result: dict = {"period_days": days}

    rows = await db.execute(text("""
        SELECT
            preliminary_by_name AS resident,
            COUNT(*) AS preliminary_count,
            COUNT(*) FILTER (WHERE status = 'FINAL') AS finalized_count,
            COUNT(*) FILTER (WHERE status = 'PRELIMINARY') AS pending_count,
            COUNT(*) FILTER (
                WHERE status = 'FINAL'
                AND btrim(COALESCE(preliminary_content->>'impression','')) IS DISTINCT FROM btrim(COALESCE(impression,''))
            ) AS impression_changed,
            COUNT(*) FILTER (
                WHERE status = 'FINAL'
                AND btrim(COALESCE(preliminary_content->>'findings','')) IS DISTINCT FROM btrim(COALESCE(findings,''))
            ) AS findings_changed,
            ROUND(AVG(EXTRACT(EPOCH FROM (preliminary_at - created_at)) / 60)
                  FILTER (WHERE preliminary_at IS NOT NULL)) AS avg_prelim_min
        FROM reports
        WHERE preliminary_by_id IS NOT NULL
          AND created_at >= :from_dt
        GROUP BY preliminary_by_name
        ORDER BY preliminary_count DESC
    """), {"from_dt": from_dt})

    residents = []
    for r in rows:
        d = dict(r._mapping)
        fin = d.get("finalized_count") or 0
        ic = d.get("impression_changed") or 0
        d["correction_rate"] = round(100 * ic / fin) if fin else None
        d["agreement_rate"] = round(100 * (1 - ic / fin)) if fin else None
        residents.append(d)
    result["by_resident"] = residents

    total_prelim = sum(d["preliminary_count"] for d in residents)
    total_fin = sum((d["finalized_count"] or 0) for d in residents)
    total_ic = sum((d["impression_changed"] or 0) for d in residents)
    result["summary"] = {
        "resident_count": len(residents),
        "preliminary_count": total_prelim,
        "finalized_count": total_fin,
        "avg_correction_rate": round(100 * total_ic / total_fin) if total_fin else None,
        "avg_agreement_rate": round(100 * (1 - total_ic / total_fin)) if total_fin else None,
    }
    return result
