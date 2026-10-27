# Design: Phase 3 — DICOM Normalization Engine

**Date**: 2026-05-13  
**Phase**: Design (Phase 3)  
**Status**: READY FOR IMPLEMENTATION  
**Author**: AI Assistant (PDCA)

---

## 1. Executive Summary

This design document provides detailed technical specifications for Phase 3 (DICOM Normalization Engine), which extends Phase 2's validation capabilities with automatic correction of detected issues. The system implements a **tiered normalization strategy** that safely corrects low-risk DICOM anomalies while maintaining strict audit trails for compliance.

**Key Design Decisions**:
- **Safety-First**: Only auto-correct 🟢 Safe issues; 🟡 Medium and 🔴 Risky issues require manual review
- **Audit-Driven**: All corrections logged with original/corrected values + rationale
- **Non-Destructive**: Never modify pixel data, clinical measurements, or patient identifiers
- **Backward-Compatible**: Normalization disabled by default (`auto_normalize=false`)

---

## 2. Architecture Overview

### 2.1 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    STOW-RS Upload Handler                   │
│  POST /api/v1/dicomweb/studies?auto_normalize=true          │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────▼────────────┐
         │  DicomValidator        │  ← Phase 2 (detects issues)
         │  .validate(data)       │
         └───────────┬────────────┘
                     │
         ┌───────────▼──────────────────────┐
         │  DicomNormalizer (NEW)           │
         │  .normalize(ds, report)          │
         │  ├─ PixelSpacingNormalizer      │
         │  ├─ TagNormalizer               │
         │  ├─ PhotometricNormalizer       │
         │  └─ CharsetNormalizer           │
         └───────────┬──────────────────────┘
                     │
         ┌───────────▼────────────┐
         │  DicomValidator        │  ← Re-validation (post-fix)
         │  .validate(ds)         │
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │  AuditLogger           │  ← Log all corrections
         │  .log(action, data)    │
         └────────────────────────┘
```

### 2.2 Data Flow

```
Raw DICOM File
    ↓
[Validation] → Findings (critical, error, warning, info)
    ↓
[Check auto_normalize flag]
    ├─ false → Store with warnings (current behavior)
    └─ true → Proceed to normalization
        ↓
    [Categorize findings by severity]
        ├─ SAFE (auto-correct) → Pixel Spacing, default tags
        ├─ MEDIUM (manual review) → PhotometricInterpretation
        └─ RISKY (manual only) → SamplesPerPixel, Rows/Columns
    ↓
    [Apply safe corrections]
        ├─ Recalculate Pixel Spacing from JPEG DPI
        ├─ Insert missing tags with defaults
        ├─ Infer photometric interpretation (if safe)
        └─ Detect/normalize character encoding
    ↓
    [Re-validate dataset]
        ├─ Pass → Store normalized + audit log
        └─ Fail → Reject (even with auto_normalize=true)
    ↓
    [Audit Trail]
        - Original value
        - Corrected value
        - Correction rationale
        - Risk level
```

---

## 3. Detailed Specifications

### 3.1 DicomNormalizer Service

**File**: `backend/app/services/dicom_normalizer.py`  
**Purpose**: Apply safe corrections to DICOM datasets based on validation findings  
**Dependencies**: pydicom, app.services.dicom_validator, app.models.audit

#### Class: DicomNormalizer

```python
class DicomNormalizer:
    """Normalize DICOM datasets based on validation findings."""
    
    async def normalize(
        self,
        ds: Dataset,
        validation_report: ValidationReport,
        audit_logger: AuditLogger | None = None,
    ) -> NormalizationResult:
        """
        Normalize DICOM dataset.
        
        Args:
            ds: pydicom Dataset to normalize
            validation_report: Output from DicomValidator.validate()
            audit_logger: Optional audit logger for tracking corrections
            
        Returns:
            NormalizationResult with:
            - modified: True if any corrections applied
            - changes: List of ChangeSummary objects
            - error: Optional error message if normalization failed
        """
```

#### Output Model: NormalizationResult

```python
@dataclass
class ChangeSummary:
    """Record of a single correction applied."""
    tag_keyword: str  # e.g., "PixelSpacing"
    original_value: str | None
    corrected_value: str
    rationale: str  # e.g., "Calculated from JPEG 300 DPI"
    risk_level: str  # "safe", "medium", "risky"
    category: str  # "pixel_spacing", "tag", "photometric", "charset"

@dataclass
class NormalizationResult:
    modified: bool
    changes: list[ChangeSummary]
    error: str | None = None
```

### 3.2 Normalization Algorithms

#### 3.2.1 Pixel Spacing Normalization (SAFE)

**Trigger**: 
- Finding with `rule_code == "JPEG_DENSITY_MISMATCH"`
- AND severity in [WARNING, ERROR]

**Algorithm**:
```
1. Extract JPEG DPI from JFIF header (via DicomValidator._parse_jfif_density)
2. Convert DPI to mm: pixel_spacing_mm = 25.4 / dpi
3. Round to 4 decimal places
4. If ds.PixelSpacing exists but wrong:
   - Store original value
   - Set ds.PixelSpacing = [calculated, calculated]
   - Log change with risk="safe"
5. If ds.PixelSpacing missing but JFIF found:
   - Insert PixelSpacing tag
   - Log change with risk="safe"
6. Validate result: abs(calculated - original) < 5% tolerance
```

**Safety Checks**:
- Only apply if JFIF density unit is valid (1 = DPI, 2 = dots/cm)
- Verify result tolerance is < 5% (matching Phase 2 "OK" tier)
- Never modify if no JFIF header present
- Log all intermediate values for audit trail

#### 3.2.2 Missing Tag Normalization (SAFE)

**Trigger**: Finding with `rule_code == "MISSING_RECOMMENDED_TAG"`

**Algorithm**:

| Tag | Default Value | Rationale | Condition |
|-----|---------------|-----------|-----------|
| `PatientBirthDate` | `"00000000"` | Unknown DoB (DICOM standard) | If missing |
| `PatientSex` | `"O"` | Other (DICOM standard) | If missing |
| `StudyDate` | Current date (YYYYMMDD) | Use upload time if missing | If StudyDate missing |
| `SeriesDate` | Current date (YYYYMMDD) | Use upload time if missing | If SeriesDate missing |
| `SeriesTime` | Current time (HHMMSS) | Use upload time if missing | If SeriesTime missing |
| `ContentDate` | Current date (YYYYMMDD) | Use upload time if missing | If ContentDate missing |
| `InstanceCreationDate` | Current date (YYYYMMDD) | Use upload time if missing | If missing |
| `InstanceCreationTime` | Current time (HHMMSS) | Use upload time if missing | If missing |
| `Timezone` | `"+00:00"` | UTC (neutral) | If missing |

**Safety Rules**:
- Only insert **recommended** tags (Type 2 in DICOM standard)
- Never modify **mandatory** tags (Type 1)
- Never insert fictitious patient/study identifiers
- Always use safe defaults (unknown, neutral, current time)

#### 3.2.3 Photometric Interpretation Normalization (MEDIUM)

**Trigger**: Finding with `rule_code == "MISSING_PHOTOMETRIC_INTERPRETATION"`

**Algorithm**:
```
1. Check SamplesPerPixel:
   - If SamplesPerPixel == 1:
     → PhotometricInterpretation = "MONOCHROME2"
   - If SamplesPerPixel == 3:
     → PhotometricInterpretation = "RGB"
   - Else: Cannot infer safely → Skip
2. Verify against Rows/Columns (must be present)
3. Log as risk="medium" (inference could be wrong)
```

**Safety Rules**:
- Only infer if SamplesPerPixel is explicit and valid
- Require Rows and Columns to be present
- Mark as MEDIUM risk (requires manual review before auto-apply)
- Do NOT auto-apply MEDIUM corrections; return in changes list for admin review

#### 3.2.4 Character Set Normalization (MEDIUM)

**Trigger**: Finding with `rule_code == "MISSING_CHARSET"` AND non-ASCII patient name detected

**Algorithm**:
```
1. Detect byte patterns in PatientName:
   - If valid UTF-8: infer SpecificCharacterSet = "ISO_IR 192" (UTF-8)
   - If valid Latin-1: infer SpecificCharacterSet = "ISO_IR 100"
   - Else: Cannot infer → Skip
2. Log as risk="medium"
```

**Safety Rules**:
- Only infer if PatientName contains non-ASCII bytes
- Require valid UTF-8 or Latin-1 validation
- Mark as MEDIUM risk (encoding inference could be wrong)
- Do NOT auto-apply; return for manual review

### 3.3 STOW-RS Integration

**File**: `backend/app/api/dicomweb.py` (modify `stow_rs` endpoint)

**New Query Parameter**:
```python
auto_normalize: bool = Query(False),
    # Docstring: "Automatically correct detected DICOM issues (safe corrections only)"
```

**New Flow**:
```python
@router.post("/studies")
async def stow_rs(
    ...
    auto_normalize: bool = Query(False),
):
    data = await file.read()
    
    # Phase 2: Validate
    report = validator.validate(data)
    if validate == "strict" and not report.accepted:
        raise DicomValidationError(...)
    
    # NEW: Phase 3: Normalize (optional)
    if auto_normalize:
        ds = pydicom.dcmread(io.BytesIO(data), force=True)
        result = await normalizer.normalize(ds, report, audit_logger)
        
        if result.error:
            raise DicomNormalizationError(...)
        
        # Re-serialize normalized dataset
        buf = io.BytesIO()
        ds.save_as(buf)
        data = buf.getvalue()
        
        # Re-validate post-normalization
        report = validator.validate(data)
        if not report.accepted:
            raise DicomValidationError(
                message="DICOM still invalid after normalization",
                details={"findings": [...]}
            )
    
    # Store in Orthanc
    resp = await request.app.state.http_client.post(...)
    
    # Log all corrections
    if auto_normalize and result.changes:
        for change in result.changes:
            audit_logger.log(
                action=f"DICOM_NORMALIZED_{change.category.upper()}",
                entity_type="DicomFile",
                details={
                    "tag": change.tag_keyword,
                    "original": change.original_value,
                    "corrected": change.corrected_value,
                    "risk_level": change.risk_level,
                }
            )
```

**Example Usage**:
```bash
# Without normalization (current behavior)
curl -X POST https://his.example.org/pacs-api/api/v1/dicomweb/studies \
  -F "file=@study.dcm"
# Result: Upload accepted with warnings in response

# With safe auto-correction
curl -X POST https://his.example.org/pacs-api/api/v1/dicomweb/studies?auto_normalize=true \
  -F "file=@study.dcm"
# Result: Auto-corrects safe issues (Pixel Spacing, missing tags) before storing
```

### 3.4 Audit Logging

**File**: `backend/app/models/audit.py` (extend AuditAction enum)

**New Actions**:
```python
class AuditAction(str, Enum):
    # ... existing actions ...
    DICOM_NORMALIZED_PIXEL_SPACING = "DICOM_NORMALIZED_PIXEL_SPACING"
    DICOM_NORMALIZED_TAGS = "DICOM_NORMALIZED_TAGS"
    DICOM_NORMALIZED_PHOTOMETRIC = "DICOM_NORMALIZED_PHOTOMETRIC"
    DICOM_NORMALIZED_CHARSET = "DICOM_NORMALIZED_CHARSET"
```

**Audit Record Example**:
```json
{
  "action": "DICOM_NORMALIZED_PIXEL_SPACING",
  "entity_type": "DicomFile",
  "entity_id": "study-uid:1.2.3.4",
  "performed_by": "system",
  "timestamp": "2026-05-13T14:32:00Z",
  "details": {
    "tag": "PixelSpacing",
    "original_value": "[0.08934, 0.08934]",
    "corrected_value": "[0.0847, 0.0847]",
    "rationale": "Calculated from JPEG JFIF 300 DPI header",
    "risk_level": "safe",
    "confidence": 0.99
  }
}
```

### 3.5 Safety Guardrails

#### 3.5.1 Correction Classification Matrix

| Category | Rule Code | Risk Level | Auto-Apply | Manual Review | Never Apply |
|----------|-----------|------------|-----------|---------------|-------------|
| Pixel Spacing | JPEG_DENSITY_MISMATCH (<5%) | Safe | ✅ | - | - |
| Pixel Spacing | JPEG_DENSITY_MISMATCH (5-20%) | Safe | ✅ | - | - |
| Pixel Spacing | JPEG_DENSITY_MISMATCH (>20%) | Medium | ❌ | ✅ | - |
| Missing Tags | MISSING_RECOMMENDED_TAG | Safe | ✅ | - | - |
| Photometric | MISSING_PHOTOMETRIC_INTERP | Medium | ❌ | ✅ | - |
| Character Set | MISSING_CHARSET | Medium | ❌ | ✅ | - |
| Mandatory Tags | MISSING_MANDATORY_TAG | Risky | ❌ | ❌ | ✅ |
| Pixel Data | INVALID_PIXEL_DATA | Risky | ❌ | ❌ | ✅ |

#### 3.5.2 Validation Gates

1. **Pre-Normalization**: Validate input dataset (Phase 2)
2. **During Normalization**: Apply only safe corrections
3. **Post-Normalization**: Re-validate dataset
   - If still invalid → Reject (fail safely)
   - If valid → Store with audit trail
4. **Error Handling**:
   - Normalization errors → Return error response (do not store)
   - Validation errors → Reject regardless of auto_normalize flag

#### 3.5.3 Disable Option

Admins can disable normalization globally:
```bash
# In .env or config
DICOM_NORMALIZATION_ENABLED=false
```

OR per-upload:
```bash
curl ... ?auto_normalize=false  # Default; no normalization
```

---

## 4. Data Models

### 4.1 NormalizationResult (Output)

```python
from dataclasses import dataclass

@dataclass
class ChangeSummary:
    tag_keyword: str  # DICOM tag keyword (e.g., "PixelSpacing")
    original_value: str | None  # Original value (or None if tag was missing)
    corrected_value: str  # New value after normalization
    rationale: str  # Human-readable explanation
    risk_level: str  # Enum: "safe", "medium", "risky"
    category: str  # Enum: "pixel_spacing", "tag", "photometric", "charset"

@dataclass
class NormalizationResult:
    modified: bool  # True if any corrections applied
    changes: list[ChangeSummary]  # List of corrections made
    error: str | None  # Error message if normalization failed
    elapsed_ms: float  # Processing time
```

### 4.2 API Response

```json
POST /api/v1/dicomweb/studies?auto_normalize=true
↓
{
  "status": "stored",
  "orthanc_id": "abc123def456",
  "sop_instance_uid": "1.2.3.4.5.6.7.8.9",
  "study_instance_uid": "1.2.3.4.5",
  "normalization": {
    "applied": true,
    "changes": [
      {
        "tag": "PixelSpacing",
        "original": "[0.08934, 0.08934]",
        "corrected": "[0.0847, 0.0847]",
        "rationale": "Calculated from JPEG 300 DPI",
        "risk_level": "safe"
      },
      {
        "tag": "PatientBirthDate",
        "original": null,
        "corrected": "00000000",
        "rationale": "Default for unknown DoB",
        "risk_level": "safe"
      }
    ]
  },
  "validation": {
    "accepted": true,
    "findings": []
  }
}
```

---

## 5. Implementation Order

### Phase 3.1: Pixel Spacing Normalizer (Days 1-2)

1. **File**: `backend/app/services/dicom_normalizer.py` (create)
   - Implement `DicomNormalizer` class
   - Implement `_normalize_pixel_spacing(ds, report)` method
   - Implement `_parse_jfif_density(ds)` (leverage Phase 2 code)

2. **Algorithm**:
   - Extract JPEG DPI from JFIF header
   - Convert to mm: 25.4 / DPI
   - Compare with current PixelSpacing (if present)
   - Apply correction if tolerance < 5%

3. **Tests** (`backend/tests/test_dicom_normalizer.py`):
   - `test_pixel_spacing_exact_match_300dpi` - No change
   - `test_pixel_spacing_warning_320dpi` - Corrects 6.3% mismatch
   - `test_pixel_spacing_error_375dpi` - Corrects 25% mismatch
   - `test_pixel_spacing_missing_tag` - Inserts from JPEG
   - `test_normalization_result_structure` - Verify output format

### Phase 3.2: Tag Normalizer (Days 2-3)

1. **File**: `backend/app/services/dicom_normalizer.py` (extend)
   - Implement `_normalize_tags(ds, report)` method
   - Insert defaults for missing recommended tags
   - Use datetime.utcnow() for StudyDate/SeriesDate/Time defaults

2. **Tests**:
   - `test_insert_patient_birth_date_default` - "00000000" if missing
   - `test_insert_study_date_from_upload_time` - Use current date
   - `test_insert_patient_sex_default` - "O" if missing
   - `test_preserve_existing_tag_values` - Don't overwrite valid tags

### Phase 3.3: STOW-RS Integration (Days 3-4)

1. **File**: `backend/app/api/dicomweb.py` (modify `stow_rs`)
   - Add `auto_normalize: bool = Query(False)` parameter
   - Call `normalizer.normalize(ds, report)` if auto_normalize=True
   - Re-serialize and re-validate post-normalization
   - Update response to include normalization details

2. **File**: `backend/app/models/audit.py` (extend)
   - Add new AuditAction enum values
   - Ensure audit_logger captures all corrections

3. **Tests**:
   - `test_stow_rs_without_normalization` - Baseline (existing behavior)
   - `test_stow_rs_with_auto_normalize_true` - Apply corrections
   - `test_stow_rs_with_auto_normalize_false` - Disable normalization
   - `test_stow_rs_normalization_audit_trail` - Verify logging

### Phase 3.4: Testing & Polish (Days 4)

1. **Gap Analysis** - Run `/pdca analyze phase-3-normalizer`
   - Compare Design vs Implementation (target ≥90% match rate)
   - Identify missing features

2. **Security Review**:
   - Verify no pixel data modification
   - Verify no clinical data modification
   - Verify audit trail completeness

3. **Performance Testing**:
   - Measure normalization time (target <100ms)
   - Test with large datasets (2048x2048 images)
   - Verify cache behavior (if any caching added)

---

## 6. Testing Strategy

### 6.1 Unit Tests

**File**: `backend/tests/test_dicom_normalizer.py`

```python
class TestPixelSpacingNormalizer:
    """Test pixel spacing correction algorithm."""
    def test_exact_match_no_change(self, jfif_300dpi_dicom)
    def test_warning_tier_applies_correction(self, jfif_320dpi_dicom)
    def test_error_tier_applies_correction(self, jfif_375dpi_dicom)
    def test_missing_pixel_spacing_from_jfif(self, jfif_300dpi_no_spacing)
    def test_tolerance_5_percent(self, jfif_307dpi_dicom)
    def test_handles_implicit_vr_dataset(self, implicit_vr_dicom)

class TestTagNormalizer:
    """Test missing tag insertion."""
    def test_insert_patient_birth_date(self, dicom_missing_dob)
    def test_insert_patient_sex(self, dicom_missing_sex)
    def test_insert_study_date_uses_current(self, dicom_missing_study_date)
    def test_preserve_existing_values(self, complete_dicom)
    def test_does_not_insert_mandatory_tags(self, dicom_missing_patient_id)
    def test_handles_empty_string_values(self, dicom_empty_values)

class TestNormalizationResult:
    """Test output data structures."""
    def test_result_contains_changes(self, normalized_result)
    def test_change_summary_fields(self, change_summary)
    def test_audit_fields_present(self, normalized_result)

class TestNormalizationIntegration:
    """Integration tests with DicomValidator."""
    def test_normalize_then_revalidate_passes(self, invalid_spacing_dicom)
    def test_normalization_error_on_still_invalid(self, severely_broken_dicom)
    def test_performance_under_100ms(self, large_dicom_2048x2048)
```

### 6.2 Integration Tests

**File**: `backend/tests/test_stow_rs_normalization.py`

```python
class TestStowRsNormalization:
    """Integration tests for STOW-RS with normalization."""
    def test_auto_normalize_false_baseline(self, client, invalid_spacing_dicom)
    def test_auto_normalize_true_corrects_spacing(self, client, invalid_spacing_dicom)
    def test_auto_normalize_applies_safe_corrections(self, client, incomplete_dicom)
    def test_response_includes_changes(self, client, invalid_dicom)
    def test_audit_log_records_all_corrections(self, client, db, invalid_dicom)
    def test_revalidation_failure_rejects_file(self, client, irreparable_dicom)
    def test_backward_compatibility_no_auto_normalize(self, client, old_client_version)
```

### 6.3 Test Fixtures

Extend `backend/tests/conftest.py`:

```python
@pytest.fixture
def dicom_invalid_spacing():
    """DICOM with 375 DPI JFIF but 0.0847 Pixel Spacing (25% mismatch)."""

@pytest.fixture
def dicom_missing_patient_dob():
    """Valid DICOM without PatientBirthDate."""

@pytest.fixture
def dicom_missing_study_date():
    """Valid DICOM without StudyDate."""

@pytest.fixture
def irreparable_dicom():
    """DICOM with critical mandatory tag missing (cannot be auto-corrected)."""
```

---

## 7. Error Handling

### 7.1 Exception Hierarchy

```python
class DicomNormalizationError(AppException):
    """Base exception for normalization errors."""
    error_code = "DICOM_NORMALIZATION_ERROR"

class NormalizationFailedError(DicomNormalizationError):
    """Normalization algorithm failed."""
    error_code = "NORMALIZATION_FAILED"

class RevalidationFailedError(DicomNormalizationError):
    """Post-normalization validation failed."""
    error_code = "REVALIDATION_FAILED"
```

### 7.2 Error Response

```json
{
  "error": {
    "code": "DICOM_NORMALIZATION_ERROR",
    "message": "Failed to normalize DICOM",
    "request_id": "req-abc123",
    "details": {
      "phase": "post_normalization_validation",
      "reason": "PixelSpacing still invalid after correction",
      "findings": [
        {
          "severity": "critical",
          "rule_code": "INVALID_PIXEL_SPACING",
          "message": "..."
        }
      ]
    }
  }
}
```

---

## 8. Deployment Considerations

### 8.1 Backward Compatibility

- Default: `auto_normalize=false` (no behavior change)
- Existing clients: Continue working without modification
- New clients: Can opt-in via query parameter

### 8.2 Configuration

```bash
# .env
DICOM_NORMALIZATION_ENABLED=true  # Global enable/disable
DICOM_NORMALIZATION_MAX_CHANGES=10  # Limit corrections per file
DICOM_NORMALIZATION_TIMEOUT_MS=1000  # Abort if takes too long
```

### 8.3 Rollback Plan

If issues detected post-deployment:
1. Set `DICOM_NORMALIZATION_ENABLED=false`
2. Restart FastAPI service
3. All subsequent uploads: normalization skipped
4. Pre-normalized files: remain in Orthanc (not reverted)

### 8.4 Monitoring

- Track normalization success rate: `(applied / uploaded) * 100%`
- Monitor performance: Measure normalization time per instance
- Alert on: Revalidation failures, audit trail gaps
- Dashboard metrics: Changes applied by category, risk levels

---

## 9. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Normalization accuracy | 99% | Real test DICOM suite (>100 files) |
| Pixel Spacing calculation | ±0.5% tolerance | Compare calculated vs reference |
| Performance | <100ms/instance | Load test with 1000 files |
| Audit coverage | 100% | Verify all corrections logged |
| Match rate (Design vs Implementation) | ≥90% | Gap detector analysis |
| Safe/Medium correction ratio | 95% safe, 5% medium | Classification accuracy |
| Backward compatibility | 100% | Existing clients pass tests |
| Error handling | All cases covered | Error scenario testing |

---

## 10. Known Limitations & Deferred

### 10.1 Current Scope (In Design)

- ✅ Pixel Spacing from JPEG (safe)
- ✅ Missing recommended tags (safe)
- ⏳ Photometric interpretation (medium, manual review only)
- ⏳ Character set detection (medium, manual review only)

### 10.2 Phase 4+ (Deferred)

- Advanced AI-based anomaly detection
- Supplier-specific normalization rules
- Batch normalization with progress tracking
- Manual correction UI for medium-risk items
- Integration with DICOM standardization services
- Automatic photometric normalization (currently manual review)

---

## 11. Design Review Checklist

- [ ] Architecture supports concurrent normalizations
- [ ] All exception paths tested
- [ ] Audit trail covers 100% of corrections
- [ ] Safety guardrails prevent risky corrections
- [ ] Backward compatibility confirmed
- [ ] Performance targets achievable
- [ ] Error messages are actionable
- [ ] Documentation complete
- [ ] Ready for implementation

---

## References

- Phase 3 Plan: `docs/01-plan/features/phase-3-normalizer.plan.md`
- Phase 2 Validator: `backend/app/services/dicom_validator.py`
- DICOM Standard Part 3: Information Object Definitions
- JPEG JFIF Specification: ITU-T T.81

---

**Design Status**: ✅ READY FOR IMPLEMENTATION  
**Next Step**: `/pdca do phase-3-normalizer` (start implementation)
