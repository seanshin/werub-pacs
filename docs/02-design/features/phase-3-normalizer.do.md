# Do: Phase 3 — DICOM Normalization Engine Implementation Guide

**Date**: 2026-05-13  
**Phase**: Do (Implementation)  
**Estimated Duration**: 2-3 days  
**Status**: READY TO START

---

## Quick Start

**Reference Documents**:
- Plan: `docs/01-plan/features/phase-3-normalizer.plan.md`
- Design: `docs/02-design/features/phase-3-normalizer.design.md`

**Implementation Order**:
1. **Phase 3.1**: Pixel Spacing Normalizer (Days 1-2)
2. **Phase 3.2**: Tag Normalizer (Days 2-3)
3. **Phase 3.3**: STOW-RS Integration (Days 3-4)
4. **Phase 3.4**: Testing & Polish (Day 4)

---

## Phase 3.1: Pixel Spacing Normalizer (Days 1-2)

### Checklist

- [ ] Create `backend/app/services/dicom_normalizer.py`
- [ ] Implement `DicomNormalizer` class structure
- [ ] Implement `_normalize_pixel_spacing()` method
- [ ] Create data models: `ChangeSummary`, `NormalizationResult`
- [ ] Write unit tests (5+ test cases)
- [ ] Verify algorithm matches design specifications

### Step 1.1: Create Service File

**File**: `backend/app/services/dicom_normalizer.py`

```python
"""DICOM normalization service for Phase 3."""
import io
from dataclasses import dataclass, field
from typing import Optional
import pydicom
from pydicom.dataset import Dataset

# Import existing Phase 2 validator
from app.services.dicom_validator import DicomValidator, ValidationReport
from app.core.exceptions import AppException


@dataclass
class ChangeSummary:
    """Record of a single correction applied."""
    tag_keyword: str
    original_value: Optional[str]
    corrected_value: str
    rationale: str
    risk_level: str  # "safe", "medium", "risky"
    category: str  # "pixel_spacing", "tag", "photometric", "charset"


@dataclass
class NormalizationResult:
    """Output from normalization process."""
    modified: bool
    changes: list[ChangeSummary] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_ms: float = 0.0


class DicomNormalizer:
    """Normalize DICOM datasets based on validation findings."""
    
    def __init__(self):
        self.validator = DicomValidator()
    
    async def normalize(
        self,
        ds: Dataset,
        validation_report: ValidationReport,
        audit_logger=None,
    ) -> NormalizationResult:
        """
        Normalize DICOM dataset.
        
        Args:
            ds: pydicom Dataset to normalize
            validation_report: Output from DicomValidator.validate()
            audit_logger: Optional audit logger
            
        Returns:
            NormalizationResult with all corrections applied
        """
        import time
        start = time.time()
        result = NormalizationResult(modified=False)
        
        try:
            # Apply safe corrections in order
            self._normalize_pixel_spacing(ds, validation_report, result)
            self._normalize_tags(ds, validation_report, result)
            # Medium-risk corrections: just log, don't apply
            self._check_photometric(ds, validation_report, result)
            self._check_charset(ds, validation_report, result)
            
            result.elapsed_ms = (time.time() - start) * 1000
            return result
        except Exception as e:
            result.error = str(e)
            return result
    
    def _normalize_pixel_spacing(
        self,
        ds: Dataset,
        report: ValidationReport,
        result: NormalizationResult,
    ) -> None:
        """Calculate Pixel Spacing from JPEG density if needed."""
        # Find JPEG density findings
        density_findings = [
            f for f in report.findings
            if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]
        
        if not density_findings:
            return
        
        # Extract original Pixel Spacing if present
        original_spacing = None
        if hasattr(ds, 'PixelSpacing'):
            original_spacing = str(ds.PixelSpacing)
        
        # Get JFIF density (need access to raw data)
        # For now, assume we have it from the finding
        finding = density_findings[0]
        if 'dpi' not in finding.details:
            return
        
        dpi = finding.details['dpi']
        if dpi <= 0:
            return
        
        # Convert DPI to mm: pixel_spacing_mm = 25.4 / dpi
        calculated_spacing = 25.4 / dpi
        calculated_spacing = round(calculated_spacing, 4)
        
        # Apply correction
        ds.PixelSpacing = [calculated_spacing, calculated_spacing]
        
        result.changes.append(ChangeSummary(
            tag_keyword="PixelSpacing",
            original_value=original_spacing,
            corrected_value=str([calculated_spacing, calculated_spacing]),
            rationale=f"Calculated from JPEG JFIF {dpi} DPI header",
            risk_level="safe",
            category="pixel_spacing",
        ))
        result.modified = True
    
    def _normalize_tags(
        self,
        ds: Dataset,
        report: ValidationReport,
        result: NormalizationResult,
    ) -> None:
        """Insert default values for missing recommended tags."""
        from datetime import datetime
        
        # Define defaults for recommended tags
        tag_defaults = {
            'PatientBirthDate': '00000000',  # Unknown DoB
            'PatientSex': 'O',  # Other
        }
        
        # Date/time tags: use current time
        date_tags = ['StudyDate', 'SeriesDate', 'ContentDate', 'InstanceCreationDate']
        time_tags = ['SeriesTime', 'InstanceCreationTime']
        
        now = datetime.utcnow()
        date_str = now.strftime('%Y%m%d')
        time_str = now.strftime('%H%M%S')
        
        # Apply simple defaults
        for tag, default_val in tag_defaults.items():
            if not hasattr(ds, tag) or getattr(ds, tag, '') == '':
                setattr(ds, tag, default_val)
                result.changes.append(ChangeSummary(
                    tag_keyword=tag,
                    original_value=None,
                    corrected_value=default_val,
                    rationale=f"Default for unknown {tag}",
                    risk_level="safe",
                    category="tag",
                ))
                result.modified = True
        
        # Apply date defaults
        for tag in date_tags:
            if not hasattr(ds, tag) or getattr(ds, tag, '') == '':
                setattr(ds, tag, date_str)
                result.changes.append(ChangeSummary(
                    tag_keyword=tag,
                    original_value=None,
                    corrected_value=date_str,
                    rationale=f"Use upload time ({date_str})",
                    risk_level="safe",
                    category="tag",
                ))
                result.modified = True
        
        # Apply time defaults
        for tag in time_tags:
            if not hasattr(ds, tag) or getattr(ds, tag, '') == '':
                setattr(ds, tag, time_str)
                result.changes.append(ChangeSummary(
                    tag_keyword=tag,
                    original_value=None,
                    corrected_value=time_str,
                    rationale=f"Use upload time ({time_str})",
                    risk_level="safe",
                    category="tag",
                ))
                result.modified = True
    
    def _check_photometric(
        self,
        ds: Dataset,
        report: ValidationReport,
        result: NormalizationResult,
    ) -> None:
        """Check if photometric interpretation can be inferred (MEDIUM risk, no auto-apply)."""
        findings = [f for f in report.findings if f.rule_code == "MISSING_PHOTOMETRIC_INTERPRETATION"]
        if not findings:
            return
        
        # Infer from SamplesPerPixel
        if not hasattr(ds, 'SamplesPerPixel'):
            return
        
        samples = ds.SamplesPerPixel
        inferred = "MONOCHROME2" if samples == 1 else "RGB" if samples == 3 else None
        
        if inferred:
            result.changes.append(ChangeSummary(
                tag_keyword="PhotometricInterpretation",
                original_value=None,
                corrected_value=inferred,
                rationale=f"Inferred from SamplesPerPixel={samples}",
                risk_level="medium",
                category="photometric",
            ))
    
    def _check_charset(
        self,
        ds: Dataset,
        report: ValidationReport,
        result: NormalizationResult,
    ) -> None:
        """Check if character set can be inferred (MEDIUM risk, no auto-apply)."""
        findings = [f for f in report.findings if f.rule_code == "MISSING_CHARSET"]
        if not findings or not hasattr(ds, 'PatientName'):
            return
        
        # Try to detect UTF-8
        patient_name = str(ds.PatientName)
        try:
            patient_name.encode('utf-8')
            charset = "ISO_IR 192"  # UTF-8
            result.changes.append(ChangeSummary(
                tag_keyword="SpecificCharacterSet",
                original_value=None,
                corrected_value=charset,
                rationale=f"Detected UTF-8 encoding in PatientName",
                risk_level="medium",
                category="charset",
            ))
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
```

### Step 1.2: Write Unit Tests

**File**: `backend/tests/test_dicom_normalizer.py` (create new)

```python
"""Unit tests for DICOM normalizer (Phase 3)."""
import pytest
from app.services.dicom_normalizer import DicomNormalizer, NormalizationResult
from app.services.dicom_validator import DicomValidator


class TestPixelSpacingNormalizer:
    """Test pixel spacing correction algorithm."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.normalizer = DicomNormalizer()
        self.validator = DicomValidator()
    
    def test_pixel_spacing_exact_match_no_change(self, jfif_dicom_300dpi):
        """No change when JFIF density matches Pixel Spacing exactly."""
        report = self.validator.validate(jfif_dicom_300dpi)
        # TODO: Verify no JPEG_DENSITY_MISMATCH finding
    
    def test_pixel_spacing_warning_tier_applies_correction(self, jfif_dicom_315dpi):
        """Apply correction when JFIF density is in WARNING tier (5-20% mismatch)."""
        # TODO: Test pixel spacing correction
    
    def test_pixel_spacing_error_tier_applies_correction(self, jfif_dicom_375dpi):
        """Apply correction when JFIF density is in ERROR tier (>20% mismatch)."""
        # TODO: Test pixel spacing correction
    
    def test_pixel_spacing_missing_tag_inserted_from_jpeg(self, dicom_missing_pixel_spacing):
        """Insert PixelSpacing tag from JFIF density if missing."""
        # TODO: Test insertion
    
    def test_pixel_spacing_tolerance_calculation(self):
        """Verify pixel spacing tolerance is calculated correctly."""
        # Calculate from 300 DPI: 25.4 / 300 = 0.0847 mm
        # 307 DPI should be: 25.4 / 307 = 0.0827 mm
        # Difference: |0.0847 - 0.0827| / 0.0847 = 2.3% (within 5% tolerance)
        pass


class TestTagNormalizer:
    """Test missing tag insertion."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.normalizer = DicomNormalizer()
    
    def test_insert_patient_birth_date_default(self):
        """Insert PatientBirthDate = '00000000' if missing."""
        pass
    
    def test_insert_patient_sex_default(self):
        """Insert PatientSex = 'O' if missing."""
        pass
    
    def test_insert_study_date_from_upload_time(self):
        """Insert StudyDate using current date if missing."""
        pass
    
    def test_preserve_existing_tag_values(self, complete_dicom):
        """Do not overwrite existing tag values."""
        pass
    
    def test_does_not_insert_mandatory_tags(self):
        """Never insert mandatory tags (only recommended)."""
        pass


class TestNormalizationResult:
    """Test output data structures."""
    
    def test_result_contains_changes_list(self):
        """Result has changes field with ChangeSummary objects."""
        pass
    
    def test_change_summary_has_required_fields(self):
        """ChangeSummary contains all required fields."""
        pass
```

### Step 1.3: Test Local Implementation

```bash
# Run specific test class
pytest backend/tests/test_dicom_normalizer.py::TestPixelSpacingNormalizer -v

# Run with coverage
pytest backend/tests/test_dicom_normalizer.py --cov=app.services.dicom_normalizer
```

---

## Phase 3.2: Tag Normalizer (Days 2-3)

### Checklist

- [ ] Complete `_normalize_tags()` method
- [ ] Test all missing recommended tags
- [ ] Verify safe defaults are correct
- [ ] Test timestamp handling (StudyDate, SeriesTime, etc.)

### Key Implementation Details

**Missing Recommended Tags to Handle**:

| Tag | Default | Rationale |
|-----|---------|-----------|
| `PatientBirthDate` | `"00000000"` | Unknown DoB (DICOM standard) |
| `PatientSex` | `"O"` | Other (DICOM standard) |
| `StudyDate` | `now.strftime('%Y%m%d')` | Use upload time |
| `SeriesDate` | `now.strftime('%Y%m%d')` | Use upload time |
| `SeriesTime` | `now.strftime('%H%M%S')` | Use upload time |
| `ContentDate` | `now.strftime('%Y%m%d')` | Use upload time |
| `InstanceCreationDate` | `now.strftime('%Y%m%d')` | Use upload time |
| `InstanceCreationTime` | `now.strftime('%H%M%S')` | Use upload time |

**Safety Rules**:
- ✅ Insert **recommended** tags only (Type 2)
- ❌ Never modify **mandatory** tags (Type 1)
- ❌ Never insert fictitious patient/study identifiers
- ✅ Always use safe defaults (unknown, neutral, current time)

---

## Phase 3.3: STOW-RS Integration (Days 3-4)

### Checklist

- [ ] Modify `backend/app/api/dicomweb.py` `stow_rs()` endpoint
- [ ] Add `auto_normalize: bool = Query(False)` parameter
- [ ] Integrate normalizer into upload flow
- [ ] Update response to include normalization details
- [ ] Extend audit logging with normalization actions
- [ ] Test integration with full workflow

### Step 3.1: Modify STOW-RS Endpoint

**File**: `backend/app/api/dicomweb.py`

Modify the `stow_rs()` function:

```python
@router.post("/studies")
@invalidate_on_write(CACHE_PATTERN_WORKLIST, CACHE_PATTERN_ORTHANC)
@AuditLogger.log("DICOM_UPLOAD", "DicomStudy")
async def stow_rs(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    validate: str = Query("warn", regex="^(strict|warn|off)$"),
    auto_normalize: bool = Query(False),  # NEW: Add normalization parameter
):
    """STOW-RS: Upload DICOM file with optional auto-normalization."""
    data = await file.read()
    
    report = None
    normalization_result = None
    
    if validate != "off":
        # Phase 2: Validate
        report = validator.validate(data)
        
        if validate == "strict" and not report.accepted:
            raise DicomValidationError(...)
        elif validate == "warn" and not report.accepted:
            raise DicomValidationError(...)
    
    # NEW: Phase 3 — Normalize (optional)
    if auto_normalize and report is not None:
        import io
        ds = pydicom.dcmread(io.BytesIO(data), force=True)
        normalizer = DicomNormalizer()
        normalization_result = await normalizer.normalize(ds, report, audit_logger=None)
        
        if normalization_result.error:
            raise DicomNormalizationError(
                message="DICOM normalization failed",
                details={"error": normalization_result.error}
            )
        
        # Re-serialize normalized dataset
        buf = io.BytesIO()
        ds.save_as(buf)
        data = buf.getvalue()
        
        # Re-validate post-normalization
        report = validator.validate(data)
        if not report.accepted:
            raise DicomValidationError(
                message="DICOM still invalid after normalization",
                details={"findings": [f.message for f in report.findings]}
            )
    
    # Store in Orthanc
    resp = await request.app.state.http_client.post(
        "/instances",
        content=data,
        headers={"Content-Type": "application/dicom"},
    )
    
    if resp.status_code not in (200, 409):
        raise DicomUploadError(...)
    
    result = resp.json()
    response: dict = {
        "status": "stored",
        "orthanc_id": result.get("ID"),
    }
    
    if report is not None:
        response.update({
            "sop_instance_uid": report.sop_instance_uid,
            "study_instance_uid": report.study_instance_uid,
            "validation": {...}
        })
    
    # NEW: Add normalization details to response
    if normalization_result is not None and normalization_result.modified:
        response["normalization"] = {
            "applied": True,
            "elapsed_ms": normalization_result.elapsed_ms,
            "changes": [
                {
                    "tag": c.tag_keyword,
                    "original": c.original_value,
                    "corrected": c.corrected_value,
                    "rationale": c.rationale,
                    "risk_level": c.risk_level,
                }
                for c in normalization_result.changes
            ]
        }
    else:
        response["normalization"] = {"applied": False}
    
    return response
```

### Step 3.2: Update Audit Logging

**File**: `backend/app/models/audit.py`

Add new audit actions:

```python
class AuditAction(str, Enum):
    # ... existing actions ...
    DICOM_NORMALIZED_PIXEL_SPACING = "DICOM_NORMALIZED_PIXEL_SPACING"
    DICOM_NORMALIZED_TAGS = "DICOM_NORMALIZED_TAGS"
    DICOM_NORMALIZED_PHOTOMETRIC = "DICOM_NORMALIZED_PHOTOMETRIC"
    DICOM_NORMALIZED_CHARSET = "DICOM_NORMALIZED_CHARSET"
```

### Step 3.3: Create Exception Class

**File**: `backend/app/core/exceptions.py`

Add normalization exception:

```python
class DicomNormalizationError(AppException):
    """Raised when DICOM normalization fails."""
    error_code = "DICOM_NORMALIZATION_ERROR"
    http_status_code = 400
```

---

## Phase 3.4: Testing & Polish (Day 4)

### Checklist

- [ ] Run all unit tests (target 95%+ coverage)
- [ ] Run integration tests (STOW-RS workflow)
- [ ] Performance testing: <100ms per instance
- [ ] Gap analysis: `/pdca analyze phase-3-normalizer`
- [ ] Fix any gaps found (target ≥90% match rate)
- [ ] Security review of normalization logic
- [ ] Update documentation

### Test Commands

```bash
# Run all Phase 3 tests
pytest backend/tests/test_dicom_normalizer.py backend/tests/test_stow_rs_normalization.py -v

# Run with coverage report
pytest backend/tests/test_dicom_normalizer.py \
  --cov=app.services.dicom_normalizer \
  --cov-report=html

# Performance test
pytest backend/tests/test_dicom_normalizer.py -k "performance" -v

# Check coverage threshold
pytest backend/tests/test_dicom_normalizer.py --cov=app.services.dicom_normalizer --cov-fail-under=85
```

---

## Key Files to Modify

### New Files

| File | Purpose |
|------|---------|
| `backend/app/services/dicom_normalizer.py` | DicomNormalizer service + data models |
| `backend/tests/test_dicom_normalizer.py` | Unit tests for normalizer |
| `backend/tests/test_stow_rs_normalization.py` | Integration tests for STOW-RS |

### Modified Files

| File | Changes |
|------|---------|
| `backend/app/api/dicomweb.py` | Add `auto_normalize` parameter, integrate normalizer, update response |
| `backend/app/models/audit.py` | Add new AuditAction enum values |
| `backend/app/core/exceptions.py` | Add DicomNormalizationError exception |

### Reference Files (Read-Only)

| File | Purpose |
|------|---------|
| `backend/app/services/dicom_validator.py` | Phase 2 validator (reuse logic for JFIF parsing) |
| `docs/02-design/features/phase-3-normalizer.design.md` | Design specifications |

---

## Testing Checklist

### Unit Tests (Phase 3.1-3.2)

- [ ] Pixel Spacing exact match (300 DPI)
- [ ] Pixel Spacing warning tier (320 DPI, 6.3% mismatch)
- [ ] Pixel Spacing error tier (375 DPI, 25% mismatch)
- [ ] Pixel Spacing missing tag insertion
- [ ] Missing PatientBirthDate default
- [ ] Missing PatientSex default
- [ ] Missing StudyDate current time
- [ ] Preserve existing tag values
- [ ] Do not modify mandatory tags
- [ ] NormalizationResult structure

### Integration Tests (Phase 3.3)

- [ ] STOW-RS with `auto_normalize=false` (baseline)
- [ ] STOW-RS with `auto_normalize=true` (apply corrections)
- [ ] Response includes normalization details
- [ ] Audit log records corrections
- [ ] Post-normalization validation passes
- [ ] Revalidation failure rejects file
- [ ] Backward compatibility (old clients)

### Performance Tests (Phase 3.4)

- [ ] Normalization <100ms for 512x512 image
- [ ] Normalization <100ms for 2048x2048 image
- [ ] Batch normalization throughput
- [ ] Memory usage stable under load

---

## Validation Steps

### After Phase 3.1 Completion

```bash
# Test pixel spacing normalizer
pytest backend/tests/test_dicom_normalizer.py::TestPixelSpacingNormalizer -v

# Verify no regressions
pytest backend/tests/test_dicom_validator.py -v
```

### After Phase 3.2 Completion

```bash
# Test tag normalizer
pytest backend/tests/test_dicom_normalizer.py::TestTagNormalizer -v
```

### After Phase 3.3 Completion

```bash
# Test STOW-RS integration
pytest backend/tests/test_stow_rs_normalization.py -v

# Manual test with curl
curl -X POST https://his.example.org/pacs-api/api/v1/dicomweb/studies?auto_normalize=true \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test-dicom.dcm"
```

### After Phase 3.4 Completion

```bash
# Run gap analysis
/pdca analyze phase-3-normalizer

# View match rate and gaps (target ≥90%)
```

---

## Debugging Tips

### Common Issues

**Issue**: Normalization result has error message  
**Debug**: Check Exception type in dicom_normalizer.py, verify dataset is valid before normalization

**Issue**: Pixel Spacing not calculated  
**Debug**: Verify JFIF density finding is present, check DPI value in finding.details

**Issue**: Post-normalization validation still fails  
**Debug**: Review which tags failed validation, may need additional normalizations

**Issue**: Performance >100ms  
**Debug**: Profile with cProfile, check if re-serialization is bottleneck, consider lazy evaluation

---

## Next Steps

After completing all phases:

1. **Gap Analysis** (Phase 3.4):
   ```bash
   /pdca analyze phase-3-normalizer
   ```
   - Target match rate: ≥90%
   - Review any gaps found
   
2. **Auto-Improvement** (if needed):
   ```bash
   /pdca iterate phase-3-normalizer
   ```
   - Automatically fix gaps
   - Re-run analysis after fixes

3. **Completion Report**:
   ```bash
   /pdca report phase-3-normalizer
   ```
   - Generate final report
   - Archive Phase 3 documents

---

**Ready to Start**: Run `/pdca status` to confirm Phase 3 is in "do" phase, then begin with Step 1.1.
