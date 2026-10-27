"""Modality Worklist models."""
from datetime import date, datetime, time
from enum import Enum as PyEnum

from sqlalchemy import Date, DateTime, Enum, Index, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ProcedureStatus(str, PyEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISCONTINUED = "discontinued"


class Priority(str, PyEnum):
    STAT = "stat"
    HIGH = "high"
    ROUTINE = "routine"
    LOW = "low"


class WorklistItem(Base, UUIDMixin, TimestampMixin):
    """Scheduled procedure step — Modality Worklist entry."""

    __tablename__ = "worklist_items"

    # Patient info
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    patient_name: Mapped[str] = mapped_column(String(256), nullable=False)
    patient_birth_date: Mapped[date | None] = mapped_column(Date)
    patient_sex: Mapped[str | None] = mapped_column(String(2))

    # Requested Procedure
    accession_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    requested_procedure_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_procedure_description: Mapped[str | None] = mapped_column(String(256))
    referring_physician: Mapped[str | None] = mapped_column(String(256))
    requesting_physician: Mapped[str | None] = mapped_column(String(256))

    # Scheduled Procedure Step
    scheduled_station_ae_title: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    scheduled_time: Mapped[time | None] = mapped_column(Time)
    scheduled_procedure_step_description: Mapped[str | None] = mapped_column(String(256))
    body_part_examined: Mapped[str | None] = mapped_column(String(64))

    # Study reference
    study_instance_uid: Mapped[str | None] = mapped_column(String(128))

    # Status tracking
    status: Mapped[str] = mapped_column(
        Enum(ProcedureStatus, name="procedure_status_enum"),
        nullable=False,
        default=ProcedureStatus.SCHEDULED,
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        Enum(Priority, name="priority_enum"),
        nullable=False,
        default=Priority.ROUTINE,
    )

    # MPPS tracking
    performed_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    performed_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    performed_station_ae_title: Mapped[str | None] = mapped_column(String(16))
    # MPPS SOP Instance UID assigned at N-CREATE — links the later N-SET back to this item.
    mpps_sop_instance_uid: Mapped[str | None] = mapped_column(String(128), index=True)

    # Notes
    clinical_info: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_worklist_date_status", "scheduled_date", "status"),
        Index("ix_worklist_patient_date", "patient_id", "scheduled_date"),
    )
