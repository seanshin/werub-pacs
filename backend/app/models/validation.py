"""DICOM validation result models."""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class Severity(str, PyEnum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationCategory(str, PyEnum):
    METADATA = "metadata"
    PIXEL_DATA = "pixel_data"
    TRANSFER_SYNTAX = "transfer_syntax"
    JPEG = "jpeg"
    CHARACTER_SET = "character_set"
    UID = "uid"


class ValidationResult(Base, UUIDMixin, TimestampMixin):
    """Individual validation finding for a DICOM instance."""

    __tablename__ = "validation_results"

    # DICOM identifiers
    sop_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    series_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    orthanc_id: Mapped[str | None] = mapped_column(String(64))

    # Source info
    ae_title: Mapped[str | None] = mapped_column(String(16))
    modality: Mapped[str | None] = mapped_column(String(16))
    manufacturer: Mapped[str | None] = mapped_column(String(64))
    station_name: Mapped[str | None] = mapped_column(String(64))

    # Patient info snapshot
    patient_name: Mapped[str | None] = mapped_column(String(256))
    patient_id: Mapped[str | None] = mapped_column(String(64))
    study_description: Mapped[str | None] = mapped_column(String(256))
    study_date: Mapped[str | None] = mapped_column(String(8))

    # Validation result
    severity: Mapped[str] = mapped_column(Enum(Severity, name="severity_enum"), nullable=False)
    category: Mapped[str] = mapped_column(Enum(ValidationCategory, name="validation_category_enum"), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)

    # Action taken
    auto_fixed: Mapped[bool] = mapped_column(default=False)
    fix_description: Mapped[str | None] = mapped_column(Text)

    # Issue status tracking
    issue_status: Mapped[str] = mapped_column(String(16), default="unreviewed", server_default="unreviewed")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_validation_severity_created", "severity", "created_at"),
        Index("ix_validation_ae_title_rule", "ae_title", "rule_code"),
        Index("ix_validation_issue_status", "issue_status"),
        Index("ix_validation_study_rule", "study_instance_uid", "rule_code"),
    )


class ValidationSummary(Base, UUIDMixin, TimestampMixin):
    """Summary of validation for a DICOM instance."""

    __tablename__ = "validation_summaries"

    sop_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    orthanc_id: Mapped[str | None] = mapped_column(String(64))

    # Counts per severity
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)

    # Overall status
    max_severity: Mapped[str | None] = mapped_column(Enum(Severity, name="severity_enum", create_type=False))
    accepted: Mapped[bool] = mapped_column(default=True)

    # Metadata snapshot
    ae_title: Mapped[str | None] = mapped_column(String(16))
    modality: Mapped[str | None] = mapped_column(String(16))
