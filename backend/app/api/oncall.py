"""On-call radiologist schedule management — DB-backed."""
from datetime import datetime, date as date_cls, time as time_cls, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/oncall", tags=["온콜 관리"])


def _as_date(s: str) -> date_cls:
    """Parse YYYY-MM-DD → date (asyncpg needs real date objects, not str)."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValidationError(message=f"invalid date (YYYY-MM-DD): {s}")


def _as_time(s: str) -> time_cls:
    """Parse HH:MM[:SS] → time."""
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except (ValueError, TypeError):
            continue
    raise ValidationError(message=f"invalid time (HH:MM): {s}")


class OnCallEntry(BaseModel):
    radiologist_username: str
    radiologist_name: str
    date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    is_primary: bool = True


@router.get("", summary="온콜 스케줄 조회")
async def get_oncall_schedule(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
):
    """온콜 판독의 스케줄을 조회합니다."""
    query = "SELECT * FROM oncall_schedule WHERE 1=1"
    params: dict = {}
    if from_date:
        query += " AND schedule_date >= :from_date"
        params["from_date"] = _as_date(from_date)
    if to_date:
        query += " AND schedule_date <= :to_date"
        params["to_date"] = _as_date(to_date)
    query += " ORDER BY schedule_date, start_time"

    result = await db.execute(text(query), params)
    rows = result.mappings().all()

    schedule = [
        {
            "id": str(r["id"]),
            "radiologist_username": r["radiologist_username"],
            "radiologist_name": r["radiologist_name"],
            "date": str(r["schedule_date"]),
            "start_time": str(r["start_time"])[:5],
            "end_time": str(r["end_time"])[:5],
            "is_primary": r["is_primary"],
        }
        for r in rows
    ]
    return {"schedule": schedule, "total": len(schedule)}


@router.get("/current", summary="현재 온콜 판독의")
async def get_current_oncall(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
):
    """현재 시간 기준 온콜 판독의를 반환합니다."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            SELECT * FROM oncall_schedule
            WHERE schedule_date = :today
              AND start_time <= :now_time
              AND end_time >= :now_time
            ORDER BY is_primary DESC
            LIMIT 1
        """),
        {"today": now.date(), "now_time": now.time().replace(microsecond=0)},
    )
    row = result.mappings().first()

    if row:
        return {
            "oncall": {
                "id": str(row["id"]),
                "radiologist_username": row["radiologist_username"],
                "radiologist_name": row["radiologist_name"],
                "date": str(row["schedule_date"]),
                "start_time": str(row["start_time"])[:5],
                "end_time": str(row["end_time"])[:5],
                "is_primary": row["is_primary"],
            },
            "status": "active",
        }

    return {"oncall": None, "status": "no_oncall", "message": "현재 온콜 판독의가 없습니다"}


@router.post("", summary="온콜 스케줄 등록", status_code=status.HTTP_201_CREATED)
async def create_oncall(
    body: OnCallEntry,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """온콜 스케줄을 등록합니다."""
    result = await db.execute(
        text("""
            INSERT INTO oncall_schedule
                (radiologist_username, radiologist_name, schedule_date, start_time, end_time, is_primary)
            VALUES
                (:username, :name, :date, :start_time, :end_time, :is_primary)
            RETURNING id
        """),
        {
            "username": body.radiologist_username,
            "name": body.radiologist_name,
            "date": _as_date(body.date),
            "start_time": _as_time(body.start_time),
            "end_time": _as_time(body.end_time),
            "is_primary": body.is_primary,
        },
    )
    row = result.mappings().first()
    await db.commit()

    return {
        "id": str(row["id"]),
        **body.model_dump(),
    }


@router.delete("/{entry_id}", summary="온콜 스케줄 삭제")
async def delete_oncall(
    entry_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """온콜 스케줄을 삭제합니다."""
    result = await db.execute(
        text("DELETE FROM oncall_schedule WHERE id = :id RETURNING id"),
        {"id": entry_id},
    )
    row = result.mappings().first()
    await db.commit()

    if not row:
        raise NotFoundError("OnCallEntry", entry_id)

    return {"status": "deleted", "id": entry_id}
