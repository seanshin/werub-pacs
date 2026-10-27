"""DICOM Study/Series Archive (IOCM) model."""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum, Integer, BigInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ArchiveReason(str, PyEnum):
    QUALITY_REJECT = "quality_reject"          # 113001 화질 불량
    PATIENT_SAFETY = "patient_safety"          # 113037 잘못된 환자
    WORKLIST_ERROR = "worklist_error"          # 113038 오더 오류
    RETENTION_EXPIRED = "retention_expired"    # 113039 보존기간 만료
    SUPERSEDED = "superseded"                  # 재촬영으로 대체
    STORAGE_MIGRATION = "storage_migration"    # 스토리지 계층 이동
    MANUAL = "manual"                          # 수동 아카이브


class StorageType(str, PyEnum):
    LOCAL = "local"
    S3 = "s3"
    GLACIER = "glacier"


# DICOM Rejection Note codes (IHE IOCM)
REJECTION_CODES = {
    ArchiveReason.QUALITY_REJECT: "113001",
    ArchiveReason.PATIENT_SAFETY: "113037",
    ArchiveReason.WORKLIST_ERROR: "113038",
    ArchiveReason.RETENTION_EXPIRED: "113039",
    ArchiveReason.SUPERSEDED: "",
    ArchiveReason.STORAGE_MIGRATION: "",
    ArchiveReason.MANUAL: "",
}


class ArchivedStudy(Base, UUIDMixin, TimestampMixin):
    """Archived DICOM study or series with full audit trail."""

    __tablename__ = "archived_studies"

    # Original DICOM identifiers
    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    series_instance_uid: Mapped[str | None] = mapped_column(String(128))
    orthanc_study_id: Mapped[str | None] = mapped_column(String(64))
    orthanc_series_id: Mapped[str | None] = mapped_column(String(64))

    # Patient info snapshot
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    patient_name: Mapped[str | None] = mapped_column(String(256))
    patient_birth_date: Mapped[str | None] = mapped_column(String(16))
    patient_sex: Mapped[str | None] = mapped_column(String(4))

    # Study info snapshot
    modality: Mapped[str | None] = mapped_column(String(16))
    study_date: Mapped[str | None] = mapped_column(String(16))
    study_description: Mapped[str | None] = mapped_column(String(256))
    series_count: Mapped[int] = mapped_column(Integer, default=0)
    instance_count: Mapped[int] = mapped_column(Integer, default=0)

    # Archive reason & audit
    reason: Mapped[str] = mapped_column(
        Enum(ArchiveReason, name="archive_reason_enum", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text)
    rejection_code: Mapped[str | None] = mapped_column(String(16))

    # Who archived
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    archived_by_name: Mapped[str | None] = mapped_column(String(128))
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Original DICOM metadata snapshot
    orthanc_metadata: Mapped[dict | None] = mapped_column(JSONB)

    # Thumbnail & preview
    thumbnail: Mapped[bytes | None] = mapped_column()  # 128x128 JPEG
    preview_path: Mapped[str | None] = mapped_column(String(512))

    # Storage
    storage_path: Mapped[str | None] = mapped_column(String(512))
    storage_type: Mapped[str] = mapped_column(
        Enum(StorageType, name="storage_type_enum", values_callable=lambda e: [x.value for x in e]),
        default=StorageType.LOCAL,
    )
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    # Restore tracking
    is_restorable: Mapped[bool] = mapped_column(Boolean, default=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    restored_by_name: Mapped[str | None] = mapped_column(String(128))

    # Linked report
    original_report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Retention policy
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
