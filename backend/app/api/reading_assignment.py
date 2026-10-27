"""Shift-based reading assignment — routes unread studies to on-duty readers.

Reuses the existing ``oncall_schedule`` (current on-duty radiologists) as the
shift source and records study→reader assignments in ``reading_assignments``.
Auto-assignment is admin-triggered and idempotent: a study that already has a
current (open) assignment is skipped, and load is balanced across the readers
on duty now. Falls back to all active radiologists when nobody is on call.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import RequireRole, get_current_user
from app.models.report import Report
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reading-assignments", tags=["판독 배정"])


class ManualAssign(BaseModel):
    study_instance_uid: str = Field(..., min_length=4)
    assigned_to_username: str
    assigned_to_name: str | None = None
    patient_id: str | None = None
    patient_name: str | None = None
    modality: str | None = None


class StatusUpdate(BaseModel):
    status: str  # pending | in_progress | completed


_VALID_STATUS = {"pending", "in_progress", "completed"}


async def _on_duty_readers(db: AsyncSession) -> list[dict]:
    """Readers on call right now (primary first), else all active radiologists."""
    now = datetime.now(timezone.utc)
    # asyncpg requires real date/time objects (no implicit str cast).
    rows = (await db.execute(
        text("""
            SELECT radiologist_username AS username, radiologist_name AS name,
                   id AS oncall_id, is_primary
            FROM oncall_schedule
            WHERE schedule_date = :today
              AND start_time <= :now_time AND end_time >= :now_time
            ORDER BY is_primary DESC
        """),
        {"today": now.date(), "now_time": now.time().replace(microsecond=0)},
    )).mappings().all()
    if rows:
        return [dict(r) for r in rows]
    # Fallback: nobody on call → all active radiologists/residents
    users = (await db.execute(
        select(User).where(
            User.role.in_([Role.RADIOLOGIST, Role.RESIDENT]),
            User.is_active.is_(True),
        )
    )).scalars().all()
    return [{"username": u.username, "name": u.full_name,
             "oncall_id": None, "is_primary": False} for u in users]


def _enqueue_prefetch(study_uid: str, username: str):
    """Warm the assigned study ahead of reading (3d-ai-performance Track A).
    Best-effort: assignment must succeed even when the broker is down."""
    try:
        from app.services.prefetch_worker import warm_study
        warm_study.delay(study_uid, username, "assignment", "assignment")
    except Exception as e:
        logger.warning(f"prefetch enqueue failed for {study_uid}: {e}")


async def _notify(db: AsyncSession, username: str, study_uid: str, patient_name: str | None):
    await db.execute(text("""
        INSERT INTO notifications (id, type, title, message, urgency, target_role,
            target_username, study_instance_uid, action_url, is_read, acknowledged, created_at)
        VALUES (:id, 'reading_assigned', :title, :msg, 'normal', 'radiologist',
                :user, :study_uid, :url, false, false, NOW())
    """), {
        "id": str(uuid.uuid4()),
        "title": "새 판독 배정",
        "msg": f"{patient_name or study_uid} 검사가 배정되었습니다.",
        "user": username, "study_uid": study_uid,
        "url": f"/pacs-admin/reading/view?study={study_uid}",
    })


@router.get("", summary="판독 배정 목록")
async def list_assignments(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
    status_filter: str | None = Query(None, alias="status"),
    assignee: str | None = Query(None),
    current_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
):
    """판독 배정 목록을 조회합니다."""
    q = "SELECT * FROM reading_assignments WHERE 1=1"
    p: dict = {}
    if current_only:
        q += " AND is_current = true"
    if status_filter:
        q += " AND status = :st"; p["st"] = status_filter
    if assignee:
        q += " AND assigned_to_username = :as"; p["as"] = assignee
    q += " ORDER BY assigned_at DESC LIMIT :lim"; p["lim"] = limit
    rows = (await db.execute(text(q), p)).mappings().all()
    return {"total": len(rows), "assignments": [
        {
            "id": str(r["id"]),
            "study_instance_uid": r["study_instance_uid"],
            "patient_id": r["patient_id"], "patient_name": r["patient_name"],
            "modality": r["modality"],
            "assigned_to_username": r["assigned_to_username"],
            "assigned_to_name": r["assigned_to_name"],
            "assignment_type": r["assignment_type"], "status": r["status"],
            "assigned_by": r["assigned_by"],
            "assigned_at": r["assigned_at"].isoformat() if r["assigned_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "viewer_url": f"/pacs-admin/reading/view?study={r['study_instance_uid']}",
        } for r in rows
    ]}


@router.get("/on-duty", summary="현재 근무 판독의")
async def on_duty(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
):
    """현재 시간 근무(온콜) 판독의 + 각자 진행중 배정 수."""
    readers = await _on_duty_readers(db)
    load = dict((await db.execute(text("""
        SELECT assigned_to_username, COUNT(*) FROM reading_assignments
        WHERE is_current = true AND status != 'completed'
        GROUP BY assigned_to_username
    """))).all())
    for r in readers:
        r["open_assignments"] = int(load.get(r["username"], 0))
        r["oncall_id"] = str(r["oncall_id"]) if r["oncall_id"] else None
    has_oncall = any(r["oncall_id"] for r in readers)
    return {"on_call": has_oncall, "readers": readers}


@router.post("", summary="수동 판독 배정", status_code=status.HTTP_201_CREATED)
async def assign_manual(
    body: ManualAssign,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """특정 검사를 특정 판독의에게 수동 배정합니다(기존 현재 배정은 해제)."""
    from sqlalchemy.exc import IntegrityError
    # Deactivate any existing current assignment for this study
    await db.execute(text("""
        UPDATE reading_assignments SET is_current = false
        WHERE study_instance_uid = :s AND is_current = true
    """), {"s": body.study_instance_uid})
    new_id = str(uuid.uuid4())
    try:
        await db.execute(text("""
            INSERT INTO reading_assignments
                (id, study_instance_uid, patient_id, patient_name, modality,
                 assigned_to_username, assigned_to_name, assignment_type, status,
                 is_current, assigned_by, assigned_at)
            VALUES (:id, :s, :pid, :pname, :mod, :au, :an, 'manual', 'pending',
                    true, :by, NOW())
        """), {
            "id": new_id, "s": body.study_instance_uid, "pid": body.patient_id,
            "pname": body.patient_name, "mod": body.modality,
            "au": body.assigned_to_username, "an": body.assigned_to_name or body.assigned_to_username,
            "by": user.username,
        })
        await _notify(db, body.assigned_to_username, body.study_instance_uid, body.patient_name)
        await db.commit()
    except IntegrityError:
        # H3: uq_reading_assignments_current 위반 = 다른 요청이 동시에 배정함(race) → 거부
        await db.rollback()
        raise ValidationError("다른 사용자가 동시에 이 검사를 배정했습니다. 새로고침 후 확인하세요.")
    _enqueue_prefetch(body.study_instance_uid, body.assigned_to_username)
    return {"id": new_id, "status": "assigned", "assigned_to": body.assigned_to_username}


@router.post("/auto", summary="미배정 검사 자동 배정 (근무 시간대 기준)")
async def auto_assign(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """판독 미완료 + 미배정 검사를 현재 근무 판독의에게 부하 분산 자동 배정합니다."""
    readers = await _on_duty_readers(db)
    if not readers:
        return {"ok": True, "assigned": 0, "reason": "배정 가능한 판독의가 없습니다.",
                "on_call": False}
    on_call = any(r["oncall_id"] for r in readers)

    # Current per-reader open load (for balancing)
    load = {r["username"]: 0 for r in readers}
    for uname, cnt in (await db.execute(text("""
        SELECT assigned_to_username, COUNT(*) FROM reading_assignments
        WHERE is_current = true AND status != 'completed' GROUP BY assigned_to_username
    """))).all():
        if uname in load:
            load[uname] = int(cnt)

    # Studies already having a current assignment
    assigned_uids = {row[0] for row in (await db.execute(text(
        "SELECT study_instance_uid FROM reading_assignments WHERE is_current = true"
    ))).all()}

    # Reports → reading status (skip studies already finalized)
    reports = {r.study_instance_uid: r for r in
               (await db.execute(select(Report))).scalars().all()}

    client = request.app.state.http_client
    # 성능: 1콜로 전체 study 메타+modality(기존 1+200 GET N+1 제거 — reading-queue 동일 패턴)
    try:
        resp = await client.post("/tools/find", json={
            "Level": "Study", "Query": {}, "Since": 0, "Limit": 200,
            "Expand": True, "RequestedTags": ["ModalitiesInStudy"],
        })
        studies = resp.json() if resp.status_code == 200 and isinstance(resp.json(), list) else []
    except Exception:
        studies = []

    name_by_user = {r["username"]: r["name"] for r in readers}
    oncall_by_user = {r["username"]: r["oncall_id"] for r in readers}
    assigned = 0
    skipped_final = 0
    first_per_reader: dict[str, str] = {}  # warm only each reader's first new study
    for study in studies:
        tags = study.get("MainDicomTags", {})
        ptags = study.get("PatientMainDicomTags", {})
        uid = tags.get("StudyInstanceUID", "")
        if not uid or uid in assigned_uids:
            continue
        rep = reports.get(uid)
        if rep and rep.status == "final":
            skipped_final += 1
            continue

        # Pick least-loaded reader on duty
        pick = min(load, key=lambda u: load[u])
        load[pick] += 1
        oc = oncall_by_user.get(pick)
        await db.execute(text("""
            INSERT INTO reading_assignments
                (id, study_instance_uid, patient_id, patient_name, modality,
                 assigned_to_username, assigned_to_name, assignment_type, status,
                 oncall_id, is_current, assigned_by, assigned_at)
            VALUES (:id, :s, :pid, :pname, :mod, :au, :an, 'shift', 'pending',
                    :oc, true, :by, NOW())
        """), {
            "id": str(uuid.uuid4()), "s": uid,
            "pid": ptags.get("PatientID"), "pname": ptags.get("PatientName"),
            "mod": study.get("RequestedTags", {}).get("ModalitiesInStudy") or tags.get("ModalitiesInStudy"),
            "au": pick, "an": name_by_user.get(pick, pick),
            "oc": str(oc) if oc else None, "by": user.username,
        })
        await _notify(db, pick, uid, ptags.get("PatientName"))
        assigned_uids.add(uid)
        assigned += 1
        first_per_reader.setdefault(pick, uid)

    await db.commit()
    for reader, uid in first_per_reader.items():
        _enqueue_prefetch(uid, reader)
    return {"ok": True, "assigned": assigned, "skipped_final": skipped_final,
            "on_call": on_call, "readers": len(readers),
            "load": load}


@router.patch("/{assignment_id}", summary="배정 상태 변경")
async def update_status(
    assignment_id: str,
    body: StatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """배정 상태(pending/in_progress/completed)를 변경합니다."""
    if body.status not in _VALID_STATUS:
        raise ValidationError(message=f"invalid status: {body.status}")
    completed = ", completed_at = NOW()" if body.status == "completed" else ""
    current = ", is_current = false" if body.status == "completed" else ""
    row = (await db.execute(
        text(f"UPDATE reading_assignments SET status = :st{completed}{current} "
             f"WHERE id = :id RETURNING id"),
        {"st": body.status, "id": assignment_id},
    )).mappings().first()
    await db.commit()
    if not row:
        raise NotFoundError("ReadingAssignment", assignment_id)
    return {"id": assignment_id, "status": body.status}
