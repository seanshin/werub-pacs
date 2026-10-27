# Phase 5: AI Model Integration and Inference Pipeline — Design Document

> **Design Phase**: Detailed architecture, file structure, API contracts, and implementation order
>
> **Project**: OpenPACS
> **Version**: 1.0.0
> **Date**: 2026-05-14
> **Based on Plan**: `docs/01-plan/features/phase-5-ai-integration.plan.md`
> **Status**: Design Review Ready

---

## 1. Architecture Overview

### 1.1 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Client Layer (OHIF + Admin UI)              │
├────────────────────┬──────────────────────┬─────────────────────┤
│  OHIF Viewer       │  Admin Dashboard     │   WebSocket Client  │
│  "Run AI" Button   │  Model Management    │   Progress Monitor  │
│  Result Overlay    │  Inference Monitor   │                     │
└────────┬───────────┴──────────┬───────────┴──────────┬──────────┘
         │ HTTP                 │ HTTP                 │ WS
         ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Router Layer                       │
├─────────────────────────────────────────────────────────────────┤
│  POST   /api/v1/ai/models           (register)                 │
│  GET    /api/v1/ai/models           (list + filter)            │
│  PUT    /api/v1/ai/models/{id}      (update + activate)        │
│  DELETE /api/v1/ai/models/{id}      (soft-delete)              │
│  POST   /api/v1/ai/inferences       (submit job)               │
│  GET    /api/v1/ai/inferences       (list jobs)                │
│  GET    /api/v1/ai/inferences/{id}  (job detail)               │
│  GET    /api/v1/ai/results/{id}     (retrieve DICOM)           │
│  WS     /api/v1/ws/ai/{id}          (progress stream)          │
└──────────┬─────────────────────────────┬────────────────────────┘
           │ Service Layer               │ Task Queue
           ▼                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Business Logic Layer                           │
├──────────────────────────────────────────────────────────────────┤
│  AIModelService        InferenceJobService      ResultService   │
│  - CRUD models         - Create/track jobs      - Store/fetch   │
│  - Redis cache mgmt    - Celery task enqueue   - Orthanc push  │
│  - File validation     - Job querying           - DICOM build  │
└──────────┬──────────────┬──────────────┬────────────────────────┘
           │              │              │
           ▼              ▼              ▼
    ┌──────────┐   ┌───────────────┐  ┌──────────────┐
    │ Database │   │  Redis Cache  │  │ Celery Queue │
    │ (Models) │   │  (Model List) │  │ (ai_infer)   │
    │ (Jobs)   │   │               │  │              │
    └──────────┘   └───────────────┘  └──────┬───────┘
                                              │
                                              ▼
                   ┌──────────────────────────────────┐
                   │  Celery Worker (ai_inference)    │
                   ├──────────────────────────────────┤
                   │  - Fetch DICOM from Orthanc      │
                   │  - Run ONNX inference            │
                   │  - Build DICOM SEG/SR            │
                   │  - Store result in Orthanc       │
                   │  - Emit WebSocket progress       │
                   └──────────────┬───────────────────┘
                                  │
                              ┌────▼─────┐
                              │ Orthanc  │
                              │ + Models │
                              └──────────┘
```

### 1.2 Data Flow: Inference Submission to Completion

```
1. Admin registers ONNX model
   POST /api/v1/ai/models (multipart)
   └─> AIModelService.create()
       ├─> Validate model file
       ├─> Save file to /models/{name}_{version}.onnx
       ├─> Store AIModel record in DB
       └─> Invalidate Redis model cache

2. Radiologist submits inference job
   POST /api/v1/ai/inferences { model_id, study_uid, series_uid }
   └─> InferenceJobService.create()
       ├─> Validate model active status
       ├─> Create InferenceJob record (status=queued)
       ├─> Enqueue Celery task with (job_id, model_id, study_uid)
       └─> Return 202 Accepted { job_id, celery_task_id }

3. Client opens WebSocket
   WS /api/v1/ws/ai/{inference_id}
   └─> WebSocket manager subscribes to Redis pub/sub channel: ai:job:{job_id}

4. Celery worker processes task
   ai_inference_task(job_id, model_id, study_uid)
   ├─> Update job status → running
   ├─> Publish WebSocket event: { event: "running" }
   ├─> Fetch DICOM series from Orthanc via DICOMweb
   ├─> Load ONNX model from /models/
   ├─> Detect GPU availability (ONNX Runtime providers)
   ├─> Run inference on series pixels
   ├─> Build DICOM SEG from inference mask
   ├─> POST SEG to Orthanc /instances
   ├─> Save InferenceResult { job_id, orthanc_id, metadata }
   ├─> Update job status → completed
   ├─> Publish WebSocket event: { event: "completed", result_path: "..." }
   └─> Publish audit log event

5. Admin views inference job detail
   GET /api/v1/ai/inferences/{job_id}
   └─> InferenceJobService.get_detail()
       ├─> Fetch job record + related model
       ├─> Fetch result metadata
       └─> Return with error_message (if failed)

6. Radiologist views AI result in OHIF
   GET /api/v1/ai/results/{job_id}
   └─> ResultService.get_result()
       ├─> Fetch InferenceResult record
       ├─> Construct Orthanc DICOMweb URL to SEG instance
       └─> Redirect to /dicom-web/instances/{orthanc_id}
```

---

## 2. Database Schema (Implementation Detail)

### 2.1 Three Tables and Indexes

```sql
-- Table 1: AI Models Registry
CREATE TABLE ai_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128)  NOT NULL,           -- "lung-nodule-detector"
    version         VARCHAR(32)   NOT NULL,           -- "1.0.0"
    modality        VARCHAR(16)   NOT NULL,           -- "CT", "MR", "CR", "DX", "US"
    description     TEXT,                             -- Clinical purpose
    file_path       VARCHAR(512)  NOT NULL,           -- "/models/lung-nodule-detector_1.0.0.onnx"
    gpu_required    BOOLEAN       NOT NULL DEFAULT FALSE,
    status          VARCHAR(16)   NOT NULL DEFAULT 'inactive',  -- active | inactive | deleted
    created_by      UUID          REFERENCES users(id),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE(name, version),
    UNIQUE(status, name)  -- Only one active version per model name
);

-- Table 2: Inference Job Queue
CREATE TABLE inference_jobs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id             UUID          NOT NULL REFERENCES ai_models(id),
    study_instance_uid   VARCHAR(64)   NOT NULL,
    series_instance_uid  VARCHAR(64),
    status               VARCHAR(16)   NOT NULL DEFAULT 'queued',  -- queued|running|completed|failed
    celery_task_id       VARCHAR(128),                            -- Celery task UUID
    error_message        TEXT,                                     -- On failure
    inference_time_ms    INTEGER,                                  -- After completion
    confidence_score     NUMERIC(5,4),                            -- 0.0 - 1.0
    created_by           UUID          REFERENCES users(id),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Table 3: Inference Results
CREATE TABLE inference_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID          NOT NULL UNIQUE REFERENCES inference_jobs(id),
    dicom_type      VARCHAR(8)    NOT NULL,           -- 'SEG' | 'SR' | 'SC'
    orthanc_id      VARCHAR(128),                     -- Orthanc instance UID
    file_path       VARCHAR(512),                     -- Local temp path (before Orthanc)
    metadata        JSONB,                             -- { model_name, version, confidence, etc }
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Indexes for query performance
CREATE INDEX idx_inference_jobs_status     ON inference_jobs(status);
CREATE INDEX idx_inference_jobs_model_id   ON inference_jobs(model_id);
CREATE INDEX idx_inference_jobs_study_uid  ON inference_jobs(study_instance_uid);
CREATE INDEX idx_inference_jobs_created_at ON inference_jobs(created_at DESC);
CREATE INDEX idx_ai_models_status          ON ai_models(status);
CREATE INDEX idx_ai_models_modality        ON ai_models(modality);
```

### 2.2 ORM Models (SQLAlchemy + Pydantic)

**Location**: `backend/app/models/ai.py`

```python
from sqlalchemy import Column, String, UUID, Boolean, Integer, Numeric, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from uuid import uuid4

class AIModel(Base):
    __tablename__ = "ai_models"
    
    id = Column(UUID, primary_key=True, default=uuid4)
    name = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False)
    modality = Column(String(16), nullable=False)  # CT, MR, CR, DX, US, etc
    description = Column(Text)
    file_path = Column(String(512), nullable=False)
    gpu_required = Column(Boolean, default=False)
    status = Column(String(16), default="inactive")  # active | inactive | deleted
    created_by = Column(UUID, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_ai_models_status", "status"),
        Index("idx_ai_models_modality", "modality"),
        Index("uq_model_version", "name", "version", unique=True),
    )

class InferenceJob(Base):
    __tablename__ = "inference_jobs"
    
    id = Column(UUID, primary_key=True, default=uuid4)
    model_id = Column(UUID, ForeignKey("ai_models.id"), nullable=False)
    study_instance_uid = Column(String(64), nullable=False)
    series_instance_uid = Column(String(64))
    status = Column(String(16), default="queued")  # queued|running|completed|failed
    celery_task_id = Column(String(128))
    error_message = Column(Text)
    inference_time_ms = Column(Integer)
    confidence_score = Column(Numeric(5, 4))
    created_by = Column(UUID, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_inference_jobs_status", "status"),
        Index("idx_inference_jobs_model_id", "model_id"),
        Index("idx_inference_jobs_study_uid", "study_instance_uid"),
        Index("idx_inference_jobs_created_at", "created_at", "desc"),
    )

class InferenceResult(Base):
    __tablename__ = "inference_results"
    
    id = Column(UUID, primary_key=True, default=uuid4)
    job_id = Column(UUID, ForeignKey("inference_jobs.id"), unique=True, nullable=False)
    dicom_type = Column(String(8), nullable=False)  # SEG | SR | SC
    orthanc_id = Column(String(128))
    file_path = Column(String(512))
    metadata = Column(JSONB)  # { model_name, version, confidence, inference_time_ms, ... }
    created_at = Column(DateTime, default=datetime.utcnow)
```

### 2.3 Pydantic Schemas

**Location**: `backend/app/schemas/ai.py`

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

# Request schemas
class AIModelRegisterRequest(BaseModel):
    name: str = Field(..., description="Model name, e.g., 'lung-nodule-detector'")
    version: str = Field(..., description="Semantic version, e.g., '1.0.0'")
    modality: str = Field(..., description="DICOM modality: CT, MR, CR, DX, US, etc")
    description: Optional[str] = None
    gpu_required: bool = Field(False, description="Whether GPU is required")

class AIModelUpdateRequest(BaseModel):
    status: Optional[str] = Field(None, enum=["active", "inactive", "deleted"])
    description: Optional[str] = None

class InferenceJobRequest(BaseModel):
    model_id: UUID
    study_instance_uid: str
    series_instance_uid: Optional[str] = None

# Response schemas
class AIModelResponse(BaseModel):
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

class InferenceJobResponse(BaseModel):
    id: UUID
    model_id: UUID
    study_instance_uid: str
    series_instance_uid: Optional[str]
    status: str
    celery_task_id: Optional[str]
    error_message: Optional[str]
    inference_time_ms: Optional[int]
    confidence_score: Optional[float]
    created_at: datetime
    created_by: Optional[UUID] = None
    
    class Config:
        from_attributes = True

class InferenceJobDetailResponse(InferenceJobResponse):
    model: AIModelResponse
    result: Optional[dict] = None  # { dicom_type, orthanc_id, metadata }

class InferenceJobListResponse(BaseModel):
    items: list[InferenceJobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

class AIResultResponse(BaseModel):
    id: UUID
    job_id: UUID
    dicom_type: str
    orthanc_id: Optional[str]
    metadata: Optional[dict]
```

---

## 3. File Structure and Implementation Order

### 3.1 New Files to Create

```
backend/
├── app/
│   ├── models/
│   │   └── ai.py                          # SQLAlchemy ORM models (AIModel, InferenceJob, InferenceResult)
│   ├── schemas/
│   │   └── ai.py                          # Pydantic request/response schemas
│   ├── services/
│   │   ├── ai_model_service.py            # AIModelService (CRUD, caching, file validation)
│   │   ├── inference_job_service.py       # InferenceJobService (create, list, get detail)
│   │   └── inference_result_service.py    # ResultService (build DICOM, store Orthanc, fetch)
│   ├── tasks/
│   │   └── ai_inference_task.py           # Celery task: run ONNX, produce SEG, push to Orthanc
│   ├── api/
│   │   └── ai.py                          # Router: POST/GET models, jobs, results, WebSocket
│   ├── core/
│   │   ├── exceptions.py                  # (extend) Add AIModelError, InferenceError
│   │   └── websocket.py                   # (extend) Add Redis pub/sub for ai: channels
│   └── alembic/
│       └── versions/
│           └── XXXX_add_ai_inference.py   # Migration: create 3 tables + indexes
│
admin/
├── src/
│   ├── app/
│   │   └── ai/
│   │       ├── models/
│   │       │   └── page.tsx               # Model Management page
│   │       └── inferences/
│   │           └── page.tsx               # Inference Monitor page
│   └── components/
│       └── ai/
│           ├── ModelTable.tsx             # Model list table with actions
│           ├── ModelUploadForm.tsx        # Register model form
│           ├── InferenceTable.tsx         # Job queue table
│           └── InferenceProgressBar.tsx   # Real-time progress indicator
```

### 3.2 Modified Files

```
backend/
├── app/
│   ├── main.py                            # Import ai router, register routes
│   ├── celery.py                          # Add ai_inference queue config
│   └── core/
│       ├── config.py                      # Add MODEL_STORAGE_PATH, cache TTL env vars
│       └── websocket.py                   # Extend manager for ai: channel pattern
│
admin/
├── src/
│   ├── app/
│   │   └── layout.tsx                     # Add /admin/ai nav items
│   └── lib/
│       └── api.ts                         # (no change; reuse existing apiFetch)
│
docker-compose.yml                         # Add celery-ai service, model volume mount
requirements.txt                           # Add onnxruntime, highdicom packages
```

### 3.3 Implementation Order (5–7 days)

| Day | Tasks | Files | Depends On |
|-----|-------|-------|-----------|
| **Day 1** | DB migration + AIModelService CRUD + Redis cache | ai.py (models), ai.py (schemas), ai_model_service.py, alembic migration | None |
| **Day 2** | InferenceJobService + Celery task scaffold | inference_job_service.py, ai_inference_task.py, ai.py (router) | Day 1 |
| **Day 3** | DICOM SEG/SR building + Orthanc storage | inference_result_service.py, ai_inference_task.py (extend) | Day 2 |
| **Day 4** | WebSocket inference progress + end-to-end test | websocket.py (extend), integration test | Day 3 |
| **Day 5** | Admin Model Management page (`/admin/ai/models`) | ModelTable.tsx, ModelUploadForm.tsx, page.tsx | Day 2 |
| **Day 6** | Admin Inference Monitor page (`/admin/ai/inferences`) | InferenceTable.tsx, InferenceProgressBar.tsx, page.tsx | Day 4 |
| **Day 7** | OHIF extension + full regression + docs + staging deploy | ohif/ai-extension | Day 6 |

---

## 4. API Endpoint Details

### 4.1 Model Management Endpoints

#### **POST /api/v1/ai/models** — Register new model
**Auth**: Admin  
**Content-Type**: multipart/form-data

**Request**:
```
name          (string, required)  "lung-nodule-detector"
version       (string, required)  "1.0.0"
modality      (string, required)  "CT"
description   (string, optional)  "Lung nodule detection on CT imaging"
gpu_required  (boolean, required) false
file          (binary, required)  <ONNX model file>
```

**Response** (201 Created):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "lung-nodule-detector",
  "version": "1.0.0",
  "modality": "CT",
  "description": "Lung nodule detection on CT imaging",
  "gpu_required": false,
  "status": "inactive",
  "file_path": "/models/lung-nodule-detector_1.0.0.onnx",
  "created_at": "2026-05-14T10:00:00Z",
  "created_by": "user-uuid"
}
```

**Error** (400 Bad Request):
```json
{
  "error": "INVALID_MODEL_FORMAT",
  "message": "ONNX model opset not supported. Expected opset 14+, got 12"
}
```

---

#### **GET /api/v1/ai/models** — List models (with caching)
**Auth**: Radiologist+  
**Query Params**: `page=1, page_size=20, modality=CT, status=active`

**Response** (200 OK, cached 300s):
```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "lung-nodule-detector",
      "version": "1.0.0",
      "modality": "CT",
      "status": "active",
      "gpu_required": false,
      "created_at": "2026-05-14T10:00:00Z"
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "name": "fracture-detector",
      "version": "2.1.0",
      "modality": "CR",
      "status": "active",
      "gpu_required": true,
      "created_at": "2026-05-13T14:30:00Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

---

#### **PUT /api/v1/ai/models/{model_id}** — Update model (status, description)
**Auth**: Admin

**Request**:
```json
{
  "status": "active",
  "description": "Updated description"
}
```

**Response** (200 OK):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "lung-nodule-detector",
  "version": "1.0.0",
  "status": "active",
  "updated_at": "2026-05-14T10:05:00Z"
}
```

**Side Effect**: Invalidate Redis cache on any status change

---

#### **DELETE /api/v1/ai/models/{model_id}** — Soft-delete model
**Auth**: Admin

**Response** (204 No Content)  
**Side Effect**: Set `status = 'deleted'`, preserve InferenceJob history for audit

---

### 4.2 Inference Job Endpoints

#### **POST /api/v1/ai/inferences** — Submit inference job
**Auth**: Radiologist+  
**Content-Type**: application/json

**Request**:
```json
{
  "model_id": "550e8400-e29b-41d4-a716-446655440000",
  "study_instance_uid": "1.2.840.113619.2.408.1.1234567",
  "series_instance_uid": "1.2.840.113619.2.408.1.1234567.0"
}
```

**Response** (202 Accepted):
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440005",
  "model_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "study_instance_uid": "1.2.840.113619.2.408.1.1234567",
  "series_instance_uid": "1.2.840.113619.2.408.1.1234567.0",
  "celery_task_id": "abcd-1234-efgh-5678",
  "created_at": "2026-05-14T10:10:00Z"
}
```

**Side Effect**: Enqueue Celery task, write AuditLog: `AI_INFERENCE_SUBMITTED`

---

#### **GET /api/v1/ai/inferences** — List inference jobs
**Auth**: Admin  
**Query Params**: `page=1, page_size=20, status=running, model_id=uuid, date_from=2026-05-14`

**Response** (200 OK):
```json
{
  "items": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440005",
      "model_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "running",
      "study_instance_uid": "1.2.840...",
      "inference_time_ms": null,
      "created_at": "2026-05-14T10:10:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

---

#### **GET /api/v1/ai/inferences/{inference_id}** — Job detail
**Auth**: Radiologist+

**Response** (200 OK):
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440005",
  "model": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "lung-nodule-detector",
    "version": "1.0.0",
    "modality": "CT"
  },
  "status": "completed",
  "study_instance_uid": "1.2.840...",
  "series_instance_uid": "1.2.840...",
  "inference_time_ms": 2345,
  "confidence_score": 0.89,
  "error_message": null,
  "result": {
    "dicom_type": "SEG",
    "orthanc_id": "orthanc-instance-uuid",
    "metadata": {
      "model_name": "lung-nodule-detector",
      "model_version": "1.0.0",
      "confidence_score": 0.89,
      "inference_time_ms": 2345
    }
  },
  "created_at": "2026-05-14T10:10:00Z"
}
```

---

#### **GET /api/v1/ai/results/{inference_id}** — Retrieve DICOM result
**Auth**: Radiologist+

**Response**: HTTP 302 Redirect to Orthanc DICOMweb

```
Location: /dicom-web/studies/1.2.840.../series/.../instances/...
```

Or (alternative) return JSON with URL:
```json
{
  "dicom_url": "/dicom-web/studies/1.2.840.../series/.../instances/...",
  "dicom_type": "SEG",
  "orthanc_id": "orthanc-instance-uuid"
}
```

---

### 4.3 WebSocket Endpoint

#### **WS /api/v1/ws/ai/{inference_id}** — Real-time inference progress
**Auth**: Radiologist+ (JWT in query: `?token=...`)

**Message Flow** (server → client):

```json
// Message 1: Job accepted and queued
{
  "event": "queued",
  "inference_id": "770e8400-e29b-41d4-a716-446655440005",
  "timestamp": "2026-05-14T10:10:05Z"
}

// Message 2: Job started processing
{
  "event": "running",
  "inference_id": "770e8400-e29b-41d4-a716-446655440005",
  "progress_pct": 40,
  "timestamp": "2026-05-14T10:10:15Z"
}

// Message 3: Job completed successfully
{
  "event": "completed",
  "inference_id": "770e8400-e29b-41d4-a716-446655440005",
  "result_path": "/api/v1/ai/results/770e8400-e29b-41d4-a716-446655440005",
  "inference_time_ms": 2345,
  "confidence_score": 0.89,
  "timestamp": "2026-05-14T10:10:25Z"
}

// Or Message 3: Job failed
{
  "event": "failed",
  "inference_id": "770e8400-e29b-41d4-a716-446655440005",
  "error": "ONNX Runtime error: Model incompatible with system GPU",
  "timestamp": "2026-05-14T10:10:30Z"
}
```

**Implementation**: Redis pub/sub on channel `ai:job:{inference_id}`. Celery task publishes on completion.

---

## 5. Service Layer Architecture

### 5.1 AIModelService

**Location**: `backend/app/services/ai_model_service.py`

```python
class AIModelService:
    def __init__(self, db_session, redis_client):
        self.db = db_session
        self.redis = redis_client
        self.model_path = settings.MODEL_STORAGE_PATH
    
    async def register_model(
        self,
        name: str,
        version: str,
        modality: str,
        gpu_required: bool,
        file: UploadFile,
        user_id: UUID
    ) -> AIModel:
        """
        1. Validate ONNX file format (check opset version)
        2. Save file to /models/{name}_{version}.onnx
        3. Store AIModel record in DB (status='inactive')
        4. Invalidate Redis cache
        """
    
    async def list_models(
        self,
        modality: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """
        1. Check Redis cache (key: ai:models:{modality}:{status}:{page})
        2. If miss, query DB with filters
        3. Cache result for 300 seconds
        """
    
    async def update_model(
        self,
        model_id: UUID,
        status: str = None,
        description: str = None
    ) -> AIModel:
        """
        Update status or description.
        Enforce: Only one 'active' version per model name.
        If activating new version, deactivate others with same name.
        Invalidate cache on any update.
        """
    
    async def delete_model(self, model_id: UUID) -> None:
        """Soft-delete: set status='deleted', preserve InferenceJob records."""
    
    def _validate_onnx_file(self, file_path: str) -> bool:
        """Check ONNX model opset >= 14. Raise AIModelError if invalid."""
```

---

### 5.2 InferenceJobService

**Location**: `backend/app/services/inference_job_service.py`

```python
class InferenceJobService:
    def __init__(self, db_session, celery_app, redis_client):
        self.db = db_session
        self.celery = celery_app
        self.redis = redis_client
    
    async def create_job(
        self,
        model_id: UUID,
        study_uid: str,
        series_uid: str,
        user_id: UUID
    ) -> dict:
        """
        1. Validate model is active and exists
        2. Create InferenceJob record (status='queued')
        3. Enqueue Celery task: ai_inference_task.delay(job_id, model_id, study_uid)
        4. Return { id, job_id, status, celery_task_id }
        5. Write AuditLog: AI_INFERENCE_SUBMITTED
        """
    
    async def list_jobs(
        self,
        status: str = None,
        model_id: UUID = None,
        study_uid: str = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """Query DB with filters, return paginated result."""
    
    async def get_job_detail(self, job_id: UUID) -> dict:
        """
        Return job record + related model + result metadata.
        If result exists, include InferenceResult details.
        """
    
    async def update_job_status(
        self,
        job_id: UUID,
        new_status: str,
        error_message: str = None,
        inference_time_ms: int = None,
        confidence_score: float = None
    ) -> None:
        """
        Update job record.
        Used by Celery task to mark job as running/completed/failed.
        """
```

---

### 5.3 InferenceResultService

**Location**: `backend/app/services/inference_result_service.py`

```python
class InferenceResultService:
    def __init__(self, db_session, orthanc_client):
        self.db = db_session
        self.orthanc = orthanc_client
    
    async def build_dicom_seg(
        self,
        series_pixels: np.ndarray,
        inference_mask: np.ndarray,
        model_name: str,
        model_version: str,
        confidence_score: float
    ) -> bytes:
        """
        Build DICOM SEG using highdicom library.
        Input: CT/MR/CR pixels, binary or multi-class mask.
        Output: DICOM SEG file (bytes).
        Metadata tags: ModelName (0008,103E), SeriesDescription.
        """
    
    async def store_result_in_orthanc(
        self,
        dicom_bytes: bytes,
        job_id: UUID
    ) -> str:
        """
        POST DICOM file to Orthanc /instances.
        Return Orthanc instance UID.
        Store in InferenceResult table.
        """
    
    async def get_result_url(self, job_id: UUID) -> str:
        """
        Fetch InferenceResult.orthanc_id.
        Return Orthanc DICOMweb URL: /dicom-web/instances/{orthanc_id}
        """
```

---

## 6. Celery Task Architecture

### 6.1 AI Inference Task

**Location**: `backend/app/tasks/ai_inference_task.py`

```python
@shared_task(
    name='app.tasks.ai_inference_task',
    queue='ai_inference',
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def ai_inference_task(
    job_id: str,
    model_id: str,
    study_uid: str,
    series_uid: str
):
    """
    Async Celery task for inference.
    
    Steps:
    1. Mark job as 'running', publish WebSocket event
    2. Fetch DICOM series from Orthanc DICOMweb
    3. Load ONNX model file from /models/
    4. Detect GPU (ONNX Runtime providers)
    5. Preprocess pixels (resize, normalize) if needed
    6. Run ONNX inference → output mask
    7. Build DICOM SEG using inference_result_service
    8. POST SEG to Orthanc /instances
    9. Update InferenceJob: status='completed', inference_time_ms, confidence_score
    10. Publish WebSocket event: { event: 'completed', result_path: '...' }
    11. Write AuditLog: AI_INFERENCE_COMPLETED
    12. On error: set status='failed', error_message, publish failed event
    """
    
    try:
        job = InferenceJob.query.get(job_id)
        model = AIModel.query.get(model_id)
        
        # Step 1
        job.status = 'running'
        db.commit()
        publish_ws_event(job_id, { "event": "running" })
        
        # Step 2: Fetch series
        series_pixels = orthanc_client.fetch_series_pixels(study_uid, series_uid)
        
        # Step 3-4: Load model
        ort_session = get_ort_session(model.file_path, model.gpu_required)
        
        # Step 5-6: Infer
        inference_mask = ort_session.run(None, { 'input': series_pixels })[0]
        confidence_score = np.max(inference_mask)
        
        # Step 7-8: Build & store SEG
        dicom_seg = inference_result_service.build_dicom_seg(
            series_pixels, inference_mask, model.name, model.version, confidence_score
        )
        orthanc_id = inference_result_service.store_result_in_orthanc(dicom_seg, job_id)
        
        # Step 9-11
        end_time = time.time()
        job.status = 'completed'
        job.inference_time_ms = int((end_time - start_time) * 1000)
        job.confidence_score = confidence_score
        db.commit()
        
        publish_ws_event(job_id, {
            "event": "completed",
            "result_path": f"/api/v1/ai/results/{job_id}",
            "inference_time_ms": job.inference_time_ms,
            "confidence_score": confidence_score
        })
        
        audit_log.write("AI_INFERENCE_COMPLETED", job_id, { ... })
        
    except Exception as e:
        job.status = 'failed'
        job.error_message = str(e)
        db.commit()
        
        publish_ws_event(job_id, { "event": "failed", "error": str(e) })
        audit_log.write("AI_INFERENCE_FAILED", job_id, { "error": str(e) })
        
        raise  # Celery will retry
```

**Queue**: `ai_inference` (separate from `normalization` queue)  
**Concurrency**: 2 workers by default (prevent memory bloat from ONNX models)  
**Retry Policy**: Up to 3 retries with exponential back-off

---

## 7. Admin Dashboard Pages

### 7.1 Model Management Page: `/admin/ai/models`

**Layout**:
```
┌─ Header: "AI Model Management"
│  ├─ Button: "Register New Model"
│  └─ Search/Filter: Name, Modality, Status
│
├─ ModelTable
│  ├─ Columns: Name | Version | Modality | Status | GPU? | Created | Actions
│  ├─ Status Badge: green(active) | gray(inactive) | red(deleted)
│  ├─ Actions: Activate/Deactivate, View Metrics, Delete
│  └─ Pagination
│
└─ (Modal when "Register" clicked)
   └─ ModelUploadForm
      ├─ Input: Name, Version, Modality, Description
      ├─ Checkbox: GPU Required
      ├─ File upload: ONNX/PyTorch
      └─ Submit button
```

**Features**:
- List all models with pagination (20 per page)
- Filter by modality, status
- Activate/deactivate toggle (one active per model name)
- Delete model (soft-delete)
- Per-model metrics: total inference count, success rate, avg time
- Real-time updates (invalidate cache on action)

---

### 7.2 Inference Monitor Page: `/admin/ai/inferences`

**Layout**:
```
┌─ Header: "Inference Job Monitor"
│  ├─ Summary Cards: Total today | Success rate | Avg duration
│  └─ Filters: Status, Model, Date range
│
├─ InferenceTable
│  ├─ Columns: Model | Study UID | Status | Duration | Confidence | Created
│  ├─ Status Badge: yellow(queued) | blue(running) | green(completed) | red(failed)
│  ├─ Row click → Job Detail Drawer
│  └─ Pagination with auto-refresh (5 sec) when jobs are running
│
└─ (Drawer when row clicked)
   └─ Job Details
      ├─ Model info, Study/Series UID
      ├─ Status timeline with timestamps
      ├─ Inference time, Confidence score
      ├─ Error message (if failed)
      ├─ Result DICOM link
      └─ Close button
```

**Features**:
- Real-time queue view (WebSocket subscription for running jobs)
- Filter by status, model, date
- Per-job detail: timing, confidence, error message
- Link to view result in OHIF
- Summary KPIs: success rate, avg duration

---

## 8. Frontend Components (React/Next.js)

### 8.1 Shared Component: `ModelTable.tsx`

```typescript
interface ModelTableProps {
  models: AIModel[];
  loading: boolean;
  onActivate: (modelId: UUID) => void;
  onDeactivate: (modelId: UUID) => void;
  onDelete: (modelId: UUID) => void;
}

export default function ModelTable({ models, loading, onActivate, onDeactivate, onDelete }: ModelTableProps) {
  // Render table with status badges, action buttons
  // On status button click, call API PUT /api/v1/ai/models/{id}
  // Show toast on success/error
}
```

### 8.2 Shared Component: `InferenceTable.tsx`

```typescript
interface InferenceTableProps {
  jobs: InferenceJob[];
  loading: boolean;
  onRowClick: (jobId: UUID) => void;
}

export default function InferenceTable({ jobs, loading, onRowClick }: InferenceTableProps) {
  // Render table with real-time status updates
  // WebSocket listener for running jobs
  // Auto-refresh every 5s if any job is running
}
```

### 8.3 Shared Component: `InferenceProgressBar.tsx`

```typescript
interface InferenceProgressBarProps {
  jobId: UUID;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress_pct?: number;
  inference_time_ms?: number;
}

export default function InferenceProgressBar({ jobId, status, progress_pct, inference_time_ms }: InferenceProgressBarProps) {
  // WebSocket listener on /api/v1/ws/ai/{jobId}
  // Display progress bar with status label
  // Show timing and confidence after completion
}
```

---

## 9. Error Handling & Exceptions

### 9.1 New Exception Classes

**Location**: `backend/app/core/exceptions.py` (extend existing)

```python
class AIModelError(AppException):
    """Base class for AI model errors"""
    status_code = 400
    error_code = "AI_MODEL_ERROR"

class InvalidONNXFormat(AIModelError):
    """ONNX file format validation failed"""
    error_code = "INVALID_ONNX_FORMAT"

class ModelAlreadyExists(AIModelError):
    """Model with same name/version already exists"""
    error_code = "MODEL_ALREADY_EXISTS"

class InferenceJobError(AppException):
    """Base class for inference job errors"""
    status_code = 400
    error_code = "INFERENCE_JOB_ERROR"

class ModelNotActive(InferenceJobError):
    """Requested model is not in active status"""
    error_code = "MODEL_NOT_ACTIVE"

class InferenceTaskFailed(InferenceJobError):
    """Celery task execution failed"""
    status_code = 500
    error_code = "INFERENCE_TASK_FAILED"

class ORTRuntimeError(InferenceJobError):
    """ONNX Runtime execution error (GPU not available, incompatible opset, etc)"""
    status_code = 500
    error_code = "ORT_RUNTIME_ERROR"
```

---

## 10. Testing Strategy

### 10.1 Unit Tests (40 tests total)

**test_ai_model_service.py**:
- Register model: valid ONNX, invalid format, duplicate name
- List models: pagination, filtering, Redis cache hit/miss
- Activate/deactivate: enforce one active per name
- Delete: soft-delete preserves InferenceJob records

**test_inference_job_service.py**:
- Create job: validate model active, enqueue Celery task
- List/get jobs: pagination, filtering, related model fetch
- Update status: running → completed, running → failed

**test_inference_result_service.py**:
- Build DICOM SEG: input validation, metadata tags
- Store in Orthanc: multipart POST, Orthanc ID capture
- Get result URL: construct DICOMweb path

### 10.2 Integration Tests (8 tests)

**test_ai_e2e.py**:
- Register model → create job → Celery executes → WebSocket event → result retrievable
- CPU/GPU fallback detection
- Redis model cache invalidation on update
- Phase 4 normalization queue not affected by AI queue

### 10.3 Coverage Goal

- `ai_model_service.py`: 85%+
- `inference_job_service.py`: 85%+
- `inference_result_service.py`: 80%+
- `ai_inference_task.py`: 75%+ (Celery task tricky to mock)
- **Overall ai/ module**: 80%+

---

## 11. Environment Variables & Configuration

### 11.1 New Environment Variables

| Variable | Purpose | Default | Required |
|----------|---------|---------|----------|
| `MODEL_STORAGE_PATH` | Path to store ONNX/PyTorch files | `/models` | Yes |
| `CELERY_AI_CONCURRENCY` | Concurrent workers for ai_inference queue | `2` | No |
| `CELERY_AI_MAX_RETRIES` | Max retries on inference task failure | `3` | No |
| `REDIS_MODEL_CACHE_TTL` | Model list cache TTL (seconds) | `300` | No |
| `NEXT_PUBLIC_AI_ENABLED` | Feature flag: show AI in admin UI | `true` | No |
| `ONNX_INTRA_OP_NUM_THREADS` | ONNX intra-op parallelism | `4` | No |

### 11.2 docker-compose Configuration

```yaml
backend:
  environment:
    - MODEL_STORAGE_PATH=/models
    - CELERY_AI_CONCURRENCY=2
    - REDIS_MODEL_CACHE_TTL=300
  volumes:
    - ./models:/models

celery-ai:
  build: ./backend
  command: celery -A app.celery worker -Q ai_inference --concurrency 2
  environment:
    - MODEL_STORAGE_PATH=/models
    - CELERY_AI_MAX_RETRIES=3
  volumes:
    - ./models:/models
  depends_on:
    - redis
    - backend
```

---

## 12. Security Considerations

### 12.1 Authentication & Authorization

| Endpoint | Required Role | Notes |
|----------|---------------|-------|
| POST /api/v1/ai/models | admin | File upload restricted to admins |
| GET /api/v1/ai/models | radiologist+ | Model list readable by radiologists |
| PUT /api/v1/ai/models/{id} | admin | Status changes by admins only |
| DELETE /api/v1/ai/models/{id} | admin | Soft-delete by admins |
| POST /api/v1/ai/inferences | radiologist+ | Inference submission by radiologists+ |
| GET /api/v1/ai/inferences | admin | Job list visible to admins |
| GET /api/v1/ai/inferences/{id} | radiologist+ | Job creator can view own job |
| WS /api/v1/ws/ai/{id} | radiologist+ | WebSocket requires JWT + matching user |

### 12.2 File Upload Validation

- ONNX file size limit: 2GB
- Model file format check: ONNX opset >= 14
- Model name regex: `^[a-zA-Z0-9_-]{3,128}$`
- Sandbox upload directory with restricted permissions

### 12.3 Inference Task Security

- Task enqueued with authenticated user_id
- Audit log tracks all inferences
- Failed tasks logged with error details
- GPU access: no privilege escalation (Celery runs as app user)

---

## 13. Monitoring & Observability

### 13.1 Audit Log Events

| Event | Trigger | Payload |
|-------|---------|---------|
| `AI_MODEL_REGISTERED` | POST /api/v1/ai/models | { model_id, name, version, modality } |
| `AI_MODEL_ACTIVATED` | PUT status→active | { model_id, name } |
| `AI_MODEL_DEACTIVATED` | PUT status→inactive | { model_id, name } |
| `AI_MODEL_DELETED` | DELETE or PUT status→deleted | { model_id, name } |
| `AI_INFERENCE_SUBMITTED` | POST /api/v1/ai/inferences | { job_id, model_id, study_uid } |
| `AI_INFERENCE_COMPLETED` | Celery task success | { job_id, inference_time_ms, confidence_score } |
| `AI_INFERENCE_FAILED` | Celery task failure | { job_id, error_message } |

### 13.2 Metrics to Track

- Model registration count per modality
- Inference job submission rate (jobs/hour)
- Inference success rate (%)
- Average inference duration (ms) per model
- Celery queue depth (queued jobs)
- GPU availability status (yes/no/degraded)

### 13.3 Logging Strategy

```python
# Celery task logging
logger.info(f"[{job_id}] Inference started. Model: {model.name}, Series: {series_uid}")
logger.info(f"[{job_id}] ONNX session loaded. Providers: {providers}")
logger.info(f"[{job_id}] Inference completed in {duration_ms}ms. Confidence: {confidence:.2f}")
logger.error(f"[{job_id}] Inference failed: {error_msg}")
```

---

## 14. Deployment Checklist

- [ ] Database migration: `alembic upgrade head`
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Model directory created: `/models` with 777 permissions
- [ ] docker-compose updated: celery-ai service, volumes
- [ ] Backend service rebuilt: `docker compose build backend`
- [ ] AI worker started: `docker compose up -d celery-ai`
- [ ] Reference models uploaded via API
- [ ] WebSocket connectivity tested
- [ ] DICOM SEG output validated in OHIF
- [ ] Admin dashboard pages accessible
- [ ] Phase 4 normalization tests pass (regression)

---

## 15. Success Criteria & Acceptance Tests

| Criterion | Test | Expected Result |
|-----------|------|-----------------|
| Model registration | POST /api/v1/ai/models with valid ONNX | 201 Created + model stored in `/models/` |
| Model list caching | GET /api/v1/ai/models (2nd call within 300s) | <100ms latency, cache hit logged |
| Inference submission | POST /api/v1/ai/inferences | 202 Accepted + Celery task queued |
| Inference progress | Connect WebSocket, monitor job | Receive queued→running→completed messages |
| DICOM SEG output | Fetch result via GET /api/v1/ai/results/{id} | Orthanc returns valid SEG instance |
| Admin Model page | Navigate `/admin/ai/models` | List, register, activate/deactivate models |
| Admin Inference page | Navigate `/admin/ai/inferences` | Real-time job queue with live status |
| CPU fallback | Run inference on CPU-only system | Job completes successfully |
| Phase 4 regression | Run Phase 4 batch normalization tests | 100% pass rate (zero new failures) |
| Audit compliance | Query AuditLog table for AI_* events | All inferences logged with timestamps |

---

## 16. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| ONNX model incompatibility | Validate opset at upload time; clear error message |
| GPU exhaustion from large models | Limit concurrency to 2 workers; log memory usage |
| Long inference times blocking queue | Set task timeout = 5 minutes; retry logic |
| OHIF version drift | Pin OHIF version; test extension compatibility |
| Storage bloat from SEG files | Implement cleanup job: delete SEG >30 days old |
| Phase 4 interference | Dedicated Celery queue (ai_inference) + worker pool |

---

## 17. Next Phase (Phase 6 — Deferred)

- Advanced DICOM output: ANN (Annotation) format, multi-class SEG
- Model fine-tuning UI
- Statistical analytics: ROC curves, AUC, confusion matrices
- S3 object storage for models
- Multi-GPU distributed inference
- Model marketplace integration

---

**Document Version**: 1.0.0  
**Status**: Ready for implementation (Day 1)  
**Approver**: CTO/Tech Lead  
**Last Updated**: 2026-05-14
