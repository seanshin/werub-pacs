# Phase 6 Plan: E2E Integration Testing

**Document Version**: 1.0  
**Date**: 2026-05-14  
**Status**: PLANNING  
**Target Completion**: 2026-05-21 (1 week)  
**Project Level**: Enterprise

---

## 1. Executive Summary

Phase 6 establishes comprehensive **End-to-End (E2E) Integration Testing** for the OpenPACS system. This phase validates that all components from Phase 1-5 work together seamlessly in a complete workflow.

**Scope**: Full PACS workflow from DICOM upload → AI inference → report generation → result retrieval, with automated test validation and 24-hour monitoring.

---

## 2. Problem Statement & Motivation

### Current State (After Phase 5)
- ✅ Phase 1: Docker infrastructure
- ✅ Phase 2: PACS core + DICOMweb
- ✅ Phase 3: DICOM normalization/validation
- ✅ Phase 4: Batch processing
- ✅ Phase 5: AI model integration

**Gap**: No comprehensive E2E tests validating the entire workflow working together. Current tests are unit/service-level only.

### Business Need
- **Risk**: Partial system failures in production (e.g., AI results don't save correctly, WebSocket drops, batch processor fails mid-inference)
- **Requirement**: Automated E2E tests that validate complete workflows before staging/production deployment
- **Compliance**: Medical systems require traceability of data flow (audit logs, result storage, inference tracking)

### Why Phase 6 Matters
1. **Production Confidence**: Verify no data loss or state corruption in real workflows
2. **Performance Baseline**: Establish SLA metrics (inference latency, throughput, error rates)
3. **Regression Prevention**: Catch unintended breaking changes from future phases
4. **Documentation**: E2E tests serve as executable documentation for system behavior

---

## 3. Goals & Success Criteria

### Primary Goals

**G1: Complete E2E Workflow Tests**
- Submit DICOM study → Batch normalization → AI inference → Download results
- Validate all status transitions and data persistence
- Success: ≥95% test pass rate across 3 major workflows

**G2: Cross-Phase Integration Validation**
- Verify Phase 1 Docker containers work together
- Confirm Phase 2-5 APIs integrate seamlessly
- Ensure database transactions are atomic (no partial updates)
- Success: Zero data corruption in 1000+ concurrent requests

**G3: Performance Baseline Establishment**
- Measure inference latency (p50, p95, p99)
- Measure throughput (jobs/hour)
- Establish error rate baseline
- Success: Document metrics meeting design assumptions

**G4: Production Readiness Gate**
- Run 24-hour continuous soak test
- Validate log aggregation and monitoring
- Verify all error paths are handled gracefully
- Success: <0.1% error rate over 24 hours

### Success Criteria

| Criterion | Threshold | Status |
|-----------|-----------|--------|
| E2E Test Pass Rate | ≥95% | TBD |
| Data Integrity | 100% (no loss) | TBD |
| 24-Hour Uptime | ≥99.9% | TBD |
| Error Recovery | <0.1% failures | TBD |
| Documentation | Executable specs | TBD |

---

## 4. Scope Definition

### In Scope ✅

**Core Workflows**:
1. **Workflow A: Standard PACS + AI**
   - Upload DICOM study → Batch normalize → Submit AI inference → Download SEG result
   - Duration: ~30-60 seconds
   - Success Path: queued → running → completed

2. **Workflow B: Batch Processing + QC**
   - Upload study with JPEG density issues → Batch normalize with fix → Verify result
   - Duration: ~45 seconds
   - Success Path: detects non-standard DICOM, normalizes, validates

3. **Workflow C: AI Model Management**
   - Register new model → Activate → Submit inference → Monitor progress → Download result
   - Duration: ~5 minutes
   - Success Path: model validation → activation → inference execution

4. **Workflow D: Error Scenarios**
   - Invalid DICOM file → Error handling
   - Model inactive → Inference rejection
   - WebSocket disconnect → Auto-reconnect
   - Duration: ~10 seconds per scenario

**Test Coverage**:
- ✅ Happy path (successful completion)
- ✅ Error paths (graceful failure handling)
- ✅ Concurrency (100+ parallel jobs)
- ✅ State transitions (queued → running → completed/failed)
- ✅ Data persistence (restart doesn't lose state)
- ✅ Permission checks (RBAC enforcement)

**Infrastructure Validation**:
- ✅ Docker containers healthy (all 5 services)
- ✅ Database (PostgreSQL) maintaining consistency
- ✅ Cache (Redis) working without stale data
- ✅ Message queue (Celery) processing jobs
- ✅ Logs properly aggregated

### Out of Scope ❌

- Performance optimization (that's Phase 7+)
- Multi-datacenter failover (Phase 8)
- Advanced analytics (Phase 9+)
- Network chaos testing (Phase 7 load testing)
- Security penetration testing (separate engagement)

---

## 5. Key Workflows

### Workflow A: Complete DICOM + AI Pipeline
```
1. Upload DICOM study (CT chest, 50 images)
   ↓
2. Phase 2: DICOMweb ingestion → Orthanc
   ↓
3. Phase 3: Batch normalize (check JPEG density, validate tags)
   ↓
4. Phase 5: Submit AI inference (lung cancer model)
   ↓
5. Celery: Process 12-step pipeline
   - Fetch DICOM
   - Load model
   - Inference (GPU/CPU)
   - Generate SEG
   - Upload to Orthanc
   ↓
6. Client: WebSocket track progress (real-time)
   ↓
7. Client: Download SEG result (DICOM)
   ↓
8. Validation: Check file integrity, metadata
   ✅ PASS if: No data loss, correct result format
```

**Expected Duration**: 45-60 seconds  
**Success Path**: queued → running (12 steps) → completed  
**Error Paths**: Model inactive, study not found, Orthanc down  

### Workflow B: Batch Normalization + AI
```
1. Upload DICOM with JPEG density issue
   ↓
2. Phase 3: Detect density mismatch
   ↓
3. Phase 3: Auto-fix (normalize density to Pixel Spacing)
   ↓
4. Phase 5: Submit AI on normalized image
   ↓
5. Celery: Inference on corrected DICOM
   ↓
6. Validation: Compare original vs normalized
   ✅ PASS if: Normalization correct, AI works on fixed image
```

**Expected Duration**: 60-90 seconds  
**Success Metric**: Density mismatch detected and fixed  

### Workflow C: Concurrent Jobs
```
1. Submit 100 parallel AI inference jobs
   ↓
2. Monitor queue via /api/v1/ai/inferences
   ↓
3. Track individual jobs via WebSocket
   ↓
4. Validate all 100 complete without corruption
   ✅ PASS if: All jobs process, no race conditions, all results retrievable
```

**Expected Duration**: 5-10 minutes  
**Concurrency Target**: 100+ simultaneous jobs  
**Success Metric**: 100% completion rate, zero data loss  

---

## 6. Test Strategy

### Test Pyramid

```
                    [Manual Exploratory]
                   /                     \
              Smoke Tests          UI Interaction
             (Quick, 5 tests)          Tests
                  /                      \
           E2E API Tests          Performance
         (Main, ~40 tests)         Tests (SLA)
              /    |     \            /
        Workflow A B C  Error      Load Test
        (Integration)    (Recovery)  (24hrs)
```

### Test Categories

#### 1. Happy Path E2E Tests (20 tests)
- **test_complete_dicom_ai_workflow** ✅
- **test_batch_normalization_with_ai** ✅
- **test_ai_model_registration_to_inference** ✅
- **test_concurrent_100_jobs** ✅
- **test_websocket_progress_tracking** ✅
- Additional scenario variations

#### 2. Error Path Tests (12 tests)
- Invalid DICOM → rejection with proper error
- Model inactive → inference rejection (404)
- WebSocket disconnect → auto-reconnect
- Database connection loss → graceful degradation
- File system full → quota exceeded error
- Network timeout → retry logic

#### 3. Data Integrity Tests (8 tests)
- No data loss on container restart
- Transaction atomicity (all-or-nothing)
- Concurrent write conflicts resolved
- File deletion cascade (model → inference jobs → results)
- Cache invalidation on updates

#### 4. Performance Baseline Tests (5 tests)
- Inference latency (p50, p95, p99 percentiles)
- Throughput under load (jobs/hour)
- WebSocket message latency (< 100ms)
- Database query performance (indexes working)
- API response time (p95 < 500ms)

#### 5. Soak Tests (1 test)
- **24-hour continuous operation**
  - Submit jobs at constant rate (5 jobs/min)
  - Monitor error rate, latency, memory usage
  - Success: <0.1% error rate, stable memory

### Test Execution Plan

| Phase | Duration | What | Where |
|-------|----------|------|-------|
| **Setup** | 1 day | Docker stack, test data, monitoring | Local |
| **Happy Path** | 2 days | 20 core E2E tests | Local → Staging |
| **Error Path** | 1 day | 12 failure scenarios | Staging |
| **Data Integrity** | 1 day | 8 corruption tests | Staging |
| **Performance** | 1 day | Baseline metrics | Staging |
| **24-Hour Soak** | 1 day | Production-like load | Staging |
| **Analysis** | 1 day | Report & fixes | All |

**Total**: 7 days (1 week)

---

## 7. Acceptance Criteria

### Phase 6 Completion Checklist

- [ ] **E2E Test Suite**: ≥40 tests with ≥95% pass rate
- [ ] **Workflow Documentation**: Executable specs for A/B/C/D workflows
- [ ] **Performance Report**: Latency/throughput baseline established
- [ ] **24-Hour Soak Test**: ≥99.9% uptime, <0.1% error rate
- [ ] **Production Readiness**: Sign-off from ops team
- [ ] **Deployment Plan**: Steps for deploying to his.example.org
- [ ] **Rollback Plan**: Procedures for quick rollback
- [ ] **Monitoring Setup**: Alerts for key metrics

### Definition of Done

A workflow test is "DONE" when:
1. ✅ Passes consistently (5 runs without flakes)
2. ✅ Documented (what it tests, expected duration)
3. ✅ Integrated into CI/CD (auto-runs on PR)
4. ✅ Error paths handled (no hanging, proper cleanup)
5. ✅ Performance baseline (< SLA target)

---

## 8. Risks & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| **WebSocket flakiness** | Medium | High | Implement retry logic (already in Phase 5) |
| **Database race conditions** | Low | High | Atomic transactions, test concurrency |
| **Orthanc performance** | Medium | Medium | Connection pooling, request timeouts |
| **AI model OOM on GPU** | Low | High | CPU fallback testing, memory monitoring |
| **24-hour test timeout** | Medium | Medium | Incremental monitoring, auto-restart on failure |

---

## 9. Dependencies & Prerequisites

### Technology Stack (Unchanged)
- Docker Compose (5 services)
- PostgreSQL 16
- Redis 7
- Orthanc 1.12
- FastAPI + Celery
- Next.js + OHIF
- pytest + pytest-asyncio

### Test Data Requirements
- 20 sample DICOM files (various modalities: CT, MR, CR)
- 5 test models (ONNX, small for fast inference)
- Pre-loaded test user accounts (radiologist, admin)
- Monitoring dashboards (Grafana, if available)

### Integration Points
- Phase 1: Docker infrastructure ✅
- Phase 2: DICOMweb API ✅
- Phase 3: Normalization service ✅
- Phase 4: Batch processor ✅
- Phase 5: AI inference pipeline ✅

---

## 10. Success Metrics & KPIs

### Functional Metrics
- **E2E Test Pass Rate**: Target ≥95%
- **Workflow A Duration**: Target 45-60 seconds
- **Workflow B Duration**: Target 60-90 seconds
- **Workflow C (100 jobs)**: Target 5-10 minutes

### Performance Metrics
- **Inference Latency (p95)**: Target <10 seconds
- **API Response Time (p95)**: Target <500ms
- **Throughput**: Target ≥10 jobs/minute
- **Error Rate**: Target <0.1%

### Reliability Metrics
- **24-Hour Uptime**: Target ≥99.9%
- **Data Integrity**: Target 100% (zero loss)
- **WebSocket Reconnect Success**: Target ≥99%
- **Graceful Degradation**: Target 100% error handling

### Coverage Metrics
- **Code Coverage**: Target ≥80% (via pytest)
- **Workflow Coverage**: 4/4 workflows (A, B, C, D)
- **Error Path Coverage**: ≥12 failure scenarios

---

## 11. Deliverables

### Test Code
- [ ] `backend/tests/test_e2e_dicom_ai.py` (20 tests)
- [ ] `backend/tests/test_e2e_error_scenarios.py` (12 tests)
- [ ] `backend/tests/test_e2e_data_integrity.py` (8 tests)
- [ ] `backend/tests/test_e2e_performance.py` (5 tests)
- [ ] `backend/tests/test_soak_24hour.py` (1 test)

### Documentation
- [ ] `docs/05-e2e-tests/test-plan.md` (this document)
- [ ] `docs/05-e2e-tests/workflows.md` (workflow definitions)
- [ ] `docs/05-e2e-tests/performance-baseline.md` (metrics)
- [ ] `docs/05-e2e-tests/monitoring-setup.md` (alerts/dashboards)

### Artifacts
- [ ] Test results summary (pass/fail count)
- [ ] Performance report (latency, throughput)
- [ ] 24-hour soak test report (uptime, errors)
- [ ] Coverage report (code coverage %)

---

## 12. Timeline & Milestones

| Date | Milestone | Deliverable |
|------|-----------|-------------|
| Day 1 | Setup & Happy Path | 20 E2E tests (>90% passing) |
| Day 3 | Error Paths | 12 error scenario tests |
| Day 4 | Data Integrity | 8 corruption/recovery tests |
| Day 5 | Performance | Baseline metrics established |
| Day 6 | 24-Hour Soak | Soak test running |
| Day 7 | Analysis & Report | Final test report, sign-off |

---

## 13. Rollout Strategy

### Pre-Deployment (This Phase)
- ✅ Complete all E2E tests locally
- ✅ Establish performance baseline
- ✅ Run 24-hour soak test
- ✅ Document findings

### Staging Deployment (Phase 6 → Phase 7)
- Deploy to staging.his.example.org
- Run E2E tests against staging
- Monitor 48 hours before prod approval

### Production Deployment (Phase 7)
- Blue-green deployment
- Gradual rollout (10% → 50% → 100%)
- Continuous monitoring (first 7 days)

---

## 14. Assumptions

1. **All Phase 1-5 code is stable** (no breaking changes during Phase 6)
2. **Test environment mirrors production** (same hardware, OS, database)
3. **Test data is representative** (realistic DICOM files, workloads)
4. **Monitoring tools available** (Docker stats, database logs, application logs)
5. **Database snapshots available** (for rollback after each test cycle)

---

## 15. Notes & Open Questions

### Open Questions
- Q1: What's the target GPU model for inference? (Affects performance baseline)
- Q2: Should we test multi-GPU scenarios? (Phase 7+?)
- Q3: Is Orthanc clustering in scope? (Probably Phase 8)
- Q4: What's the SLA for 99.9% uptime? (Define error budget)

### Potential Scope Creep
- Advanced analytics dashboard (Phase 9)
- Performance optimization (Phase 7)
- Security testing (separate engagement)
- Load testing at scale (Phase 7)

---

**Document Prepared By**: Claude Code  
**Status**: Ready for Design Phase  
**Next Step**: `/pdca design phase-6-e2e-integration-testing`
