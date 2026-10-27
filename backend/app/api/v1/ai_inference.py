"""AI Inference API endpoints (Phase 5).

Endpoints for submitting, tracking, and retrieving AI inference job results.

Routes:
- POST /api/v1/ai/inferences — Submit new inference job
- GET /api/v1/ai/inferences — List jobs (admin only)
- GET /api/v1/ai/inferences/{id} — Get job details
- DELETE /api/v1/ai/inferences/{id} — Cancel running job
- GET /api/v1/ai/results/{id} — Retrieve DICOM result from Orthanc
"""
import logging
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_user
from app.schemas.ai import InferenceJobRequest, InferenceJobResponse, InferenceJobDetailResponse
from app.services.inference_job_service import InferenceJobService
from app.services.result_storage_service import ResultStorageService
from app.models.ai import InferenceResult
from app.core.security import ClinicalWriteRoles
from app.models.user import User
from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    InferenceJobError,
    ModelNotAvailable,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["AI Inference"])


@router.post(
    "/inferences",
    response_model=InferenceJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit AI inference job",
    description="Submit a DICOM study for AI model inference. Returns 202 Accepted with job_id.",
)
async def submit_inference_job(
    request: InferenceJobRequest,
    current_user: User = Depends(ClinicalWriteRoles),
    db: AsyncSession = Depends(get_db),
) -> InferenceJobResponse:
    """Submit a new inference job for async processing.

    Required roles: radiologist, admin

    Request body:
    {
        "model_id": "uuid",
        "study_instance_uid": "1.2.3...",
        "series_instance_uid": "1.2.3..." (optional)
    }

    Response (202 Accepted):
    {
        "id": "job-uuid",
        "model_id": "model-uuid",
        "study_instance_uid": "1.2.3...",
        "status": "queued",
        "celery_task_id": "task-uuid",
        "created_at": "2026-05-14T10:30:00Z",
        ...
    }

    Errors:
    - 404: Model not found or inactive
    - 422: Validation error
    - 500: Celery task queueing failed
    """
    try:
        # Verify user is radiologist or admin
        if current_user.role not in ("radiologist", "admin"):
            raise PermissionDeniedError("Only radiologists can submit inference jobs")

        service = InferenceJobService(db=db)
        job = await service.submit_job(request=request, user_id=current_user.id)

        logger.info(
            f"Inference job submitted",
            extra={"job_id": str(job.id), "user_id": str(current_user.id), "model_id": str(request.model_id)},
        )

        return job

    except ModelNotAvailable as e:
        logger.warning(f"Model not available: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

    except PermissionDeniedError as e:
        logger.warning(f"Permission denied: {str(e)}")
        raise HTTPException(status_code=403, detail=str(e))

    except InferenceJobError as e:
        logger.error(f"Inference job error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        logger.error(f"Unexpected error submitting inference job: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit inference job")


@router.get(
    "/inferences",
    response_model=dict,
    summary="List inference jobs",
    description="List all inference jobs with optional filtering. Admin only.",
)
async def list_inference_jobs(
    status: Optional[str] = None,
    model_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(ClinicalWriteRoles),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List inference jobs with pagination and filters.

    Required roles: admin

    Query parameters:
    - status: Filter by job status (queued, running, completed, failed)
    - model_id: Filter by model UUID
    - page: Page number (1-indexed)
    - page_size: Results per page (default 20, max 100)

    Response:
    {
        "total": 150,
        "page": 1,
        "page_size": 20,
        "items": [
            {
                "id": "job-uuid",
                "model_id": "model-uuid",
                "status": "completed",
                "inference_time_ms": 1234,
                "confidence_score": 0.95,
                ...
            },
            ...
        ]
    }

    Errors:
    - 403: Only admins can list all jobs
    """
    try:
        # Verify user is admin
        if current_user.role != "admin":
            raise PermissionDeniedError("Only admins can list all inference jobs")

        service = InferenceJobService(db=db)

        # Convert string model_id to UUID if provided
        model_id_uuid = UUID(model_id) if model_id else None

        result = await service.list_jobs(
            status=status,
            model_id=model_id_uuid,
            page=page,
            page_size=min(page_size, 100),  # Max 100 per page
        )

        logger.info(
            f"Listed inference jobs",
            extra={"total": result['total'], "filters": {"status": status, "model_id": model_id}},
        )

        return result

    except PermissionDeniedError as e:
        logger.warning(f"Permission denied: {str(e)}")
        raise HTTPException(status_code=403, detail=str(e))

    except ValueError as e:
        logger.warning(f"Invalid query parameter: {str(e)}")
        raise HTTPException(status_code=422, detail="Invalid model_id format")

    except Exception as e:
        logger.error(f"Error listing inference jobs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list inference jobs")


@router.get(
    "/inferences/{job_id}",
    response_model=InferenceJobDetailResponse,
    summary="Get inference job details",
    description="Retrieve full details of an inference job including model and result.",
)
async def get_inference_job(
    job_id: str,
    current_user: User = Depends(ClinicalWriteRoles),
    db: AsyncSession = Depends(get_db),
) -> InferenceJobDetailResponse:
    """Retrieve a single inference job with full details.

    Response includes:
    - Job metadata (status, timing, confidence)
    - Nested model details
    - Nested result (DICOM references)

    Errors:
    - 404: Job not found
    - 403: User lacks permission to view job
    """
    try:
        service = InferenceJobService(db=db)

        job = await service.get_job(
            job_id=UUID(job_id),
            user_id=current_user.id if current_user.role != "admin" else None,
        )

        logger.info(f"Retrieved inference job {job_id}")
        return job

    except NotFoundError as e:
        logger.warning(f"Job not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

    except PermissionDeniedError as e:
        logger.warning(f"Permission denied: {str(e)}")
        raise HTTPException(status_code=403, detail=str(e))

    except ValueError as e:
        logger.warning(f"Invalid job_id format: {str(e)}")
        raise HTTPException(status_code=422, detail="Invalid job_id format")

    except Exception as e:
        logger.error(f"Error retrieving inference job: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve inference job")


@router.delete(
    "/inferences/{job_id}",
    status_code=status.HTTP_200_OK,
    summary="Cancel inference job",
    description="Cancel a queued or running inference job.",
)
async def cancel_inference_job(
    job_id: str,
    current_user: User = Depends(ClinicalWriteRoles),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel an inference job.

    Only jobs in 'queued' or 'running' status can be cancelled.
    Completed/failed jobs are immutable.

    Response:
    {
        "id": "job-uuid",
        "status": "failed",
        "error_message": "Job cancelled by user"
    }

    Errors:
    - 404: Job not found
    - 409: Job cannot be cancelled (invalid state)
    - 403: User lacks permission to cancel
    """
    try:
        service = InferenceJobService(db=db)

        job = await service.cancel_job(job_id=UUID(job_id))

        logger.info(
            f"Cancelled inference job {job_id}",
            extra={"user_id": str(current_user.id), "cancelled_by": str(current_user.id)},
        )

        return {"id": str(job.id), "status": job.status, "error_message": job.error_message}

    except NotFoundError as e:
        logger.warning(f"Job not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

    except InferenceJobError as e:
        logger.warning(f"Cannot cancel job: {str(e)}")
        raise HTTPException(status_code=409, detail=str(e))

    except ValueError as e:
        logger.warning(f"Invalid job_id format: {str(e)}")
        raise HTTPException(status_code=422, detail="Invalid job_id format")

    except Exception as e:
        logger.error(f"Error cancelling inference job: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to cancel inference job")


@router.get(
    "/results/{job_id}",
    summary="Retrieve DICOM result",
    description="Download DICOM SEG or SR result from a completed inference job.",
)
async def get_inference_result(
    job_id: str,
    result_type: str = "seg",  # 'seg' or 'sr'
    current_user: User = Depends(ClinicalWriteRoles),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve DICOM result (SEG or SR) from a completed inference job.

    Query parameters:
    - result_type: 'seg' (segmentation) or 'sr' (structured report) [default: seg]

    Response:
    - DICOM file download (application/dicom)

    Errors:
    - 404: Job or result not found
    - 409: Job not completed (no result yet)
    - 422: Invalid result_type parameter
    """
    try:
        # Validate result_type parameter
        result_type_upper = result_type.upper()
        if result_type_upper not in ["SEG", "SR"]:
            raise ValueError(f"result_type must be 'seg' or 'sr', got '{result_type}'")

        # Parse job_id UUID
        job_uuid = UUID(job_id)

        # Verify job exists and is completed. 소유자 스코프 — 비-admin은 본인 job만(IDOR 차단,
        # get_inference_job와 동일 패턴). 이전엔 user_id=None이라 타 환자 AI 결과 다운로드 가능했음.
        job_service = InferenceJobService(db=db)
        job = await job_service.get_job(
            job_id=job_uuid,
            user_id=current_user.id if current_user.role != "admin" else None,
        )

        if job.status != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Job not completed yet (current status: {job.status}). Results are only available for completed jobs."
            )

        # Query for result with matching dicom_type
        result = await db.execute(
            select(InferenceResult).where(
                (InferenceResult.job_id == job_uuid) &
                (InferenceResult.dicom_type == result_type_upper)
            )
        )
        result = result.scalar_one_or_none()

        if not result:
            raise NotFoundError(f"Inference result with type '{result_type}'", str(job_id))

        # Retrieve DICOM bytes from storage
        storage_service = ResultStorageService(db=db)
        dicom_bytes = await storage_service.get_result_file(result_id=result.id)

        # Return as file download
        filename = f"result_{result_type_upper}_{job_id[:8]}.dcm"
        logger.info(
            f"Retrieved result for job {job_id}",
            extra={"result_type": result_type_upper, "user_id": str(current_user.id)}
        )

        return Response(
            content=dicom_bytes,
            media_type="application/dicom",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except ValueError as e:
        logger.warning(f"Invalid result_type parameter: {str(e)}")
        raise HTTPException(status_code=422, detail="Invalid result_type parameter")

    except NotFoundError as e:
        logger.warning(f"Result not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        logger.error(f"Error retrieving result: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve result")
