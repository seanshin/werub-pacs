"""AI model and inference job models."""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ModelType(str, PyEnum):
    ONNX = "onnx"
    DOCKER = "docker"
    EXTERNAL_API = "external_api"
    TRITON = "triton"


class ModelStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class ClinicalUse(str, PyEnum):
    CLINICAL = "clinical"
    RESEARCH = "research"


class JobStatus(str, PyEnum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    INFERRING = "inferring"
    POSTPROCESSING = "postprocessing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobPriority(str, PyEnum):
    EMERGENCY = "emergency"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class AIModel(Base, UUIDMixin, TimestampMixin):
    """Registered AI model."""

    __tablename__ = "ai_models"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    model_type: Mapped[str] = mapped_column(Enum(ModelType, name="model_type_enum"), nullable=False)
    status: Mapped[str] = mapped_column(Enum(ModelStatus, name="model_status_enum"), default=ModelStatus.ACTIVE)
    clinical_use: Mapped[str] = mapped_column(Enum(ClinicalUse, name="clinical_use_enum"), default=ClinicalUse.RESEARCH)

    # What this model handles
    modalities: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "CR,DX" or "CT"
    body_parts: Mapped[str | None] = mapped_column(String(256))  # e.g. "CHEST,ABDOMEN"
    sop_classes: Mapped[str | None] = mapped_column(String(512))

    # Execution config
    endpoint_url: Mapped[str | None] = mapped_column(String(512))  # for external_api / triton
    model_path: Mapped[str | None] = mapped_column(String(512))  # for onnx local path
    # 로컬 모델 파일 무결성 (arch-invariants INV-NET-02): 설정 시 로드 전 대조,
    # 불일치면 로드 거부. None = 검증 생략(기존 모델 호환)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    docker_image: Mapped[str | None] = mapped_column(String(256))  # for docker type
    input_config: Mapped[dict | None] = mapped_column(JSONB)  # preprocessing params
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    # Regulatory
    certification: Mapped[str | None] = mapped_column(String(128))  # FDA/CE/MFDS
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Stats
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    successful_runs: Mapped[int] = mapped_column(Integer, default=0)
    avg_inference_time: Mapped[float | None] = mapped_column(Float)


class InferenceJob(Base, UUIDMixin, TimestampMixin):
    """AI inference job."""

    __tablename__ = "inference_jobs"

    model_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_models.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Input
    study_instance_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    series_instance_uid: Mapped[str | None] = mapped_column(String(128))
    orthanc_study_id: Mapped[str | None] = mapped_column(String(64))
    patient_id: Mapped[str | None] = mapped_column(String(64))
    modality: Mapped[str | None] = mapped_column(String(16))

    # Status
    status: Mapped[str] = mapped_column(Enum(JobStatus, name="job_status_enum"), default=JobStatus.QUEUED, index=True)
    priority: Mapped[str] = mapped_column(Enum(JobPriority, name="job_priority_enum"), default=JobPriority.NORMAL)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inference_time_ms: Mapped[int | None] = mapped_column(Integer)

    # Results
    results: Mapped[dict | None] = mapped_column(JSONB)
    result_dicom_uids: Mapped[dict | None] = mapped_column(JSONB)  # stored SEG/SR UIDs
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    max_confidence: Mapped[float | None] = mapped_column(Float)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)

    # Who requested
    requested_by: Mapped[str | None] = mapped_column(String(128))
    trigger_type: Mapped[str | None] = mapped_column(String(16))  # "auto" or "manual"

    # Parameters
    parameters: Mapped[dict | None] = mapped_column(JSONB)


class InferenceResult(Base, UUIDMixin, TimestampMixin):
    """Inference result storage (DICOM SEG/SR/SC).

    Added in Phase 5 for result file tracking.
    """

    __tablename__ = "inference_results"

    job_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inference_jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    dicom_type: Mapped[str] = mapped_column(String(8), nullable=False)  # SEG | SR | SC
    orthanc_id: Mapped[str | None] = mapped_column(String(128))
    file_path: Mapped[str | None] = mapped_column(String(512))
    result_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)  # model_name, version, confidence_score, etc.
