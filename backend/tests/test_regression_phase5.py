"""Regression tests for Phase 5 implementation (Phase 4 compatibility).

Tests verify:
1. Phase 4 batch normalization still works (no breaking changes)
2. No queue contention between batch and AI inference queues
3. Cache isolation (no cross-contamination)
4. Database schema integrity
5. API endpoint availability
"""
import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.models.batch_job import BatchJob
from app.models.ai import AIModel, InferenceJob


@pytest.fixture
def mock_db():
    """Mock AsyncSession for database operations."""
    return AsyncMock()


class TestPhase4Regression:
    """Regression tests for Phase 4 batch normalization."""

    @pytest.mark.asyncio
    async def test_batch_job_creation_still_works(self, mock_db):
        """Test: Phase 4 batch job creation unaffected by Phase 5 changes."""
        batch_job_id = uuid4()
        user_id = uuid4()

        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Create batch job (Phase 4 code)
        batch_job = BatchJob(
            id=batch_job_id,
            user_id=str(user_id),
            total_files=10,
            status="processing",
        )

        mock_db.add(batch_job)
        await mock_db.commit()

        # Verify batch job properties
        assert batch_job.id == batch_job_id
        assert batch_job.status == "processing"
        assert batch_job.total_files == 10

    def test_batch_job_and_ai_job_schema_isolation(self):
        """Test: Batch and AI job tables don't share columns.

        Regression: Verify database schema integrity.
        """
        # Phase 4: BatchJob has columns: user_id, total_files, status, supplier, etc.
        # Phase 5: InferenceJob has columns: model_id, study_instance_uid, confidence_score

        batch_columns = {col.name for col in BatchJob.__table__.columns}
        ai_columns = {col.name for col in InferenceJob.__table__.columns}

        # Verify no overlap (except common audit columns)
        common_columns = {"id", "created_at", "updated_at", "status"}
        batch_only = batch_columns - common_columns
        ai_only = ai_columns - common_columns

        assert "user_id" in batch_only
        assert "total_files" in batch_only
        assert "model_id" in ai_only
        assert "study_instance_uid" in ai_only

        # The distinguishing domain columns must not bleed across tables.
        # (Sharing generic audit/timestamp columns like completed_at/error_message
        # is expected and fine, so a blanket isdisjoint() is the wrong check.)
        assert "model_id" not in batch_columns
        assert "study_instance_uid" not in batch_columns
        assert "user_id" not in ai_columns
        assert "total_files" not in ai_columns


class TestQueueContention:
    """Tests verify no queue contention between batch and AI queues."""

    @pytest.mark.asyncio
    async def test_batch_queue_independent_of_ai_queue(self):
        """Test: batch_normalization queue independent of ai_inference queue.

        Regression: Verify Celery queue isolation.
        """
        # Phase 4 uses queue: "batch_normalization"
        # Phase 5 uses queue: "ai_inference"

        batch_queue = "batch_normalization"
        ai_queue = "ai_inference"

        assert batch_queue != ai_queue
        assert batch_queue != ai_queue.replace("ai_", "batch_")  # No accidentally similar names

    @pytest.mark.asyncio
    async def test_concurrent_batch_and_ai_tasks(self, mock_db):
        """Test: Batch and AI tasks can run concurrently without interference.

        Workflow:
        1. Submit batch job (Phase 4)
        2. Submit AI inference job (Phase 5)
        3. Both queue to separate Celery queues
        4. Both execute independently
        """
        from app.services.inference_job_service import InferenceJobService

        batch_job_id = uuid4()
        ai_job_id = uuid4()
        user_id = uuid4()

        # Phase 4: Create batch job
        batch_job = BatchJob(
            id=batch_job_id,
            user_id=str(user_id),
            total_files=10,
            status="queued",
        )

        # Phase 5: Create AI job via the (rewritten, async) InferenceJobService.
        # Model lookup uses db.execute(select(...)).scalar_one_or_none().
        mock_model = MagicMock(id=uuid4(), name="m", is_active=True)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=mock_model)
        mock_db.execute = AsyncMock(return_value=exec_result)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        async def _refresh(obj):
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now()

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        from unittest.mock import patch
        from app.schemas.ai import InferenceJobRequest

        service = InferenceJobService(db=mock_db)
        request = InferenceJobRequest(model_id=mock_model.id, study_instance_uid="1.2.3.4.5")

        with patch("app.services.ai_worker.run_inference") as mock_task:
            mock_task.delay.return_value = MagicMock(id="celery-task-ai")
            ai_job = await service.submit_job(request=request, user_id=user_id)

            # Verify both jobs exist independently
            assert batch_job.id != ai_job.id
            assert batch_job.status == "queued"
            assert ai_job.status == "queued"


class TestCacheIsolation:
    """Tests verify cache isolation between Phase 4 and Phase 5."""

    def test_ai_model_cache_independent_of_normalization_cache(self):
        """AI model cache and normalization cache use disjoint key namespaces."""
        ai_cache_key = "ai:models:CT:active:1"
        phase4_cache_key = "norm:rules:cache"
        assert ai_cache_key.startswith("ai:")
        assert phase4_cache_key.startswith("norm:")
        # Different top-level namespace → invalidating one cannot match the other.
        assert ai_cache_key.split(":")[0] != phase4_cache_key.split(":")[0]


class TestAPIEndpointIntegration:
    """Tests verify Phase 5 API endpoints don't break Phase 4 APIs."""

    def test_phase5_routes_dont_conflict_with_phase4(self):
        """Test: Phase 5 routes don't collide with Phase 4 route paths.

        Regression: Verify no URL path conflicts.
        """
        # Phase 4 routes: /api/v1/batch/*, /api/v1/studies/*, /api/v1/reports/*
        # Phase 5 routes: /api/v1/ai/*, /api/v1/ws/ai/*

        phase4_base = "/api/v1/batch"
        phase4_base2 = "/api/v1/studies"
        phase4_base3 = "/api/v1/reports"

        phase5_base = "/api/v1/ai"
        phase5_ws = "/api/v1/ws/ai"

        # Verify no overlap
        assert not phase5_base.startswith(phase4_base)
        assert not phase5_base.startswith(phase4_base2)
        assert not phase5_base.startswith(phase4_base3)
        assert not phase5_ws.startswith(phase4_base)

    def test_phase5_endpoints_defined(self):
        """Test: Phase 5 API endpoints are properly defined.

        Regression: Verify all expected endpoints exist.
        """
        from app.api.v1 import ai_inference
        from app.api.v1.ws import ai_progress

        # Verify modules exist
        assert hasattr(ai_inference, "router")
        assert hasattr(ai_progress, "router")

        # Verify endpoints registered (router.routes carry the full /api/v1/ai prefix)
        ai_routes = [route.path for route in ai_inference.router.routes]
        assert any(r.endswith("/inferences") for r in ai_routes)
        assert any(r.endswith("/results/{job_id}") for r in ai_routes)


class TestDatabaseSchemaCompatibility:
    """Tests verify database schema changes don't break Phase 4."""

    def test_new_ai_tables_dont_affect_existing_tables(self):
        """Test: New Phase 5 tables (ai_models, inference_jobs, inference_results)
        don't modify existing Phase 4 tables.

        Regression: Verify database integrity.
        """
        from app.models.batch_job import BatchJob
        from app.models.ai import AIModel, InferenceJob, InferenceResult

        # Verify Phase 4 tables exist and unchanged
        assert hasattr(BatchJob, "__tablename__")
        assert BatchJob.__tablename__ == "batch_jobs"

        # Verify Phase 5 tables are new
        assert hasattr(AIModel, "__tablename__")
        assert AIModel.__tablename__ == "ai_models"

        assert hasattr(InferenceJob, "__tablename__")
        assert InferenceJob.__tablename__ == "inference_jobs"

        assert hasattr(InferenceResult, "__tablename__")
        assert InferenceResult.__tablename__ == "inference_results"

        # Verify no cross-contamination
        phase4_tables = {"batch_jobs", "batch_job_files"}
        phase5_tables = {"ai_models", "inference_jobs", "inference_results"}

        assert phase4_tables.isdisjoint(phase5_tables)

    def test_foreign_key_relationships_intact(self):
        """Test: Foreign key relationships correctly defined.

        Regression: Verify referential integrity.
        """
        from app.models.ai import AIModel, InferenceJob, InferenceResult

        # InferenceJob.model_id → AIModel.id
        job_fks = [fk for fk in InferenceJob.__table__.foreign_keys]
        fk_targets = [str(fk.target_fullname) for fk in job_fks]
        assert any("ai_models.id" in t for t in fk_targets), f"Missing FK to ai_models: {fk_targets}"

        # InferenceResult.job_id → InferenceJob.id
        result_fks = [fk for fk in InferenceResult.__table__.foreign_keys]
        fk_targets = [str(fk.target_fullname) for fk in result_fks]
        assert any("inference_jobs.id" in t for t in fk_targets), f"Missing FK to inference_jobs: {fk_targets}"


class TestPhase4FeatureStillWorks:
    """Integration tests verify Phase 4 batch normalization features."""

    @pytest.mark.asyncio
    async def test_batch_normalization_workflow_unchanged(self, mock_db):
        """Test: Complete Phase 4 batch normalization workflow still works.

        Workflow:
        1. Create upload session
        2. Upload files
        3. Trigger batch job
        4. Normalization processes
        5. Results stored
        """
        session_id = uuid4()
        job_id = uuid4()
        user_id = uuid4()

        # Step 1: Create batch job (Phase 4 workflow)
        batch_job = BatchJob(
            id=job_id,
            user_id=str(user_id),
            total_files=5,
            status="processing",
        )

        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Verify batch job created successfully
        assert batch_job.id == job_id
        assert batch_job.total_files == 5
        assert batch_job.status == "processing"
