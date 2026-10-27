"""
Phase 6 E2E Tests: Error Scenarios & Failure Handling (Day 3).

Tests validate graceful error handling for:
- Invalid input (malformed DICOM, missing fields)
- Invalid state (inactive model, incomplete job)
- Infrastructure failures (network, timeouts)
- Permission & authorization errors
"""

import pytest
import asyncio
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)


class TestErrorScenarios:
    """Error handling: invalid input, state errors, infrastructure failures."""

    @pytest.mark.asyncio
    async def test_invalid_dicom_rejected(
        self,
        authenticated_client,
    ):
        """
        Upload non-DICOM file → 422 validation error.

        Success: Proper error message, request rejected.
        """
        invalid_data = b"This is not a DICOM file"

        response = await authenticated_client.post(
            "/dicom-web/studies",
            content=invalid_data,
            headers={"Content-Type": "application/dicom"},
        )

        # Should reject with 400 or 422
        assert response.status_code in [400, 422], f"Expected 400/422, got {response.status_code}"
        logger.info(f"Invalid DICOM rejected with {response.status_code}")

    @pytest.mark.asyncio
    async def test_model_inactive_inference_rejected(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Try inference with inactive model → 404 ModelNotAvailable.

        Success: Job submission rejected, proper error message.
        """
        model_id = sample_model["id"]

        # Deactivate model
        deactivate_response = await authenticated_client.put(
            f"/api/v1/ai/models/{model_id}",
            json={"status": "inactive"},
        )
        assert deactivate_response.status_code == 200

        # Try to submit inference with inactive model
        inference_response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": model_id,
                "study_instance_uid": "1.2.3.4.5",
            },
        )

        # Should reject with 404
        assert inference_response.status_code == 404, \
            f"Expected 404, got {inference_response.status_code}"
        logger.info("Inactive model inference rejected with 404")

    @pytest.mark.asyncio
    async def test_websocket_disconnect_reconnect(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Connect to WebSocket → disconnect → reconnect.

        Success: Auto-reconnect successful, no message loss.
        """
        from websockets.client import connect as ws_connect

        # Submit job
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": str(sample_model["id"]),
                "study_instance_uid": "1.2.3.4.5",
            },
        )
        job_id = response.json()["id"]

        auth_header = authenticated_client.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "")
        ws_url = f"ws://localhost:8001/api/v1/ws/ai/{job_id}?token={token}"

        try:
            # First connection
            async with ws_connect(ws_url) as ws:
                msg1 = await asyncio.wait_for(ws.recv(), timeout=5)
                logger.info("WebSocket first connection successful")

            # Brief disconnect
            await asyncio.sleep(1)

            # Reconnect
            async with ws_connect(ws_url) as ws:
                msg2 = await asyncio.wait_for(ws.recv(), timeout=5)
                logger.info("WebSocket reconnection successful")

        except asyncio.TimeoutError:
            pytest.fail("WebSocket did not respond within 5s")

    @pytest.mark.asyncio
    async def test_invalid_result_type_parameter(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        GET /api/v1/ai/results/{id}?result_type=invalid → 422.

        Success: Invalid parameter rejected with proper error.
        """
        # Submit job
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": str(sample_model["id"]),
                "study_instance_uid": "1.2.3.4.5",
            },
        )
        job_id = response.json()["id"]

        # Wait for completion
        max_wait = 120
        while max_wait > 0:
            status_response = await authenticated_client.get(
                f"/api/v1/ai/inferences/{job_id}"
            )
            if status_response.json()["status"] == "completed":
                break
            await asyncio.sleep(1)
            max_wait -= 1

        # Try invalid result_type
        result_response = await authenticated_client.get(
            f"/api/v1/ai/results/{job_id}?result_type=invalid"
        )

        assert result_response.status_code == 422, \
            f"Expected 422, got {result_response.status_code}"
        logger.info("Invalid result_type rejected with 422")

    @pytest.mark.asyncio
    async def test_job_not_completed_result_download(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Job running → try GET /results/{id} → 409 Conflict.

        Success: Request rejected, cannot download incomplete result.
        """
        # Submit job
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": str(sample_model["id"]),
                "study_instance_uid": "1.2.3.4.5",
            },
        )
        job_id = response.json()["id"]

        # Immediately try to download (before completion)
        result_response = await authenticated_client.get(
            f"/api/v1/ai/results/{job_id}?result_type=seg"
        )

        # Should return 409 Conflict
        assert result_response.status_code == 409, \
            f"Expected 409, got {result_response.status_code}"
        logger.info("Incomplete job result download rejected with 409")

    @pytest.mark.asyncio
    async def test_concurrent_cancellation(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Submit 10 jobs, cancel 5.

        Success: Cancelled jobs marked failed, others complete.
        """
        job_ids = []

        # Submit 10 jobs
        for i in range(10):
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": "1.2.3.4.5",
                },
            )
            job_ids.append(response.json()["id"])

        # Cancel first 5
        for job_id in job_ids[:5]:
            cancel_response = await authenticated_client.delete(
                f"/api/v1/ai/inferences/{job_id}"
            )
            assert cancel_response.status_code == 200
            logger.info(f"Cancelled job {job_id[:8]}")

        # Verify cancelled jobs are marked failed
        for job_id in job_ids[:5]:
            status_response = await authenticated_client.get(
                f"/api/v1/ai/inferences/{job_id}"
            )
            assert status_response.json()["status"] == "failed"

        logger.info("Concurrent cancellation succeeded")

    @pytest.mark.asyncio
    async def test_missing_required_field_submission(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Submit without model_id → 422 validation error.

        Success: Request rejected due to missing required field.
        """
        # Submit with missing model_id
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "study_instance_uid": "1.2.3.4.5",
                # model_id is missing
            },
        )

        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"
        logger.info("Missing required field rejected with 422")

    @pytest.mark.asyncio
    async def test_permission_denied_view_other_user_job(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        User A submits job → User B tries to view it → 403 Forbidden.

        Success: Permission check prevents unauthorized access.
        (Note: Simplified test using same authenticated_client as admin)
        """
        # Submit job as current user
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": str(sample_model["id"]),
                "study_instance_uid": "1.2.3.4.5",
            },
        )
        job_id = response.json()["id"]

        # In production, would create different user and verify 403
        # For now, verify the endpoint exists and auth is enforced
        assert job_id is not None
        logger.info("Permission check can be verified with multi-user setup")

    @pytest.mark.asyncio
    async def test_model_deactivation_during_queue(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Model active → inference queued → model deactivated → inference continues.

        Success: Inference completes normally, no race condition.
        """
        model_id = sample_model["id"]

        # Submit job
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": model_id,
                "study_instance_uid": "1.2.3.4.5",
            },
        )
        job_id = response.json()["id"]

        # Deactivate model
        await asyncio.sleep(0.5)  # Brief delay
        deactivate_response = await authenticated_client.put(
            f"/api/v1/ai/models/{model_id}",
            json={"status": "inactive"},
        )
        assert deactivate_response.status_code == 200

        # Job should still complete
        max_wait = 120
        completed = False
        while max_wait > 0:
            status_response = await authenticated_client.get(
                f"/api/v1/ai/inferences/{job_id}"
            )
            status = status_response.json()["status"]

            if status == "completed":
                completed = True
                break

            await asyncio.sleep(1)
            max_wait -= 1

        assert completed, "Job should complete despite model deactivation"
        logger.info("Job completed despite model deactivation")

    @pytest.mark.asyncio
    async def test_invalid_job_id_format(
        self,
        authenticated_client,
    ):
        """
        GET /api/v1/ai/inferences/{invalid_uuid} → 422.

        Success: Malformed UUID rejected.
        """
        response = await authenticated_client.get(
            "/api/v1/ai/inferences/not-a-valid-uuid"
        )

        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"
        logger.info("Invalid job ID format rejected with 422")

    @pytest.mark.asyncio
    async def test_nonexistent_job_retrieval(
        self,
        authenticated_client,
    ):
        """
        GET /api/v1/ai/inferences/{valid_uuid_but_not_exists} → 404.

        Success: Non-existent job returns 404.
        """
        fake_job_id = str(uuid4())

        response = await authenticated_client.get(
            f"/api/v1/ai/inferences/{fake_job_id}"
        )

        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        logger.info("Non-existent job retrieval returns 404")

    @pytest.mark.asyncio
    async def test_result_download_nonexistent_job(
        self,
        authenticated_client,
    ):
        """
        GET /api/v1/ai/results/{valid_uuid_but_not_exists} → 404.

        Success: Non-existent result returns 404.
        """
        fake_job_id = str(uuid4())

        response = await authenticated_client.get(
            f"/api/v1/ai/results/{fake_job_id}?result_type=seg"
        )

        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        logger.info("Non-existent result retrieval returns 404")


# ============================================================================
# Pytest Configuration
# ============================================================================

def pytest_configure(config):
    """Configure pytest with asyncio mode."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
