"""팔로업 추적 API — 판독 후 추적 관찰 일정 관리.

판독의가 '3개월 후 추적' 등을 권고할 때 이를 체계적으로 추적하고,
미이행 건에 대한 알림 및 워크리스트 자동 생성을 지원합니다.
"""
import logging
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/followups", tags=["팔로업 추적"])


# ── 요청/응답 스키마 ──────────────────────────────────────────────────────────

class FollowupCreate(BaseModel):
    """팔로업 생성 요청."""
    report_id: str | None = None
    patient_id: str
    study_instance_uid: str | None = None
    recommended_date: date
    reason: str
    category: str | None = None


class FollowupComplete(BaseModel):
    """팔로업 완료 처리 요청."""
    completed_study_uid: str


class WorklistItemCreate(BaseModel):
    """워크리스트 항목 생성 옵션."""
    modality: str = "CT"
    scheduled_station_ae_title: str = Field(default_factory=lambda: settings.orthanc_aet)
    scheduled_procedure_step_description: str | None = None


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, summary="팔로업 생성")
async def create_followup(
    body: FollowupCreate,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
    db: AsyncSession = Depends(get_db),
):
    """판독 보고서에 기반한 팔로업 추적 항목을 생성합니다.

    - report_id: 연관 판독 보고서 ID (선택)
    - recommended_date: 추적 검사 권고일
    - category: 스키마 카테고리 (예: BI-RADS 3, Lung-RADS 4A)
    """
    followup_id = str(uuid4())
    await db.execute(text("""
        INSERT INTO followups (id, report_id, patient_id, study_instance_uid,
                               recommended_date, reason, category, status, created_by)
        VALUES (:id, :report_id, :patient_id, :study_uid,
                :rec_date, :reason, :category, 'pending', :created_by)
    """), {
        "id": followup_id,
        "report_id": body.report_id,
        "patient_id": body.patient_id,
        "study_uid": body.study_instance_uid,
        "rec_date": body.recommended_date,
        "reason": body.reason,
        "category": body.category,
        "created_by": user.username,
    })
    await db.commit()

    logger.info("팔로업 생성: %s (환자: %s, 권고일: %s)", followup_id, body.patient_id, body.recommended_date)
    return {"id": followup_id, "status": "pending", "message": "팔로업이 생성되었습니다"}


@router.get("", summary="팔로업 목록 조회")
async def list_followups(
    status_filter: str = Query(None, alias="status", description="상태 필터 (pending/overdue/completed)"),
    patient_id: str = Query(None, description="환자 ID 필터"),
    from_date: str = Query(None, description="권고일 시작 (YYYY-MM-DD)"),
    to_date: str = Query(None, description="권고일 종료 (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
    db: AsyncSession = Depends(get_db),
):
    """팔로업 목록을 필터 조건에 따라 조회합니다.

    - status=overdue: 권고일이 지났으나 미완료인 건
    - status=pending: 아직 권고일이 도래하지 않은 건
    - status=completed: 완료 처리된 건
    """
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if status_filter == "overdue":
        conditions.append("f.status = 'pending' AND f.recommended_date < CURRENT_DATE")
    elif status_filter:
        conditions.append("f.status = :status")
        params["status"] = status_filter

    if patient_id:
        conditions.append("f.patient_id = :patient_id")
        params["patient_id"] = patient_id

    # date 객체 바인딩 — recommended_date는 DATE 컬럼, str 바인딩은 asyncpg DataError.
    if from_date:
        conditions.append("f.recommended_date >= :from_date")
        params["from_date"] = datetime.strptime(from_date, "%Y-%m-%d").date()

    if to_date:
        conditions.append("f.recommended_date <= :to_date")
        params["to_date"] = datetime.strptime(to_date, "%Y-%m-%d").date()

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    # 총 건수
    count_result = await db.execute(
        text(f"SELECT count(*) FROM followups f {where}"), params
    )
    total = count_result.scalar() or 0

    # 목록 조회
    result = await db.execute(text(f"""
        SELECT f.id, f.report_id, f.patient_id, f.study_instance_uid,
               f.recommended_date, f.reason, f.category, f.status,
               f.completed_study_uid, f.notified_at, f.created_by, f.created_at,
               CASE WHEN f.status = 'pending' AND f.recommended_date < CURRENT_DATE
                    THEN true ELSE false END as is_overdue
        FROM followups f
        {where}
        ORDER BY f.recommended_date ASC
        LIMIT :limit OFFSET :offset
    """), params)

    rows = [dict(r._mapping) for r in result]
    for row in rows:
        if row.get("recommended_date"):
            row["recommended_date"] = str(row["recommended_date"])
        if row.get("created_at"):
            row["created_at"] = row["created_at"].isoformat()
        if row.get("notified_at"):
            row["notified_at"] = row["notified_at"].isoformat()

    return {"total": total, "items": rows}


@router.put("/{followup_id}/complete", summary="팔로업 완료 처리")
async def complete_followup(
    followup_id: str,
    body: FollowupComplete,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
    db: AsyncSession = Depends(get_db),
):
    """팔로업을 완료 처리하고 완료된 검사의 Study UID를 연결합니다."""
    result = await db.execute(
        text("SELECT id, status FROM followups WHERE id = :id"),
        {"id": followup_id},
    )
    row = result.first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="팔로업을 찾을 수 없습니다")
    if row._mapping["status"] == "completed":
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="이미 완료 처리된 팔로업입니다")

    await db.execute(text("""
        UPDATE followups
        SET status = 'completed', completed_study_uid = :study_uid
        WHERE id = :id
    """), {"id": followup_id, "study_uid": body.completed_study_uid})
    await db.commit()

    logger.info("팔로업 완료: %s → Study %s", followup_id, body.completed_study_uid)
    return {"id": followup_id, "status": "completed", "message": "팔로업이 완료 처리되었습니다"}


@router.get("/overdue-report", summary="미이행 팔로업 보고서")
async def overdue_report(
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
    db: AsyncSession = Depends(get_db),
):
    """기한이 지난 팔로업의 요약 보고서를 반환합니다.

    - 전체 미이행 건수
    - 카테고리별 분포
    - 지연 기간별 분포 (1주 이내, 1-4주, 1-3개월, 3개월 초과)
    """
    # 전체 미이행 건수
    total_result = await db.execute(text("""
        SELECT count(*) FROM followups
        WHERE status = 'pending' AND recommended_date < CURRENT_DATE
    """))
    total_overdue = total_result.scalar() or 0

    # 카테고리별 분포
    cat_result = await db.execute(text("""
        SELECT COALESCE(category, '미분류') as category, count(*) as count
        FROM followups
        WHERE status = 'pending' AND recommended_date < CURRENT_DATE
        GROUP BY category
        ORDER BY count DESC
    """))
    by_category = [dict(r._mapping) for r in cat_result]

    # 지연 기간별 분포
    delay_result = await db.execute(text("""
        SELECT
            count(CASE WHEN CURRENT_DATE - recommended_date <= 7 THEN 1 END) as within_1w,
            count(CASE WHEN CURRENT_DATE - recommended_date BETWEEN 8 AND 28 THEN 1 END) as within_1m,
            count(CASE WHEN CURRENT_DATE - recommended_date BETWEEN 29 AND 90 THEN 1 END) as within_3m,
            count(CASE WHEN CURRENT_DATE - recommended_date > 90 THEN 1 END) as over_3m
        FROM followups
        WHERE status = 'pending' AND recommended_date < CURRENT_DATE
    """))
    delay_row = delay_result.mappings().first()
    by_delay = dict(delay_row) if delay_row else {}

    # 최근 미이행 환자 목록 (상위 10명)
    patient_result = await db.execute(text("""
        SELECT patient_id, count(*) as overdue_count,
               min(recommended_date) as earliest_date
        FROM followups
        WHERE status = 'pending' AND recommended_date < CURRENT_DATE
        GROUP BY patient_id
        ORDER BY earliest_date ASC
        LIMIT 10
    """))
    top_patients = []
    for r in patient_result:
        m = r._mapping
        top_patients.append({
            "patient_id": m["patient_id"],
            "overdue_count": m["overdue_count"],
            "earliest_date": str(m["earliest_date"]),
        })

    return {
        "total_overdue": total_overdue,
        "by_category": by_category,
        "by_delay_period": by_delay,
        "top_overdue_patients": top_patients,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{followup_id}/create-worklist-item", summary="워크리스트 항목 자동 생성")
async def create_worklist_item(
    followup_id: str,
    body: WorklistItemCreate | None = None,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
    db: AsyncSession = Depends(get_db),
):
    """팔로업에 대한 워크리스트 항목을 자동 생성합니다.

    팔로업 정보(환자 ID, 권고일, 사유)를 바탕으로
    worklist_items 테이블에 검사 예약 항목을 추가합니다.
    """
    if body is None:
        body = WorklistItemCreate()

    # 팔로업 정보 조회
    result = await db.execute(
        text("SELECT * FROM followups WHERE id = :id"),
        {"id": followup_id},
    )
    row = result.mappings().first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="팔로업을 찾을 수 없습니다")

    worklist_id = str(uuid4())
    accession = f"FU-{worklist_id[:8].upper()}"
    procedure_desc = body.scheduled_procedure_step_description or f"Follow-up: {row['reason']}"

    await db.execute(text("""
        INSERT INTO worklist_items (
            id, patient_id, patient_name, accession_number,
            requested_procedure_id, requested_procedure_description,
            scheduled_station_ae_title, modality,
            scheduled_date, scheduled_procedure_step_description,
            status, priority, clinical_info, notes
        ) VALUES (
            :id, :patient_id, :patient_id, :accession,
            :req_proc_id, :proc_desc,
            :ae_title, :modality,
            :sched_date, :step_desc,
            'SCHEDULED', 'ROUTINE', :clinical_info, :notes
        )
    """), {
        "id": worklist_id,
        "patient_id": row["patient_id"],
        "accession": accession,
        "req_proc_id": accession,
        "proc_desc": procedure_desc,
        "ae_title": body.scheduled_station_ae_title,
        "modality": body.modality,
        "sched_date": row["recommended_date"],
        "step_desc": procedure_desc,
        "clinical_info": f"카테고리: {row.get('category', 'N/A')}",
        "notes": f"팔로업 자동 생성 (followup_id: {followup_id})",
    })
    await db.commit()

    logger.info("워크리스트 항목 생성: %s (팔로업: %s)", worklist_id, followup_id)
    return {
        "worklist_item_id": worklist_id,
        "accession_number": accession,
        "scheduled_date": str(row["recommended_date"]),
        "message": "워크리스트 항목이 생성되었습니다",
    }
