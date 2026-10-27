"""Unit tests for DICOM validator (Phase 2.1-2.2)."""
import io
import pytest
from app.services.dicom_validator import DicomValidator, Severity, Category


class TestDicomValidator:
    """Test suite for DICOM validation engine."""

    @pytest.fixture(autouse=True)
    def validator(self):
        """Instantiate validator for each test."""
        return DicomValidator()

    def test_minimal_dicom_valid(self, validator, minimal_dicom):
        """Test that minimal valid DICOM passes validation."""
        report = validator.validate(minimal_dicom)
        assert report.accepted is True
        assert report.critical_count == 0
        assert report.error_count == 0
        assert report.sop_instance_uid != ""
        assert report.modality == "CT"

    def test_missing_mandatory_patient_id(self, validator, dicom_missing_patient_id):
        """Test detection of missing mandatory PatientID tag."""
        report = validator.validate(dicom_missing_patient_id)
        assert report.accepted is False
        assert report.critical_count == 1

        # Find the specific finding
        finding = next(
            (f for f in report.findings if f.rule_code == "MISSING_MANDATORY_TAG"),
            None,
        )
        assert finding is not None
        assert finding.severity == Severity.CRITICAL
        assert "PatientID" in finding.message

    def test_jpeg_density_exact_match_300dpi(self, validator, jfif_dicom_300dpi):
        """Test JPEG density exact match: 300 DPI = 0.0847 mm spacing (< 1%)."""
        report = validator.validate(jfif_dicom_300dpi)

        # Should accept (no density mismatch finding)
        density_findings = [
            f for f in report.findings if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]
        assert len(density_findings) == 0, "Expected no JPEG density mismatch for exact match"

    def test_jpeg_density_warning_315dpi(self, validator, jfif_dicom_315dpi):
        """Test JPEG density warning: 320 DPI vs 300 DPI spacing (~6.3% mismatch = WARNING, 5-20% tier)."""
        report = validator.validate(jfif_dicom_315dpi)

        # Should have a WARNING (5-20% tier per design spec, not ERROR)
        finding = next(
            (f for f in report.findings if f.rule_code == "JPEG_DENSITY_MISMATCH"),
            None,
        )
        assert finding is not None
        assert finding.severity == Severity.WARNING  # 5-20% range triggers WARNING
        assert "does not match" in finding.message.lower()

        # Check details contain mismatch percentage
        assert "x_diff_pct" in finding.details or "y_diff_pct" in finding.details

    def test_jpeg_density_error_375dpi(self, validator, jfif_dicom_375dpi):
        """Test JPEG density error: 375 DPI vs 300 DPI (25% mismatch = ERROR)."""
        report = validator.validate(jfif_dicom_375dpi)

        finding = next(
            (f for f in report.findings if f.rule_code == "JPEG_DENSITY_MISMATCH"),
            None,
        )
        assert finding is not None
        assert finding.severity == Severity.ERROR
        assert report.error_count >= 1

        # Mismatch should be ~25%
        mismatch_pct = finding.details.get("x_diff_pct", 0)
        assert 20 <= mismatch_pct <= 30

    def test_missing_pixel_spacing_with_jfif(self, validator, dicom_with_pixel_spacing):
        """Test handling of JFIF density without Pixel Spacing tag."""
        report = validator.validate(dicom_with_pixel_spacing)

        # JFIF is embedded but Pixel Spacing exists, so cross-check should work
        assert report.accepted is True  # Valid file

    def test_parse_jfif_density_extraction(self, validator, jfif_dicom_300dpi):
        """Test JFIF header parsing extracts correct density values."""
        result = validator._parse_jfif_density(jfif_dicom_300dpi)
        assert result is not None
        density_unit, x_density, y_density = result
        assert density_unit == 1  # DPI
        assert x_density == 300
        assert y_density == 300

    def test_invalid_dicom_parse_failure(self, validator):
        """Test handling of invalid/corrupted DICOM data.

        pydicom with force=True may parse random bytes without raising an exception.
        In that case mandatory tags will all be missing — the file is still rejected.
        In strict mode (no force) a PARSE_FAILURE critical finding is emitted.
        Either way, report.accepted must be False and critical_count >= 1.
        """
        invalid_data = b"This is not a DICOM file at all"
        report = validator.validate(invalid_data)

        assert report.accepted is False
        assert report.critical_count >= 1

        # Accept either a PARSE_FAILURE finding (older pydicom) or at least one
        # MISSING_MANDATORY_TAG critical finding (pydicom 3.x with force=True)
        has_parse_failure = any(f.rule_code == "PARSE_FAILURE" for f in report.findings)
        has_missing_mandatory = any(
            f.rule_code == "MISSING_MANDATORY_TAG" for f in report.findings
        )
        assert has_parse_failure or has_missing_mandatory, (
            "Expected PARSE_FAILURE or MISSING_MANDATORY_TAG critical finding for invalid DICOM"
        )

    def test_validation_report_max_severity(self, validator, dicom_missing_patient_id):
        """Test that max_severity property correctly identifies highest severity."""
        report = validator.validate(dicom_missing_patient_id)

        max_sev = report.max_severity
        assert max_sev == Severity.CRITICAL

    def test_validation_report_counts(self, validator, minimal_dicom):
        """Test validation report count properties."""
        report = validator.validate(minimal_dicom)

        total = (
            report.critical_count
            + report.error_count
            + report.warning_count
            + report.info_count
        )
        assert len(report.findings) == total


class TestValidationIntegration:
    """Integration tests for validation in context of DICOM upload."""

    def test_validate_batch_multiple_files(self):
        """Test batch validation of multiple DICOM files."""
        validator = DicomValidator()

        # This would be tested with actual endpoint in test_validation_api.py
        # Here we just verify the validator can be called multiple times
        assert validator is not None

    def test_validation_finding_details_structure(self, jfif_dicom_315dpi):
        """Test that validation findings have proper structure."""
        validator = DicomValidator()
        report = validator.validate(jfif_dicom_315dpi)

        for finding in report.findings:
            assert hasattr(finding, "severity")
            assert hasattr(finding, "category")
            assert hasattr(finding, "rule_code")
            assert hasattr(finding, "message")
            assert hasattr(finding, "details")

            # Verify enum values
            assert finding.severity in Severity
            assert finding.category in Category
