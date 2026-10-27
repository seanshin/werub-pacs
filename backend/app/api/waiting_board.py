"""Patient waiting board — today's exam status for technologists."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.worklist import WorklistItem, ProcedureStatus
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/waiting-board", tags=["대기 현황"])


@router.get("", summary="오늘 촬영 대기 현황")
async def get_waiting_board(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
):
    """오늘의 촬영 대기/진행/완료 현황을 반환합니다.

    방사선사 워크스테이션의 현황판에 사용.
    """
    # A7 fix: scheduled_date is a Date column — asyncpg rejects a str ("expected
    # a datetime.date instance, got 'str'"). Pass a date object, not strftime().
    today = datetime.now(timezone.utc).date()

    result = await db.execute(
        select(WorklistItem)
        .where(WorklistItem.scheduled_date == today)
        .order_by(WorklistItem.scheduled_time.asc())
    )
    items = result.scalars().all()

    waiting = []
    in_progress = []
    completed = []

    for item in items:
        entry = {
            "patient_name": item.patient_name,
            "patient_id": item.patient_id,
            "modality": item.modality,
            "body_part": item.requested_procedure,
            "scheduled_time": str(item.scheduled_time) if item.scheduled_time else "",
            "priority": item.priority,
            "status": item.status,
            "study_uid": item.study_instance_uid,
        }

        if item.status in (ProcedureStatus.SCHEDULED.value, 'scheduled'):
            waiting.append(entry)
        elif item.status in (ProcedureStatus.IN_PROGRESS.value, 'in_progress'):
            in_progress.append(entry)
        else:
            completed.append(entry)

    return {
        "date": today,
        "waiting": waiting,
        "in_progress": in_progress,
        "completed": completed,
        "counts": {
            "waiting": len(waiting),
            "in_progress": len(in_progress),
            "completed": len(completed),
            "total": len(items),
        },
    }
