# Phase 6 Design: E2E Integration Testing

**Document Version**: 1.0  
**Date**: 2026-05-14  
**Based On**: phase-6-e2e-integration-testing.plan.md  
**Target**: Implementation in Phase 6 Do  

---

## 1. Architecture Overview

### Test Infrastructure Stack

```
┌─────────────────────────────────────────────────────────┐
│                   E2E Test Framework                     │
│  (pytest, pytest-asyncio, httpx, websockets-client)    │
└────────────────┬────────────────────────────────────────┘
                 │
     ┌───────────┼───────────────────────┬────────────┐
     │           │                       │            │
┌────▼────┐ ┌──▼──────┐ ┌──────────┐ ┌─▼──────┐ ┌──▼──────┐
│ API     │ │WebSocket│ │Database  │ │Docker  │ │Monitoring
│Tests    │ │Tests    │ │Snapshot  │ │Health  │ │/Metrics
└─────────┘ └─────────┘ └──────────┘ └────────┘ └─────────┘
     │           │           │            │           │
     └───────────┴───────────┴────────────┴───────────┘
            ↓
    [Docker Compose Stack]
    - PostgreSQL 16
    - Redis 7
    - Orthanc 1.12
    - FastAPI (8001)
    - OHIF (3001)
```

### Test Execution Flow

```
Test Discovery
    ↓
Setup (Fixtures: DB, Redis, Docker, Seed Data)
    ↓
Happy Path Tests (Workflow A, B, C, D)
    ↓
Error Path Tests (Exception Handling)
    ↓
Data Integrity Tests (Crash Recovery)
    ↓
Performance Tests (SLA Validation)
    ↓
24-Hour Soak Test (Stability)
    ↓
Teardown (Cleanup, Snapshots)
    ↓
Report Generation
```

---

## 2. Test Framework Design

### Framework Selection
- **Primary**: pytest 8.0+ (async support via pytest-asyncio)
- **HTTP Client**: httpx (async)
- **WebSocket Client**: websockets 12.0+
- **Database**: sqlalchemy + asyncpg
- **Mocking**: unittest.mock + pytest-mock
- **Fixtures**: Custom pytest fixtures for setup/teardown

### Test Structure

```
backend/tests/
├── conftest.py                           # Global fixtures
├── test_e2e_dicom_ai.py                 # Workflow A, B, C
├── test_e2e_error_scenarios.py          # Error paths
├── test_e2e_data_integrity.py           # Crash/recovery
├── test_e2e_performance.py              # Latency/throughput
├── test_soak_24hour.py                  # Stability
├── fixtures/
│   ├── docker.py                        # Docker setup
│   ├── database.py                      # DB snapshots
│   ├── sample_data.py                   # DICOM files, models
│   └── mocks.py                         # Orthanc mocks
└── integration/
    ├── conftest.py                      # Shared setup
    └── test_*.py                        # Integration tests
```

### Key Fixtures (pytest)

```python
@pytest.fixture(scope="session")
async def docker_stack():
    """Start/stop Docker Compose stack for entire session"""
    yield stack

@pytest.fixture(autouse=True)
async def reset_db(docker_stack):
    """Reset database to snapshot before each test"""
    yield
    await restore_db_snapshot()

@pytest.fixture
async def authenticated_client(docker_stack):
    """HTTP client with JWT token"""
    token = await create_test_user()
    yield httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}
    )

@pytest.fixture
async def sample_dicom_file():
    """Load test DICOM file (CT chest, 50 images)"""
    return load_dicom("fixtures/ct_chest_sample.dcm")

@pytest.fixture
async def sample_model():
    """Register test AI model (small ONNX for fast inference)"""
    return await register_test_model("model_small_v1.0.onnx")
```

---

## 3. Test Specifications

### Test Suite 1: Happy Path Workflows (20 tests)

#### Test Group A: Complete DICOM + AI Pipeline

**Test: test_complete_workflow_dicom_upload_to_result_download**
```gherkin
Given: Test user (radiologist role)
When:  
  1. Upload CT chest DICOM (50 images)
  2. Wait for batch normalization
  3. Register AI model (lung cancer detector)
  4. Submit inference job
  5. Track progress via WebSocket (verify step 1→12)
  6. Download SEG result
Then:
  - Job status: queued → running → completed
  - WebSocket received ≥8 progress updates
  - Result file exists, valid DICOM format
  - Metadata saved in database
Expected Duration: 45-60 seconds
```

**Test: test_ai_inference_latency_p95**
```python
# Measure: Time from submission to completed
# Expected: P95 < 10 seconds
# Validate: Consistent across 10 runs
```

**Test: test_concurrent_100_jobs**
```python
# Submit 100 parallel inference jobs
# Expected: All complete without race conditions
# Validate: 100% success rate, zero data loss
# Duration: 5-10 minutes
```

**Test: test_websocket_real_time_progress**
```python
# Connect WebSocket, track job
# Verify:
#   - initial_state message (job metadata)
#   - status_update messages (each step)
#   - Message latency < 100ms
#   - Auto-reconnect on disconnect (>99% success)
```

#### Test Group B: Batch Normalization + AI

**Test: test_batch_normalize_jpeg_density_then_ai**
```python
# Upload DICOM with JPEG DPI mismatch
# Verify:
#   - Phase 3 detects density issue
#   - Auto-corrects (density → Pixel Spacing)
#   - Phase 5 AI works on corrected image
#   - Result accuracy matches normalized image
```

#### Test Group C: Model Management

**Test: test_register_activate_infer_workflow**
```python
# 1. Register new ONNX model
# 2. Activate model
# 3. Submit inference
# 4. Verify uses activated model
# 5. Deactivate, verify rejection
```

#### Test Group D: API Integration

**Test: test_get_ai_results_download**
```python
# Verify GET /api/v1/ai/results/{job_id}
# Validates:
#   - Returns DICOM bytes (application/dicom)
#   - Correct file integrity (MD5 checksum)
#   - Proper error codes (404, 409, 422)
#   - Permission checks (owner/admin)
```

### Test Suite 2: Error Path Scenarios (12 tests)

**Error Group E1: Invalid Input**
- test_upload_invalid_dicom_format → 400 Bad Request
- test_submit_inference_model_not_found → 404 Not Found
- test_register_duplicate_model → 409 Conflict
- test_invalid_result_type_parameter → 422 Unprocessable Entity

**Error Group E2: State Errors**
- test_inference_on_inactive_model → 404 Model not available
- test_download_incomplete_job → 409 Job not completed
- test_cancel_completed_job → 409 Invalid state transition
- test_websocket_job_not_found → WebSocket close code 1008

**Error Group E3: Infrastructure Failures**
- test_orthanc_connection_timeout → Retry 3x, then fail
- test_database_connection_loss → Graceful degradation
- test_websocket_disconnect_auto_reconnect → Exponential backoff
- test_celery_task_timeout → 10-minute hard limit

### Test Suite 3: Data Integrity (8 tests)

**Integrity Group I1: Atomicity**
- test_inference_all_or_nothing → No partial updates
- test_model_registration_rollback → File + DB synchronized
- test_cascade_delete_model_deletes_jobs → Foreign key constraints

**Integrity Group I2: Crash Recovery**
- test_db_snapshot_restore → State preserved on restart
- test_orphaned_result_cleanup → 30-day retention policy
- test_concurrent_writes_no_corruption → Pessimistic locking

**Integrity Group I3: Idempotency**
- test_duplicate_job_submission → Only one actual job created
- test_retry_same_inference → Same result as first attempt

### Test Suite 4: Performance Baselines (5 tests)

**Performance Group P1: Latency**
```python
# test_inference_latency_percentiles
# Measure from submission → completed
results = run_10_inferences()
assert results['p50'] < 5.0   # seconds
assert results['p95'] < 10.0
assert results['p99'] < 15.0
```

**Performance Group P2: Throughput**
```python
# test_throughput_jobs_per_minute
jobs_submitted = 0
for 1_minute:
    submit_job()
    jobs_submitted += 1
assert jobs_submitted >= 10  # jobs/minute
```

**Performance Group P3: WebSocket Latency**
```python
# test_websocket_message_latency
# Measure: emit → receive
latencies = []
for msg in progress_updates:
    latencies.append(msg.received_at - msg.sent_at)
assert percentile(latencies, 95) < 100  # milliseconds
```

**Performance Group P4: API Response Time**
```python
# test_api_response_time
responses = []
for endpoint in [list_jobs, get_models, submit_inference]:
    latencies = run_100_requests(endpoint)
    assert percentile(latencies, 95) < 500  # milliseconds
```

**Performance Group P5: Database Query Performance**
```python
# test_db_query_performance
# Verify indexes are used
# list_jobs with pagination: < 50ms
# get_job with nested model: < 30ms
```

### Test Suite 5: 24-Hour Soak Test (1 test)

**Soak Test: test_24hour_continuous_operation**
```python
duration = 24 * 3600  # seconds
submit_rate = 5 / 60  # jobs per second
start_time = now()

while (now() - start_time) < duration:
    # Submit job every 12 seconds
    if should_submit():
        submit_inference_job()
    
    # Monitor metrics every minute
    if minute_elapsed():
        log_metrics({
            'jobs_completed': count,
            'error_count': errors,
            'avg_latency': avg,
            'memory_usage': mem,
            'db_connections': conns,
        })

# Success Criteria:
assert error_rate < 0.001  # < 0.1%
assert memory_growth < 100  # MB (no leaks)
assert db_connections == initial  # stable
assert uptime == 99.9  # %
```

---

## 4. Test Data Strategy

### Sample DICOM Files

| File | Modality | Size | Purpose | Source |
|------|----------|------|---------|--------|
| ct_chest_sample.dcm | CT | 50 images | Happy path | DICOM samples |
| ct_abnormal.dcm | CT | 30 images | Detection test | With lung lesion |
| cr_jpeg_density_issue.dcm | CR | 1 image | Normalization | Malformed JPEG DPI |
| mr_brain.dcm | MR | 40 images | Multi-modality test | MR sample |
| invalid.dcm | Invalid | N/A | Error path | Corrupted header |

**Location**: `backend/tests/fixtures/sample_dicom/`

### Test Models

| Model | Format | Size | Purpose |
|-------|--------|------|---------|
| model_tiny_v1.0.onnx | ONNX | <5MB | Fast inference (<1s) |
| model_small_v2.0.onnx | ONNX | <20MB | Moderate inference (2-3s) |
| model_invalid.onnx | ONNX | Invalid | Error path |

**Location**: `backend/tests/fixtures/models/`

### Database Snapshots

**Snapshot Strategy**:
- Create initial snapshot after Docker stack starts
- Restore before each test (ensures clean state)
- Snapshot format: PostgreSQL SQL dump (pg_dump)

```bash
# Create snapshot
pg_dump openpacs > snapshot_base.sql

# Restore before test
psql openpacs < snapshot_base.sql
```

---

## 5. Implementation Details

### Setup Phase (Pre-Test)

```python
# 1. Start Docker Compose
docker_compose_up(["postgres", "redis", "orthanc", "backend"])

# 2. Wait for health checks
wait_for_services(timeout=30s)

# 3. Create test users
create_user("radiologist", role="radiologist")
create_user("admin", role="admin")

# 4. Register test models
register_model("model_tiny_v1.0.onnx", modality="CT")

# 5. Create database snapshot
pg_dump openpacs > snapshot_base.sql

# 6. Start monitoring (if available)
start_prometheus_scrape()
start_docker_stats_collection()
```

### Teardown Phase (Post-Test)

```python
# 1. Collect logs/metrics
docker_logs_save("logs/docker_errors.txt")
metrics_save("logs/metrics.json")

# 2. Cleanup
docker_compose_down()

# 3. Generate report
generate_html_report(
    passed=pass_count,
    failed=fail_count,
    skipped=skip_count,
    duration=test_duration,
    metrics=perf_metrics,
)
```

### Test Execution Command

```bash
# Run all E2E tests with markers
pytest backend/tests/test_e2e_*.py \
  -v \
  --tb=short \
  -m "not soak" \
  --timeout=60 \
  --asyncio-mode=auto

# Run only soak test (24 hours)
pytest backend/tests/test_soak_24hour.py \
  -v \
  --timeout=86400 \
  --asyncio-mode=auto
```

---

## 6. Workflow Specifications

### Workflow A: Complete DICOM + AI Pipeline

**Sequence Diagram**:
```
Client          API         Celery      Orthanc     Database
  |              |             |           |            |
  |--POST        |             |           |            |
  | DICOM--------|             |           |            |
  |              |--Validate---|           |            |
  |              |--202--------|           |            |
  |              |             |--Fetch----|--Create----|
  |              |             | Study     |            |
  |              |             |           |            |
  |--WS--------- |             |           |            |
  | Subscribe   |             |           |            |
  |              |             |--Infer----|            |
  |<--Message----|             |           |            |
  | (step 5/12)  |             |           |            |
  |              |             |           |--Generate--|
  |              |             |           | SEG        |
  |              |             |--Upload---|--Update----|
  |<--Message----|             |           |            |
  | (step 12/12) |             |           |            |
  |              |             |--Mark-----|--Status----|
  |              |             | complete  | completed  |
  |--GET--------|             |           |            |
  | results/id  |             |           |            |
  |<--DICOM-----|             |           |            |
```

**Expected Timing**:
- Fetch DICOM: 1s
- Validate: 1s
- Load model: 2s
- Inference: 5s
- Build SEG: 2s
- Upload: 2s
- Database update: 1s
- **Total**: 14s ± 2s

---

## 7. Success Criteria & Metrics

### Functional Criteria (Must Pass)

| Criterion | Threshold | Validation |
|-----------|-----------|------------|
| E2E Test Pass Rate | ≥95% (44/46 tests) | Automated |
| Workflow A Success | 100% (20/20 tests) | Manual review |
| Workflow B Success | 100% (5/5 tests) | Manual review |
| Workflow C Success | 100% (10/10 tests) | Manual review |
| Workflow D Success | 100% (11/11 tests) | Error logs |
| Data Integrity | 100% (no loss) | Database audit |

### Performance Criteria (SLA Baseline)

| Metric | Target | Notes |
|--------|--------|-------|
| Inference Latency (P50) | <5s | Single job |
| Inference Latency (P95) | <10s | 95% of jobs |
| Inference Latency (P99) | <15s | 99% of jobs |
| API Response Time (P95) | <500ms | /api/v1/ai/* |
| WebSocket Latency | <100ms | Message roundtrip |
| Throughput | ≥10 jobs/min | Peak sustained |
| Error Rate | <0.1% | Over 24 hours |

### Reliability Criteria (24-Hour Soak)

| Metric | Target | Validation |
|--------|--------|------------|
| Uptime | ≥99.9% | Continuous monitoring |
| Memory Stability | <100MB growth | Every 10 minutes |
| Database Connections | Stable (±5%) | Connection pooling |
| WebSocket Reconnect Success | ≥99% | Forced disconnect tests |
| Log Errors | Zero critical | Error log analysis |

---

## 8. Monitoring & Observability

### Metrics to Collect

```
Application Metrics:
  - inference_latency (histogram: p50, p95, p99)
  - job_submission_rate (counter: jobs/minute)
  - job_completion_time (histogram: seconds)
  - websocket_connections_active (gauge)
  - websocket_reconnect_attempts (counter)
  - api_request_duration (histogram: milliseconds)
  
System Metrics:
  - docker_container_memory (gauge: MB)
  - docker_container_cpu (gauge: %)
  - postgres_connections (gauge)
  - redis_memory (gauge: MB)
  - disk_space_free (gauge: GB)
  
Error Metrics:
  - inference_failures (counter)
  - api_errors_4xx (counter)
  - api_errors_5xx (counter)
  - websocket_disconnects (counter)
  - database_errors (counter)
```

### Logging Requirements

- **INFO**: Test start/stop, workflow transitions
- **DEBUG**: API requests/responses, WebSocket messages
- **WARN**: Retries, slow operations (>SLA)
- **ERROR**: Failed tests, exception stack traces

**Log Format**: JSON (for parsing)

```json
{
  "timestamp": "2026-05-14T10:30:45.123Z",
  "level": "INFO",
  "test": "test_complete_workflow_dicom_upload_to_result_download",
  "message": "Workflow A completed",
  "duration_ms": 47500,
  "job_id": "uuid-1234",
  "status": "PASS"
}
```

---

## 9. Risk Mitigation

### Identified Risks

| Risk | Probability | Mitigation |
|------|-------------|-----------|
| WebSocket timeout | Medium | Configurable timeouts, auto-retry |
| Orthanc slowdown | Low | Mock Orthanc for unit tests |
| Database deadlock | Low | Optimistic/pessimistic locking tests |
| Out of disk space | Low | Cleanup old test data |
| Test flakiness | Medium | Retry failed tests 3x |

### Flakiness Handling

```python
@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_sometimes_slow_operation():
    """Automatically retry if fails"""
    pass
```

---

## 10. Acceptance Criteria

### For Phase 6 Completion

- [ ] All 46 E2E tests written and passing
- [ ] Happy path coverage: 100% (Workflows A, B, C, D)
- [ ] Error path coverage: ≥12 scenarios
- [ ] Performance baselines established (5 tests)
- [ ] 24-hour soak test completed successfully
- [ ] Test report generated (HTML)
- [ ] Documentation complete (test plan, results)
- [ ] CI/CD integration ready (GitHub Actions)

### Definition of Done

A test is "DONE" when:
1. ✅ Passes consistently (5 runs without flakes)
2. ✅ Documented (purpose, expected duration)
3. ✅ Metrics tracked (latency, error rate)
4. ✅ Integrated into test suite
5. ✅ No external dependencies (self-contained)

---

## 11. Implementation Order

### Week 1 (Phase 6 Do)

**Day 1**: Setup & Fixtures
- Docker Compose integration
- Pytest fixture setup
- Sample data loading

**Day 2**: Happy Path Tests
- Workflow A (DICOM + AI)
- Workflow B (Batch normalization)
- Workflow C (Concurrent jobs)

**Day 3**: Error & Recovery Tests
- Error path scenarios
- Database crash recovery
- WebSocket auto-reconnect

**Day 4**: Performance Tests
- Latency baselines
- Throughput measurements
- API response times

**Day 5-6**: Soak Test
- 24-hour continuous operation
- Metrics collection
- Report generation

**Day 7**: Analysis & Review
- Test report finalization
- Gap analysis
- Sign-off

---

## 12. Documentation Outputs

### Code-Level Documentation

- Docstrings on all test functions
- Inline comments for complex logic
- Type hints (async function signatures)

### User-Level Documentation

- `test-plan.md` (objectives, scope)
- `workflows.md` (A, B, C, D specifications)
- `performance-baseline.md` (SLA metrics)
- `monitoring-setup.md` (observability)
- `troubleshooting.md` (common failures)

### Generated Reports

- `test-results.html` (pass/fail, duration)
- `performance-report.json` (latencies, throughput)
- `coverage-report.html` (code coverage %)
- `soak-test-report.json` (24-hour metrics)

---

## 13. Conclusion

This design provides a **comprehensive E2E testing framework** validating Phase 1-5 integration. The **46-test suite** covers happy paths, error scenarios, data integrity, and performance baselines within a **7-day timeline**.

**Next Step**: `/pdca do phase-6-e2e-integration-testing` (Implementation)

---

*Design prepared for Phase 6 Do implementation*  
*Reference: phase-6-e2e-integration-testing.plan.md*
