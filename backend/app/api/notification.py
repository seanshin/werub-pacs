"""Notification API — real-time alerts for reading workflow."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    unread_only: bool = Query(False),
    urgency: str | None = Query(None),
    ntype: str | None = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get notifications for current user (filter + offset pagination)."""
    scope = (
        (Notification.target_user_id == str(user.id)) |
        (Notification.target_username == user.username) |
        (Notification.target_role == user.role) |
        (Notification.target_user_id.is_(None))  # broadcast
    )
    query = select(Notification).where(scope).order_by(Notification.created_at.desc())

    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    if urgency:
        query = query.where(Notification.urgency == urgency)
    if ntype:
        query = query.where(Notification.type == ntype)

    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    # unread는 필터와 무관한 전체 미읽음 수 (벨 배지용 — 기존엔 페이지 내 카운트라 20건 캡)
    unread = await db.scalar(
        select(func.count()).select_from(
            select(Notification.id).where(scope).where(Notification.is_read.is_(False)).subquery()
        )
    ) or 0

    result = await db.execute(query.offset(offset).limit(limit))
    notifs = result.scalars().all()

    return {
        "count": len(notifs),
        "total": total,
        "unread": unread,
        "notifications": [
            {
                "id": str(n.id),
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "urgency": n.urgency,
                "study_instance_uid": n.study_instance_uid,
                "patient_id": n.patient_id,
                "action_url": n.action_url,
                "is_read": n.is_read,
                "acknowledged": n.acknowledged,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifs
        ],
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Mark notification as read. Only owner can mark."""
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .where(
            (Notification.target_user_id == str(user.id)) |
            (Notification.target_username == user.username) |
            (Notification.target_user_id.is_(None))
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "read"}


@router.post("/read-all")
async def mark_all_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Mark all notifications as read for current user."""
    await db.execute(
        update(Notification)
        .where(
            (Notification.target_user_id == str(user.id)) |
            (Notification.target_username == user.username)
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "all_read"}


@router.post("/{notification_id}/acknowledge")
async def acknowledge(
    notification_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Acknowledge a critical notification. Only owner can acknowledge."""
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .where(
            (Notification.target_user_id == str(user.id)) |
            (Notification.target_username == user.username) |
            (Notification.target_user_id.is_(None))
        )
        .values(acknowledged=True, is_read=True)
    )
    await db.commit()
    return {"status": "acknowledged"}


async def create_notification(
    db: AsyncSession,
    type: str,
    title: str,
    message: str,
    urgency: str = "normal",
    target_user_id: str | None = None,
    target_username: str | None = None,
    target_role: str | None = None,
    study_instance_uid: str | None = None,
    patient_id: str | None = None,
    action_url: str | None = None,
):
    """Helper to create a notification (called from other modules)."""
    n = Notification(
        type=type,
        title=title,
        message=message,
        urgency=urgency,
        target_user_id=target_user_id,
        target_username=target_username,
        target_role=target_role,
        study_instance_uid=study_instance_uid,
        patient_id=patient_id,
        action_url=action_url,
    )
    db.add(n)
    await db.commit()
    return n
