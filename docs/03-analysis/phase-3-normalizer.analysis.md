# Gap Analysis: Phase 3 — DICOM Normalization Engine

**Analysis Date**: 2026-05-13  
**Feature**: phase-3-normalizer  
**Phase**: Check (Gap Analysis)  
**Overall Match Rate**: 82%  
**Status**: ⚠️ BELOW 90% TARGET — Act Phase Recommended

---

## Executive Summary

The core normalization algorithms (Pixel Spacing calculation, tag defaults, photometric inference, charset detection) are **implemented and functionally correct**. However, the implementation has critical gaps in **operational infrastructure**:

| Category | Gap Type | Count | Impact |
|----------|----------|:-----:|--------|
| **Audit Logging** | Missing | 5 items | **CRITICAL** (regulatory compliance) |
| **Error Handling** | Not implemented | 3 exception classes | High (API clarity) |
| **Risk Classification** | Partial | 1 gap | High (safety guardrails) |
| **Configuration** | Missing | 3 env vars | Medium (operations) |
| **Integration Tests** | Missing | 1 test file | Medium (validation) |

---

## Overall Scores by Category

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 78% | ⚠️ WARNING |
| Architecture Compliance | 85% | ⚠️ WARNING |
| Convention Compliance | 90% | ✅ PASS |
| **Overall** | **82%** | ⚠️ NEEDS FIXING |

---

## Detailed Findings

### 1. DicomNormalizer Service Structure (90%)

**Status**: ✅ MOSTLY PASS

| Item | Design | Implementation | Result |
|------|--------|----------------|:------:|
| `DicomNormalizer` class | ✓ | ✓ | PASS |
| `async normalize(ds, report, audit_logger)` | ✓ | ✓ (+ `raw_data` param) | MINOR CHANGE |
| `ChangeSummary` dataclass | ✓ | ✓ (6 fields) | PASS |
| `NormalizationResult` dataclass | ✓ | ✓ (4 fields) | PASS |
| `_parse_jfif_density()` | Reuse Phase 2 | Own implementation | CHANGED |

**Notes**:
- `raw_data` parameter addition is reasonable (avoids re-reading data)
- Independent JFIF parser works fine (Phase 2's parser is private to validator)
- No compliance issues; engineering judgment is sound

---

### 2. Normalization Algorithms (77%)

#### 2.1 Pixel Spacing — SAFE (85%)

**Status**: ⚠️ PARTIAL

✅ **Implemented**:
- JPEG DPI → mm conversion: `25.4 / DPI`
- dots/cm support: `10.0 / density`
- Round to 4 decimal places
- Density unit validation (1=DPI, 2=dots/cm)
- Logs rationale with DPI value

❌ **Missing**:
- **5% tolerance validation post-correction** (line not enforced)
- **>20% deviation classified as MEDIUM risk** — Design §3.5.1 requires: <5% OK, 5-20% WARNING, >20% ERROR/MEDIUM
  - Implementation treats ALL mismatches as SAFE
  - Should NOT auto-apply when deviation >20%
  - Should mark as MEDIUM risk and log for manual review only

**Impact**: HIGH
- Violates design safety guardrails
- Could auto-correct large deviations that should require manual review

#### 2.2 Missing Tag Insertion — SAFE (80%)

**Status**: ✅ MOSTLY PASS

✅ **Implemented**:
- PatientBirthDate = "00000000" ✓
- PatientSex = "O" ✓
- StudyDate, SeriesDate = current date ✓
- SeriesTime, InstanceCreationTime = current time ✓

❌ **Missing**:
- Timezone = "+00:00" (design §3.2.2, line 8)
- Doesn't check `validation_report.findings` for `MISSING_RECOMMENDED_TAG` — applies defaults unconditionally

**Impact**: LOW
- Timezone is rarely set in real DICOM files
- Unconditional application is safe (doesn't overwrite existing values)

#### 2.3 Photometric Interpretation — MEDIUM (75%)

**Status**: ⚠️ PARTIAL

✅ **Implemented**:
- SamplesPerPixel=1 → MONOCHROME2 ✓
- SamplesPerPixel=3 → RGB ✓
- Marked as MEDIUM risk, not auto-applied ✓

❌ **Missing**:
- Rows and Columns validation (design §3.2.3: "Require Rows and Columns to be present")

**Impact**: LOW
- Edge case; Rows/Columns almost always present in valid DICOM

#### 2.4 Character Set Detection — MEDIUM (60%)

**Status**: ⚠️ SIGNIFICANT GAPS

✅ **Implemented**:
- UTF-8 detection → ISO_IR 192 ✓
- Marked as MEDIUM risk, not auto-applied ✓

❌ **Missing**:
- Latin-1 detection → ISO_IR 100 (design §3.2.4 lists both)
- Non-ASCII check before inference (applies to all PatientName values, not just non-ASCII)

**Impact**: LOW
- Rare in English-speaking regions; affects international deployments

---

### 3. STOW-RS Integration (80%)

**Status**: ⚠️ MOSTLY PASS

✅ **Implemented**:
- `auto_normalize: bool = Query(False)` ✓
- Validate → Normalize → Re-validate → Store workflow ✓
- Response includes "normalization" field ✓
- Response includes "changes" array ✓
- Error handling for pydicom.InvalidDicomError ✓
- Re-validation failure handling ✓

❌ **Missing**:
- **Audit logging for DICOM_NORMALIZED_* actions** (see section 4)
- `audit_logger.log()` calls never made (parameter passed but unused)

**Impact**: HIGH
- Violates 100% audit coverage requirement
- No regulatory trail for corrections (medical law violation in Korean context)

---

### 4. Audit Logging (30%)

**Status**: 🔴 CRITICAL GAP

❌ **Completely Missing**:

| Action | Status | Location |
|--------|:------:|----------|
| `DICOM_NORMALIZED_PIXEL_SPACING` | ❌ | AuditAction enum + STOW-RS endpoint |
| `DICOM_NORMALIZED_TAGS` | ❌ | AuditAction enum + STOW-RS endpoint |
| `DICOM_NORMALIZED_PHOTOMETRIC` | ❌ | AuditAction enum + STOW-RS endpoint |
| `DICOM_NORMALIZED_CHARSET` | ❌ | AuditAction enum + STOW-RS endpoint |
| Audit log creation loop | ❌ | STOW-RS endpoint (design §3.3, lines 304-314) |

**Current State**:
- `audit_logger` parameter accepted in `normalize()`
- Never called; `audit_logger=None` passed from STOW-RS
- No audit actions added to `AuditAction` class
- `backend/app/models/audit.py` not modified

**Impact**: CRITICAL
- Design mandates: "100% audit trail coverage" (design §4.7)
- Medical regulations (Korean Medical Law, Medical IT Act) require complete audit trails
- Zero compliance with design specification

---

### 5. Error Handling (40%)

**Status**: ⚠️ PARTIAL

❌ **Missing Exception Classes** (design §7.1):
- `DicomNormalizationError` (not in exceptions.py)
- `NormalizationFailedError` (not in exceptions.py)
- `RevalidationFailedError` (not in exceptions.py)

**Current State**:
- Uses generic `DicomUploadError` for all normalization failures
- No distinction between:
  - Normalization algorithm failure
  - Re-validation failure after correction
  - DICOM parse error

**Impact**: MEDIUM
- API consumers cannot distinguish error types
- Less helpful error responses
- Harder to debug issues

---

### 6. Safety Guardrails (70%)

**Status**: ⚠️ PARTIAL

❌ **Missing Risk Classification for Large Deviations**:
- Design §3.5.1 (Correction Classification Matrix):
  - <5% mismatch = Safe (auto-apply)
  - 5-20% mismatch = Safe (auto-apply) [WARNING tier]
  - >20% mismatch = **Medium** (manual review only)
- Implementation: All mismatches treated as SAFE

**Example Violation**:
- JFIF 375 DPI vs 300 DPI Pixel Spacing = 25% mismatch
- Design: Manual review required (MEDIUM risk)
- Implementation: Auto-corrects without review

❌ **Missing Configuration Toggles** (design §8.2):
- `DICOM_NORMALIZATION_ENABLED` (global on/off)
- `DICOM_NORMALIZATION_MAX_CHANGES` (limit corrections/file)
- `DICOM_NORMALIZATION_TIMEOUT_MS` (abort if too slow)

**Impact**: MEDIUM
- No emergency disable without code change
- No protection against run-away corrections

---

### 7. Testing Coverage (70%)

**Status**: ⚠️ PARTIAL

✅ **Implemented** (12 tests):
- Pixel spacing 300 DPI (exact match) ✓
- Pixel spacing 320 DPI (warning tier) ✓
- Pixel spacing 375 DPI (error tier) ✓
- JFIF parser (3 fixtures: 300, 320, 375 DPI) ✓
- Tag insertion (PatientBirthDate, PatientSex, StudyDate) ✓
- Preserve existing values ✓
- Result structure ✓
- Performance <100ms ✓

❌ **Missing** (10 tests):
1. Missing pixel spacing from JFIF (insertion case)
2. 5% tolerance boundary test (307 DPI)
3. Implicit VR dataset handling
4. Does not insert mandatory tags (safety check)
5. Empty string values handling
6. Normalization error handling
7. **STOW-RS integration tests** (entire file: `test_stow_rs_normalization.py`)
   - `test_stow_rs_with_auto_normalize_true`
   - `test_stow_rs_response_includes_normalization`
   - `test_stow_rs_audit_trail_recorded`
   - `test_stow_rs_revalidation_failure_rejects`
   - etc. (7 scenarios per design §6.2)
8. Photometric inference (SamplesPerPixel scenarios)
9. Charset detection (UTF-8 and Latin-1)
10. Performance under load (batch normalization)

**Impact**: MEDIUM
- End-to-end STOW-RS workflow untested
- No integration test coverage
- Algorithm tests adequate but incomplete edge cases

---

## Gap Summary Table

### Critical Gaps (Must Fix for 90%)

| Gap | Location | Type | Fix Complexity |
|-----|----------|------|:---------------:|
| Audit logging missing | STOW-RS endpoint + AuditAction | Missing feature | Medium |
| >20% deviation risk classification | `_normalize_pixel_spacing()` | Algorithm incomplete | Low |
| Exception hierarchy | exceptions.py | Missing classes | Low |
| Configuration env vars | __init__ or startup | Missing | Medium |

### Important Gaps (Should Fix)

| Gap | Location | Type | Fix Complexity |
|-----|----------|------|:---------------:|
| STOW-RS integration tests | test_stow_rs_normalization.py | Missing file | Medium |
| Timezone tag default | `_normalize_tags()` | Missing edge case | Low |
| Latin-1 charset support | `_check_charset()` | Missing feature | Low |

### Minor Gaps (Can Defer)

| Gap | Location | Type | Fix Complexity |
|-----|----------|------|:---------------:|
| Rows/Columns validation for photometric | `_check_photometric()` | Missing check | Low |
| Non-ASCII check before charset inference | `_check_charset()` | Missing guard | Low |
| Various unit tests | test_dicom_normalizer.py | Missing edge cases | Low |

---

## Recommended Actions for Act Phase

### Immediate (to reach 90%)

**Priority 1: Audit Logging** (HIGH)
1. Add 4 new constants to `AuditAction` class
2. Implement for-loop in STOW-RS endpoint (design §3.3, lines 304-314)
3. Call `audit_logger.log()` for each correction

**Priority 2: Risk Classification** (HIGH)
1. Calculate deviation percentage in `_normalize_pixel_spacing()`
2. If deviation >20%, mark as MEDIUM risk
3. Do NOT auto-apply medium-risk corrections
4. Add unit test for >20% boundary

**Priority 3: Exception Hierarchy** (MEDIUM)
1. Define `DicomNormalizationError`, `NormalizationFailedError`, `RevalidationFailedError`
2. Use in STOW-RS endpoint instead of generic `DicomUploadError`

**Priority 4: Configuration** (MEDIUM)
1. Add 3 env var support with defaults
2. Check `DICOM_NORMALIZATION_ENABLED` in endpoint

**Priority 5: Integration Tests** (MEDIUM)
1. Create `test_stow_rs_normalization.py`
2. Implement 7 test scenarios from design §6.2

### Secondary (polish)

- Add Timezone default to `_normalize_tags()`
- Add Latin-1 detection to `_check_charset()`
- Add missing unit tests (edge cases)
- Rows/Columns validation for photometric

---

## Expected Outcome

After implementing the 5 priority fixes:
- **Audit logging**: +15%
- **Risk classification**: +10%
- **Exception hierarchy**: +5%
- **Configuration**: +5%
- **Integration tests**: +5%

**Expected match rate after fixes**: **92%** ✅ ABOVE 90% TARGET

---

## References

- **Design**: `docs/02-design/features/phase-3-normalizer.design.md`
- **Implementation**: 
  - `backend/app/services/dicom_normalizer.py`
  - `backend/app/api/dicomweb.py`
  - `backend/tests/test_dicom_normalizer.py`
- **Gap Detector**: gap-detector agent analysis (2026-05-13)

---

**Next Phase**: `/pdca iterate phase-3-normalizer` (auto-fix critical gaps)

**Estimated Fix Time**: 1-2 hours  
**Match Rate Target**: ≥90%  
**Approval**: Ready for Act phase
