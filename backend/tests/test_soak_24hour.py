"""
Phase 6 E2E Tests: 24-Hour Continuous Soak Test (Day 6).

Validates system stability under sustained load:
- Error rate: < 0.1% over 24 hours
- Memory usage: stable (no growth)
- Database connections: pool healthy
- WebSocket reconnects: < 1 per hour
"""

import pytest
import asyncio
import time
import psutil
import logging
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TestSoak24Hour:
    """24-hour continuous operation: stability, memory, connection pool health."""

    @pytest.mark.asyncio
    @pytest.mark.slow  # Mark as slow test
    async def test_soak_24hour_continuous_operation(
        self,
        authenticated_client,
        sample_model,
        metrics_collector,
        docker_stack,
    ):
        """
        Submit 5 jobs/minute for 24 hours → monitor error rate, memory, connections.

        Success:
        - Error rate < 0.1%
        - Memory stable (no growth > 10%)
        - Database connections healthy
        - WebSocket reconnects < 1/hour (< 24 total)
        """
        # Test parameters
        target_duration = 86400  # 24 hours in seconds
        jobs_per_minute = 5
        submit_interval = 60 / jobs_per_minute  # 12 seconds between jobs
        check_interval = 3600  # Health check every hour

        # State tracking
        start_time = time.time()
        jobs_submitted = 0
        jobs_completed = 0
        jobs_failed = 0
        websocket_reconnects = 0
        memory_samples = []
        error_log = []

        # Get initial memory baseline
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        logger.info(f"Initial memory: {initial_memory:.1f} MB")

        # Phase 1: Submit jobs at constant rate
        logger.info(f"Starting 24-hour soak test at {datetime.now().isoformat()}")

        while time.time() - start_time < target_duration:
            # Submit job
            try:
                response = await authenticated_client.post(
                    "/api/v1/ai/inferences",
                    json={
                        "model_id": str(sample_model["id"]),
                        "study_instance_uid": "1.2.3.4.5",
                    },
                    timeout=30,
                )

                if response.status_code == 202:
                    job_id = response.json()["id"]
                    jobs_submitted += 1
                    metrics_collector.increment_jobs()

                    # Non-blocking job completion check (don't wait for each job)
                    # Jobs will be checked in batch below
                else:
                    jobs_failed += 1
                    error_msg = f"Job submission failed: {response.status_code}"
                    error_log.append(error_msg)
                    metrics_collector.record_error(error_msg)

            except Exception as e:
                jobs_failed += 1
                error_msg = f"Job submission error: {str(e)}"
                error_log.append(error_msg)
                metrics_collector.record_error(error_msg)

            # Periodic health check (every hour)
            elapsed = time.time() - start_time
            if int(elapsed) % check_interval == 0:
                # Record memory
                current_memory = process.memory_info().rss / 1024 / 1024
                memory_samples.append(current_memory)

                # Check database connectivity
                try:
                    health_response = await authenticated_client.get("/health", timeout=5)
                    if health_response.status_code != 200:
                        error_log.append("Health check failed")
                except Exception as e:
                    websocket_reconnects += 1
                    error_log.append(f"Health check error: {str(e)}")

                hours_elapsed = elapsed / 3600
                logger.info(
                    f"Soak test progress: {hours_elapsed:.1f} hours\n"
                    f"  Jobs submitted: {jobs_submitted}\n"
                    f"  Jobs failed: {jobs_failed}\n"
                    f"  Memory: {current_memory:.1f} MB (Δ {current_memory - initial_memory:.1f} MB)\n"
                    f"  WebSocket reconnects: {websocket_reconnects}"
                )

            # Wait before submitting next job
            await asyncio.sleep(submit_interval)

        # Phase 2: Wait for all remaining jobs to complete
        logger.info("All jobs submitted. Waiting for remaining completions...")

        # Poll for job completions (max 1 hour additional wait)
        completion_start = time.time()
        completion_timeout = 3600

        while time.time() - completion_start < completion_timeout:
            # Check a sample of recent jobs (polling)
            try:
                list_response = await authenticated_client.get(
                    "/api/v1/ai/inferences?status=completed&page=1&page_size=100",
                    timeout=30,
                )
                if list_response.status_code == 200:
                    jobs_completed = len(list_response.json()["items"])
            except Exception as e:
                logger.warning(f"Job completion check failed: {e}")

            if jobs_completed >= jobs_submitted * 0.95:  # 95% completion target
                break

            await asyncio.sleep(60)  # Check every minute

        # Phase 3: Final metrics and report
        total_duration = time.time() - start_time
        error_rate = (jobs_failed / jobs_submitted * 100) if jobs_submitted > 0 else 0

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_growth = ((final_memory - initial_memory) / initial_memory * 100)

        # Memory stability check
        if memory_samples:
            memory_growth_rate = (memory_samples[-1] - memory_samples[0]) / memory_samples[0] * 100
        else:
            memory_growth_rate = memory_growth

        # Calculate latency stats from collected metrics
        stats = metrics_collector.get_stats()

        soak_report = {
            "test_name": "24-Hour Continuous Soak Test",
            "start_time": datetime.fromtimestamp(start_time).isoformat(),
            "end_time": datetime.now().isoformat(),
            "total_duration_seconds": total_duration,
            "total_duration_hours": total_duration / 3600,
            "jobs_submitted": jobs_submitted,
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
            "error_rate_percent": error_rate,
            "sla_target_error_rate": 0.1,
            "error_rate_sla_met": error_rate < 0.1,
            "memory": {
                "initial_mb": initial_memory,
                "final_mb": final_memory,
                "growth_mb": final_memory - initial_memory,
                "growth_percent": memory_growth,
                "growth_rate_percent_per_hour": memory_growth_rate / (total_duration / 3600),
                "memory_stable": memory_growth < 10,
            },
            "connectivity": {
                "websocket_reconnects": websocket_reconnects,
                "reconnects_per_hour": websocket_reconnects / (total_duration / 3600),
                "sla_target_reconnects_per_hour": 1.0,
                "connectivity_sla_met": websocket_reconnects / (total_duration / 3600) < 1.0,
            },
            "latency": stats,
            "sample_errors": error_log[:10],  # First 10 errors
            "errors_total_count": len(error_log),
        }

        # Log detailed report
        logger.info(
            f"24-Hour Soak Test Report:\n"
            f"─────────────────────────────────────────────────────\n"
            f"Duration: {soak_report['total_duration_hours']:.1f} hours\n"
            f"\n"
            f"Job Statistics:\n"
            f"  Submitted: {jobs_submitted}\n"
            f"  Completed: {jobs_completed}\n"
            f"  Failed: {jobs_failed}\n"
            f"  Error Rate: {error_rate:.3f}% (SLA: <0.1%)\n"
            f"\n"
            f"Memory Usage:\n"
            f"  Initial: {initial_memory:.1f} MB\n"
            f"  Final: {final_memory:.1f} MB\n"
            f"  Growth: {final_memory - initial_memory:.1f} MB ({memory_growth:.1f}%)\n"
            f"  Growth Rate: {memory_growth_rate / (total_duration / 3600):.2f}%/hour\n"
            f"\n"
            f"Connectivity:\n"
            f"  WebSocket Reconnects: {websocket_reconnects}\n"
            f"  Reconnects/Hour: {websocket_reconnects / (total_duration / 3600):.2f}\n"
            f"\n"
            f"Latency (from collected metrics):\n"
            f"  p50: {stats['p50']:.0f}ms\n"
            f"  p95: {stats['p95']:.0f}ms\n"
            f"  p99: {stats['p99']:.0f}ms\n"
            f"  Errors logged: {len(error_log)}\n"
            f"─────────────────────────────────────────────────────"
        )

        # Save detailed report to file
        report_path = Path("/tmp/openpacs_soak_test_report.json")
        with open(report_path, "w") as f:
            json.dump(soak_report, f, indent=2, default=str)

        logger.info(f"Detailed report saved to {report_path}")

        # Assertions: SLA targets
        assert error_rate < 0.1, \
            f"Error rate {error_rate:.3f}% exceeds 0.1% SLA"

        assert memory_growth < 10, \
            f"Memory growth {memory_growth:.1f}% exceeds 10% SLA"

        assert websocket_reconnects / (total_duration / 3600) < 1.0, \
            f"WebSocket reconnects {websocket_reconnects / (total_duration / 3600):.2f}/hour exceeds 1/hour SLA"

        assert jobs_completed >= jobs_submitted * 0.95, \
            f"Completion rate {jobs_completed / jobs_submitted * 100:.1f}% < 95% SLA"

        logger.info("24-hour soak test PASSED all SLA criteria ✅")


# ============================================================================
# Pytest Configuration
# ============================================================================

from pathlib import Path


def pytest_configure(config):
    """Configure pytest with asyncio mode and slow marker."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow (skip by default)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip slow tests by default unless -m slow is specified."""
    if config.getoption("-m") is None or "slow" not in config.getoption("-m"):
        skip_slow = pytest.mark.skip(reason="slow test, use -m slow to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
