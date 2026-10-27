"""InferenceJobService - Manage inference jobs and Celery task queuing.

Responsibilities:
- Create inference jobs from submitted requests
- Track job status through lifecycle (queued → running → completed/failed)
- Queue Celery tasks for async inference execution
- Update job status from task results
- Handle job cancellation and retry logic

Note: inference execution is delegated to ``app.services.ai_worker.run_inference``
(the same worker used by the ``/api/v1/ai/inference`` endpoint), so both REST
surfaces share one proven inference pipeline (ONNX / Ollama / statistical fallback).
"""
import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIModel, InferenceJob, InferenceResult, JobStatus
from app.schemas.ai import (
    InferenceJobDetailResponse,
    InferenceJobResponse,
    InferenceResultResponse,
)
from app.core.exceptions import (
    InferenceJobError,
    ModelNotAvailable,
    NotFoundError,
)

logger = logging.getLogger(__name__)


def _to_response(job: InferenceJob) -> InferenceJobResponse:
    """Map an InferenceJob ORM row to the API response schema.

    Explicit mapping avoids ORM/schema field drift (the model stores
    ``max_confidence``/``requested_by`` while the schema exposes
    ``confidence_score``/``created_by``).
    """
    return InferenceJobResponse(
        id=job.id,
        model_id=job.model_id,
        study_instance_uid=job.study_instance_uid,
        series_instance_uid=job.series_instance_uid,
        status=str(job.status.value if hasattr(job.status, "value") else job.status),
        celery_task_id=job.celery_task_id,
        error_message=job.error_message,
        inference_time_ms=job.inference_time_ms,
        confidence_score=job.max_confidence,
        created_at=job.created_at,
        created_by=None,
    )


class InferenceJobService:
    """Service for managing AI inference jobs and Celery task queuing."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit_job(
        self,
        request,
        user_id: UUID,
    ) -> InferenceJobResponse:
        """Submit a new inference job for async processing.

        Raises:
            ModelNotAvailable: If model doesn't exist or is inactive
            InferenceJobError: If job submission fails
        """
        # Step 1: Verify model exists and is active
        result = await self.db.execute(
            select(AIModel).where(AIModel.id == request.model_id)
        )
        model = result.scalar_one_or_none()
        if not model or not model.is_active:
            raise ModelNotAvailable(str(request.model_id))

        # Step 2: Create inference job record
        job = InferenceJob(
            model_id=model.id,
            model_name=model.name,
            study_instance_uid=request.study_instance_uid,
            series_instance_uid=request.series_instance_uid,
            status=JobStatus.QUEUED,
            trigger_type="manual",
            requested_by=str(user_id),
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        logger.info(
            "Inference job created",
            extra={
                "job_id": str(job.id),
                "model_id": str(model.id),
                "study_uid": request.study_instance_uid,
                "user_id": str(user_id),
            },
        )

        # Step 3: Queue Celery task on the shared worker
        try:
            from app.services.ai_worker import run_inference

            task = run_inference.delay(str(job.id))
            job.celery_task_id = task.id
            await self.db.commit()
            logger.info(f"Celery task queued: {task.id} for job {job.id}")
        except Exception as e:
            logger.error(f"Failed to queue Celery task: {e}", exc_info=True)
            job.status = JobStatus.FAILED
            job.error_message = f"Failed to queue inference task: {e}"
            await self.db.commit()
            raise InferenceJobError(
                f"Failed to queue inference task: {e}",
                details={"job_id": str(job.id)},
            )

        await self.db.refresh(job)
        return _to_response(job)

    async def get_job(
        self, job_id: UUID, user_id: Optional[UUID] = None
    ) -> InferenceJobDetailResponse:
        """Retrieve a single inference job with full details."""
        result = await self.db.execute(
            select(InferenceJob).where(InferenceJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise NotFoundError("Inference job", str(job_id))

        # Load stored DICOM result (SEG/SR/SC), if any
        res_row = await self.db.execute(
            select(InferenceResult).where(InferenceResult.job_id == job_id)
        )
        res = res_row.scalar_one_or_none()

        base = _to_response(job)
        detail = InferenceJobDetailResponse(**base.model_dump())
        if res:
            detail.result = InferenceResultResponse(
                dicom_type=res.dicom_type,
                orthanc_id=res.orthanc_id,
                metadata=res.result_metadata,
            )
        return detail

    async def list_jobs(
        self,
        status: Optional[str] = None,
        model_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
    ) -> dict:
        """List inference jobs with filters (admin endpoint)."""
        filters = []
        if status:
            filters.append(InferenceJob.status == status)
        if model_id:
            filters.append(InferenceJob.model_id == model_id)
        if user_id:
            filters.append(InferenceJob.requested_by == str(user_id))

        count_stmt = select(func.count()).select_from(InferenceJob)
        list_stmt = select(InferenceJob).order_by(InferenceJob.created_at.desc())
        for f in filters:
            count_stmt = count_stmt.where(f)
            list_stmt = list_stmt.where(f)

        total = (await self.db.execute(count_stmt)).scalar() or 0
        offset = (page - 1) * page_size
        rows = (
            await self.db.execute(list_stmt.offset(offset).limit(page_size))
        ).scalars().all()

        logger.info(
            f"Listed {len(rows)} inference jobs",
            extra={"total": total, "page": page},
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_to_response(j) for j in rows],
        }

    async def update_job_status(
        self,
        job_id: UUID,
        status: str,
        inference_time_ms: Optional[int] = None,
        confidence_score: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> InferenceJobResponse:
        """Update job status and metrics (result-handler hook)."""
        result = await self.db.execute(
            select(InferenceJob).where(InferenceJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise NotFoundError("Inference job", str(job_id))

        job.status = status
        if inference_time_ms is not None:
            job.inference_time_ms = inference_time_ms
        if confidence_score is not None:
            job.max_confidence = confidence_score
        if error_message is not None:
            job.error_message = error_message

        await self.db.commit()
        await self.db.refresh(job)
        logger.info(
            "Updated inference job status",
            extra={"job_id": str(job_id), "status": status},
        )
        return _to_response(job)

    async def cancel_job(self, job_id: UUID) -> InferenceJobResponse:
        """Cancel a queued or running inference job."""
        result = await self.db.execute(
            select(InferenceJob).where(InferenceJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise NotFoundError("Inference job", str(job_id))

        current = job.status.value if hasattr(job.status, "value") else job.status
        # 취소 가능 = 비종결(non-terminal) 상태 전부. JobStatus enum엔 "running"이 없어
        # inferring/postprocessing 중인 작업이 취소 불가였음(F6) — 실제 활성 상태로 교정.
        if current not in ("queued", "preprocessing", "inferring", "postprocessing"):
            raise InferenceJobError(
                f"Cannot cancel job with status '{current}'",
                details={"job_id": str(job_id), "status": current},
            )

        if job.celery_task_id:
            try:
                from app.services.ai_worker import celery_app

                celery_app.control.revoke(job.celery_task_id, terminate=True)
                logger.info(f"Revoked Celery task {job.celery_task_id} for job {job_id}")
            except Exception as e:
                logger.warning(f"Failed to revoke Celery task: {e}")

        job.status = JobStatus.FAILED
        job.error_message = "Job cancelled by user"
        await self.db.commit()
        await self.db.refresh(job)
        logger.info(f"Cancelled inference job {job_id}")
        return _to_response(job)
