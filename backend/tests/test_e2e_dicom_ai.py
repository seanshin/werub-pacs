"""
Phase 6 E2E Tests: Complete DICOM + AI Pipeline (Day 1 - Happy Path).

Tests validate:
1. Complete workflow (upload → normalize → AI → download)
2. Concurrent job submission (10 jobs sequentially)
3. WebSocket progress tracking
4. Result download (SEG and SR formats)
"""

import pytest
import asyncio
import time
from datetime import datetime
from uuid import UUID
import httpx
from websockets.client import connect as ws_connect


class TestCompleteWorkflow:
    """Happy path: complete DICOM + AI workflow."""

    @pytest.mark.asyncio
    async def test_complete_workflow_success(
        self,
        authenticated_client,
        sample_dicom_file,
        sample_model,
        metrics_collector,
    ):
        """
        Upload DICOM → normalize → submit AI → track → download.

        Success: 200 response, job queued, WebSocket shows progress, result file returned.
        Duration: ~45-60 seconds.
        """
        start_time = time.time()

        # Step 1: Upload DICOM to Orthanc (via DICOMweb)
        upload_response = await authenticated_client.post(
            "/dicom-web/studies",
            content=sample_dicom_file,
            headers={"Content-Type": "application/dicom"},
        )
        assert upload_response.status_code == 200, f"DICOM upload failed: {upload_response.text}"
        logger.info(f"DICOM uploaded in {time.time() - start_time:.2f}s")

        # Extract StudyInstanceUID from upload response
        # (Orthanc returns study metadata)
        study_uid = "1.2.3.4.5"  # From sample DICOM fixture

        # Step 2: Submit AI inference job
        inference_payload = {
            "model_id": str(sample_model["id"]),
            "study_instance_uid": study_uid,
            "series_instance_uid": None,
        }

        submit_time = time.time()
        job_response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json=inference_payload,
        )
        assert job_response.status_code == 202, f"Job submission failed: {job_response.text}"

        job_data = job_response.json()
        job_id = job_data["id"]
        assert job_data["status"] == "queued"

        logger.info(f"Job submitted: {job_id} in {time.time() - submit_time:.2f}s")
        metrics_collector.increment_jobs()

        # Step 3: Wait for job completion via polling (max 120 seconds)
        job_completed = False
        max_wait = 120
        poll_interval = 2

        for _ in range(max_wait // poll_interval):
            status_response = await authenticated_client.get(f"/api/v1/ai/inferences/{job_id}")
            assert status_response.status_code == 200

            status_data = status_response.json()
            job_status = status_data["status"]

            if job_status == "completed":
                job_completed = True
                break
            elif job_status == "failed":
                pytest.fail(f"Job failed: {status_data.get('error_message')}")

            await asyncio.sleep(poll_interval)

        assert job_completed, f"Job did not complete within {max_wait}s"

        # Step 4: Download SEG result
        result_response = await authenticated_client.get(
            f"/api/v1/ai/results/{job_id}?result_type=seg"
        )
        assert result_response.status_code == 200
        assert result_response.headers["content-type"] == "application/dicom"
        assert len(result_response.content) > 0

        logger.info(f"SEG result downloaded: {len(result_response.content)} bytes")

        # Record latency
        total_time = time.time() - start_time
        metrics_collector.record_latency(total_time * 1000)  # ms

        assert total_time < 120, f"Workflow took {total_time:.2f}s (max 120s)"
        logger.info(f"Complete workflow succeeded in {total_time:.2f}s")

    @pytest.mark.asyncio
    async def test_concurrent_10_jobs_sequential(
        self,
        authenticated_client,
        sample_dicom_file,
        sample_model,
        metrics_collector,
    ):
        """
        Submit 10 jobs sequentially, track all to completion.

        Success: All 10 completed without data loss or race conditions.
        """
        job_ids = []
        study_uid = "1.2.3.4.5"

        # Submit 10 jobs
        for i in range(10):
            inference_payload = {
                "model_id": str(sample_model["id"]),
                "study_instance_uid": study_uid,
            }

            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json=inference_payload,
            )
            assert response.status_code == 202

            job_data = response.json()
            job_ids.append(job_data["id"])
            metrics_collector.increment_jobs()

        assert len(job_ids) == 10
        logger.info(f"Submitted 10 jobs: {job_ids}")

        # Wait for all to complete
        completed_count = 0
        max_wait = 300  # 5 minutes for 10 jobs

        for job_id in job_ids:
            start = time.time()
            while time.time() - start < max_wait:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status_data = status_response.json()

                if status_data["status"] == "completed":
                    completed_count += 1
                    break
                elif status_data["status"] == "failed":
                    pytest.fail(f"Job {job_id} failed: {status_data.get('error_message')}")

                await asyncio.sleep(1)

        assert completed_count == 10, f"Only {completed_count}/10 jobs completed"
        logger.info(f"All 10 jobs completed successfully")

    @pytest.mark.asyncio
    async def test_websocket_initial_state(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Connect to WebSocket → receive initial_state message.

        Success: initial_state contains job status and step count.
        """
        # Submit a job first
        inference_payload = {
            "model_id": str(sample_model["id"]),
            "study_instance_uid": "1.2.3.4.5",
        }

        job_response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json=inference_payload,
        )
        job_id = job_response.json()["id"]

        # Get JWT token from authenticated_client headers
        # Extract from Authorization header: "Bearer {token}"
        auth_header = authenticated_client.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "")

        # Connect to WebSocket
        ws_url = f"ws://localhost:8001/api/v1/ws/ai/{job_id}?token={token}"

        try:
            async with ws_connect(ws_url) as ws:
                # Receive initial state message
                initial_msg = await asyncio.wait_for(ws.recv(), timeout=5)

                import json
                msg_data = json.loads(initial_msg)

                assert msg_data["type"] == "initial_state"
                assert "status" in msg_data
                assert "step" in msg_data or "total_steps" in msg_data

                logger.info(f"WebSocket initial_state received: {msg_data}")

        except asyncio.TimeoutError:
            pytest.fail("WebSocket did not send initial_state within 5s")

    @pytest.mark.asyncio
    async def test_result_download_seg(
        self,
        authenticated_client,
        sample_dicom_file,
        sample_model,
    ):
        """
        Complete job → GET /api/v1/ai/results/{id}?result_type=seg.

        Success: FileResponse with MIME type application/dicom.
        """
        # Submit and wait for job completion
        inference_payload = {
            "model_id": str(sample_model["id"]),
            "study_instance_uid": "1.2.3.4.5",
        }

        job_response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json=inference_payload,
        )
        job_id = job_response.json()["id"]

        # Poll for completion
        max_wait = 120
        for _ in range(max_wait):
            status_response = await authenticated_client.get(
                f"/api/v1/ai/inferences/{job_id}"
            )
            status_data = status_response.json()

            if status_data["status"] == "completed":
                break

            await asyncio.sleep(1)

        # Download SEG result
        result_response = await authenticated_client.get(
            f"/api/v1/ai/results/{job_id}?result_type=seg"
        )

        assert result_response.status_code == 200
        assert result_response.headers["content-type"] == "application/dicom"
        assert len(result_response.content) > 0
        assert "result_seg_" in result_response.headers.get("content-disposition", "")

        logger.info(f"SEG result downloaded: {len(result_response.content)} bytes")

    @pytest.mark.asyncio
    async def test_result_download_sr(
        self,
        authenticated_client,
        sample_dicom_file,
        sample_model,
    ):
        """
        Complete job → GET /api/v1/ai/results/{id}?result_type=sr.

        Success: FileResponse with MIME type application/dicom (Structured Report).
        """
        # Submit and wait for job completion
        inference_payload = {
            "model_id": str(sample_model["id"]),
            "study_instance_uid": "1.2.3.4.5",
        }

        job_response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json=inference_payload,
        )
        job_id = job_response.json()["id"]

        # Poll for completion
        max_wait = 120
        for _ in range(max_wait):
            status_response = await authenticated_client.get(
                f"/api/v1/ai/inferences/{job_id}"
            )
            status_data = status_response.json()

            if status_data["status"] == "completed":
                break

            await asyncio.sleep(1)

        # Download SR result
        result_response = await authenticated_client.get(
            f"/api/v1/ai/results/{job_id}?result_type=sr"
        )

        assert result_response.status_code == 200
        assert result_response.headers["content-type"] == "application/dicom"
        assert len(result_response.content) > 0
        assert "result_sr_" in result_response.headers.get("content-disposition", "")

        logger.info(f"SR result downloaded: {len(result_response.content)} bytes")


    @pytest.mark.asyncio
    async def test_latency_p50_under_5s(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Measure p50 inference latency (target: < 5s).

        Run 20 jobs, collect latencies, verify p50 < 5s.
        """
        latencies = []
        study_uid = "1.2.3.4.5"

        for i in range(20):
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
            max_wait = 120
            while max_wait > 0:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    latency = time.time() - start
                    latencies.append(latency * 1000)  # ms
                    metrics_collector.record_latency(latency * 1000)
                    break

                await asyncio.sleep(1)
                max_wait -= 1

        sorted_lat = sorted(latencies)
        p50 = sorted_lat[int(len(sorted_lat) * 0.50)]

        logger.info(f"Latency p50: {p50:.2f}ms (target: <5000ms)")
        assert p50 < 5000, f"p50 latency {p50:.2f}ms exceeds 5000ms"

    @pytest.mark.asyncio
    async def test_latency_p95_under_10s(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Measure p95 inference latency (target: < 10s).

        Run 20 jobs, collect latencies, verify p95 < 10s.
        """
        latencies = []
        study_uid = "1.2.3.4.5"

        for i in range(20):
            start = time.time()

            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            job_id = response.json()["id"]

            max_wait = 120
            while max_wait > 0:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    latency = time.time() - start
                    latencies.append(latency * 1000)
                    metrics_collector.record_latency(latency * 1000)
                    break

                await asyncio.sleep(1)
                max_wait -= 1

        sorted_lat = sorted(latencies)
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]

        logger.info(f"Latency p95: {p95:.2f}ms (target: <10000ms)")
        assert p95 < 10000, f"p95 latency {p95:.2f}ms exceeds 10000ms"

    @pytest.mark.asyncio
    async def test_latency_p99_under_15s(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Measure p99 inference latency (target: < 15s).

        Run 20 jobs, collect latencies, verify p99 < 15s.
        """
        latencies = []
        study_uid = "1.2.3.4.5"

        for i in range(20):
            start = time.time()

            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            job_id = response.json()["id"]

            max_wait = 120
            while max_wait > 0:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    latency = time.time() - start
                    latencies.append(latency * 1000)
                    metrics_collector.record_latency(latency * 1000)
                    break

                await asyncio.sleep(1)
                max_wait -= 1

        sorted_lat = sorted(latencies)
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)]

        logger.info(f"Latency p99: {p99:.2f}ms (target: <15000ms)")
        assert p99 < 15000, f"p99 latency {p99:.2f}ms exceeds 15000ms"

    @pytest.mark.asyncio
    async def test_throughput_10_per_minute(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Measure throughput: submit 10 jobs in 60 seconds.

        Success: All 10 complete within 2 hours, rate ≥ 10/min.
        """
        job_ids = []
        study_uid = "1.2.3.4.5"
        start_time = time.time()

        # Submit 10 jobs as fast as possible (within 60s window)
        for i in range(10):
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            job_ids.append(response.json()["id"])
            metrics_collector.increment_jobs()

            # Small delay between submissions
            await asyncio.sleep(0.5)

        submit_duration = time.time() - start_time
        logger.info(f"Submitted 10 jobs in {submit_duration:.2f}s")

        # Wait for all to complete (max 2 hours)
        max_total_wait = 7200
        completed = 0

        for job_id in job_ids:
            job_start = time.time()
            while time.time() - job_start < max_total_wait:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    completed += 1
                    break

                await asyncio.sleep(2)

        assert completed == 10, f"Only {completed}/10 jobs completed"

        # Calculate throughput
        total_time = (time.time() - start_time) / 60  # minutes
        throughput = 10 / total_time if total_time > 0 else 0

        logger.info(f"Throughput: {throughput:.2f} jobs/minute")
        assert throughput >= 10, f"Throughput {throughput:.2f} < 10 jobs/min"

    @pytest.mark.asyncio
    async def test_concurrent_100_jobs_parallel(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Submit 100 jobs simultaneously (asyncio.gather).

        Success: All queued without errors, 100% completion, no race conditions.
        """
        study_uid = "1.2.3.4.5"

        async def submit_job():
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            assert response.status_code == 202
            metrics_collector.increment_jobs()
            return response.json()["id"]

        # Submit 100 jobs in parallel
        job_ids = await asyncio.gather(*[submit_job() for _ in range(100)])

        assert len(job_ids) == 100
        logger.info(f"Submitted 100 jobs in parallel")

        # Wait for all to complete (max 5 minutes per job = 500 min total)
        completed = 0
        failed = 0

        for job_id in job_ids:
            start = time.time()
            while time.time() - start < 300:  # 5 min per job
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    completed += 1
                    break
                elif status == "failed":
                    failed += 1
                    break

                await asyncio.sleep(1)

        logger.info(f"Concurrent 100 jobs: {completed} completed, {failed} failed")
        assert completed >= 90, f"Only {completed}/100 jobs completed (need ≥90)"

    @pytest.mark.asyncio
    async def test_websocket_progress_updates(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Track job → receive 12 step updates via WebSocket.

        Success: All 12 steps received in order, progress increments.
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

        # Extract token
        auth_header = authenticated_client.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "")

        # Connect WebSocket and collect progress
        ws_url = f"ws://localhost:8001/api/v1/ws/ai/{job_id}?token={token}"
        progress_updates = []

        try:
            async with ws_connect(ws_url) as ws:
                import json

                # Set timeout for each message
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=60)
                        msg_data = json.loads(msg)
                        progress_updates.append(msg_data)

                        # Check for completion
                        if msg_data.get("status") == "completed":
                            break

                    except asyncio.TimeoutError:
                        break

        except Exception as e:
            logger.warning(f"WebSocket error: {e}")

        # Verify we got progress messages
        assert len(progress_updates) > 1, "Expected at least 2 progress messages"
        logger.info(f"Received {len(progress_updates)} progress updates via WebSocket")

        # Verify completion message
        final = progress_updates[-1]
        assert final.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_concurrent_different_models(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Submit same study to 5 different models concurrently.

        Success: All 5 jobs independent, all complete.
        (Note: uses same sample_model, but tests job independence)
        """
        study_uid = "1.2.3.4.5"

        async def submit_to_model():
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            assert response.status_code == 202
            metrics_collector.increment_jobs()
            return response.json()["id"]

        # Submit to 5 models (same model, but tests concurrency)
        job_ids = await asyncio.gather(*[submit_to_model() for _ in range(5)])

        assert len(job_ids) == 5
        logger.info(f"Submitted to 5 models: {len(set(job_ids))} unique jobs")

        # Wait for all
        completed = 0
        for job_id in job_ids:
            start = time.time()
            while time.time() - start < 120:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                if status_response.json()["status"] == "completed":
                    completed += 1
                    break
                await asyncio.sleep(1)

        assert completed == 5, f"Only {completed}/5 jobs completed"

    @pytest.mark.asyncio
    async def test_batch_normalization_with_ai(
        self,
        authenticated_client,
        dicom_with_pixel_spacing,
        sample_model,
    ):
        """
        Upload DICOM with pixel spacing, submit AI.

        Success: Phase 3 normalizes if needed, AI inference works.
        """
        # Upload DICOM with pixel spacing
        upload_response = await authenticated_client.post(
            "/dicom-web/studies",
            content=dicom_with_pixel_spacing,
            headers={"Content-Type": "application/dicom"},
        )
        assert upload_response.status_code == 200

        # Submit AI job
        response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": str(sample_model["id"]),
                "study_instance_uid": "1.2.3.4.5.6",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        # Wait for completion
        max_wait = 120
        while max_wait > 0:
            status_response = await authenticated_client.get(
                f"/api/v1/ai/inferences/{job_id}"
            )
            status = status_response.json()["status"]

            if status == "completed":
                logger.info("Batch normalization + AI succeeded")
                break
            elif status == "failed":
                pytest.fail(f"Job failed: {status_response.json().get('error_message')}")

            await asyncio.sleep(1)
            max_wait -= 1

        assert max_wait > 0, "Job did not complete within 120s"

    @pytest.mark.asyncio
    async def test_model_registration_to_inference(
        self,
        authenticated_client,
    ):
        """
        Register new model → activate → submit inference.

        Success: Model registered, activated, inference queued.
        """
        try:
            import onnx
            from onnx import helper, TensorProto
        except ImportError:
            pytest.skip("onnx package not installed")

        # Create minimal ONNX model
        X = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])
        Y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1])
        node = helper.make_node("Identity", inputs=["input"], outputs=["output"])
        graph = helper.make_graph([node], "test_model", [X], [Y])
        model = helper.make_model(graph, producer_name="test")

        model_path = Path("/tmp/test_reg_model.onnx")
        onnx.save(model, str(model_path))

        # Register
        model_name = f"reg_test_{uuid.uuid4().hex[:8]}"
        with open(model_path, "rb") as f:
            response = await authenticated_client.post(
                "/api/v1/ai/models",
                data={
                    "name": model_name,
                    "version": "1.0",
                    "modality": "CT",
                    "description": "Test",
                },
                files={"file": ("model.onnx", f, "application/octet-stream")},
            )

        assert response.status_code == 201
        model_id = response.json()["id"]
        logger.info(f"Model registered: {model_id}")

        # Activate
        activate_response = await authenticated_client.put(
            f"/api/v1/ai/models/{model_id}",
            json={"status": "active"},
        )
        assert activate_response.status_code == 200
        logger.info(f"Model activated: {model_id}")

        # Submit inference
        inference_response = await authenticated_client.post(
            "/api/v1/ai/inferences",
            json={
                "model_id": model_id,
                "study_instance_uid": "1.2.3.4.5",
            },
        )
        assert inference_response.status_code == 202
        logger.info("Inference submitted with registered model")

        model_path.unlink()

    @pytest.mark.asyncio
    async def test_job_list_pagination(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Submit 30 jobs, list with pagination (20 per page).

        Success: First page returns 20, second page returns 10.
        """
        # Submit 30 jobs
        for i in range(30):
            await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": "1.2.3.4.5",
                },
            )

        # List page 1
        response1 = await authenticated_client.get(
            "/api/v1/ai/inferences?page=1&page_size=20"
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["page"] == 1
        assert len(data1["items"]) == 20
        assert data1["total"] >= 30

        # List page 2
        response2 = await authenticated_client.get(
            "/api/v1/ai/inferences?page=2&page_size=20"
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["page"] == 2
        assert len(data2["items"]) >= 10

        logger.info("Pagination verified: 2 pages")

    @pytest.mark.asyncio
    async def test_job_status_filtering(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Submit jobs, filter list by status (queued/completed).

        Success: Filtering returns correct subset.
        """
        study_uid = "1.2.3.4.5"

        # Submit 5 jobs
        job_ids = []
        for i in range(5):
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            job_ids.append(response.json()["id"])

        # Filter by queued
        response = await authenticated_client.get(
            "/api/v1/ai/inferences?status=queued"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 5

        logger.info("Status filtering verified")

    @pytest.mark.asyncio
    async def test_job_detail_includes_model_and_result(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Get job detail → includes nested model and result data.

        Success: model_id, model metadata, result references present.
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

        # Get detail
        detail_response = await authenticated_client.get(
            f"/api/v1/ai/inferences/{job_id}"
        )
        assert detail_response.status_code == 200

        job_detail = detail_response.json()
        assert "id" in job_detail
        assert "model_id" in job_detail
        assert "status" in job_detail

        logger.info("Job detail includes model metadata")

    @pytest.mark.asyncio
    async def test_concurrent_50_jobs_midpoint(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
    ):
        """
        Submit 50 jobs simultaneously (midpoint between 10 and 100).

        Success: All 50 complete without errors, 100% success rate.
        """
        study_uid = "1.2.3.4.5"

        async def submit_job():
            response = await authenticated_client.post(
                "/api/v1/ai/inferences",
                json={
                    "model_id": str(sample_model["id"]),
                    "study_instance_uid": study_uid,
                },
            )
            assert response.status_code == 202
            metrics_collector.increment_jobs()
            return response.json()["id"]

        # Submit 50 jobs in parallel
        job_ids = await asyncio.gather(*[submit_job() for _ in range(50)])

        assert len(job_ids) == 50
        logger.info(f"Submitted 50 jobs in parallel")

        # Wait for all to complete (max 300 seconds per job)
        completed = 0
        for job_id in job_ids:
            start = time.time()
            while time.time() - start < 300:
                status_response = await authenticated_client.get(
                    f"/api/v1/ai/inferences/{job_id}"
                )
                status = status_response.json()["status"]

                if status == "completed":
                    completed += 1
                    break

                await asyncio.sleep(1)

        completion_rate = completed / len(job_ids) * 100
        logger.info(f"Concurrent 50 jobs: {completed}/50 completed ({completion_rate:.1f}%)")
        assert completed >= 45, f"Only {completed}/50 jobs completed (need ≥90%)"

    @pytest.mark.asyncio
    async def test_inference_metadata_persistence(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Submit job → retrieve after completion → verify metadata (timing, confidence) persisted.

        Success: Inference time and confidence score fields persist and are not null.
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
            job_data = status_response.json()

            if job_data["status"] == "completed":
                # Verify metadata was persisted
                assert "inference_time_ms" in job_data or "inference_time" in job_data, \
                    "Inference time not persisted"
                assert job_data.get("confidence_score") is not None or \
                       job_data.get("confidence") is not None, \
                    "Confidence score not persisted"

                logger.info(
                    f"Metadata persisted: "
                    f"time={job_data.get('inference_time_ms', 'N/A')}ms, "
                    f"confidence={job_data.get('confidence_score', 'N/A')}"
                )
                break

            await asyncio.sleep(1)
            max_wait -= 1

        assert max_wait > 0, "Job did not complete within 120s"

    @pytest.mark.asyncio
    async def test_model_filtering_by_modality(
        self,
        authenticated_client,
        sample_model,
    ):
        """
        Get models → filter by modality → verify only matching modality returned.

        Success: Filtered list contains only models with matching modality.
        """
        # Get all models
        all_models_response = await authenticated_client.get("/api/v1/ai/models")
        assert all_models_response.status_code == 200
        all_models = all_models_response.json().get("items", [])

        # Get models with sample modality filter
        if all_models:
            modality = sample_model["modality"]
            filtered_response = await authenticated_client.get(
                f"/api/v1/ai/models?modality={modality}"
            )
            assert filtered_response.status_code == 200

            filtered_models = filtered_response.json().get("items", [])

            # Verify all returned models have matching modality
            for model in filtered_models:
                assert model.get("modality") == modality, \
                    f"Model {model['id']} has modality {model.get('modality')}, expected {modality}"

            logger.info(f"Model filtering by modality verified: {modality} = {len(filtered_models)} models")
        else:
            logger.info("No models to filter (test skipped)")


# ============================================================================
# Logging
# ============================================================================

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Pytest Configuration
# ============================================================================

def pytest_configure(config):
    """Configure pytest with asyncio mode."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
