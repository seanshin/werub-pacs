"""Integration tests for InferenceJobService (Phase 5).

Rewritten to match the async SQLAlchemy implementation (``db.execute(select(...))``)
and the consolidated worker path (``app.services.ai_worker.run_inference``).

Tests cover:
1. Job submission with model validation
2. Job status tracking
3. Celery task queueing on the shared worker
4. Job listing with pagination
5. Job cancellation
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.inference_job_service import InferenceJobService
from app.schemas.ai import InferenceJobRequest
from app.models.ai import JobStatus
from app.core.exceptions import InferenceJobError, ModelNotAvailable, NotFoundError


def _make_job(**kw):
    """A lightweight stand-in for an InferenceJob ORM row with concrete values
    (Pydantic response mapping requires real datetimes/UUIDs, not MagicMocks)."""
    base = dict(
        id=uuid4(),
        model_id=uuid4(),
        study_instance_uid="1.2.3",
        series_instance_uid=None,
        status="queued",
        celery_task_id=None,
        error_message=None,
        inference_time_ms=None,
        max_confidence=None,
        created_at=datetime.now(timezone.utc),
        requested_by=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _exec(scalar=None, scalars_list=None, scalar_value=None):
    """Build a mock result for a single ``db.execute(...)`` call."""
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=scalar)
    res.scalar = MagicMock(return_value=scalar_value)
    scalars_obj = MagicMock()
    scalars_obj.all = MagicMock(return_value=scalars_list or [])
    res.scalars = MagicMock(return_value=scalars_obj)
    return res


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def _refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


@pytest.fixture
def inference_service(mock_db):
    return InferenceJobService(db=mock_db)


@pytest.fixture
def sample_model_id():
    return uuid4()


@pytest.fixture
def sample_user_id():
    return uuid4()


@pytest.fixture
def sample_job_id():
    return uuid4()


@pytest.fixture
def sample_study_uid():
    return "1.2.826.0.1.3680043.8.498.13100413110012866583153708344337172"


class TestInferenceJobSubmission:
    @pytest.mark.asyncio
    async def test_submit_job_success(self, inference_service, mock_db, sample_model_id, sample_user_id, sample_study_uid):
        model = SimpleNamespace(id=sample_model_id, name="chest-xray", is_active=True)
        mock_db.execute = AsyncMock(return_value=_exec(scalar=model))
        request = InferenceJobRequest(model_id=sample_model_id, study_instance_uid=sample_study_uid)

        with patch("app.services.ai_worker.run_inference") as mock_task:
            mock_task.delay.return_value = MagicMock(id="celery-task-id")
            result = await inference_service.submit_job(request=request, user_id=sample_user_id)

        assert result.model_id == sample_model_id
        assert result.status == "queued"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()
        mock_task.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_job_model_not_found(self, inference_service, mock_db, sample_model_id, sample_user_id, sample_study_uid):
        mock_db.execute = AsyncMock(return_value=_exec(scalar=None))
        request = InferenceJobRequest(model_id=sample_model_id, study_instance_uid=sample_study_uid)
        with pytest.raises(ModelNotAvailable):
            await inference_service.submit_job(request=request, user_id=sample_user_id)

    @pytest.mark.asyncio
    async def test_submit_job_model_inactive(self, inference_service, mock_db, sample_model_id, sample_user_id, sample_study_uid):
        model = SimpleNamespace(id=sample_model_id, name="x", is_active=False)
        mock_db.execute = AsyncMock(return_value=_exec(scalar=model))
        request = InferenceJobRequest(model_id=sample_model_id, study_instance_uid=sample_study_uid)
        with pytest.raises(ModelNotAvailable):
            await inference_service.submit_job(request=request, user_id=sample_user_id)

    @pytest.mark.asyncio
    async def test_submit_job_queues_shared_worker(self, inference_service, mock_db, sample_model_id, sample_user_id, sample_study_uid):
        model = SimpleNamespace(id=sample_model_id, name="x", is_active=True)
        mock_db.execute = AsyncMock(return_value=_exec(scalar=model))
        request = InferenceJobRequest(model_id=sample_model_id, study_instance_uid=sample_study_uid)

        with patch("app.services.ai_worker.run_inference") as mock_task:
            mock_task.delay.return_value = MagicMock(id="celery-task-123")
            result = await inference_service.submit_job(request=request, user_id=sample_user_id)

        # Worker is invoked with the job id only (shared pipeline contract)
        mock_task.delay.assert_called_once()
        assert result.celery_task_id == "celery-task-123"


class TestInferenceJobRetrieval:
    @pytest.mark.asyncio
    async def test_get_job_success(self, inference_service, mock_db, sample_job_id, sample_model_id):
        job = _make_job(id=sample_job_id, model_id=sample_model_id, status="running")
        # 1st execute → job, 2nd execute → result row (none)
        mock_db.execute = AsyncMock(side_effect=[_exec(scalar=job), _exec(scalar=None)])
        result = await inference_service.get_job(job_id=sample_job_id)
        assert result.id == sample_job_id
        assert result.status == "running"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, inference_service, mock_db, sample_job_id):
        mock_db.execute = AsyncMock(return_value=_exec(scalar=None))
        with pytest.raises(NotFoundError):
            await inference_service.get_job(job_id=sample_job_id)


class TestInferenceJobListing:
    @pytest.mark.asyncio
    async def test_list_jobs_all(self, inference_service, mock_db):
        jobs = [_make_job(status="queued"), _make_job(status="completed")]
        mock_db.execute = AsyncMock(side_effect=[_exec(scalar_value=2), _exec(scalars_list=jobs)])
        result = await inference_service.list_jobs(page=1, page_size=20)
        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_list_jobs_filter_by_status(self, inference_service, mock_db):
        jobs = [_make_job(status="completed")]
        mock_db.execute = AsyncMock(side_effect=[_exec(scalar_value=1), _exec(scalars_list=jobs)])
        result = await inference_service.list_jobs(status="completed", page=1, page_size=20)
        assert result["total"] == 1
        assert result["items"][0].status == "completed"

    @pytest.mark.asyncio
    async def test_list_jobs_pagination(self, inference_service, mock_db):
        jobs = [_make_job() for _ in range(10)]
        mock_db.execute = AsyncMock(side_effect=[_exec(scalar_value=50), _exec(scalars_list=jobs)])
        result = await inference_service.list_jobs(page=2, page_size=10)
        assert result["total"] == 50
        assert result["page"] == 2
        assert len(result["items"]) == 10


class TestInferenceJobStatusUpdate:
    @pytest.mark.asyncio
    async def test_update_job_to_running(self, inference_service, mock_db, sample_job_id):
        job = _make_job(id=sample_job_id, status="queued")
        mock_db.execute = AsyncMock(return_value=_exec(scalar=job))
        result = await inference_service.update_job_status(job_id=sample_job_id, status="running")
        assert result.status == "running"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_job_to_completed(self, inference_service, mock_db, sample_job_id):
        job = _make_job(id=sample_job_id, status="running")
        mock_db.execute = AsyncMock(return_value=_exec(scalar=job))
        result = await inference_service.update_job_status(
            job_id=sample_job_id, status="completed", inference_time_ms=1500, confidence_score=0.95
        )
        assert result.confidence_score == 0.95
        assert result.inference_time_ms == 1500

    @pytest.mark.asyncio
    async def test_update_job_with_error_message(self, inference_service, mock_db, sample_job_id):
        job = _make_job(id=sample_job_id, status="running")
        mock_db.execute = AsyncMock(return_value=_exec(scalar=job))
        result = await inference_service.update_job_status(
            job_id=sample_job_id, status="failed", error_message="ONNX inference timeout"
        )
        assert result.error_message == "ONNX inference timeout"


class TestInferenceJobCancellation:
    @pytest.mark.asyncio
    async def test_cancel_queued_job(self, inference_service, mock_db, sample_job_id):
        job = _make_job(id=sample_job_id, status="queued", celery_task_id=None)
        mock_db.execute = AsyncMock(return_value=_exec(scalar=job))
        result = await inference_service.cancel_job(job_id=sample_job_id)
        assert result.status == JobStatus.FAILED.value
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_cancel_running_job_revokes_celery(self, inference_service, mock_db, sample_job_id):
        job = _make_job(id=sample_job_id, status="running", celery_task_id="celery-task-123")
        mock_db.execute = AsyncMock(return_value=_exec(scalar=job))
        with patch("app.services.ai_worker.celery_app") as mock_celery:
            await inference_service.cancel_job(job_id=sample_job_id)
            mock_celery.control.revoke.assert_called_once_with("celery-task-123", terminate=True)

    @pytest.mark.asyncio
    async def test_cancel_completed_job_fails(self, inference_service, mock_db, sample_job_id):
        job = _make_job(id=sample_job_id, status="completed")
        mock_db.execute = AsyncMock(return_value=_exec(scalar=job))
        with pytest.raises(InferenceJobError):
            await inference_service.cancel_job(job_id=sample_job_id)
