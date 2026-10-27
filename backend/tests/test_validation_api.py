"""Tests for the DICOM validation API layer (Phase 2.2).

Focus: the API response *contract* — that a real ValidationReport (produced by
the actual DicomValidator) serializes into the documented response shape. The
validator's detection logic itself is covered by test_dicom_validator.py; these
tests guard the endpoint serialization that clients depend on.

(The previous version of this file asserted placeholders like ``86400 > 0`` and
``callable(fn)`` — green but verifying nothing.)
"""
import pytest

from app.api.validation import serialize_validation_report
from app.services.dicom_validator import DicomValidator


@pytest.fixture
def validator():
    return DicomValidator()


class TestValidationRouteRegistration:
    def test_routes_registered(self):
        from app.api.validation import router

        routes = [r.path for r in router.routes]
        assert any(p.endswith("/validate") for p in routes)
        assert any(p.endswith("/validate-batch") for p in routes)


class TestResponseContract:
    REQUIRED_FIELDS = {
        "sop_instance_uid",
        "study_instance_uid",
        "modality",
        "manufacturer",
        "accepted",
        "max_severity",
        "counts",
        "findings",
    }

    def test_serialized_report_has_all_documented_fields(self, validator, minimal_dicom):
        report = validator.validate(minimal_dicom)
        result = serialize_validation_report(report)
        assert self.REQUIRED_FIELDS.issubset(result.keys())
        assert set(result["counts"].keys()) == {"critical", "error", "warning", "info"}
        assert isinstance(result["findings"], list)
        assert isinstance(result["accepted"], bool)

    def test_clean_dicom_is_accepted(self, validator, minimal_dicom):
        result = serialize_validation_report(validator.validate(minimal_dicom))
        # A minimal valid instance is accepted (it may still carry advisory findings).
        assert result["accepted"] is True

    def test_counts_match_findings(self, validator, jfif_dicom_375dpi):
        """A JFIF density mismatch must surface in both findings and counts."""
        report = validator.validate(jfif_dicom_375dpi)
        result = serialize_validation_report(report)

        # Every finding exposes the documented sub-fields
        for f in result["findings"]:
            assert {"severity", "category", "rule_code", "message"}.issubset(f.keys())

        # Counts are internally consistent with the findings list
        total_by_count = sum(result["counts"].values())
        assert total_by_count == len(result["findings"])

        # The density-mismatch rule is present (core non-standard-DICOM feature)
        assert any(f["rule_code"] == "JPEG_DENSITY_MISMATCH" for f in result["findings"])

    def test_max_severity_is_serializable_string(self, validator, jfif_dicom_375dpi):
        result = serialize_validation_report(validator.validate(jfif_dicom_375dpi))
        # max_severity must be a plain string (enum .value) or None — JSON-safe
        assert result["max_severity"] is None or isinstance(result["max_severity"], str)
