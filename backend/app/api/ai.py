"""AI model management and inference API."""
import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.cache import get_cache_manager
from app.core.cache_config import CACHE_KEY_MODELS, CACHE_TTL_MODELS, CACHE_PATTERN_MODELS
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import ClinicalPHIReadRoles, ClinicalWriteRoles, RequireRole, get_current_user
from app.models.ai import (
    AIModel, ClinicalUse, InferenceJob, JobPriority, JobStatus, ModelStatus, ModelType,
)
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ── Schemas ──

class ModelCreate(BaseModel):
    name: str
    version: str
    description: str | None = None
    model_type: ModelType
    clinical_use: ClinicalUse = ClinicalUse.RESEARCH
    modalities: str
    body_parts: str | None = None
    endpoint_url: str | None = None
    model_path: str | None = None
    checksum_sha256: str | None = None  # 로컬 모델 파일 sha256 (설정 시 로드 전 대조)
    docker_image: str | None = None
    input_config: dict | None = None
    timeout_seconds: int = 120
    certification: str | None = None
    manufacturer: str | None = None


class InferenceRequest(BaseModel):
    model_id: str | None = None
    model_name: str | None = None
    study_instance_uid: str
    series_instance_uid: str | None = None
    orthanc_study_id: str | None = None
    priority: JobPriority = JobPriority.NORMAL
    parameters: dict | None = None


def _model_response(m: AIModel) -> dict:
    return {
        "id": str(m.id),
        "name": m.name,
        "version": m.version,
        "description": m.description,
        "model_type": m.model_type,
        "status": m.status,
        "clinical_use": m.clinical_use,
        "modalities": m.modalities,
        "body_parts": m.body_parts,
        "endpoint_url": m.endpoint_url,
        "model_path": m.model_path,
        "certification": m.certification,
        "manufacturer": m.manufacturer,
        "is_active": m.is_active,
        "total_runs": m.total_runs,
        "successful_runs": m.successful_runs,
        "avg_inference_time": m.avg_inference_time,
        "created_at": m.created_at.isoformat(),
    }


def _job_response(j: InferenceJob) -> dict:
    return {
        "id": str(j.id),
        "model_id": str(j.model_id),
        "model_name": j.model_name,
        "study_instance_uid": j.study_instance_uid,
        "series_instance_uid": j.series_instance_uid,
        "patient_id": j.patient_id,
        "modality": j.modality,
        "status": j.status,
        "priority": j.priority,
        "progress": j.progress,
        "error_message": j.error_message,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "inference_time_ms": j.inference_time_ms,
        "results": j.results,
        "findings_count": j.findings_count,
        "max_confidence": j.max_confidence,
        "is_critical": j.is_critical,
        "trigger_type": j.trigger_type,
        "created_at": j.created_at.isoformat(),
    }


# ── Model Management ──

@router.get("/models")
async def list_models(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    model_type: ModelType | None = Query(None),
    modality: str | None = Query(None),
    active_only: bool = Query(True),
):
    """List registered AI models. Results cached for 24 hours."""
    # Try to get from cache (only for default filters)
    cache_mgr = get_cache_manager()
    cache_key = CACHE_KEY_MODELS + ":list"

    if not model_type and not modality and active_only:
        # Default query - use cache
        try:
            cached_data = await cache_mgr.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception:
            pass

    # Cache miss or filtered query - query database
    query = select(AIModel).order_by(AIModel.name)
    if model_type:
        query = query.where(AIModel.model_type == model_type)
    if modality:
        query = query.where(AIModel.modalities.contains(modality))
    if active_only:
        query = query.where(AIModel.is_active == True)

    result = await db.execute(query)
    models = result.scalars().all()
    response = {"count": len(models), "models": [_model_response(m) for m in models]}

    # Cache the default query result
    if not model_type and not modality and active_only:
        try:
            await cache_mgr.set(cache_key, json.dumps(response, default=str), ttl=CACHE_TTL_MODELS)
        except Exception:
            pass

    return response


@router.post("/models", status_code=status.HTTP_201_CREATED)
@AuditLogger.log("AI_MODEL_REGISTERED", "AIModel")
async def register_model(
    body: ModelCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Register a new AI model. Admin only. Invalidates model cache."""
    existing = await db.execute(select(AIModel).where(AIModel.name == body.name))
    if existing.scalar_one_or_none():
        raise ConflictError(message="Model name already exists")

    # 추론 픽셀이 원외로 나가지 않도록 endpoint host를 등록 시점에 검증
    # (실행 시점 가드 ai_worker._endpoint_allowed와 동일 기준 — INV-PHI-03)
    if body.endpoint_url:
        from app.services.ai_worker import _endpoint_allowed
        if not _endpoint_allowed(body.endpoint_url):
            raise ValidationError(
                message="endpoint_url host가 허용 목록에 없습니다 "
                        "(ai_server_url host/localhost/AI_ENDPOINT_ALLOWLIST만 허용)")

    model = AIModel(**body.model_dump())
    db.add(model)
    await db.commit()
    await db.refresh(model)

    # Invalidate model cache
    cache_mgr = get_cache_manager()
    if cache_mgr.available:
        try:
            await cache_mgr.delete(CACHE_KEY_MODELS + ":list")
        except Exception:
            pass

    return _model_response(model)


@router.get("/models/{model_id}")
async def get_model(
    model_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise NotFoundError("AI model", str(model_id))
    return _model_response(model)


@router.patch("/models/{model_id}/toggle")
@AuditLogger.log("AI_MODEL_TOGGLED", "AIModel")
async def toggle_model(
    model_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Activate/deactivate a model. Invalidates model cache."""
    result = await db.execute(select(AIModel).where(AIModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise NotFoundError("AI model", str(model_id))

    model.is_active = not model.is_active
    model.status = ModelStatus.ACTIVE if model.is_active else ModelStatus.INACTIVE
    await db.commit()

    # Invalidate model cache
    cache_mgr = get_cache_manager()
    if cache_mgr.available:
        try:
            await cache_mgr.delete(CACHE_KEY_MODELS + ":list")
        except Exception:
            pass

    return {"id": str(model.id), "name": model.name, "is_active": model.is_active}


# ── Inference ──

@router.post("/inference")
@AuditLogger.log("AI_INFERENCE_SUBMITTED", "InferenceJob")
async def submit_inference(
    body: InferenceRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalWriteRoles)],
):
    """Submit an AI inference job."""
    # Find model
    if body.model_id:
        result = await db.execute(select(AIModel).where(AIModel.id == body.model_id))
    elif body.model_name:
        result = await db.execute(select(AIModel).where(AIModel.name == body.model_name))
    else:
        raise ValidationError("model_id or model_name required")

    model = result.scalar_one_or_none()
    if not model:
        raise NotFoundError("AI model")
    if not model.is_active:
        raise ValidationError("Model is inactive")

    # Create job
    job = InferenceJob(
        model_id=model.id,
        model_name=model.name,
        study_instance_uid=body.study_instance_uid,
        series_instance_uid=body.series_instance_uid,
        orthanc_study_id=body.orthanc_study_id,
        priority=body.priority,
        parameters=body.parameters,
        trigger_type="manual",
        requested_by=user.username,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Queue to Celery (if available)
    try:
        from app.services.ai_worker import run_inference
        run_inference.delay(str(job.id))
    except Exception:
        pass  # Worker not running — job stays in QUEUED

    return _job_response(job)


class InferenceFeedback(BaseModel):
    decision: str  # "accepted" | "dismissed"


# on-demand AI 수용률 추적 — 판독의가 수동(on-demand) 추론 결과를 채택/기각했는지
# 기록. 거버넌스 롤업이 trigger_type='manual' + acceptance로 수용률을 집계한다.
# 스크리닝 ack(api/screening.py)의 on-demand 대응물.
_FEEDBACK_DDL = (
    "ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS acceptance TEXT",
    "ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS acceptance_by TEXT",
    "ALTER TABLE inference_jobs ADD COLUMN IF NOT EXISTS acceptance_at TIMESTAMPTZ",
)


@router.post("/inference/{job_id}/feedback", summary="on-demand 추론 결과 수용/기각")
async def inference_feedback(
    job_id: UUID,
    body: InferenceFeedback,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN)),
):
    decision = (body.decision or "").lower()
    if decision not in ("accepted", "dismissed"):
        raise ValidationError("decision must be 'accepted' or 'dismissed'")
    # acceptance 컬럼은 startup 마이그레이션(schema_migrations._FEEDBACK_DDL)이 보장 —
    # 매 콜 ALTER(락 경합) 제거.
    res = await db.execute(text("""
        UPDATE inference_jobs
        SET acceptance = :d, acceptance_by = :by, acceptance_at = now()
        WHERE id = :id
        RETURNING model_name
    """), {"d": decision, "by": user.username, "id": str(job_id)})
    row = res.first()
    if not row:
        raise NotFoundError("InferenceJob")
    await db.commit()
    return {"job_id": str(job_id), "decision": decision, "model_name": row[0]}


@router.get("/jobs")
async def list_jobs(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalPHIReadRoles)],
    study_uid: str | None = Query(None),
    model_name: str | None = Query(None),
    job_status: JobStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List inference jobs."""
    query = select(InferenceJob).order_by(InferenceJob.created_at.desc())
    if study_uid:
        query = query.where(InferenceJob.study_instance_uid == study_uid)
    if model_name:
        query = query.where(InferenceJob.model_name == model_name)
    if job_status:
        query = query.where(InferenceJob.status == job_status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()
    result = await db.execute(query.offset(offset).limit(limit))
    jobs = result.scalars().all()

    return {"total": total, "count": len(jobs), "results": [_job_response(j) for j in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalPHIReadRoles)],
):
    result = await db.execute(select(InferenceJob).where(InferenceJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Inference job", str(job_id))
    return _job_response(job)


@router.get("/ollama-health")
async def ollama_health(user: Annotated[User, Depends(get_current_user)]):
    """Check Ollama server status and available models."""
    from app.services.ollama_inference import OllamaInferenceEngine
    engine = OllamaInferenceEngine()
    return engine.check_health()


# ── Dashboard ──

@router.get("/dashboard")
async def ai_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """AI performance dashboard."""
    # Models
    models_result = await db.execute(select(AIModel))
    models = models_result.scalars().all()

    # Status counts — DB-side GROUP BY (avoid loading the whole inference_jobs table)
    sc = await db.execute(select(InferenceJob.status, func.count()).group_by(InferenceJob.status))
    status_counts = {}
    total_jobs = 0
    for st, cnt in sc:
        status_counts[st] = cnt
        total_jobs += cnt

    # Per-model aggregates — DB-side (PostgreSQL aggregate FILTER). Compare against
    # the enum member so SQLAlchemy binds the stored NAME correctly.
    agg = await db.execute(
        select(
            InferenceJob.model_id,
            func.count().label("total"),
            func.count().filter(InferenceJob.status == JobStatus.COMPLETED).label("completed"),
            func.count().filter(InferenceJob.status == JobStatus.FAILED).label("failed"),
            func.avg(InferenceJob.inference_time_ms)
                .filter(InferenceJob.status == JobStatus.COMPLETED).label("avg_ms"),
            func.count()
                .filter(InferenceJob.status == JobStatus.COMPLETED, InferenceJob.is_critical.is_(True))
                .label("critical"),
        ).group_by(InferenceJob.model_id)
    )
    by_model = {row.model_id: row for row in agg}

    model_stats = []
    for m in models:
        r = by_model.get(m.id)
        model_stats.append({
            "name": m.name,
            "version": m.version,
            "description": m.description,
            "model_type": m.model_type,
            "clinical_use": m.clinical_use,
            "manufacturer": m.manufacturer,
            "modalities": m.modalities,
            "body_parts": m.body_parts,
            "certification": m.certification,
            "is_active": m.is_active,
            "total_jobs": r.total if r else 0,
            "completed": r.completed if r else 0,
            "failed": r.failed if r else 0,
            "avg_inference_ms": round(r.avg_ms or 0) if r else 0,
            "critical_findings": r.critical if r else 0,
        })

    return {
        "total_models": len(models),
        "active_models": sum(1 for m in models if m.is_active),
        "total_jobs": total_jobs,
        "jobs_by_status": status_counts,
        "models": model_stats,
    }
