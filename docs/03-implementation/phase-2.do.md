# PDCA Do: Phase 2 — Implementation Guide

**Reference Design**: `docs/02-design/features/phase-2.design.md`  
**Implementation Date**: 2026-05-13  
**Estimated Duration**: 2 weeks (concurrent work possible)

---

## Quick Start

```bash
# 1. Setup environment
cd /Users/user/GitHub_project/pacs
git checkout -b feature/phase-2

# 2. Install new dependency (if needed)
pip install Pillow  # For JPEG JFIF parsing

# 3. Follow implementation order below
```

---

## Implementation Order (4 Phases)

### Phase 2.1: JPEG Density Validator (Days 1-2)

**Goal**: Implement core JPEG density validation algorithm

#### Task 2.1.1: Extend DicomValidator class

**File**: `backend/app/services/dicom_validator.py`

**Checklist**:
- [ ] Read existing DicomValidator implementation
- [ ] Add `validate_jpeg_density()` method
  - [ ] Extract JFIF Xdensity, Ydensity from pydicom pixel_array metadata
  - [ ] Extract DICOM Pixel Spacing (PixelSpacingRow, PixelSpacingColumn)
  - [ ] Calculate expected DPI: `25.4 / pixel_spacing_mm`
  - [ ] Calculate mismatch percentage
  - [ ] Return ValidationIssue if mismatch > tolerance
  - [ ] Tolerance logic: < 5% (ok), 5-20% (warning), > 20% (error)
- [ ] Add `validate_required_tags()` method
  - [ ] Check for: PatientID, StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
  - [ ] Return list of missing tags
- [ ] Add data classes: `ValidationIssue`, `ValidationResult`
- [ ] Update `validate_study()` to call new validators

**Code Structure**:
```python
class DicomValidator:
    async def validate_jpeg_density(
        self,
        pixel_spacing: Tuple[float, float],
        jpeg_metadata: dict
    ) -> Optional[ValidationIssue]:
        """Validate JPEG DPI vs Pixel Spacing"""
        
        # 1. Extract JPEG JFIF density
        xdensity = jpeg_metadata.get("xdensity")  # DPI
        ydensity = jpeg_metadata.get("ydensity")
        
        if not xdensity or not pixel_spacing:
            return None  # Skip if missing data
        
        # 2. Calculate expected DPI from Pixel Spacing
        expected_dpi = 25.4 / pixel_spacing[0]
        actual_dpi = xdensity
        
        # 3. Calculate mismatch
        mismatch_pct = abs(actual_dpi - expected_dpi) / expected_dpi * 100
        
        # 4. Determine severity
        if mismatch_pct < 5:
            return None  # OK
        elif mismatch_pct < 20:
            return ValidationIssue(
                type="JPEG_DENSITY_MISMATCH",
                severity="warning",
                message=f"JPEG DPI {actual_dpi} vs Pixel Spacing {pixel_spacing[0]}mm mismatch {mismatch_pct:.1f}%",
                details={"expected_dpi": expected_dpi, "actual_dpi": actual_dpi, "mismatch_pct": mismatch_pct}
            )
        else:
            return ValidationIssue(
                type="JPEG_DENSITY_MISMATCH",
                severity="error",
                message=f"JPEG DPI mismatch {mismatch_pct:.1f}% exceeds tolerance",
                details={...}
            )
```

#### Task 2.1.2: Unit tests for validator

**File**: `backend/tests/test_dicom_validator.py`

**Test Cases**:
- [ ] `test_jpeg_density_exact_match()` — DPI 300 matches Pixel Spacing 0.0847mm
- [ ] `test_jpeg_density_5_percent_warning()` — Mismatch 5.7% returns WARNING
- [ ] `test_jpeg_density_25_percent_error()` — Mismatch 25% returns ERROR
- [ ] `test_missing_required_tags()` — Missing PatientID detected
- [ ] `test_validation_caching()` — Cache hit within 24h

**Run Tests**:
```bash
pytest backend/tests/test_dicom_validator.py -v
```

---

### Phase 2.2: Validation API Endpoints (Days 2-3)

**Goal**: Create REST endpoints for validation results

#### Task 2.2.1: Create validation.py API module

**File**: `backend/app/api/validation.py` (new)

**Endpoints to Implement**:

```python
# 1. POST /api/v1/validation/study/{study_id}
@router.post("/api/v1/validation/study/{study_id}")
@AuditLogger.log("VALIDATION_REQUESTED", "DicomStudy")
async def validate_study(
    study_id: str,
    force_revalidate: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))
):
    """Run validation on study. Cache 24h. Audit log all decisions."""
    
    # 1. Check cache
    cache_key = f"validation:{study_id}"
    if not force_revalidate:
        cached = await cache_mgr.get(cache_key)
        if cached:
            return json.loads(cached)
    
    # 2. Get study from Orthanc
    orthanc_resp = await client.get(f"/studies/{study_id}")
    if orthanc_resp.status_code == 404:
        raise NotFoundError(resource="Study", resource_id=study_id)
    
    study_data = orthanc_resp.json()
    
    # 3. Run validator
    validator = DicomValidator()
    result = await validator.validate_study(study_id)
    
    # 4. Cache result
    await cache_mgr.set(cache_key, result.to_json(), ttl=86400)
    
    # 5. Audit log
    audit = AuditLog(
        user_id=str(user.id),
        username=user.username,
        action="validation_requested",
        resource_type="DicomStudy",
        resource_id=study_id,
        details={"issue_count": len(result.issues), "status": result.status}
    )
    db.add(audit)
    await db.commit()
    
    return result

# 2. GET /api/v1/validation/study/{study_id}/report
@router.get("/api/v1/validation/study/{study_id}/report")
async def get_validation_report(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve cached validation result."""
    cache_key = f"validation:{study_id}"
    cached = await cache_mgr.get(cache_key)
    if not cached:
        raise NotFoundError(resource="ValidationReport", resource_id=study_id)
    return json.loads(cached)
```

**Checklist**:
- [ ] Create validation.py with imports (DicomValidator, AuditLogger, AppException)
- [ ] Implement POST /validation/study/{id} endpoint
  - [ ] Cache management (check, set with TTL)
  - [ ] Orthanc client call
  - [ ] Validator integration
  - [ ] Audit logging
  - [ ] Error handling (NotFoundError)
- [ ] Implement GET /validation/study/{id}/report endpoint
- [ ] Add route registration in main.py: `app.include_router(validation.router)`
- [ ] Test endpoints with curl/Postman

---

#### Task 2.2.2: Modify STOW-RS endpoint

**File**: `backend/app/api/dicomweb.py` (modify existing `stow_rs`)

**Changes**:
- [ ] Add query parameter: `validate: str = Query("warn", regex="^(strict|warn|off)$")`
- [ ] Pre-upload validation step:
  ```python
  validator = DicomValidator()
  for file in files:
      dcm = pydicom.dcmread(file.file)
      issues = await validator.validate_series(dcm)
      
      if validate == "strict" and issues:
          raise DicomValidationError(
              message=f"Validation failed: {file.filename}",
              details={"issues": [i.to_dict() for i in issues]}
          )
  ```
- [ ] Cache validation results after upload
- [ ] Update audit log with validation_mode

**Test**:
```bash
# Test strict mode (reject invalid)
curl -X POST http://localhost:8001/api/v1/studies \
  -F "files=@test_invalid.dcm" \
  -H "Authorization: Bearer $TOKEN" \
  "?validate=strict"

# Test warn mode (log warning)
curl -X POST http://localhost:8001/api/v1/studies \
  -F "files=@test_invalid.dcm" \
  -H "Authorization: Bearer $TOKEN" \
  "?validate=warn"
```

---

### Phase 2.3: DICOMweb Endpoint Expansion (Days 3-4)

**Goal**: Add 4 missing QIDO-RS/WADO-RS endpoints

#### Task 2.3.1: Add series-level and instance-level QIDO endpoints

**File**: `backend/app/api/dicomweb.py`

**New Endpoints**:

```python
# 1. GET /studies/{study_id}/series/{series_id}
@router.get("/api/v1/studies/{study_id}/series/{series_id}")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:series:detail")
async def qido_series_detail(
    study_id: str,
    series_id: str,
    user: User = Depends(get_current_user)
) -> Dict:
    """Series-level metadata (Modality, SeriesDescription, InstanceCount)"""
    resp = await client.get(f"/studies/{study_id}/series/{series_id}")
    if resp.status_code != 200:
        raise NotFoundError(resource="Series", resource_id=series_id)
    return resp.json()

# 2. GET /studies/{study_id}/series/{series_id}/instances/{instance_id}
@router.get("/api/v1/studies/{study_id}/series/{series_id}/instances/{instance_id}")
@cached(ttl=CACHE_TTL_ORTHANC, key_prefix="pacs:orthanc:instances:detail")
async def qido_instance_detail(
    study_id: str,
    series_id: str,
    instance_id: str,
    user: User = Depends(get_current_user)
) -> Dict:
    """Instance-level metadata (SOP Class, rows, columns, etc)"""
    resp = await client.get(f"/studies/{study_id}/series/{series_id}/instances/{instance_id}")
    if resp.status_code != 200:
        raise NotFoundError(resource="Instance", resource_id=instance_id)
    return resp.json()

# 3. GET /studies/{study_id}/series/{series_id}/instances/{instance_id}/frames
@router.get("/api/v1/studies/{study_id}/series/{series_id}/instances/{instance_id}/frames")
async def qido_frames(
    study_id: str,
    series_id: str,
    instance_id: str,
    user: User = Depends(get_current_user)
) -> Dict:
    """Multiframe instance support (for CT/MR series)"""
    resp = await client.get(f"/studies/{study_id}/series/{series_id}/instances/{instance_id}")
    if resp.status_code != 200:
        raise NotFoundError(resource="Instance", resource_id=instance_id)
    
    # Return frame count and metadata
    data = resp.json()
    return {
        "frame_count": data.get("NumberOfFrames", 1),
        "instance_uid": instance_id,
        "modality": data.get("MainDicomTags", {}).get("Modality")
    }
```

**Checklist**:
- [ ] Add 3 new GET endpoints to dicomweb.py
- [ ] Add `@cached` decorators with appropriate TTL
- [ ] Test each endpoint with actual Orthanc data
- [ ] Verify caching works (check Redis)

#### Task 2.3.2: Add WADO-URI legacy endpoint

**File**: `backend/app/api/dicomweb.py`

**Implementation**:

```python
# 4. GET /wado (WADO-URI legacy endpoint)
@router.get("/wado")
async def wado_uri(
    StudyInstanceUID: str = Query(...),
    SeriesInstanceUID: str = Query(None),
    SOPInstanceUID: str = Query(None),
    user: User = Depends(get_current_user)
) -> StreamingResponse:
    """
    WADO-URI (legacy) endpoint for backward compatibility.
    Maps DICOM UIDs to Orthanc IDs and fetches content.
    """
    
    # 1. Find Orthanc IDs by DICOM UIDs
    # Query Orthanc QIDO API to find study/series/instance
    resp = await client.get(
        "/tools/find",
        json={
            "Level": "Instance",
            "Query": {
                "StudyInstanceUID": StudyInstanceUID,
                "SeriesInstanceUID": SeriesInstanceUID,
                "SOPInstanceUID": SOPInstanceUID
            }
        }
    )
    
    if not resp.json():
        raise NotFoundError(resource="Instance via WADO-URI")
    
    instance_ids = resp.json()
    orthanc_instance_id = instance_ids[0]
    
    # 2. Get file content from Orthanc
    file_resp = await client.get(f"/instances/{orthanc_instance_id}/file")
    
    return StreamingResponse(
        iter([file_resp.content]),
        media_type="application/dicom",
        headers={"Content-Disposition": f"attachment; filename={orthanc_instance_id}.dcm"}
    )
```

**Checklist**:
- [ ] Implement WADO-URI endpoint
- [ ] Test with legacy clients (if available)
- [ ] Document UID-to-ID mapping logic

---

### Phase 2.4: Testing & Polish (Days 4-5)

**Goal**: Verify implementation, gap analysis, deployment readiness

#### Task 2.4.1: Integration tests

**File**: `backend/tests/test_phase2_integration.py` (new)

**Tests to Write**:
```python
async def test_e2e_upload_with_jpeg_validation():
    """Upload real Chest X-ray, validate JPEG density, verify in OHIF"""
    
async def test_validation_caching():
    """First validation writes to cache, second read from cache"""
    
async def test_stow_rs_strict_mode_rejects():
    """Strict mode with invalid DICOM → 422 error"""
    
async def test_stow_rs_warn_mode_accepts():
    """Warn mode with invalid DICOM → 200 with warnings in response"""
    
async def test_dicomweb_series_endpoint():
    """GET /studies/{id}/series/{id} returns metadata"""
    
async def test_wado_uri_legacy():
    """WADO-URI endpoint maps UIDs to files correctly"""
```

**Run Tests**:
```bash
pytest backend/tests/test_phase2_integration.py -v --tb=short
```

**Checklist**:
- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] Coverage > 90%

#### Task 2.4.2: Database migrations (if needed)

**File**: `backend/migrations/` (new)

**Checklist**:
- [ ] If `dicom_validation_results` table needed: create migration
  - [ ] Table: dicom_validation_results (id, study_id, series_id, status, issues, created_at)
  - [ ] Run: `alembic revision --autogenerate -m "Add validation results table"`
  - [ ] Run: `alembic upgrade head`
- [ ] If no table needed (using Redis only): mark as N/A

#### Task 2.4.3: Documentation

**File**: `docs/PHASE2_IMPLEMENTATION.md` (new)

**Content**:
- API reference for new endpoints
- JPEG validation algorithm explanation
- Configuration options (tolerance levels, cache TTL)
- Troubleshooting guide

#### Task 2.4.4: Gap analysis

**Command**:
```bash
/pdca analyze phase-2
```

**Checklist**:
- [ ] Gap detector compares Design vs Implementation
- [ ] Match Rate calculated
- [ ] If < 90%: run auto-improvement with pdca-iterator
- [ ] If >= 90%: proceed to Report phase

---

## Key Files to Create/Modify

### New Files
- ✅ `backend/app/api/validation.py` — Validation API endpoints
- ✅ `backend/app/services/dicom_normalizer.py` — Auto-correction service
- ✅ `backend/tests/test_dicom_validator.py` — Unit tests
- ✅ `backend/tests/test_phase2_integration.py` — Integration tests
- ✅ `docs/PHASE2_IMPLEMENTATION.md` — Implementation guide

### Modified Files
- ✅ `backend/app/services/dicom_validator.py` — Extend with JPEG density validation
- ✅ `backend/app/api/dicomweb.py` — Add 4 new endpoints, modify STOW-RS
- ✅ `backend/app/main.py` — Register validation router

---

## Environment Setup

### Dependencies
```bash
# Already installed:
pip list | grep -E "pydicom|fastapi|sqlalchemy|redis"

# New dependency (JPEG JFIF parsing):
pip install Pillow
```

### Configuration
```python
# backend/app/core/config.py (verify these exist)

CACHE_TTL_ORTHANC = 3600  # 1 hour
VALIDATION_CACHE_TTL = 86400  # 24 hours
JPEG_DENSITY_TOLERANCE_MIN = 0.95  # ±5%
JPEG_DENSITY_TOLERANCE_MAX = 1.20  # ±20%
```

### Test DICOM Files
```bash
# Download sample DICOM for testing
# (Use existing test DICOM files or create minimal test cases)

# Option 1: Use sample data from pydicom
python -c "from pydicom.data import get_testdata_files; print(get_testdata_files('*.dcm')[0])"

# Option 2: Create mock DICOM in test fixture
# (See test_dicom_validator.py)
```

---

## Development Workflow

### Day 1-2: Core Validator
```bash
git checkout -b feature/phase-2-validator
# Implement 2.1.1 + 2.1.2
git add backend/app/services/dicom_validator.py backend/tests/test_dicom_validator.py
git commit -m "Phase 2.1: JPEG density validator + unit tests"
git push -u origin feature/phase-2-validator
```

### Day 2-3: Validation API
```bash
# Implement 2.2.1 + 2.2.2
git add backend/app/api/validation.py backend/app/api/dicomweb.py
git commit -m "Phase 2.2: Validation API endpoints + STOW-RS integration"
git push
```

### Day 3-4: DICOMweb Endpoints
```bash
# Implement 2.3.1 + 2.3.2
git add backend/app/api/dicomweb.py
git commit -m "Phase 2.3: DICOMweb expansion (series/instance endpoints + WADO-URI)"
git push
```

### Day 4-5: Testing & Deployment
```bash
# Implement 2.4.1 + 2.4.2 + 2.4.3
git add backend/tests/ docs/ backend/migrations/
git commit -m "Phase 2.4: Integration tests, documentation, deployment prep"
git push
```

### Final: Gap Analysis & Merge
```bash
/pdca analyze phase-2
# If >= 90%: proceed to Report & Archive
# If < 90%: /pdca iterate phase-2
git checkout main
git pull origin main
git merge feature/phase-2-validator --no-ff
git merge feature/phase-2-api --no-ff
# ... (merge all feature branches)
git push origin main
```

---

## Deployment Checklist

Before deploying to production:

- [ ] All tests passing (100% green)
- [ ] Gap analysis >= 90%
- [ ] Code review approved
- [ ] Security review: no SQL injection, XSS, auth bypass
- [ ] Performance test: validation < 500ms per study
- [ ] Database migration ran successfully (staging)
- [ ] Documentation complete
- [ ] Rollback plan documented
- [ ] User training materials ready
- [ ] Monitoring/alerting configured

---

## Success Criteria

| Criterion | Target | How to Verify |
|-----------|--------|---------------|
| JPEG density validation | >99% accuracy | Unit tests pass |
| API response time | <500ms per study | Load test |
| Required DICOM tags | 100% coverage | Validator tests |
| DICOMweb endpoints | 8/8 endpoints | Health check + OHIF test |
| Audit logging | 100% decisions | Audit log query |
| Match rate (Design vs Impl) | ≥90% | Gap detector |

---

## Debugging Tips

### If JPEG density validation fails:
1. Check JFIF header extraction: `python -c "from PIL import Image; img = Image.open(dcm_file); print(img.info)"`
2. Verify Pixel Spacing parsing: `dcm = pydicom.dcmread(file); print(dcm.PixelSpacing)`
3. Check calculation: `25.4 / pixel_spacing = expected_dpi`

### If STOW-RS fails:
1. Check Orthanc connectivity: `curl -u admin:password http://localhost:8042/orthanc/system`
2. Check validation rules: `logger.debug(f"Issues: {issues}")`
3. Verify cache: `redis-cli get "validation:study_id"`

### If DICOMweb endpoints timeout:
1. Check Orthanc performance: `curl http://localhost:8042/orthanc/system`
2. Verify cache is working: `@cached` decorator logs
3. Profile with: `python -m cProfile backend/main.py`

---

## Next Phase

After completion:

```bash
/pdca analyze phase-2    # Gap analysis
/pdca report phase-2     # Completion report  
/pdca archive phase-2    # Archive documents
```

Then deploy to production (his.example.org).

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-13  
**Status**: 🟢 READY FOR IMPLEMENTATION
