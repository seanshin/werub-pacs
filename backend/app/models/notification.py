"""Notification model."""
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class Notification(Base, UUIDMixin, TimestampMixin):
    """System notification for users."""

    __tablename__ = "notifications"

    # Target
    target_user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    target_role: Mapped[str | None] = mapped_column(String(32))  # broadcast to role
    target_username: Mapped[str | None] = mapped_column(String(128))

    # Content
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Types: new_study, report_ready, critical_finding, order_update, system
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), default="normal")  # normal, urgent, critical

    # Reference
    study_instance_uid: Mapped[str | None] = mapped_column(String(128))
    patient_id: Mapped[str | None] = mapped_column(String(64))
    action_url: Mapped[str | None] = mapped_column(String(512))
    data: Mapped[dict | None] = mapped_column(JSONB)

    # Status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
