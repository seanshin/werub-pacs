"""Pydantic schemas for AI model and inference APIs"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


# --- Request Schemas ---

class AIModelRegisterRequest(BaseModel):
    """Request to register a new AI model"""

    name: str = Field(..., min_length=1, max_length=128, description="Model name (e.g., 'lung-nodule-detector')")
    version: str = Field(..., min_length=1, max_length=32, description="Semantic version (e.g., '1.0.0')")
    modality: str = Field(..., min_length=1, max_length=16, description="DICOM modality (CT, MR, CR, DX, US, etc)")
    description: Optional[str] = Field(None, max_length=1000)
    gpu_required: bool = Field(False, description="Whether GPU is required for inference")


class AIModelUpdateRequest(BaseModel):
    """Request to update AI model metadata"""

    status: Optional[str] = Field(None, enum=["active", "inactive", "deleted"])
    description: Optional[str] = Field(None, max_length=1000)


class InferenceJobRequest(BaseModel):
    """Request to submit an inference job"""

    model_id: UUID
    study_instance_uid: str = Field(..., description="Study instance UID")
    series_instance_uid: Optional[str] = Field(None, description="Series instance UID (optional)")


# --- Response Schemas ---

class AIModelResponse(BaseModel):
    """Response for AI model"""

    id: UUID
    name: str
    version: str
    modality: str
    description: Optional[str]
    gpu_required: bool
    status: str
    file_path: str
    created_at: datetime
    created_by: Optional[UUID] = None

    class Config:
        from_attributes = True


class AIModelListResponse(BaseModel):
    """Paginated list of AI models"""

    items: list[AIModelResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class InferenceJobResponse(BaseModel):
    """Response for inference job"""

    id: UUID
    model_id: UUID
    study_instance_uid: str
    series_instance_uid: Optional[str]
    status: str
    celery_task_id: Optional[str] = None
    error_message: Optional[str] = None
    inference_time_ms: Optional[int] = None
    confidence_score: Optional[float] = None
    created_at: datetime
    created_by: Optional[UUID] = None

    class Config:
        from_attributes = True


class InferenceResultMetadata(BaseModel):
    """Metadata from inference result"""

    model_name: str
    model_version: str
    confidence_score: Optional[float]
    inference_time_ms: Optional[int]


class InferenceResultResponse(BaseModel):
    """Response for inference result"""

    dicom_type: str
    orthanc_id: Optional[str]
    metadata: Optional[dict]


class InferenceJobDetailResponse(InferenceJobResponse):
    """Detailed response for single inference job"""

    model: Optional[AIModelResponse] = None
    result: Optional[InferenceResultResponse] = None


class InferenceJobListResponse(BaseModel):
    """Paginated list of inference jobs"""

    items: list[InferenceJobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
