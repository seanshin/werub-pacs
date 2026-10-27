# Phase 4 Testing & Deployment Plan

## Overview
Phase 4 DICOM Batch Normalizer — Complete testing strategy and production deployment checklist.

**Timeline**: Phase 4.5 (Day 10-14)
**Test Coverage**: 100% of Phase 4.1-4.4 features
**Deployment Target**: Production (his.example.org)

---

## Testing Strategy

### 1. Unit Tests (test_phase4_integration.py)

#### BatchJobService Tests
```python
✅ test_create_batch_job()
   - Create batch with user_id, total_files, supplier
   - Assert: status='queued', processed=0

✅ test_add_batch_file()
   - Add file to batch
   - Assert: filename, modality, status='validated'

✅ test_update_batch_status()
   - Update status queued→processing→completed
   - Assert: started_at/completed_at timestamps

✅ test_increment_counters()
   - Increment processed/succeeded/failed
   - Assert: all counters updated atomically

✅ test_get_batch_statistics()
   - Get progress, success rate, pending reviews
   - Assert: correct percentages, distribution
```

#### SupplierNormalizer Tests
```python
✅ test_siemens_normalizer()
   - Detect Siemens from Manufacturer field
   - Add InstanceCreationDate, ManufacturerModelName
   - Assert: changes include dates and model

✅ test_ge_normalizer()
   - Detect GE and add SeriesDate/Time
   - Handle PhotometricInterpretation (medium risk)
   - Assert: GE-specific changes

✅ test_philips_normalizer()
   - Detect Philips and add ContentDate/Time/SeriesDesc
   - Assert: Philips-specific changes

✅ test_default_normalizer()
   - Fallback rules for unknown suppliers
   - Add PatientBirthDate, PatientSex, StudyDate/Time
   - Assert: standard mandatory fields

✅ test_normalizer_factory()
   - Get correct normalizer by supplier name
   - Assert: SiemensNormalizer, GENormalizer, etc.
```

#### ConfigService Tests
```python
✅ test_update_modality_config()
   - Create/update CT, MR, US, XR configurations
   - Assert: algorithms and risk_tiers saved

✅ test_create_supplier_rule()
   - Create siemens/ge/philips versioned rules
   - Assert: is_active=true, managed_by tracked

✅ test_deactivate_supplier_rule()
   - Soft-delete rule (is_active=false)
   - Assert: rule still queryable but inactive
```

#### NormalizerEngine Tests
```python
✅ test_normalize_siemens_dicom()
   - Load minimal DICOM with Siemens manufacturer
   - Run normalize_dicom()
   - Assert: detected_supplier='siemens', no errors

✅ test_invalid_dicom_handling()
   - Send non-DICOM data
   - Assert: error message, applied=false

✅ test_extract_dicom_tags()
   - Extract tag values (0008,0020, 0010,0030, etc.)
   - Assert: correct tag format and values
```

### 2. Integration Tests (Functional)

#### Batch Processing Pipeline
```bash
1. Create batch
   POST /api/v1/batch/normalize/upload
   - 10 DICOM files, supplier=auto_detect
   - Assert: batch_id, status='queued', task_id

2. Monitor progress via WebSocket
   ws://host/api/v1/ws/batch/{batch_id}?user_id=...
   - Assert: connected message received
   - Check progress updates (0%, 10%, 20%, ... 100%)

3. Check batch status
   GET /api/v1/batch/normalize/{batch_id}
   - Assert: status transitions: queued→processing→completed
   - Verify: succeeded/failed counts match files

4. List batch files
   GET /api/v1/batch/normalize/{batch_id}/files
   - Assert: all 10 files visible with status
   - Check: normalization_changes populated for each file
   - Verify: detected_supplier values
```

#### Admin Dashboard
```bash
1. Dashboard Statistics
   GET /api/v1/admin/dashboard/stats?hours=24
   - Assert: batch_count, file_count, success_rate
   - Check: supplier distribution accurate
   - Verify: performance metrics (avg time, throughput)

2. Recent Batches
   GET /api/v1/admin/dashboard/recent-batches
   - Assert: sorted by created_at DESC
   - Check: user_id, status, success_rate for each

3. Slow Batches
   GET /api/v1/admin/dashboard/slow-batches?threshold_minutes=30
   - Assert: only batches with processing_time >= threshold
   - Check: files_per_second calculation

4. Configuration Management
   GET/POST /api/v1/admin/config/modalities
   GET/POST /api/v1/admin/config/suppliers
   - Assert: CRUD operations work
   - Check: cache invalidation on update
```

### 3. Edge Case Testing

```python
✅ test_batch_with_zero_files()
   - Create batch with total_files=0
   - Assert: still creates, progress_percent handles division

✅ test_concurrent_file_processing()
   - Simulate 100 concurrent increment_batch_counters
   - Assert: final counts = 100 (no race conditions)

✅ test_batch_with_mixed_results()
   - 80 successful files, 20 failed
   - Assert: success_rate = 80%, error_summary populated

✅ test_large_file_batch()
   - 1000 files per batch
   - Assert: pagination works (limit=50, offset)
   - Check: WebSocket doesn't timeout during broadcast

✅ test_missing_dicom_fields()
   - DICOM missing: PatientID, StudyDate, Modality
   - Assert: normalizers add defaults correctly

✅ test_invalid_normalizer_config()
   - NormalizationConfig with invalid risk_tier
   - Assert: graceful error handling
```

### 4. Error Handling Tests

```python
✅ test_database_connection_loss()
   - Simulate DB disconnect during batch processing
   - Assert: task retry logic, error logged

✅ test_celery_task_timeout()
   - Batch with file that takes >timeout
   - Assert: task marked as failed, error_summary updated

✅ test_websocket_disconnect()
   - Client disconnects during progress broadcast
   - Assert: connection cleaned up, no memory leak

✅ test_invalid_supplier_rule()
   - Create rule with malformed rule_config
   - Assert: validation error, rule not saved

✅ test_permission_denied()
   - User tries to view other user's batch
   - Assert: HTTP 403 Forbidden

✅ test_admin_access_required()
   - Non-admin tries to access /api/v1/admin/
   - Assert: HTTP 403 Forbidden
```

### 5. Performance Tests

```bash
1. Batch Processing Throughput
   - Submit 5 batches × 100 files each (500 files total)
   - Measure: time to completion, files/second
   - Target: ≥ 10 files/second per CPU core

2. WebSocket Broadcast Load
   - 10 concurrent clients on same batch
   - Assert: all receive progress updates
   - Check: latency < 100ms per broadcast

3. Database Query Performance
   - GET /api/v1/batch/normalize?limit=50&offset=0
   - Assert: response time < 100ms
   - Check: indexes used (batch_id, status, created_at)

4. Config Cache Hit Rate
   - 100 normalize_dicom calls for same modality
   - Assert: first call hits DB, rest use Redis cache
   - Check: Redis TTL = 300 seconds
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] All tests passing (100% coverage)
- [ ] Code review completed
- [ ] Database migration tested locally
- [ ] No breaking changes to existing APIs
- [ ] Documentation updated
- [ ] Backup strategy confirmed

### Deployment Steps (scripts/deploy_phase4.sh)
- [ ] Code uploaded to server
- [ ] Database backup created
- [ ] Alembic migrations run
- [ ] Backend service restarted
- [ ] Health checks pass (5 consecutive checks)
- [ ] API endpoints verified
- [ ] 1-hour continuous monitoring

### Post-Deployment
- [ ] All health checks: GREEN ✅
- [ ] Log files reviewed (no errors)
- [ ] Batch processing test job submitted
- [ ] WebSocket connectivity verified
- [ ] Admin dashboard data accurate
- [ ] Database queries performant
- [ ] No memory leaks (monitoring enabled)

---

## Test Execution

### Run All Tests
```bash
# Run full test suite
pytest tests/test_phase4_integration.py -v --cov=app/services/batch* --cov=app/api/batch*

# Run specific test class
pytest tests/test_phase4_integration.py::TestBatchJobService -v

# Run single test
pytest tests/test_phase4_integration.py::TestBatchJobService::test_create_batch_job -v
```

### Manual Integration Test
```bash
# Create test batch
curl -X POST https://his.example.org/pacs-api/api/v1/batch/normalize/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@test1.dcm" \
  -F "files=@test2.dcm" \
  -F "supplier=auto_detect" \
  -F "auto_normalize=false"

# Monitor progress
curl -i -N -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  "wss://his.example.org/api/v1/ws/batch/{batch_id}?user_id={user_id}"

# Check results
curl https://his.example.org/pacs-api/api/v1/batch/normalize/{batch_id}
```

### Monitoring During Deployment
```bash
# SSH into server
ssh -p 819 deploy@198.51.100.73

# Watch logs in real-time
cd /home/deploy/hospital-run/infra/docker
docker compose logs -f backend --tail 100

# Check database
psql -U openpacs -h 127.0.0.1 openpacs
  \d batch_jobs
  SELECT COUNT(*) FROM batch_jobs;
  SELECT status, COUNT(*) FROM batch_jobs GROUP BY status;
```

---

## Success Criteria

### Functional
- ✅ All 45+ tests passing
- ✅ Batch creation, processing, completion working
- ✅ WebSocket real-time updates functional
- ✅ Admin dashboard statistics accurate
- ✅ Configuration management CRUD working
- ✅ Supplier detection correct for all 4 normalizers

### Performance
- ✅ Batch throughput ≥ 10 files/second
- ✅ API response time < 100ms (p99)
- ✅ WebSocket broadcast latency < 100ms
- ✅ Database queries using indexes
- ✅ No memory leaks over 1-hour monitoring

### Reliability
- ✅ Zero downtime deployment
- ✅ All health checks passing
- ✅ Error handling graceful
- ✅ Database migrations reversible
- ✅ Audit trail complete (who changed what, when)

---

## Known Limitations & Future Work

1. **FileStorage**: Currently temp directory on disk. Consider:
   - S3-backed storage for redundancy
   - Cleanup after batch completion (24-hour TTL)

2. **RealTimeUpdates**: WebSocket broadcasts all changes. Scale limit:
   - ≤ 100 concurrent connections per instance
   - Use Redis Pub/Sub for multi-instance deployments

3. **ConfigCache**: 5-minute TTL. In rare cases:
   - Config update takes up to 5 minutes to propagate
   - Manual cache clear via `ConfigService.clear_config_cache()`

4. **ManualReview**: Medium-risk items require human approval
   - Currently tracked in DB, but no review UI yet
   - Phase 5: Add admin UI for bulk approval/rejection

---

## Rollback Plan

If issues detected during/after deployment:

```bash
# Quick rollback (revert container to previous image)
cd /home/deploy/hospital-run/infra/docker
docker compose down backend
git checkout HEAD~1 backend/app/  # Revert code
docker compose up -d backend

# Full rollback (restore from backup)
psql -U openpacs -h 127.0.0.1 openpacs < /tmp/openpacs_backup_*.sql
alembic downgrade -1  # Revert last migration
```

---

## Approval & Sign-off

- [ ] Code review: _______________ Date: ______
- [ ] QA testing: _______________ Date: ______
- [ ] Deployment: _______________ Date: ______

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-14  
**Status**: Ready for Phase 4.5 Testing & Deployment
