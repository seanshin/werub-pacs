"""DICOM Issue Control Center models."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class DicomIssueRule(Base, UUIDMixin, TimestampMixin):
    """Validation rule configuration — admin-editable."""

    __tablename__ = "dicom_issue_rules"

    rule_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    default_severity: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    severity_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    default_message: Mapped[str] = mapped_column(Text, nullable=False)
    custom_message: Mapped[str | None] = mapped_column(Text)
    auto_action: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    thresholds: Mapped[dict | None] = mapped_column(JSONB, default=dict)


class ModalityRenderConfig(Base, UUIDMixin, TimestampMixin):
    """Modality renderability configuration — admin-editable."""

    __tablename__ = "modality_render_config"

    modality: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    render_type: Mapped[str] = mapped_column(String(16), nullable=False)  # non_renderable, partial, renderable
    display_label: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_text: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class DicomMessageTemplate(Base, UUIDMixin):
    """Error message templates — admin-editable."""

    __tablename__ = "dicom_message_templates"

    message_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    context: Mapped[str] = mapped_column(String(32), nullable=False)  # viewer, validation, queue
    default_text: Mapped[str] = mapped_column(Text, nullable=False)
    custom_text: Mapped[str | None] = mapped_column(Text)
    variables: Mapped[list | None] = mapped_column(ARRAY(Text))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DicomFixHistory(Base, UUIDMixin):
    """Track every auto-fix with original backup for rollback."""

    __tablename__ = "dicom_fix_history"

    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sop_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    rule_codes: Mapped[list | None] = mapped_column(ARRAY(Text))
    changes: Mapped[dict | None] = mapped_column(JSONB)
    original_hash: Mapped[str | None] = mapped_column(String(64))
    backup_orthanc_id: Mapped[str | None] = mapped_column(String(64))
    # 원본 DICOM 바이트 보존 — Orthanc instance ID 변화·UID 재작성·재업로드에 무관하게
    # 롤백이 실제로 원본을 복원할 수 있는 유일한 신뢰 소스(K1). 크기 상한 내에서만 저장.
    original_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    # 수정본의 Orthanc instance ID — 롤백 시 수정본을 삭제하기 위해(UID 재작성 시 backup_orthanc_id와 다름)
    fixed_orthanc_id: Mapped[str | None] = mapped_column(String(64))
    fix_status: Mapped[str] = mapped_column(String(16), default="applied", server_default="applied")
    post_validation: Mapped[dict | None] = mapped_column(JSONB)
    manufacturer: Mapped[str | None] = mapped_column(String(64))
    supplier_normalizer: Mapped[str | None] = mapped_column(String(32))
    fixed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fixed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadQueue(Base, UUIDMixin):
    """Upload staging queue — files await approval before Orthanc storage."""

    __tablename__ = "upload_queue"

    source: Mapped[str] = mapped_column(String(32), nullable=False)  # patient_portal, kiosk, admin, remote
    source_detail: Mapped[str | None] = mapped_column(Text)
    patient_id: Mapped[str | None] = mapped_column(String(64))
    patient_name: Mapped[str | None] = mapped_column(String(256))
    matched_patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    file_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    storage_path: Mapped[str | None] = mapped_column(Text)
    dicomdir_parsed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    study_uids: Mapped[list | None] = mapped_column(ARRAY(Text))
    modalities: Mapped[list | None] = mapped_column(ARRAY(Text))
    validation_status: Mapped[str | None] = mapped_column(String(16))
    validation_summary: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PatientUploadToken(Base, UUIDMixin):
    """Token for patient self-upload portal."""

    __tablename__ = "patient_upload_tokens"

    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_name: Mapped[str | None] = mapped_column(String(256))
    patient_birth_date: Mapped[str | None] = mapped_column(String(8))
    consent_agreed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    consent_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DicomRemote(Base, UUIDMixin, TimestampMixin):
    """External PACS peer/modality configuration."""

    __tablename__ = "dicom_remotes"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    remote_type: Mapped[str] = mapped_column(String(16), nullable=False)  # peer, modality
    url: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(64))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    ae_title: Mapped[str | None] = mapped_column(String(16))
    host: Mapped[str | None] = mapped_column(String(256))
    port: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_echo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_echo_status: Mapped[str | None] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict | None] = mapped_column(JSONB, default=dict)


class DicomTransferHistory(Base, UUIDMixin):
    """Transfer history for send/receive operations."""

    __tablename__ = "dicom_transfer_history"

    remote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # send, receive
    study_instance_uid: Mapped[str | None] = mapped_column(String(128))
    patient_id: Mapped[str | None] = mapped_column(String(64))
    patient_name: Mapped[str | None] = mapped_column(String(256))
    modality: Mapped[str | None] = mapped_column(String(16))
    series_count: Mapped[int | None] = mapped_column(Integer)
    instance_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudyProvenance(Base, UUIDMixin):
    """Track the origin/source of each DICOM study."""

    __tablename__ = "study_provenance"

    study_instance_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    orthanc_id: Mapped[str | None] = mapped_column(String(64))

    # Origin classification
    origin: Mapped[str] = mapped_column(String(32), nullable=False, server_default="unknown")
    # Values: internal, external, patient_upload, kiosk, test_data, research, ai_generated, migration, unknown

    # Source details
    source_institution: Mapped[str | None] = mapped_column(String(256))   # 전원 병원명
    source_ae_title: Mapped[str | None] = mapped_column(String(16))       # 수신 AE Title
    source_device: Mapped[str | None] = mapped_column(String(128))        # 장비명/Station Name
    source_manufacturer: Mapped[str | None] = mapped_column(String(64))   # 제조사
    upload_method: Mapped[str | None] = mapped_column(String(32))         # c-store, stow-rs, upload, cd_import, patient_portal, kiosk, migration
    uploaded_by: Mapped[str | None] = mapped_column(String(128))          # 업로더 사용자명/토큰
    remote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # 외부 PACS에서 온 경우

    # Tags for custom classification
    tags: Mapped[dict | None] = mapped_column(JSONB, default=dict)        # {"project": "lung-study", "batch": "2026-05"}
    note: Mapped[str | None] = mapped_column(Text)                        # 관리자 메모

    # Timestamps
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 관리자가 출처 확인한 시점
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AeTitleProfile(Base, UUIDMixin, TimestampMixin):
    """Equipment profile by AE Title."""

    __tablename__ = "ae_title_profiles"

    ae_title: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    manufacturer: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    issue_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    issue_summary: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    rule_overrides: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    normalization_preset: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
