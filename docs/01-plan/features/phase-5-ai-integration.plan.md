# Phase 5: AI Model Integration and Inference Pipeline

> **Summary**: End-to-end AI inference pipeline for OpenPACS — model registration, async Celery-based inference, DICOM SEG/SR output, real-time WebSocket monitoring, and an admin dashboard for model management.
>
> **Project**: OpenPACS
> **Version**: 5.0.0
> **Author**: Product Manager
> **Date**: 2026-05-14
> **Status**: Draft — Pending CTO Approval

---

## 1. Overview

### 1.1 Purpose

Phase 5 adds production-grade medical AI capabilities to OpenPACS. Radiologists and clinicians can trigger AI inference directly from the OHIF viewer while administrators manage model versions and monitor the inference queue from the admin dashboard. AI results are persisted as standard DICOM objects (SEG/SR/SC) inside Orthanc so they are immediately available for review alongside the original study.

### 1.2 Background

OpenPACS phases 1–4 established the full DICOM server and normalization pipeline (Orthanc + FastAPI + Celery + PostgreSQL + Redis). The Celery worker infrastructure and WebSocket notification patterns introduced in Phase 4 are directly reused here for inference task orchestration. The admin Next.js dashboard (`admin/`) follows the patterns from Phase 4.5 (client components, `apiFetch`, JWT auth, WebSocket).

The CLAUDE.md roadmap lists Phase 5 as: "AI model management, inference pipeline, dashboard" targeting 8 API endpoints. This document extends that target to 8–10 endpoints to cover WebSocket and result retrieval.

### 1.3 Predecessor Phase Summary

| Phase | Content | Status |
|-------|---------|--------|
| Phase 4 | Batch normalization engine, Celery workers, WebSocket | Completed |
| Phase 4.5 | Frontend admin dashboard for batch normalization | Ready for staging |
| **Phase 5** | AI model registration, async inference, DICOM output | **This document** |

### 1.4 Related Documents

- Phase 4 Plan: `docs/01-plan/features/phase-4-normalizer.plan.md`
- Phase 4.5 Plan: `docs/01-plan/features/phase-4.5-frontend-dashboard.plan.md`
- Project context: `CLAUDE.md`

---

## 2. Scope

### 2.1 In Scope

- [ ] AI model registration API (ONNX/PyTorch, name, version, modality, GPU flag)
- [ ] Model versioning with active-version toggling
- [ ] Async Celery inference task with DICOM SEG/SR/SC output stored in Orthanc
- [ ] Real-time inference job tracking via WebSocket
- [ ] Inference job listing, filtering by status, and detailed job view
- [ ] Result retrieval API returning DICOM SEG/SR file references
- [ ] CPU-based ONNX Runtime fallback for GPU-less clinics
- [ ] Redis caching of model list (300 s TTL) and Celery task queuing
- [ ] Admin dashboard pages: Model Management and Inference Monitor
- [ ] OHIF viewer integration: "Run AI" button triggering inference from study view
- [ ] AI output metadata: model_name, model_version, inference_time_ms, confidence_score

### 2.2 Out of Scope (Defer to Phase 6+)

- Model fine-tuning or retraining UI
- Advanced statistical analytics (ROC curves, AUC metrics, confusion matrices)
- Multi-GPU distributed inference
- Model marketplace or third-party model registry integration
- Federated learning
- DICOM ANN (Annotation) output format (SR and SEG are sufficient for v1)
- Mobile viewer AI trigger

---

## 3. Requirements

### 3.1 User Stories

| ID | Actor | Story | Priority |
|----|-------|-------|----------|
| US-01 | Admin | Upload an ONNX model file and register it with modality, version, and GPU requirements | Must |
| US-02 | Admin | Set one model version as active and deactivate others for the same model name | Must |
| US-03 | Radiologist | From the OHIF study viewer, select an AI model and trigger inference on the current study | Must |
| US-04 | System | Process the inference request asynchronously via Celery and persist results as DICOM SEG/SR in Orthanc | Must |
| US-05 | Radiologist | Track inference progress in real time via a WebSocket-connected progress indicator | Must |
| US-06 | Admin | View the inference queue with filters by status (queued/running/completed/failed) and by model | Must |
| US-07 | Admin | Inspect per-job details: model used, study/series, duration, confidence score, and error message on failure | Must |
| US-08 | Radiologist | Open AI results (DICOM SEG overlay) alongside the original study in the OHIF viewer | Should |
| US-09 | Admin | See per-model success rate and average inference time on the Model Management page | Should |
| US-10 | Clinic (no GPU) | System automatically falls back to CPU ONNX Runtime when no GPU is available | Must |

### 3.2 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | POST /api/v1/ai/models — register model with file upload (multipart), store ONNX/PT file, persist AIModel record | Must | Pending |
| FR-02 | GET /api/v1/ai/models — list models with filters (modality, status, name) and pagination | Must | Pending |
| FR-03 | PUT /api/v1/ai/models/{model_id} — update metadata; activate/deactivate version | Must | Pending |
| FR-04 | DELETE /api/v1/ai/models/{model_id} — soft-delete (mark inactive, preserve InferenceJob history) | Should | Pending |
| FR-05 | POST /api/v1/ai/inferences — create inference job, enqueue Celery task, return job_id | Must | Pending |
| FR-06 | GET /api/v1/ai/inferences — list jobs with pagination and filter by status, model_id, study_id | Must | Pending |
| FR-07 | GET /api/v1/ai/inferences/{inference_id} — job details including result metadata and error message | Must | Pending |
| FR-08 | GET /api/v1/ai/results/{inference_id} — return DICOM file path or redirect to Orthanc DICOMweb URL | Must | Pending |
| FR-09 | WebSocket /api/v1/ws/ai/{inference_id} — stream inference progress events (queued→running→completed/failed) | Must | Pending |
| FR-10 | Celery task: fetch DICOM series from Orthanc, run ONNX inference, produce DICOM SEG/SR, store back in Orthanc | Must | Pending |
| FR-11 | CPU/GPU auto-detection: use ONNX Runtime GPU provider if available, fall back to CPU | Must | Pending |
| FR-12 | Redis cache: model list cached 300 s; invalidated on model create/update/delete | Should | Pending |
| FR-13 | Admin dashboard — Model Management page: list, register, activate/deactivate models | Must | Pending |
| FR-14 | Admin dashboard — Inference Monitor page: queue table, real-time status, per-model metrics | Must | Pending |
| FR-15 | OHIF extension: "Run AI" toolbar button that opens model selector and submits inference request | Should | Pending |

### 3.3 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| Performance | Inference job submission API responds < 500 ms (task is async) | API response time |
| Performance | Model list API (cached) responds < 100 ms | Redis hit latency |
| Scalability | Celery worker can process 5 concurrent inference tasks without degrading Phase 4 normalization | Load test |
| Reliability | Failed inference task retried up to 3 times with exponential back-off before marking as failed | Celery retry config |
| Security | Model file upload restricted to admin role (JWT RBAC); inference trigger restricted to radiologist+ | JWT middleware |
| Storage | ONNX model files stored on server filesystem; path reference stored in DB; 5 GB cap per model | Filesystem check |
| Compliance | AI results stored as standard DICOM (SEG/SR) with metadata tag ModelName (0008,103E) | DICOM validation |
| Observability | All inference events (start, complete, fail) written to AuditLog table | DB audit query |
| Backward Compat | Phase 4 batch normalization endpoints and Celery queues must not be affected | Integration test |

---

## 4. API Specification

### 4.1 Endpoint Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/v1/ai/models | Admin | Register a new AI model (multipart upload) |
| GET | /api/v1/ai/models | Radiologist+ | List models with filtering and pagination |
| PUT | /api/v1/ai/models/{model_id} | Admin | Update model metadata or toggle active version |
| DELETE | /api/v1/ai/models/{model_id} | Admin | Soft-delete model |
| POST | /api/v1/ai/inferences | Radiologist+ | Submit inference job |
| GET | /api/v1/ai/inferences | Admin | List inference jobs with filters |
| GET | /api/v1/ai/inferences/{inference_id} | Radiologist+ | Job detail and result metadata |
| GET | /api/v1/ai/results/{inference_id} | Radiologist+ | Retrieve DICOM SEG/SR reference or redirect |
| WS | /api/v1/ws/ai/{inference_id} | Radiologist+ | Real-time inference progress stream |

### 4.2 Key Request/Response Schemas

**POST /api/v1/ai/models** (multipart/form-data)
```
name         string   required   Human-readable model name (e.g., "lung-nodule-v1")
version      string   required   Semantic version (e.g., "1.0.0")
modality     string   required   DICOM modality target (CT, MR, CR, DX, ...)
description  string   optional   Clinical purpose description
gpu_required boolean  required   Whether GPU is required (false = CPU-only ONNX)
file         binary   required   ONNX or PyTorch model file
```

**Response 201 Created**
```json
{
  "model_id": "uuid",
  "name": "lung-nodule-v1",
  "version": "1.0.0",
  "modality": "CT",
  "gpu_required": false,
  "status": "inactive",
  "file_path": "/models/lung-nodule-v1_1.0.0.onnx",
  "created_at": "2026-05-14T09:00:00Z"
}
```

**POST /api/v1/ai/inferences**
```json
{
  "model_id": "uuid",
  "study_instance_uid": "1.2.840...",
  "series_instance_uid": "1.2.840..."
}
```

**Response 202 Accepted**
```json
{
  "inference_id": "uuid",
  "job_id": "celery-task-id",
  "status": "queued",
  "model_id": "uuid",
  "study_instance_uid": "1.2.840...",
  "created_at": "2026-05-14T09:01:00Z"
}
```

**WebSocket Events (server → client)**
```json
{ "event": "queued",    "inference_id": "uuid", "timestamp": "..." }
{ "event": "running",   "inference_id": "uuid", "progress_pct": 40, "timestamp": "..." }
{ "event": "completed", "inference_id": "uuid", "result_path": "...", "inference_time_ms": 1230, "confidence_score": 0.91, "timestamp": "..." }
{ "event": "failed",    "inference_id": "uuid", "error": "ONNX runtime error", "timestamp": "..." }
```

---

## 5. Database Schema

### 5.1 New Tables

**ai_models**
```sql
CREATE TABLE ai_models (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128)  NOT NULL,
    version         VARCHAR(32)   NOT NULL,
    modality        VARCHAR(16)   NOT NULL,
    description     TEXT,
    file_path       VARCHAR(512)  NOT NULL,
    gpu_required    BOOLEAN       NOT NULL DEFAULT FALSE,
    status          VARCHAR(16)   NOT NULL DEFAULT 'inactive',  -- active | inactive | deleted
    created_by      UUID          REFERENCES users(id),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);
```

**inference_jobs**
```sql
CREATE TABLE inference_jobs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id             UUID          NOT NULL REFERENCES ai_models(id),
    study_instance_uid   VARCHAR(64)   NOT NULL,
    series_instance_uid  VARCHAR(64),
    status               VARCHAR(16)   NOT NULL DEFAULT 'queued',  -- queued | running | completed | failed
    celery_task_id       VARCHAR(128),
    error_message        TEXT,
    inference_time_ms    INTEGER,
    confidence_score     NUMERIC(5,4),
    created_by           UUID          REFERENCES users(id),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
```

**inference_results**
```sql
CREATE TABLE inference_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID          NOT NULL REFERENCES inference_jobs(id),
    dicom_type      VARCHAR(8)    NOT NULL,  -- SEG | SR | SC
    orthanc_id      VARCHAR(128),            -- Orthanc instance UID after storage
    file_path       VARCHAR(512),            -- local temp path before Orthanc upload
    metadata        JSONB,                   -- model_name, version, confidence, etc.
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
```

### 5.2 Indexes

```sql
CREATE INDEX idx_inference_jobs_status    ON inference_jobs(status);
CREATE INDEX idx_inference_jobs_model_id  ON inference_jobs(model_id);
CREATE INDEX idx_inference_jobs_study_uid ON inference_jobs(study_instance_uid);
CREATE INDEX idx_ai_models_status        ON ai_models(status);
```

### 5.3 Alembic Migration

A single migration file `add_ai_inference_tables.py` covers all three tables and indexes.

---

## 6. Architecture Decisions

### 6.1 Project Level

**Enterprise** — strict layer separation (router → service → repository → Celery task) consistent with existing FastAPI codebase.

### 6.2 Key Architecture Decisions

| Decision | Options Considered | Selected | Rationale |
|----------|--------------------|----------|-----------|
| Inference runtime | ONNX Runtime, TorchScript, TensorRT | ONNX Runtime | Vendor-neutral, CPU fallback built-in, no CUDA dependency for CPU clinics |
| Task queue | Celery (existing) vs new queue | Celery (existing) | Phase 4 already runs Celery workers; adding a dedicated `ai_inference` queue avoids normalization contention |
| AI output format | DICOM SEG, SR, SC | SEG primary, SR for measurements | OHIF v3 natively renders DICOM SEG overlays; SR carries structured findings |
| Model storage | Object store (S3) vs filesystem | Filesystem (v1) | Single-institution deployment; S3 migration deferred to v2.0 |
| Real-time updates | WebSocket (existing) vs polling | WebSocket (existing) | Phase 4 already implemented WebSocket manager; reuse pattern |
| Model list caching | Redis (existing) vs DB query | Redis 300 s TTL | Model list is read-heavy; invalidation on write is straightforward |
| Frontend routing | New Next.js pages in `admin/` | New pages in `admin/` | Follows Phase 4.5 pattern; no new frontend service needed |

### 6.3 Celery Queue Isolation

```
celery_queues:
  normalization  — Phase 4 batch normalization tasks (unchanged)
  ai_inference   — Phase 5 inference tasks (new, dedicated worker pool)
```

Workers for `ai_inference` are launched with `--concurrency 2` by default (configurable) to avoid memory contention with loaded ONNX models.

### 6.4 CPU/GPU Fallback Logic

```python
import onnxruntime as ort

def get_ort_session(model_path: str, gpu_required: bool) -> ort.InferenceSession:
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if not gpu_required:
        providers = ["CPUExecutionProvider"]
    return ort.InferenceSession(model_path, providers=providers)
```

If `gpu_required=True` but no GPU is present, ONNX Runtime silently falls back to CPU — behavior logged as a warning in the inference task.

### 6.5 DICOM SEG Output Pipeline

```
1. Fetch DICOM series from Orthanc REST API → pydicom pixel arrays
2. Run ONNX inference → segmentation mask (numpy array)
3. Construct DICOM SEG using pydicom + highdicom library
4. POST SEG to Orthanc /instances
5. Record Orthanc instance UID in inference_results
6. Notify WebSocket clients of completion
```

---

## 7. Integration Points

### 7.1 OHIF Viewer Extension

- Location: OHIF custom extension (existing or new `ai-extension`)
- Trigger: "Run AI" button in toolbar, visible when user role is radiologist+
- Flow: Opens modal → selects active model for current modality → POSTs to /api/v1/ai/inferences → opens WebSocket → shows progress bar → on completion shows link to SEG in viewer

### 7.2 Admin Dashboard Pages (Next.js `admin/`)

**Model Management** (`/admin/ai/models`)
- Table: model name, version, modality, status badge, GPU flag, created date
- Actions: Register (upload form), Activate/Deactivate, Delete
- Metrics per model: total inference count, success rate, avg inference time

**Inference Monitor** (`/admin/ai/inferences`)
- Real-time queue table with status badges (queued/running/completed/failed)
- Filters: status, model, date range
- Row click → job detail drawer: study UID, series UID, result DICOM link, error message
- Summary cards: total today, success rate, avg duration

### 7.3 Orthanc Integration

- Fetch series pixels: `GET /dicom-web/studies/{uid}/series/{uid}/instances` via existing httpx client with Basic Auth header
- Store AI results: `POST /instances` multipart with generated DICOM file

### 7.4 Existing Infrastructure Reuse

| Component | Phase 4 Usage | Phase 5 Usage |
|-----------|---------------|---------------|
| Celery | normalization tasks | ai_inference tasks (separate queue) |
| Redis | task results, WebSocket pub | model list cache + task results |
| WebSocket Manager | batch progress | inference progress (same pattern) |
| JWT RBAC middleware | all endpoints | all new endpoints |
| AuditLog table | normalization events | inference events |

---

## 8. Success Criteria

### 8.1 Definition of Done

- [ ] All Must-priority functional requirements implemented (FR-01 to FR-12)
- [ ] Admin dashboard: Model Management and Inference Monitor pages functional
- [ ] 2 reference ONNX models registered: lung nodule detection (CT), fracture detection (CR/DX)
- [ ] Real-time inference monitoring via WebSocket confirmed working
- [ ] DICOM SEG result retrievable in OHIF viewer overlay
- [ ] CPU fallback confirmed working on test environment without GPU
- [ ] Unit tests: >= 80% coverage on ai/ module
- [ ] Integration test: full end-to-end (register → infer → retrieve SEG) passing
- [ ] Phase 4 batch normalization endpoints: zero regressions (existing tests all pass)
- [ ] Code review completed and merged to main

### 8.2 Quality Metrics

| Metric | Target |
|--------|--------|
| Inference job submission latency | < 500 ms |
| Model list (cached) latency | < 100 ms |
| DICOM SEG produced for CT lung series | Confirmed loadable in OHIF |
| Celery task success rate (mock model) | >= 95% |
| Test coverage (ai/ module) | >= 80% |
| Phase 4 regression test pass rate | 100% |

---

## 9. Estimated Timeline

**Total: 5–7 days**

| Day | Tasks |
|-----|-------|
| 1 | DB migration (ai_models, inference_jobs, inference_results); AIModel CRUD API (FR-01–04); Redis cache |
| 2 | InferenceJob API (FR-05–08); Celery task scaffold with mock ONNX inference; CPU/GPU provider logic |
| 3 | DICOM SEG/SR output using pydicom + highdicom; Orthanc store integration; result retrieval API |
| 4 | WebSocket inference progress (FR-09); end-to-end integration test with reference models |
| 5 | Admin dashboard — Model Management page (`/admin/ai/models`) |
| 6 | Admin dashboard — Inference Monitor page (`/admin/ai/inferences`); WebSocket live table |
| 7 | OHIF "Run AI" extension button; full regression test; documentation; staging deploy |

---

## 10. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| highdicom DICOM SEG construction is complex | High | Medium | Prototype SEG construction on day 3 with simple binary mask; defer multi-class SEG to Phase 6 |
| ONNX Runtime incompatibility with model file | High | Low | Validate model format at upload time (FR-01); return clear error if unsupported opset |
| Celery memory spike loading large ONNX models | Medium | Medium | Set `--max-tasks-per-child 10` on ai_inference worker; model loaded per-task, not globally |
| OHIF extension API change (version drift) | Medium | Low | Pin OHIF version; limit extension to toolbar button and iframe-safe postMessage |
| Phase 4 normalization worker contention | Medium | Low | Dedicated `ai_inference` queue with separate worker pool (isolated by Celery) |
| Storage growth from DICOM SEG files | Low | High | Add cleanup job: delete SEG files older than 30 days from filesystem after Orthanc ingestion |
| GPU not available on production server | Low | High | CPU fallback is default behavior; log warning if gpu_required=True on CPU-only host |

---

## 11. Deployment Strategy

### 11.1 Prerequisites

- `onnxruntime` added to `backend/requirements.txt` (CPU version by default: `onnxruntime==1.17.x`)
- `highdicom` added to `backend/requirements.txt`
- Alembic migration run before starting updated backend service
- `/models/` directory created on server (host-mounted volume): `mkdir -p /home/deploy/openpacs/models`
- docker-compose volume mount: `./models:/models` added to backend service

### 11.2 docker-compose Changes

```yaml
backend:
  volumes:
    - ./models:/models        # AI model file storage (new)
  environment:
    - CELERY_AI_CONCURRENCY=2
    - MODEL_STORAGE_PATH=/models
```

New Celery worker for AI queue (can run as separate container or extend existing worker command):
```yaml
celery-ai:
  build: ./backend
  command: celery -A app.celery worker -Q ai_inference --concurrency 2
  volumes:
    - ./models:/models
```

### 11.3 Deployment Steps

```bash
# 1. Upload backend changes
scp -P 819 -r backend/app/ deploy@198.51.100.73:/home/deploy/openpacs/backend/app/

# 2. Create models directory on server
ssh deploy@198.51.100.73 -p 819 "mkdir -p /home/deploy/openpacs/models"

# 3. Full rebuild (new requirements)
ssh deploy@198.51.100.73 -p 819 \
  "cd /home/deploy/hospital-run/infra/docker && docker compose build backend && docker compose up -d backend"

# 4. Run Alembic migration
ssh deploy@198.51.100.73 -p 819 \
  "cd /home/deploy/hospital-run/infra/docker && docker compose exec backend alembic upgrade head"

# 5. Start AI inference worker
ssh deploy@198.51.100.73 -p 819 \
  "cd /home/deploy/hospital-run/infra/docker && docker compose up -d celery-ai"

# 6. Verify health
curl -sk https://his.example.org/pacs-api/health
curl -sk https://his.example.org/pacs-api/api/v1/ai/models
```

### 11.4 Rollback Plan

If the migration or service fails:
1. Roll back Alembic: `alembic downgrade -1`
2. Restart previous backend image: `docker compose up -d --no-build backend`
3. Phase 4 normalization is unaffected (separate queue, separate tables)

---

## 12. Environment Variables

| Variable | Purpose | Scope | Required |
|----------|---------|-------|----------|
| `MODEL_STORAGE_PATH` | Filesystem path for ONNX model files | Server | Yes |
| `CELERY_AI_CONCURRENCY` | Number of concurrent AI inference workers | Server | No (default: 2) |
| `CELERY_AI_MAX_RETRIES` | Max inference task retries on failure | Server | No (default: 3) |
| `REDIS_MODEL_CACHE_TTL` | Model list cache TTL in seconds | Server | No (default: 300) |
| `NEXT_PUBLIC_AI_ENABLED` | Feature flag to show AI button in admin UI | Client | No (default: true) |

---

## 13. MoSCoW Prioritization Summary

| Priority | Items |
|----------|-------|
| **Must** | Model registration API, model versioning, async Celery inference, DICOM SEG output, WebSocket tracking, inference job list/detail, CPU ONNX fallback, admin Model Management page, admin Inference Monitor page |
| **Should** | DICOM SR output, OHIF "Run AI" extension, per-model success rate metrics, Redis model list cache, soft-delete endpoint |
| **Could** | DICOM SC (Secondary Capture) output, inference batch mode (multiple series at once), confidence threshold filtering |
| **Won't** (Phase 6+) | Model retraining UI, ROC/AUC analytics, multi-GPU distributed inference, model marketplace, federated learning |

---

## 14. Next Steps

1. [ ] CTO review and approval of this Plan document
2. [ ] Create Design document: `docs/02-design/features/phase-5-ai-integration.design.md`
3. [ ] Prototype DICOM SEG construction with highdicom (risk mitigation for Day 3)
4. [ ] Confirm reference model files (lung nodule, fracture) available in ONNX format
5. [ ] Begin implementation following timeline in Section 9

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-14 | Initial draft | Product Manager |
