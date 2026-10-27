"""OpenPACS config and operational tables (previously created via runtime DDL)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String, Text, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
import uuid

from app.models.base import Base


class OpenpacConfig(Base):
    """Key-value configuration store (webhook, normalization, SLA settings)."""
    __tablename__ = "openpacs_config"

    key = Column(Text, primary_key=True)
    value = Column(JSONB, nullable=False, server_default="{}")
    updated_by = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RetakeRequest(Base):
    """Retake/rescan request workflow."""
    __tablename__ = "retake_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_instance_uid = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    category = Column(Text, nullable=False, server_default="quality")
    urgency = Column(Text, nullable=False, server_default="routine")
    status = Column(Text, nullable=False, server_default="requested")
    notes = Column(Text)
    requested_by = Column(Text, nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_by = Column(Text)
    reviewed_at = Column(DateTime(timezone=True))
    reviewer_notes = Column(Text)
    scheduled_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    patient_id = Column(Text)
    patient_name = Column(Text)
    modality = Column(Text)
    study_description = Column(Text)


class SlaEscalationLog(Base):
    """SLA escalation tracking."""
    __tablename__ = "sla_escalation_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_instance_uid = Column(Text, nullable=False, index=True)
    escalation_type = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=False)
    from_user = Column(Text)
    to_user = Column(Text)
    notes = Column(Text)
    triggered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))
    sla_minutes = Column(Integer)

    __table_args__ = (
        Index("idx_sla_esc_time", "triggered_at"),
    )


class HisRequest(Base):
    """HIS integration request log."""
    __tablename__ = "his_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_type = Column(Text, nullable=False, index=True)
    accession_number = Column(Text, index=True)
    study_instance_uid = Column(Text)
    patient_id = Column(Text, nullable=False, index=True)
    patient_name = Column(Text)
    status = Column(Text, nullable=False, server_default="received")
    payload = Column(JSONB, nullable=False, server_default="{}")
    requested_by = Column(Text)
    requesting_department = Column(Text)
    his_order_id = Column(Text)
    callback_url = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    processed_by = Column(Text)
    result = Column(JSONB)
