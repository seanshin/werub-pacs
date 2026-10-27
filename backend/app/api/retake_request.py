"""API endpoints for retake/rescan requests.

Workflow: Radiologist/Physician requests retake → Technologist reviews → Approved → Scheduled → Completed
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_async_db
from app.core.auth import get_current_user
from app.core.security import ClinicalPHIReadRoles, ClinicalWriteRoles, RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/retake", tags=["Retake Request"])


# ─── Models ───

class RetakeCreateRequest(BaseModel):
    study_instance_uid: str
    reason: str
    category: str = "quality"  # quality, positioning, motion, incomplete, other
    urgency: str = "routine"   # routine, urgent, stat
    notes: Optional[str] = None

class RetakeUpdateRequest(BaseModel):
    status: str  # approved, rejected, scheduled, completed, cancelled
    reviewer_notes: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO 8601

class RetakeResponse(BaseModel):
    id: str
    study_instance_uid: str
    reason: str
    category: str
    urgency: str
    status: str
    notes: Optional[str]
    requested_by: str
    requested_at: str
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    reviewer_notes: Optional[str]
    scheduled_at: Optional[str]
    completed_at: Optional[str]


# ─── Ensure table exists ───

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS retake_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid TEXT NOT NULL,
    reason TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'quality',
    urgency TEXT NOT NULL DEFAULT 'routine',
    status TEXT NOT NULL DEFAULT 'requested',
    notes TEXT,
    requested_by TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    reviewer_notes TEXT,
    scheduled_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    patient_id TEXT,
    patient_name TEXT,
    modality TEXT,
    study_description TEXT
)
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_retake_status ON retake_requests(status);
CREATE INDEX IF NOT EXISTS idx_retake_study ON retake_requests(study_instance_uid);
"""


async def _ensure_table(db: AsyncSession):
    try:
        await db.execute(text(CREATE_TABLE_SQL))
        await db.execute(text(CREATE_INDEX_SQL))
        await db.commit()
    except Exception:
        await db.rollback()


# ─── Endpoints ───

@router.post("")
async def create_retake_request(
    req: RetakeCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.RESIDENT, Role.PHYSICIAN, allow_btg=False)),
):
    """Create a new retake/rescan request. Radiologist, Physician, or Resident."""
    # retake_requests table is created at startup (core/schema_migrations).
    # Fetch study info from Orthanc
    patient_id = ""
    patient_name = ""
    modality = ""
    study_desc = ""
    try:
        import httpx
        _orthanc_auth = (settings.orthanc_username, settings.orthanc_password)
        async with httpx.AsyncClient(timeout=10.0, base_url=settings.orthanc_url) as client:
            search_resp = await client.post(
                "/tools/find",
                json={"Level": "Study", "Query": {"StudyInstanceUID": req.study_instance_uid}},
                auth=_orthanc_auth,
            )
            if search_resp.status_code == 200 and search_resp.json():
                oid = search_resp.json()[0]
                study_resp = await client.get(f"/studies/{oid}", auth=_orthanc_auth)
                tags = study_resp.json().get("MainDicomTags", {})
                patient_id = tags.get("PatientID", "")
                patient_name = tags.get("PatientName", "")
                # was: Series[0] (a series-ID hash) — store the real modality.
                modality = tags.get("ModalitiesInStudy", "")
                study_desc = tags.get("StudyDescription", "")
    except Exception:
        pass

    retake_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(text("""
        INSERT INTO retake_requests (id, study_instance_uid, reason, category, urgency, status,
            notes, requested_by, requested_at, patient_id, patient_name, modality, study_description)
        VALUES (:id, :study_uid, :reason, :category, :urgency, 'requested',
            :notes, :requested_by, :requested_at, :patient_id, :patient_name, :modality, :study_desc)
    """), {
        "id": retake_id, "study_uid": req.study_instance_uid,
        "reason": req.reason, "category": req.category, "urgency": req.urgency,
        "notes": req.notes, "requested_by": user.username, "requested_at": now,
        "patient_id": patient_id, "patient_name": patient_name,
        "modality": modality, "study_desc": study_desc,
    })
    await db.commit()

    logger.info("Retake request created by %s for study %s", user.username, req.study_instance_uid)
    return {
        "id": retake_id, "status": "requested",
        "message": "재촬영 요청이 등록되었습니다",
    }


@router.get("")
async def list_retake_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(ClinicalPHIReadRoles),
):
    """List retake requests. All authenticated users can view."""
    where = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if status:
        where += " AND status = :status"
        params["status"] = status

    result = await db.execute(text(f"""
        SELECT id, study_instance_uid, reason, category, urgency, status, notes,
               requested_by, requested_at, reviewed_by, reviewed_at, reviewer_notes,
               scheduled_at, completed_at, patient_id, patient_name, modality, study_description
        FROM retake_requests {where}
        ORDER BY
            CASE WHEN urgency = 'stat' THEN 0 WHEN urgency = 'urgent' THEN 1 ELSE 2 END,
            requested_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    rows = result.fetchall()
    count_result = await db.execute(text(f"SELECT COUNT(*) FROM retake_requests {where}"), params)
    total = count_result.scalar() or 0

    items = []
    for r in rows:
        items.append({
            "id": str(r[0]), "study_instance_uid": r[1], "reason": r[2],
            "category": r[3], "urgency": r[4], "status": r[5], "notes": r[6],
            "requested_by": r[7],
            "requested_at": r[8].isoformat() if r[8] else None,
            "reviewed_by": r[9],
            "reviewed_at": r[10].isoformat() if r[10] else None,
            "reviewer_notes": r[11],
            "scheduled_at": r[12].isoformat() if r[12] else None,
            "completed_at": r[13].isoformat() if r[13] else None,
            "patient_id": r[14], "patient_name": r[15],
            "modality": r[16], "study_description": r[17],
        })

    return {"items": items, "total": total}


@router.patch("/{retake_id}")
async def update_retake_request(
    retake_id: str,
    req: RetakeUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(ClinicalWriteRoles),
):
    """Update retake request status. Technologist/Admin can approve/reject/schedule/complete."""
    valid_transitions = {
        "requested": ["approved", "rejected", "cancelled"],
        "approved": ["scheduled", "cancelled"],
        "scheduled": ["completed", "cancelled"],
    }

    result = await db.execute(
        text("SELECT status FROM retake_requests WHERE id = :id"),
        {"id": retake_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "재촬영 요청을 찾을 수 없습니다")

    current_status = row[0]
    if req.status not in valid_transitions.get(current_status, []):
        raise HTTPException(400, f"'{current_status}' → '{req.status}' 상태 전환이 불가합니다")

    # Approval/rejection requires technologist or admin
    if req.status in ("approved", "rejected") and user.role not in ("admin", "technologist"):
        raise HTTPException(403, "방사선사 또는 관리자만 승인/거부할 수 있습니다")

    now = datetime.now(timezone.utc).isoformat()
    updates = ["status = :status"]
    params: dict = {"id": retake_id, "status": req.status}

    if req.status in ("approved", "rejected"):
        updates.extend(["reviewed_by = :reviewed_by", "reviewed_at = :reviewed_at"])
        params["reviewed_by"] = user.username
        params["reviewed_at"] = now

    if req.reviewer_notes:
        updates.append("reviewer_notes = :reviewer_notes")
        params["reviewer_notes"] = req.reviewer_notes

    if req.scheduled_at:
        updates.append("scheduled_at = :scheduled_at")
        params["scheduled_at"] = req.scheduled_at

    if req.status == "completed":
        updates.append("completed_at = :completed_at")
        params["completed_at"] = now

    await db.execute(
        text(f"UPDATE retake_requests SET {', '.join(updates)} WHERE id = :id"),
        params,
    )
    await db.commit()

    status_label = {
        "approved": "승인", "rejected": "거부", "scheduled": "스케줄 확정",
        "completed": "완료", "cancelled": "취소",
    }
    logger.info("Retake %s updated to %s by %s", retake_id, req.status, user.username)
    return {"status": req.status, "message": f"재촬영 요청이 {status_label.get(req.status, req.status)}되었습니다"}


@router.get("/stats")
async def retake_stats(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """Get retake request statistics."""
    result = await db.execute(text("""
        SELECT status, COUNT(*) as cnt FROM retake_requests GROUP BY status
    """))
    rows = result.fetchall()
    stats = {r[0]: r[1] for r in rows}

    cat_result = await db.execute(text("""
        SELECT category, COUNT(*) as cnt FROM retake_requests
        WHERE requested_at > NOW() - INTERVAL '30 days'
        GROUP BY category ORDER BY cnt DESC
    """))
    categories = [{"category": r[0], "count": r[1]} for r in cat_result.fetchall()]

    return {
        "total": sum(stats.values()),
        "by_status": stats,
        "pending": stats.get("requested", 0) + stats.get("approved", 0),
        "categories_30d": categories,
    }
