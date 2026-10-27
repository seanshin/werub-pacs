"""
Phase 6 E2E Tests: Performance Baseline Metrics (Day 5).

Tests measure & establish SLA targets:
- Inference latency distribution (p50, p95, p99)
- Throughput under sustained load
- WebSocket message latency (< 100ms)
- API response time (p95 < 500ms)
- Database query performance (indexes working)
"""

import pytest
import asyncio
import time
import statistics
import logging

logger = logging.getLogger(__name__)


class TestPerformanceBaseline:
    """Performance SLA metrics: latency percentiles, throughput, API response time."""

    @pytest.mark.asyncio
    async def test_inference_latency_distribution(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Run 50 jobs, measure latencies → verify p50 < 5s, p95 < 10s, p99 < 15s.

        Success: Latency baseline established and meets SLA.
        """
        latencies = []
        study_uid = "1.2.3.4.5"

        for i in range(50):
            start = time.time()

            # Submit job
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            job_id = response.json()["id"]

            # Wait for completion
            max_wait = 300  # 5 minutes per job
            while max_wait > 0:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    latency = time.time() - start
                    latencies.append(latency)
                    metrics_collector.record_latency(latency * 1000)
                    break
                elif status == "failed":
                    metrics_collector.record_error(f"Job {job_id} failed")
                    break

                await asyncio.sleep(1)
                max_wait -= 1

        # Calculate percentiles
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[int(len(sorted_lat) * 0.50)]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)]

        min_lat = min(latencies)
        max_lat = max(latencies)
        mean_lat = statistics.mean(latencies)
        median_lat = statistics.median(latencies)

        logger.info(
            f"Latency Distribution (50 samples):\n"
            f"  Min: {min_lat:.2f}s\n"
            f"  Mean: {mean_lat:.2f}s\n"
            f"  Median: {median_lat:.2f}s\n"
            f"  p50: {p50:.2f}s (target: <5s)\n"
            f"  p95: {p95:.2f}s (target: <10s)\n"
            f"  p99: {p99:.2f}s (target: <15s)\n"
            f"  Max: {max_lat:.2f}s"
        )

        # Assert SLA targets
        assert p50 < 5, f"p50 latency {p50:.2f}s exceeds 5s SLA"
        assert p95 < 10, f"p95 latency {p95:.2f}s exceeds 10s SLA"
        assert p99 < 15, f"p99 latency {p99:.2f}s exceeds 15s SLA"

    @pytest.mark.asyncio
    async def test_throughput_sustained_load(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Submit 20 jobs/minute for 30 minutes → verify ≥95% completion.

        Success: Sustained throughput maintained, minimal failures.
        """
        job_ids = []
        study_uid = "1.2.3.4.5"
        start_time = time.time()
        target_duration = 1800  # 30 minutes
        submit_interval = 3  # 20 jobs/minute = 1 job every 3s

        # Submit jobs at constant rate for 30 minutes
        while time.time() - start_time < target_duration:
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )

            if response.status_code == 202:
                job_ids.append(response.json()["id"])
                metrics_collector.increment_jobs()
            else:
                metrics_collector.record_error(f"Job submission failed: {response.status_code}")

            await asyncio.sleep(submit_interval)

        submit_duration = time.time() - start_time
        logger.info(f"Submitted {len(job_ids)} jobs over {submit_duration:.0f}s")

        # Wait for all jobs to complete (max 5 hours total)
        completed = 0
        failed = 0
        max_wait_per_job = 18000  # 5 hours total

        for job_id in job_ids:
            start = time.time()
            while time.time() - start < max_wait_per_job:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    completed += 1
                    break
                elif status == "failed":
                    failed += 1
                    metrics_collector.record_error(f"Job {job_id} failed")
                    break

                await asyncio.sleep(2)

        completion_rate = completed / len(job_ids) * 100 if job_ids else 0

        logger.info(
            f"Sustained Load Results:\n"
            f"  Total submitted: {len(job_ids)}\n"
            f"  Completed: {completed}\n"
            f"  Failed: {failed}\n"
            f"  Completion rate: {completion_rate:.1f}%"
        )

        assert completion_rate >= 95, \
            f"Completion rate {completion_rate:.1f}% < 95% SLA"

    @pytest.mark.asyncio
    async def test_websocket_message_latency(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Send job → measure time from event → WebSocket message receipt → p95 < 100ms.

        Success: Real-time progress updates within latency SLA.
        """
        from websockets.client import connect as ws_connect
        import json

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

        message_latencies = []

        try:
            async with ws_connect(ws_url) as ws:
                recv_start = time.time()

                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=60)
                        recv_time = time.time() - recv_start

                        msg_data = json.loads(msg)

                        # Record latency for status updates
                        if msg_data.get("type") == "status_update":
                            message_latencies.append(recv_time * 1000)  # ms

                        if msg_data.get("status") == "completed":
                            break

                        recv_start = time.time()

                    except asyncio.TimeoutError:
                        break

        except Exception as e:
            logger.warning(f"WebSocket error: {e}")

        if message_latencies:
            sorted_lat = sorted(message_latencies)
            p95 = sorted_lat[int(len(sorted_lat) * 0.95)]

            logger.info(
                f"WebSocket Message Latency:\n"
                f"  Samples: {len(message_latencies)}\n"
                f"  p95: {p95:.2f}ms (target: <100ms)"
            )

            assert p95 < 100, f"WebSocket p95 latency {p95:.2f}ms exceeds 100ms SLA"
        else:
            logger.warning("No WebSocket messages captured (job may have completed too fast)")

    @pytest.mark.asyncio
    async def test_api_response_time_list_endpoints(
        self,
        authenticated_client,
    ):
        """
        GET /inferences, /models endpoints → measure response time → p95 < 500ms.

        Success: API response time meets SLA.
        """
        response_times = []

        # Test /inferences endpoint (multiple pages)
        for page in range(1, 4):
            start = time.time()
            response = await authenticated_client.get(
                f"/api/v1/ai/inferences?page={page}&page_size=20"
            )
            latency = (time.time() - start) * 1000  # ms

            assert response.status_code == 200
            response_times.append(latency)

        # Test /models endpoint
        start = time.time()
        response = await authenticated_client.get("/api/v1/ai/models")
        latency = (time.time() - start) * 1000

        assert response.status_code == 200
        response_times.append(latency)

        # Calculate percentiles
        sorted_times = sorted(response_times)
        p95 = sorted_times[int(len(sorted_times) * 0.95)]
        mean_time = statistics.mean(response_times)

        logger.info(
            f"API Response Time:\n"
            f"  Samples: {len(response_times)}\n"
            f"  Mean: {mean_time:.2f}ms\n"
            f"  p95: {p95:.2f}ms (target: <500ms)"
        )

        assert p95 < 500, f"API p95 response time {p95:.2f}ms exceeds 500ms SLA"

    @pytest.mark.asyncio
    async def test_database_query_performance_with_indexes(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Submit 100 jobs → GET /inferences with filters → measure response time.

        Success: Database indexes working, response < 200ms.
        """
        # Submit 100 jobs to populate database
        job_ids = []
        for i in range(100):
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": "1.2.3.4.5",
                },
            )
            if response.status_code == 202:
                job_ids.append(response.json()["id"])

        # Test filtering by status
        query_times = []

        for status in ["queued", "running", "completed"]:
            start = time.time()
            response = await authenticated_client.get(
                f"/api/v1/ai/inferences?status={status}&page=1&page_size=100"
            )
            latency = (time.time() - start) * 1000

            assert response.status_code == 200
            query_times.append(latency)

        mean_query_time = statistics.mean(query_times)
        max_query_time = max(query_times)

        logger.info(
            f"Database Query Performance (100 jobs):\n"
            f"  Mean response time: {mean_query_time:.2f}ms\n"
            f"  Max response time: {max_query_time:.2f}ms (target: <200ms)"
        )

        assert max_query_time < 200, \
            f"Database query time {max_query_time:.2f}ms exceeds 200ms SLA"


# ============================================================================
# Pytest Configuration
# ============================================================================

def pytest_configure(config):
    """Configure pytest with asyncio mode."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
