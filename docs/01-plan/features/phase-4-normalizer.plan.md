# PDCA Plan: Phase 4 — DICOM Normalizer Enhancements

## Executive Summary

Phase 4 builds on the Phase 3 DICOM normalization foundation (4 core algorithms, 48+ hours healthy production operation) to introduce **scalable batch processing, supplier-specific rules, and administration/monitoring capabilities**. This phase transforms the single-instance normalizer into an enterprise-grade system supporting bulk retrospective normalization, domain-specific corrections, and real-time operational visibility.

**Target Design Match Rate**: ≥90%  
**Estimated Scope**: 2,500-3,500 lines of code  
**Priority**: 🟡 HIGH (enables production-scale workflows, reduces manual QC overhead)

**Phase 3 Baseline**:
- ✅ 4 core algorithms: Pixel Spacing, Missing Tags, Photometric, Charset
- ✅ Design Match: 93% (excellent quality)
- ✅ Tests: 100% passing (22/22 unit + 25/25 functional)
- ✅ Production: 48+ hours healthy operation
- ✅ Tech Stack: FastAPI, PostgreSQL, Redis, Orthanc, pydicom

---

## Problem Statement

### Current State (Phase 3 Complete)
- ✅ Auto-normalize single DICOM instances during upload (stow_rs endpoint)
- ✅ Safe/Medium/Risky risk-tier classification framework
- ✅ Complete audit trail for all corrections
- ✅ Four core normalization algorithms working reliably
- ❌ **No bulk normalization for existing archives** (only handles new uploads)
- ❌ **No supplier/vendor-specific rules** (generic rules only)
- ❌ **No admin visibility** into normalization metrics and history
- ❌ **No performance optimization** for large-scale batch operations

### Critical Gaps

**Use Case 1: Retrospective Normalization**
- PACS has 50,000+ legacy DICOM files with known issues
- Manual fixes infeasible (100+ hours estimated)
- Solution needed: Batch normalize existing archive, report results
- **Impact**: Enables 80%+ of archive to pass strict viewers without manual intervention

**Use Case 2: Supplier-Specific Normalization**
- Siemens CT: Pixel Spacing often embedded in proprietary tags (0019, 1008)
- GE MRI: PhotometricInterpretation non-standard for JPEG-encoded pixel data
- Philips Ultrasound: JPEG compression applies non-standard vendor-specific encoding
- **Impact**: Reduces manual review from 30% to <5% for known supplier quirks

**Use Case 3: Operational Visibility**
- Admin cannot see normalization trends (which algorithms help most?)
- Manual review queue status unknown (medium-risk items pending?)
- Performance impact of normalization on upload latency not visible
- **Impact**: Data-driven tuning, SLA tracking, audit compliance

**Use Case 4: Configuration Control**
- Safety guardrails hard-coded (e.g., 20% deviation threshold)
- No per-modality tuning (CT vs MRI vs ultrasound handle differently)
- Batch processing limits not configurable
- **Impact**: Unable to safely increase automation for specific contexts

---

## Proposed Solution

### 1. Batch Normalization Engine (Priority P1)

**Files**:
- `backend/app/services/batch_normalizer.py` (new)
- `backend/app/api/batch_operations.py` (new)

**Features**:
- 🆕 Upload DICOM batch (zip, multipart/form-data)
- 🆕 Async processing via Celery workers (scalable)
- 🆕 Per-file status tracking (pending → processing → completed/failed)
- 🆕 Progress streaming via WebSocket or polling API
- 🆕 Detailed normalization report per instance
- 🆕 Bulk approve/reject medium-risk corrections
- 🆕 Rollback capability (mark files for re-processing)

**Endpoint**:
```
POST /dicomweb/batch-normalize
  Input: 
    - files: MultiPartForm | zip file containing DICOM instances
    - auto_approve_safe: bool = true (apply safe corrections automatically)
    - auto_approve_medium: bool = false (hold medium-risk for review)
    - output_format: "report" | "archive" = "report"
  
  Output:
    {
      "batch_id": "uuid",
      "status": "queued" | "processing" | "completed",
      "total_files": int,
      "processed_files": int,
      "stats": {
        "normalized_count": int,
        "error_count": int,
        "medium_risk_count": int
      },
      "report_url": "/batches/{batch_id}/report"
    }

GET /dicomweb/batch-normalize/{batch_id}/status
  Output: Progress + per-file status array

GET /dicomweb/batch-normalize/{batch_id}/report
  Output: Comprehensive JSON report (can be exported to CSV)

GET /dicomweb/batch-normalize/{batch_id}/archive
  Output: ZIP of normalized DICOM files (optional post-processing)
```

**Architecture**:
```
Upload Request
    ↓
FastAPI endpoint (batch_operations.py)
    ↓
Save files to temp storage (Redis or local /tmp)
    ↓
Create batch job record in PostgreSQL
    ↓
Enqueue Celery task (batch_normalizer_worker.py)
    ↓
[Worker] Process files concurrently (pool_size=4)
    ├─ Extract DICOM from archive
    ├─ Validate (phase 2)
    ├─ Normalize (phase 3)
    ├─ Write to temp storage
    ├─ Log audit trail
    └─ Update batch job status
    ↓
Return batch_id to client → client polls /status endpoint
```

### 2. Supplier-Specific Rules Engine (Priority P1)

**Files**:
- `backend/app/services/suppliers/siemens.py` (new)
- `backend/app/services/suppliers/ge.py` (new)
- `backend/app/services/suppliers/philips.py` (new)
- `backend/app/services/supplier_registry.py` (new)
- `backend/app/models/supplier_rule.py` (new)

**Features**:
- 🆕 Pluggable supplier-specific normalizers
- 🆕 Detect manufacturer from DICOM header (Manufacturer tag)
- 🆕 Apply manufacturer-specific transformations
- 🆕 Per-supplier rule versioning + audit trail
- 🆕 Configuration database (enable/disable per supplier)

**Supplier Rules**:

**Siemens**:
- Extract Pixel Spacing from (0019, 1008) if standard PixelSpacing is missing
- Handle Siemens-specific CSA Image Header Info parsing
- Correct PhotometricInterpretation for JPEG LOSSLESS from vendor tag (0019, 1010)
- Risk level: Medium (vendor-specific tag parsing)

**GE**:
- Infer PhotometricInterpretation from GE-specific JPEG markers (0008, 0018 SeriesInstanceUID pattern)
- Correct SamplesPerPixel for grayscale JPEG (GE sometimes sets to 3)
- Handle GE private tags (0009, 1001) for Pixel Spacing validation
- Risk level: Medium

**Philips**:
- Parse Philips Private Creator tags (0019, 10xx) for JPEG quality metadata
- Detect and normalize Philips JPEG encoding artifacts (luminance/chrominance mismatch)
- Correct PixelRepresentation for ultrasound vendor tags
- Risk level: Medium-High (aggressive vendor-specific transformations)

**Example**: Siemens supplier rule integration:
```python
class SiemensNormalizer:
    async def normalize(self, ds: Dataset, context: NormalizationContext) -> list[ChangeSummary]:
        changes = []
        
        # Rule 1: Extract PixelSpacing from Siemens private tag
        if not ds.PixelSpacing and hasattr(ds, [(0x0019, 0x1008)]):
            spacing = self._extract_siemens_pixel_spacing(ds)
            if spacing:
                ds.PixelSpacing = spacing
                changes.append(...)
        
        # Rule 2: Fix PhotometricInterpretation if missing
        if not hasattr(ds, 'PhotometricInterpretation'):
            interp = self._infer_photometric_siemens(ds)
            if interp:
                ds.PhotometricInterpretation = interp
                changes.append(...)
        
        return changes
```

### 3. Admin Dashboard (Priority P1)

**Files**:
- `admin/src/app/normalization/page.tsx` (new)
- `admin/src/app/normalization/batch/page.tsx` (new)
- `admin/src/app/normalization/history/page.tsx` (new)
- `admin/src/app/normalization/config/page.tsx` (new)
- `backend/app/api/normalization_admin.py` (new)

**Dashboards**:

**1. Normalization Overview (Main Dashboard)**
```
┌─────────────────────────────────────────────────────────┐
│ DICOM Normalizer Status (Last 24 hours)                 │
├─────────────────────────────────────────────────────────┤
│ Total Files Processed: 1,247                            │
│ Normalized: 1,189 (95.3%)  | Errors: 25 (2%)           │
│ Avg Time: 42ms/file        | P95: 150ms                 │
├─────────────────────────────────────────────────────────┤
│ Algorithm Effectiveness:                                │
│ ├─ Pixel Spacing: 487 files fixed (39%)                │
│ ├─ Missing Tags: 203 files fixed (16%)                 │
│ ├─ Photometric: 89 files fixed (7%)                    │
│ └─ Charset: 34 files fixed (3%)                        │
├─────────────────────────────────────────────────────────┤
│ Medium-Risk Items Pending Review: 156                  │
│ ├─ PhotometricInterpretation: 98                       │
│ ├─ Charset Conversion: 58                              │
├─────────────────────────────────────────────────────────┤
│ Active Batch Jobs: 2                                    │
│ ├─ Batch #abc123: 3,500/5,000 files (70%)             │
│ └─ Batch #def456: 127/150 files (85%)                 │
└─────────────────────────────────────────────────────────┘
```

**2. Batch Processing UI**
- Upload batch (drag-drop or file selector)
- Configure: auto_approve_safe, auto_approve_medium per supplier
- Monitor progress in real-time (WebSocket)
- Download report (JSON, CSV, PDF)
- Reprocess failed files
- Archive normalized DICOM

**3. Audit/History View**
- Browse all normalization changes (filterable by date, algorithm, file, risk level)
- Detail view: Original value → Corrected value + Rationale
- Approve/reject bulk corrections (P2)
- Export audit trail

**4. Configuration Panel**
- Enable/disable algorithms per modality (CT, MR, US, etc.)
- Set safety thresholds: MAX_CHANGES per file, TIMEOUT_MS per file
- Configure batch processing: BATCH_SIZE, MAX_CONCURRENT_JOBS
- Supplier rule toggles: Enable Siemens, GE, Philips specific rules
- Risk tier configuration: Define SAFE/MEDIUM/RISKY boundaries

### 4. Latin-1 Charset Support (Priority P2)

**File**: `backend/app/services/dicom_normalizer.py` (extend)

**Features**:
- 🆕 Detect Latin-1 (ISO-8859-1) encoded text in DICOM
- 🆕 Convert Latin-1 → UTF-8 during normalization
- 🆕 Infer charset from byte pattern analysis (Phase 3 detected but didn't convert)
- 🆕 Set SpecificCharacterSet to "UTF-8" after conversion

**Algorithm**:
```python
def _detect_and_convert_charset(ds: Dataset, report: ValidationReport):
    """
    1. Scan all text elements (PatientName, PatientComments, etc.)
    2. Detect byte patterns:
       - Valid UTF-8: continues normalization
       - Valid Latin-1 but not UTF-8: flag for conversion
       - Invalid: log as advisory
    3. If Latin-1 detected:
       a. Convert all text elements Latin-1 → UTF-8
       b. Set SpecificCharacterSet = "UTF 8"
       c. Log change with "medium" risk (charset conversion reversible)
    """
```

### 5. Configuration Optimization (Priority P2)

**Files**:
- `backend/app/models/normalization_config.py` (new)
- `backend/app/core/normalization_settings.py` (extend)

**Configurable Parameters**:
```python
NormalizationConfig:
    # Safety limits
    max_changes_per_instance: int = 10  # Prevent runaway normalization
    deviation_tolerance_pct: float = 20.0  # PixelSpacing deviation threshold
    charset_confidence_threshold: float = 0.85  # Charset detection confidence
    
    # Performance tuning
    timeout_ms_per_file: int = 500  # Abort if normalization exceeds
    batch_concurrent_workers: int = 4  # Celery pool size
    batch_max_size: int = 10000  # Max files per batch
    
    # Algorithm toggles (per modality)
    algorithms_enabled: dict[Modality, list[str]] = {
        "CT": ["pixel_spacing", "tags", "photometric"],
        "MR": ["pixel_spacing", "tags", "charset"],
        "US": ["pixel_spacing", "tags"],
    }
    
    # Supplier rules
    supplier_rules_enabled: dict[str, bool] = {
        "siemens": True,
        "ge": True,
        "philips": False,  # Disable for now (high risk)
    }
    
    # Medium-risk handling
    auto_approve_medium_risk: bool = False  # Require manual review
    medium_risk_alert_threshold: int = 100  # Alert if pending > 100
```

### 6. Photometric Interpretation Manual Review UI (Priority P2)

**File**: `admin/src/app/normalization/review-medium-risk/page.tsx` (new)

**Features**:
- 🆕 Display pending medium-risk photometric interpretation changes
- 🆕 Show before/after interpretation with reasoning
- 🆕 Bulk approve/reject by rule (e.g., "approve all Siemens CT photometric changes")
- 🆕 Per-file approve/reject with comments
- 🆕 Filter by supplier, modality, change type
- 🆕 Download report of approved/rejected changes

---

## Requirements

### Functional Requirements

**F1: Batch Normalization API**
- FR1.1: Accept batch upload (≤100MB, 1,000+ files) via multipart or zip
- FR1.2: Process asynchronously without blocking upload response
- FR1.3: Track per-file status (pending/processing/completed/failed)
- FR1.4: Provide real-time progress updates (WebSocket or polling)
- FR1.5: Generate comprehensive JSON/CSV report per batch
- FR1.6: Support rollback (re-process failed files, revert changes)

**F2: Supplier-Specific Rules**
- FR2.1: Auto-detect manufacturer from DICOM Manufacturer tag
- FR2.2: Apply Siemens, GE, Philips-specific normalizations
- FR2.3: Version supplier rules with audit trail
- FR2.4: Enable/disable supplier rules via admin config
- FR2.5: Parse vendor-specific private tags safely (0019, 0009, etc.)

**F3: Admin Dashboard**
- FR3.1: Display 24-hour normalization metrics (files, algorithms, time)
- FR3.2: Show per-algorithm effectiveness (count of files fixed)
- FR3.3: Display pending medium-risk corrections (count, type)
- FR3.4: Monitor active batch jobs with progress
- FR3.5: Browse full audit trail (filterable, searchable)
- FR3.6: Configure algorithms, safety thresholds, supplier rules

**F4: Latin-1 Charset Support**
- FR4.1: Detect Latin-1 encoded text in DICOM
- FR4.2: Convert Latin-1 → UTF-8 with validation
- FR4.3: Set SpecificCharacterSet after conversion
- FR4.4: Log charset conversions to audit trail

**F5: Configuration Optimization**
- FR5.1: Set MAX_CHANGES limit per instance (prevent over-correction)
- FR5.2: Configure TIMEOUT_MS per file (abort slow normalizations)
- FR5.3: Set BATCH_SIZE and MAX_CONCURRENT_JOBS
- FR5.4: Enable/disable algorithms per modality (CT vs MR vs US)

### Non-Functional Requirements

**NR1: Performance**
- Batch processing: ≥100 files/min (42ms avg per file from Phase 3)
- API latency for batch upload: <2 seconds to return batch_id
- WebSocket progress updates: <500ms delivery latency
- Configuration changes: effective within 5 seconds (in-memory cache)

**NR2: Scalability**
- Support concurrent batch jobs (up to 10 simultaneous)
- Handle single batch up to 10,000 files
- Archive peak: 50K+ legacy files (retrospective migration)

**NR3: Reliability**
- Batch failures: Automatic retry up to 3 times (Celery default)
- Partial batch failure: Continue processing remaining files
- Data integrity: Audit trail covers 100% of changes
- Backward compatibility: Phase 3 API unchanged (additive only)

**NR4: Observability**
- Real-time batch progress via WebSocket or HTTP polling
- Detailed per-file error logs (5+ lines per error)
- Supplier rule tracing (which rule applied, why)
- Performance metrics stored in PostgreSQL (queryable)

### Compliance

- HIPAA: Batch operations logged with user/timestamp/IP/changes
- GDPR: Audit trail exportable per batch (traceability)
- Medical imaging standards: Maintain DICOM Part 3 compliance
- Korean Medical Law: 의료법 audit requirements met (user, timestamp, action logged)

---

## Implementation Roadmap

### Phase 4.1: Batch Normalization Engine (Days 1-3)

**Week 1, Days 1-2**:
1. Design batch job model (PostgreSQL schema)
2. Implement BatchJob service (create, list, get status)
3. Create Celery worker tasks (`batch_normalize_worker.py`)
4. Implement file extraction from zip/multipart
5. Add temporary file storage layer (Redis or local /tmp with cleanup)
6. Unit tests for batch operations (8+ test cases)

**Week 1, Day 3**:
1. Implement FastAPI batch endpoints (`POST /dicomweb/batch-normalize`)
2. Add progress polling endpoint (`GET /batch-normalize/{batch_id}/status`)
3. Implement report generation (JSON/CSV)
4. Integration tests with real DICOM samples (5+ test cases)

### Phase 4.2: Supplier-Specific Rules (Days 3-5)

**Week 1, Days 3-4**:
1. Implement SupplierRegistry (auto-detect manufacturer)
2. Implement SiemensNormalizer (private tag parsing, pixel spacing extraction)
3. Implement GENormalizer (photometric inference, SamplesPerPixel correction)
4. Implement PhilipsNormalizer (JPEG artifact detection, vendor tag parsing)
5. Unit tests per supplier (15+ test cases)

**Week 1, Day 5**:
1. Integrate supplier rules into batch normalizer
2. Add supplier rule configuration to database
3. Admin API for enabling/disabling rules
4. Integration tests (supplier detection, rule application)

### Phase 4.3: Admin Dashboard (Days 5-7)

**Week 2, Days 5-6**:
1. Design dashboard UI mockups (Figma or HTML)
2. Implement main normalization dashboard (React/Next.js)
3. Implement batch monitoring page (real-time progress)
4. Implement audit history view (filterable table)
5. Connect to backend APIs (`normalization_admin.py`)

**Week 2, Day 7**:
1. Implement configuration panel (algorithm toggles, thresholds)
2. Implement medium-risk review UI
3. Batch export (report download)
4. E2E tests of dashboard flows (5+ scenarios)

### Phase 4.4: Latin-1 + Config Optimization (Days 7-8)

**Week 2, Days 7-8**:
1. Implement Latin-1 detection in dicom_normalizer.py
2. Implement charset conversion + SpecificCharacterSet update
3. Add NormalizationConfig model + settings
4. Integrate config into batch processing
5. Unit + integration tests (8+ test cases)

### Phase 4.5: Testing & Polish (Days 8-10)

**Week 2, Days 8-9**:
1. Gap analysis: Design vs Implementation verification
2. Performance testing (batch processing with 1K+ files)
3. Security review of file handling (temp storage cleanup)
4. Backward compatibility verification (Phase 3 API unchanged)
5. Stress testing (10 concurrent batch jobs)

**Week 2, Day 10**:
1. Documentation updates (API spec, admin guide, troubleshooting)
2. Deployment checklist + runbook
3. Production readiness review

---

## Success Criteria

| Criterion | Target | Validation Method |
|-----------|--------|-------------------|
| Batch processing throughput | ≥100 files/min | Load test with 1K files |
| API upload latency | <2s to batch_id | Load test with 100MB upload |
| Per-file normalization time | <100ms (Phase 3 baseline) | Benchmark on prod subset |
| Supplier rule accuracy | ≥95% correct detection | Test with known supplier samples |
| Dashboard responsiveness | <500ms page load | Real browser testing |
| Audit coverage | 100% of batch operations | Audit log verification |
| Design match rate | ≥90% | Gap detector tool |
| Medium-risk handling | <5% auto-approval without review | Config verification |
| Backward compatibility | 100% Phase 3 API working | Regression tests |
| Configuration latency | <5s for cache invalidation | Timing test |

---

## Architecture Decisions

### Decision 1: Batch Processing — Sync vs Async Celery

**Options**:
- **A) Synchronous**: Handle within FastAPI request (simple but slow, blocks)
- **B) Async Celery** ✅ **CHOSEN**: Offload to worker queue (scalable, non-blocking)

**Rationale**:
- Supports 1,000+ file batches without timeout
- Allows concurrent batch jobs (10 simultaneous)
- Leverage existing Celery infrastructure (ai_worker.py)
- Progress updates via WebSocket/polling decoupled from processing
- Redis backend already deployed for caching

**Trade-offs**:
- Complexity: Need job state management in PostgreSQL + Redis
- Debugging: Async logs distributed across workers
- Consistency: File state transitions (pending → processing → done)

**Risk Mitigation**:
- Comprehensive logging of worker state transitions
- Automatic retry (Celery task_acks_late=True)
- DLQ for permanently failed jobs (for manual review)

### Decision 2: Supplier Rules — Plugin Architecture vs Config Files

**Options**:
- **A) Plugin Architecture** ✅ **CHOSEN**: Separate class per supplier (SiemensNormalizer, GENormalizer, etc.)
- **B) Configuration Files**: YAML rules (simpler but less flexible)

**Rationale**:
- Vendor-specific logic (private tag parsing) requires imperative code
- Easier to test, version, and maintain separate classes
- Plugin registry pattern proven in Phase 3 (DicomValidator extensions)
- Can add machine learning models per supplier in future

**Trade-offs**:
- Requires Python code changes to add new supplier
- Not suitable for non-technical configuration

**Risk Mitigation**:
- Document plugin API clearly
- Provide template for new suppliers
- Test coverage for each supplier (≥15 unit tests)

### Decision 3: Dashboard — Built-in FastAPI + React vs External Service

**Options**:
- **A) Built-in FastAPI + React** ✅ **CHOSEN**: Extend /admin Next.js app
- **B) External Service**: Separate Grafana/Kibana instance (over-engineered)

**Rationale**:
- Consistency with existing admin dashboard (audit, users, etc.)
- Leverage Next.js authentication already in place
- Simpler deployment (single container)
- Lower operational overhead

**Trade-offs**:
- Responsibility: Must maintain React code
- Performance: In-process analytics queries on PostgreSQL

**Risk Mitigation**:
- Use materialized views for dashboard queries (pre-calculated)
- Implement query timeouts (5s max per dashboard load)
- Cache metrics in Redis (5-minute TTL)

### Decision 4: Medium-Risk Manual Review — Require vs Auto-Approve

**Option**: **Default to require** (auto_approve_medium=false)

**Rationale**:
- Medium-risk changes (PhotometricInterpretation, Charset) can break workflows
- Manual review on first deployment safer (discover issues early)
- Audit trail shows who approved each change
- Can gradually increase automation as confidence builds

**Risk Mitigation**:
- Provide "bulk approve by rule" UI (e.g., "approve all Siemens CT photometric")
- Alert admin if pending queue exceeds threshold (100+ items)
- Keep detailed rationale/reasoning in each change record

---

## Risk Assessment & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| **Batch processing timeout** | Medium | High | Implement per-file timeout (500ms), skip on timeout, log alert |
| **Supplier rule false positives** | Medium | High | Extensive testing with real samples per supplier; start with safest (Siemens) |
| **File system exhaustion** (temp storage) | Low | High | Implement cleanup job; use Redis if available; monitor disk usage |
| **Celery worker crash mid-batch** | Low | Medium | Task retry (up to 3x); partial results saved; requeue on restart |
| **Configuration race conditions** | Low | Medium | Use in-memory cache with TTL; avoid hot-path config reads |
| **Backward compatibility break** | Low | High | Phase 3 API immutable; new features additive only; regression tests |
| **Admin dashboard performance** | Medium | Medium | Pre-calculate metrics; cache in Redis; query timeouts |
| **Supplier rule maintenance burden** | Medium | Low | Document plugin API; provide template; community contribution path |
| **Timezone issues in batch timestamps** | Low | Low | Use UTC consistently; document in API spec |

---

## Timeline & Milestones

**Total Duration**: 10-14 days (2 weeks)

```
Week 1 (Design + Core Implementation):
├─ Days 1-2: Batch Engine (core, tests)
├─ Day 3: Batch API endpoints
├─ Days 3-4: Supplier Rules (Siemens, GE, Philips)
├─ Day 5: Supplier integration + config
└─ Milestone: Batch API + suppliers functional (core feature complete)

Week 2 (Admin + Polish):
├─ Days 5-6: Admin dashboard UI + backend
├─ Day 7: Config panel + medium-risk review UI
├─ Days 7-8: Charset + optimization
├─ Days 8-9: Testing + gap analysis
├─ Day 10: Documentation + deployment
└─ Milestone: Full Phase 4 complete, production-ready
```

**Dependency Checkpoints**:
- ✅ Day 3: Batch API working (enables dashboard testing)
- ✅ Day 5: Supplier detection working (enables rule testing)
- ✅ Day 7: Dashboard MVP complete (enables E2E testing)

---

## Resource Requirements

### Development

- **Backend Engineer**: 1 FTE (core batch engine, supplier rules, Celery integration)
- **Frontend Engineer**: 1 FTE (admin dashboard, config UI)
- **QA/Test**: 0.5 FTE (gap analysis, performance testing, supplier samples)
- **DevOps** (part-time): Celery worker scaling, temp storage setup

### Infrastructure

- **PostgreSQL**: New tables (batch_jobs, batch_files, supplier_rules)
  - Estimated growth: 500MB for 50K legacy files batch + history
  - Indexes: batch_id, status, created_at, user_id
  
- **Redis**: Job queues, progress tracking, configuration cache
  - Existing setup sufficient
  - Estimated peak: <2GB (batch progress + config + cache)
  
- **Celery Workers**: 2-4 worker processes (parallel batch processing)
  - Pool size: 4 concurrent tasks per worker
  - CPU: 2-4 cores per worker (I/O bound, not CPU bound)
  - Disk: Temporary file storage (100MB - 5GB depending on batch size)

- **File Storage**: Temporary DICOM storage during batch processing
  - Option 1: Local /tmp (requires cleanup job)
  - Option 2: Redis (if batch < 500MB)
  - Option 3: S3/Object Storage (for very large batches)

### Testing

- **Test Data**: Real anonymized DICOM samples from suppliers (Siemens, GE, Philips)
  - Estimated 50-100 unique files per supplier
  - Include edge cases (missing tags, invalid encodings, etc.)
  
- **Load Test Scenario**: Simulate 1,000-file batch at P95 latency
  - Infrastructure: 2 workers, 100 concurrent connections

---

## Testing Strategy

### Unit Tests (Expected: 50-60 tests)

**Batch Operations**:
- BatchJob creation, state transitions, completion
- File extraction from zip, multipart handling
- Progress tracking, concurrent access
- Report generation (JSON/CSV formatting)

**Supplier Rules** (15+ per supplier):
- Manufacturer detection accuracy
- Private tag parsing (Siemens 0019, GE 0009, Philips private)
- Pixel spacing extraction, photometric inference
- Vendor-specific validation (±5% tolerance)

**Configuration**:
- Load/save settings, per-modality toggles
- Algorithm enable/disable, safety threshold changes
- Config cache invalidation

**Charset Detection**:
- Latin-1 detection accuracy (byte pattern analysis)
- UTF-8 validation (no false positives)
- Conversion correctness

### Integration Tests (Expected: 20-25 tests)

**End-to-End Batch Processing**:
- Upload zip → process → download report
- Multipart upload with mixed DICOM (valid, invalid, edge cases)
- Partial batch failure handling
- Retry on worker crash

**Supplier Rules in Context**:
- Batch with mixed suppliers (auto-detect + apply rules)
- Audit trail covers supplier rule application
- Config toggle affects rule application

**Admin Dashboard**:
- Metrics calculation correctness
- Filtering and search accuracy
- Bulk approve/reject functionality
- Config changes reflected in UI

### Functional Tests (Expected: 15-20 tests)

**Real-World Scenarios**:
- Legacy Siemens CT archive (500 files, known pixel spacing issues)
- GE MRI batch (unknown photometric interpretation issues)
- Mixed supplier archive (test detection logic)
- Batch with medium-risk items (manual review flow)

**Performance Benchmarks**:
- Batch of 100 files: <4.2s total (42ms baseline × 100)
- Batch of 1,000 files: <60s total (with 4 workers)
- Dashboard load: <500ms with 1M+ audit records

### Regression Tests

- All Phase 3 unit tests must still pass (backward compatibility)
- Single-instance STOW-RS with auto_normalize=true still works
- Audit logging not affected by batch operations

---

## Known Unknowns & Questions for Design Phase

### 1. File Storage Strategy
- **Q**: How to handle temporary DICOM during batch processing (100MB - 5GB)?
- **Options**: Local /tmp (cleanup required), Redis (limited), S3 (external dependency)
- **Decision needed**: Cost vs complexity trade-off

### 2. WebSocket vs HTTP Polling
- **Q**: How should clients track batch progress in real-time?
- **Options**: WebSocket (real-time, complex), HTTP polling (simple, higher latency)
- **Decision needed**: Based on expected client type (web dashboard vs CLI)

### 3. Supplier Rule Versioning
- **Q**: How to manage supplier rule updates (e.g., Siemens changes in new version)?
- **Options**: Semantic versioning, database version tracking, git history
- **Decision needed**: How to rollback old batches if rule changes?

### 4. Batch Archive Output
- **Q**: Should batch API output normalized DICOM as downloadable archive?
- **Options**: Yes (enables local backup), No (rely on PACS storage)
- **Decision needed**: Storage implications, use case priority

### 5. Scalability Limit
- **Q**: What's the maximum single-batch size (files) before performance degrades?
- **Hypothesis**: 10,000 files with 4 workers = ~60s processing
- **Decision needed**: Set hard limit + clear error message?

### 6. Medium-Risk Review Workflow
- **Q**: Approve/reject medium-risk items automatically after timeout?
- **Options**: Auto-approve after 7 days, require explicit approval, default to reject
- **Decision needed**: Based on admin preference + audit requirements

### 7. Supplier Rule Accuracy
- **Q**: How accurate must supplier detection be (false positive tolerance)?
- **Hypothesis**: 99% accuracy based on Manufacturer tag
- **Testing needed**: Validate against real-world supplier data

### 8. Configuration Persistence
- **Q**: Where to store configuration (database vs config file vs environment)?
- **Options**: PostgreSQL (runtime changes), config file (immutable), environment vars (simple)
- **Decision needed**: Support hot-reload of config changes?

### 9. Backward Compatibility
- **Q**: Will Phase 4 maintain API compatibility with Phase 3?
- **Answer**: YES (new endpoints, existing unchanged)
- **Validation needed**: Comprehensive regression tests

### 10. Modality-Specific Rules
- **Q**: Should normalization rules vary by modality (CT vs MR vs US)?
- **Options**: Yes (modality-specific thresholds), No (one-size-fits-all)
- **Decision needed**: Add modality parameter to batch API?

---

## Deferred Items (Phase 5+)

- Machine learning-based anomaly detection (automated medium-risk approval)
- Batch comparison reports (compare two batches, highlight differences)
- Supplier rule marketplace (community-contributed rules)
- Integration with DICOM standardization services (third-party normalization)
- Mobile app for batch monitoring and medium-risk approval
- API rate limiting and usage billing per tenant
- Advanced scheduling (batch processing at off-peak hours)
- Normalization cost calculator (estimate impact on storage, performance)

---

## Success Metrics & Post-Implementation Monitoring

**After Phase 4 completion, measure**:

- 🎯 **Throughput**: Batch API processes 100+ files/min consistently
- 🎯 **Quality**: ≥90% design match, ≥95% test coverage
- 🎯 **Usability**: Admin can configure normalization in <5 minutes
- 🎯 **Effectiveness**: Supplier rules reduce manual review from 30% → <5%
- 🎯 **Safety**: Zero unintended clinical data modifications in batch processing
- 🎯 **Observability**: Dashboard provides real-time visibility into normalization activity
- 🎯 **Performance**: Single-file normalization still <100ms (Phase 3 baseline maintained)
- 🎯 **Reliability**: Batch completion rate ≥99.5% (auto-retry recovers 95% of failures)

**Dashboard KPIs to track**:
- % of archive normalized (cumulative)
- Avg time to process file (trend over time)
- Error rate by supplier (detect systematic issues)
- Pending medium-risk count (SLA: resolve within 24h)

---

## References & Related Documentation

- Phase 3 Plan: `docs/01-plan/features/phase-3-normalizer.plan.md`
- Phase 3 Design: `docs/02-design/features/phase-3-normalizer.design.md`
- DICOM Standard Part 3: Information Object Definitions
- Celery Documentation: https://docs.celeryproject.io/
- FastAPI File Uploads: https://fastapi.tiangolo.com/tutorial/request-files/
- DICOM Manufacturer Tags Reference (0008, 0070)

---

## Approval Checklist

- [ ] Batch processing architecture approved (Celery vs sync decision)
- [ ] Supplier rules approach validated (plugin vs config)
- [ ] Admin dashboard wireframes approved
- [ ] Medium-risk review workflow defined
- [ ] File storage strategy selected (local vs Redis vs S3)
- [ ] Resource allocation confirmed (backend, frontend, QA)
- [ ] Performance benchmarks agreed (100 files/min target)
- [ ] Risk mitigations reviewed and acceptable
- [ ] Timeline feasible (10-14 days)
- [ ] Proceed to Design phase

**Plan Status**: 📋 READY FOR DESIGN

---

**Last Updated**: 2026-05-14  
**Phase**: 4 (Enhancing Phase 3)  
**Next Phase**: Design (detailed specification, database schema, API contracts)  
**Owner**: Backend Team + Frontend Team  
**Stakeholders**: QA, DevOps, Clinical Advisory (for supplier rule validation)
