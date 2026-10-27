"""Reading report model."""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID as PyUUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ReportStatus(str, PyEnum):
    DRAFT = "draft"
    PRELIMINARY = "preliminary"
    FINAL = "final"
    ADDENDUM = "addendum"
    CANCELLED = "cancelled"


class Report(Base, UUIDMixin, TimestampMixin):
    """Reading report for a study."""

    __tablename__ = "reports"

    # Study reference
    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    orthanc_study_id: Mapped[str | None] = mapped_column(String(64))

    # Patient snapshot
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    patient_name: Mapped[str | None] = mapped_column(String(256))
    modality: Mapped[str | None] = mapped_column(String(16))
    study_date: Mapped[str | None] = mapped_column(String(8))
    study_description: Mapped[str | None] = mapped_column(String(256))
    accession_number: Mapped[str | None] = mapped_column(String(64))

    # Report content
    clinical_info: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[str | None] = mapped_column(Text)
    impression: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[str | None] = mapped_column(String(64))
    structured_data: Mapped[dict | None] = mapped_column(JSONB)

    # Status & workflow
    status: Mapped[str] = mapped_column(
        Enum(ReportStatus, name="report_status_enum"),
        nullable=False,
        default=ReportStatus.DRAFT,
        index=True,
    )
    urgency: Mapped[str | None] = mapped_column(String(16))  # normal, non_urgent, urgent

    # Author
    author_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    author_name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Signing
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    signed_by_name: Mapped[str | None] = mapped_column(String(256))

    # Edit lock
    locked_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    locked_by_name: Mapped[str | None] = mapped_column(String(256))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Preliminary read (resident → attending)
    preliminary_by_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    preliminary_by_name: Mapped[str | None] = mapped_column(String(256))
    preliminary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preliminary_content: Mapped[dict | None] = mapped_column(JSONB)

    # Addendum parent
    parent_report_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reports.id"))

    # AI results reference
    ai_findings: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_report_study_status", "study_instance_uid", "status"),
    )
