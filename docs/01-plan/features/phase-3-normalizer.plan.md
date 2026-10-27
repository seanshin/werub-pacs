# PDCA Plan: Phase 3 — DICOM Normalization Engine

## Executive Summary

Phase 3 builds on the Phase 2 DICOM validation foundation to introduce **automatic correction of non-standard DICOM files**. This phase addresses the complementary gap: detection-only (Phase 2) → detection-and-fix (Phase 3).

**Target Match Rate**: ≥90%  
**Estimated Scope**: 1,000-1,500 lines of code  
**Priority**: 🟡 HIGH (improves data quality for downstream viewers/AI)

---

## Problem Statement

### Current State (Phase 2 Complete)
- ✅ Detects JPEG density mismatches
- ✅ Identifies missing/malformed DICOM tags
- ✅ Validates Pixel Spacing consistency
- ❌ **No automatic correction of detected issues**

### Critical Gap

Real-world DICOM files often have **repairable non-standard issues**:

1. **Pixel Spacing Calculation from JPEG Density**
   - JFIF header has correct DPI, but DICOM Pixel Spacing is missing/wrong
   - Can safely recalculate: `PixelSpacing = 25.4 / DPI`
   - **Impact**: Enables measurement tools in viewers that require Pixel Spacing
   - **Risk**: Low (mathematical derivation, not data modification)

2. **Missing Recommended Tags**
   - `PatientBirthDate` missing → can default to "00000000" (unknown)
   - `StudyDate` missing → can use current date or file metadata
   - **Impact**: Enables queries and demographic reports
   - **Risk**: Low (defaults only, no clinical data modified)

3. **Photometric Interpretation Normalization**
   - Some JPEG files omit PhotometricInterpretation
   - Can infer from SamplesPerPixel + Rows/Columns
   - **Impact**: OHIF viewer compatibility
   - **Risk**: Medium (if inference wrong, image appears corrupted)

4. **Character Set Normalization**
   - Non-ASCII patient names without SpecificCharacterSet
   - Can infer UTF-8 from byte pattern
   - **Impact**: International deployments
   - **Risk**: Medium (encoding errors possible)

---

## Proposed Solution

### 1. DicomNormalizer Service (Priority A)

**File**: `backend/app/services/dicom_normalizer.py` (new)

**Features**:
- 🆕 Pixel Spacing calculator from JPEG density
- 🆕 Default value insertion for missing recommended tags
- 🆕 Photometric interpretation inference
- 🆕 Character set detection & normalization
- 🆕 Audit trail of all corrections

**Key Algorithms**:

```python
class DicomNormalizer:
    async def normalize(self, ds: Dataset, validation_report: ValidationReport) -> NormalizationResult:
        """
        Normalize DICOM based on validation findings.
        Only corrects safe, low-risk issues.
        Returns audit trail of changes.
        """
```

### 2. Normalization Integration (Priority B)

**File**: `backend/app/api/dicomweb.py` (modify stow_rs)

**Changes**:
- Pre-validation: run DicomValidator
- Post-validation (if issues): run DicomNormalizer
- Post-normalization: re-validate
- If still invalid: reject; else: store
- Log all normalization steps to audit trail

```python
@router.post("/studies")
async def stow_rs(
    ...,
    auto_normalize: bool = Query(False),  # New param
):
    """
    STOW-RS with optional auto-normalization.
    auto_normalize=true → attempt to fix detected issues
    auto_normalize=false → reject if validation fails
    """
```

### 3. Normalization Audit Log (Priority B)

**File**: `backend/app/models/audit.py` (extend)

**New Audit Actions**:
- `DICOM_NORMALIZED_PIXEL_SPACING`
- `DICOM_NORMALIZED_TAGS`
- `DICOM_NORMALIZED_CHARSET`

**Logged Data**:
- Original value
- Corrected value
- Correction rationale
- Risk level (safe/medium/risky)

### 4. Safety Guardrails (Priority C)

**Policy**:
- Only correct **safe** issues (Pixel Spacing, missing optional tags)
- Never modify **clinical data** (patient ID, study date, measurements)
- Always log corrections with reasoning
- Provide `normalize=off` option to skip normalization
- Manual review required for **medium-risk** corrections (via admin UI)

**Severity Levels**:
- 🟢 Safe: Can be auto-corrected (Pixel Spacing from JPEG, default tags)
- 🟡 Medium: Needs user review (PhotometricInterpretation, CharacterSet)
- 🔴 Risky: Manual-only (Modality, SamplesPerPixel, Rows/Columns)

---

## Requirements

### Functional Requirements
- FR1: Calculate Pixel Spacing from JPEG density (tolerance ±5%)
- FR2: Detect missing recommended tags and insert defaults
- FR3: Infer PhotometricInterpretation from image dimensions
- FR4: Detect and normalize character encoding
- FR5: Log all normalization actions to audit trail
- FR6: Support `auto_normalize` parameter on STOW-RS endpoint
- FR7: Provide manual override for medium-risk corrections

### Non-Functional Requirements
- NR1: Normalization < 100ms per instance
- NR2: 100% audit trail coverage
- NR3: Backward compatibility (auto_normalize defaults to false)
- NR4: No modification of clinical/measurement data

### Compliance
- Aligns with DICOM Supplement 142 (normalization best practices)
- Maintains 의료법 (Korean Medical Law) audit requirements
- Enables 개인정보보호법 compliance through transparent corrections

---

## Implementation Roadmap

### Phase 3.1: Pixel Spacing Normalizer (Days 1-2)
1. Implement `calculate_pixel_spacing_from_jpeg()` algorithm
2. Integrate with DicomNormalizer class
3. Add safety checks (±5% tolerance)
4. Unit tests (5+ test cases)

### Phase 3.2: Tag Normalizer (Days 2-3)
1. Define default values for recommended tags
2. Implement safe insertion logic
3. Add timestamp-based defaults for StudyDate/SeriesDate
4. Unit tests (8+ test cases)

### Phase 3.3: STOW-RS Integration (Days 3-4)
1. Add `auto_normalize` query parameter
2. Modify upload flow: validate → normalize → re-validate → store
3. Audit logging for all corrections
4. Integration tests

### Phase 3.4: Testing & Polish (Days 4)
1. Gap analysis & auto-iteration
2. Security review of normalization logic
3. Production deployment checklist

---

## Success Criteria

| Criterion | Target | Validation |
|-----------|--------|-----------|
| Pixel Spacing calculation accuracy | 99% | Real JPEG test suite |
| Normalization speed | <100ms | Performance test |
| Audit coverage | 100% | Audit log verification |
| Match rate (Design vs Implementation) | ≥90% | Gap detector |
| Safe vs risky corrections | 95% safe, 5% medium | Classification accuracy |

---

## Dependencies & Risks

### Dependencies
- ✅ DicomValidator (Phase 2, complete)
- ✅ FastAPI + AppException (Phase 2, complete)
- ✅ AuditLogger (Phase 2, complete)
- 🆕 PIL/Pillow for JPEG header parsing (optional, for photometric inference)

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Over-correction (fixing too much) | Medium | High | Strict safe/medium/risky classification; default to off |
| Normalization breaking image | Low | High | Comprehensive test suite; never modify pixel data |
| Performance regression | Low | Medium | Cache normalization results |
| Audit trail explosion | Medium | Medium | Compress batch operations in single log entry |

---

## Success Metrics

After Phase 3 completion:

- 🎯 **Data Quality**: >95% of Phase 2 findings auto-corrected (safe issues only)
- 🎯 **User Experience**: OHIF viewer compatibility improved for >80% of incoming DICOM
- 🎯 **Safety**: Zero unintended clinical data modifications
- 🎯 **Performance**: <100ms normalization per instance
- 🎯 **Audit**: 100% traceability of all corrections

---

## Deferred Items (Phase 4+)

- Advanced AI-based anomaly correction
- Supplier-specific normalization rules
- Batch normalization with progress tracking
- Manual correction UI for medium-risk items
- Integration with DICOM standardization services

---

## References

- DICOM Standard Part 3 (Information Object Definitions)
- DICOM Supplement 142 (Normalization Best Practices)
- JPEG JFIF Specification (ITU-T T.81)
- Medical Imaging Data Quality Standards (ACR/NEMA)

---

## Approval Checklist

- [ ] Requirements reviewed with clinical team
- [ ] Normalization algorithms validated with sample DICOM files
- [ ] Safety guardrails approved
- [ ] Risk mitigations reviewed
- [ ] Resource allocation confirmed
- [ ] Timeline feasibility confirmed
- [ ] Proceed to Design phase

**Plan Status**: 📋 READY FOR DESIGN

---

**Last Updated**: 2026-05-13  
**Next Phase**: Design (detailed specification document)
