# PDCA Plan: Phase 2 — Advanced DICOM Validation & DICOMweb Expansion

## Executive Summary

Phase 2 builds on the v1.0/v1.1 foundation (22 API modules, unified error handling, audit logging) to introduce **non-standard DICOM validation** and expand **DICOMweb compliance**. This phase addresses the highest-priority gap from user feedback: detection of invalid/manipulated DICOM data before it enters the archive.

**Target Match Rate**: ≥90%  
**Estimated Scope**: 1,500-2,000 lines of code  
**Priority**: 🔴 CRITICAL (legal/clinical accuracy impact)

---

## Problem Statement

### Current State (v1.0/v1.1)
- ✅ Basic DICOM parsing (pydicom)
- ✅ DIMSE C-ECHO/C-STORE working
- ✅ DICOMweb QIDO-RS/WADO-RS/STOW-RS (v1.1)
- ❌ **No validation of DICOM spec deviations**

### Critical Gap
Real-world DICOM files frequently violate DICOM standard:

1. **JPEG Density (DPI/DPM) Misalignment** ← HIGHEST PRIORITY
   - JFIF header specifies Xdensity/Ydensity
   - DICOM Pixel Spacing specifies different resolution
   - **Impact**: Measurement tools return incorrect values (e.g., 10mm tumor appears as 15mm)
   - **Legal Risk**: Diagnostic error liability
   - **User Request** (from CLAUDE.md): "비표준 DICOM 검증이 매우 중요한 이유"

2. **Malformed DICOM Tags**
   - Missing required tags (PatientID, StudyInstanceUID)
   - Invalid VR (Value Representation) encoding
   - **Impact**: Study cannot be displayed in OHIF viewer

3. **Manufacturer-Specific Extensions**
   - Private tags not in standard (00010, 00030)
   - Non-standard SOP classes
   - **Impact**: Compatibility issues with other systems

---

## Proposed Solution

### 1. Enhanced DICOM Validator (Priority A)

**File**: `backend/app/services/dicom_validator.py` (expand existing)

**Features**:
- ✅ Existing: Basic tag presence, VR format check
- 🆕 New: JPEG density cross-validation
- 🆕 New: Pixel spacing math validation
- 🆕 New: Required tag enforcement
- 🆕 New: Manufacturer extension warnings

**Key Algorithm: JPEG Density Check**
```
JPEG JFIF Header:
  Xdensity, Ydensity (dots per inch or cm)
  
DICOM Pixel Spacing:
  PixelSpacingRow, PixelSpacingColumn (mm per pixel)
  
Formula:
  ExpectedPixelSpacing = 25.4 / JFIFDensity  (if DPI)
  
Tolerance: ±5% (manufacturer variance)
```

**Validation Rules**:
- Rule 1: If JPEG compressed + Pixel Spacing exists → cross-check
- Rule 2: If mismatch > 5% → warning (not error, allow override)
- Rule 3: If mismatch > 20% → error (reject or flag for review)

### 2. Validation Result Reporting (Priority B)

**File**: `backend/app/api/validation.py` (new endpoint)

**Endpoints**:
```
POST /api/v1/validation/study/{study_id}
  → Run validation on existing study
  → Return: { status, warnings, errors, recommendations }

GET /api/v1/validation/study/{study_id}/report
  → Retrieve last validation result
```

**Response Format**:
```json
{
  "study_id": "abc123",
  "validation_date": "2026-05-13T10:30:00Z",
  "status": "warning",  // "ok" | "warning" | "error"
  "issues": [
    {
      "type": "JPEG_DENSITY_MISMATCH",
      "severity": "warning",
      "series_id": "def456",
      "message": "JPEG DPI (300) vs Pixel Spacing (0.08mm) mismatch >5%",
      "expected_dpi": 318,
      "actual_dpi": 300,
      "mismatch_percent": 5.7,
      "recommendation": "Review with radiologist; image may require recalibration"
    }
  ],
  "upload_decision": "accept_with_warning"  // "accept" | "accept_with_warning" | "reject"
}
```

### 3. STOW-RS Upload Integration (Priority B)

**File**: `backend/app/api/dicomweb.py` (modify stow_rs)

**Changes**:
- Pre-upload validation before sending to Orthanc
- Option to reject invalid DICOM via query parameter
- Audit log validation results
- Cache validation status

```
POST /api/v1/studies?validate=strict|warn|off
  validate=strict  → Reject if any errors
  validate=warn    → Accept but log warnings (default)
  validate=off     → No validation (legacy)
```

### 4. DICOMweb Completeness (Priority C)

**Existing** (v1.1):
- QIDO-RS: GET /studies, /studies/{id}/series, /studies/{id}/series/{id}/instances
- WADO-RS: GET /studies/{id}
- STOW-RS: POST /studies

**New in Phase 2**:
- WADO-RS: GET /studies/{id}/series/{id}
- WADO-RS: GET /studies/{id}/series/{id}/instances/{id}
- WADO-RS: GET /studies/{id}/series/{id}/instances/{id}/frames (multiframe)
- WADO-URI: GET /wado?StudyInstanceUID=...&SeriesInstanceUID=... (legacy)

### 5. Normalization Pipeline (Priority C)

**File**: `backend/app/services/dicom_normalizer.py` (new)

**Features**:
- Auto-correct minor DICOM issues (when safe)
- Flag issues requiring manual intervention
- Create audit trail of corrections

**Examples**:
- Normalize Pixel Spacing if JPEG density valid → recalculate
- Auto-add missing PatientBirthDate if unavailable
- Warn on private tags requiring review

---

## Requirements

### Functional Requirements
- FR1: Detect JPEG density vs Pixel Spacing mismatch (tolerance ±5%)
- FR2: Validate all required DICOM tags before upload
- FR3: Return detailed validation report with remediation suggestions
- FR4: Integrate validation into STOW-RS pre-upload workflow
- FR5: Support validation override with audit trail
- FR6: Cache validation results (24-hour TTL)

### Non-Functional Requirements
- NR1: Validation < 500ms per series
- NR2: Support 100+ series per study batch
- NR3: Maintain backward compatibility (validation=off option)
- NR4: Audit log all validation decisions

### Compliance
- Meets DICOM Supplement 142 (Basic Profile) validation requirements
- Complies with 의료법 (Korean Medical Law) accuracy standards
- Supports 개인정보보호법 (PIPA) anonymization with validated data

---

## Implementation Roadmap

### Phase 2.1: JPEG Density Validation (Week 1-2)
1. Extend `DicomValidator` class
   - Add `validate_jpeg_density()` method
   - Extract JFIF metadata, parse Pixel Spacing
   - Calculate tolerance range, return warnings/errors
2. Unit tests (pydicom test files with known densities)
3. Integration test with real Chest X-ray (CR modality)

### Phase 2.2: Validation API & Integration (Week 2-3)
1. Create `/api/v1/validation/study/{id}` endpoint
2. Modify `stow_rs()` to call validator pre-upload
3. Add validation result caching in Redis
4. Audit logging for validation decisions

### Phase 2.3: DICOMweb Expansion (Week 3-4)
1. Add missing WADO-RS endpoints (series-level, instance-level)
2. WADO-URI legacy support
3. Multiframe instance support
4. Additional QIDO-RS filtering parameters

### Phase 2.4: Testing & Polish (Week 4)
1. Gap analysis & auto-iteration
2. Production deployment checklist
3. User documentation

---

## Success Criteria

| Criterion | Target | Validation |
|-----------|--------|-----------|
| JPEG density validation accuracy | >99% | Real test suite |
| API response time (validation) | <500ms | Load test |
| Coverage: Required DICOM tags | 100% | DICOM validator tests |
| DICOMweb endpoint coverage | 8/8 endpoints | OHIF compatibility test |
| Audit logging | 100% decisions | Audit log query |
| Match rate (Design vs Implementation) | ≥90% | Gap detector |

---

## Dependencies & Risks

### Dependencies
- ✅ pydicom (existing)
- ✅ Redis cache (existing, v1.1)
- ✅ FastAPI + AppException (existing, v1.1)
- 🆕 Pillow (for JPEG JFIF parsing) — lightweight

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| JPEG parsing edge cases | Medium | Low | Comprehensive unit tests |
| Performance (density check) | Low | Medium | Cache validation results |
| Backward compatibility break | Low | High | Support `validate=off` option |
| False positives (>20% tolerance) | Medium | Medium | User override with audit trail |

---

## Success Metrics

After Phase 2 completion:

- 🎯 **Validation Accuracy**: 99%+ of invalid DICOM detected
- 🎯 **User Confidence**: Radiology team confident in data quality
- 🎯 **Legal Compliance**: Audit trail of all validation decisions
- 🎯 **Performance**: <500ms validation per study
- 🎯 **DICOMweb**: Full compliance with DICOM standard endpoints
- 🎯 **Code Quality**: 90%+ match rate (design vs implementation)

---

## Deferred Items (Phase 3+)

- Advanced AI-based anomaly detection in DICOM pixel data
- Real-time validation streaming for large batches
- Machine learning model for manufacturer-specific rule prediction
- 3D volumetric validation for CT/MR modalities
- Integration with external DICOM validation services (e.g., DICOM Checker)

---

## References

- DICOM Standard Part 3 (Information Object Definitions)
- DICOM Supplement 142 (Basic Application Level Confidentiality Profile)
- JPEG JFIF Specification (ITU-T T.81)
- Medical Imaging DICOM Best Practices (ACR/NEMA)
- 의료법 (Korean Medical Law) Section 22 (5-year retention, accuracy)

---

## Approval Checklist

- [ ] Requirements reviewed with clinical team
- [ ] Validation algorithm validated with sample DICOM files
- [ ] Risk mitigations approved
- [ ] Resource allocation confirmed
- [ ] Timeline feasibility confirmed
- [ ] Proceed to Design phase

**Plan Status**: 📋 READY FOR DESIGN

---

**Last Updated**: 2026-05-13  
**Next Phase**: Design (detailed specification document)
