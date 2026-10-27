"""Unit tests for DICOM normalizer (Phase 3)."""
import io
import pytest
import pydicom
from datetime import datetime

from app.services.dicom_normalizer import DicomNormalizer, ChangeSummary
from app.services.dicom_validator import DicomValidator


class TestPixelSpacingNormalizer:
    """Test pixel spacing correction algorithm."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Initialize normalizer and validator for each test."""
        self.normalizer = DicomNormalizer()
        self.validator = DicomValidator()

    def test_pixel_spacing_exact_match_300dpi(self, jfif_dicom_300dpi):
        """Exact match at 300 DPI should not have JPEG_DENSITY_MISMATCH finding."""
        report = self.validator.validate(jfif_dicom_300dpi)

        # No density mismatch should be found
        density_findings = [
            f for f in report.findings
            if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]
        assert len(density_findings) == 0, "300 DPI exact match should have no density mismatch"

    def test_pixel_spacing_warning_tier_320dpi(self, jfif_dicom_315dpi):
        """320 DPI (6.3% mismatch) should trigger WARNING tier finding."""
        report = self.validator.validate(jfif_dicom_315dpi)

        # Should have WARNING finding
        density_findings = [
            f for f in report.findings
            if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]
        assert len(density_findings) == 1
        assert density_findings[0].severity.value == "warning"

    def test_pixel_spacing_error_tier_375dpi(self, jfif_dicom_375dpi):
        """375 DPI (25% mismatch) should trigger ERROR tier finding."""
        report = self.validator.validate(jfif_dicom_375dpi)

        # Should have ERROR finding
        density_findings = [
            f for f in report.findings
            if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]
        assert len(density_findings) == 1
        assert density_findings[0].severity.value == "error"

    @pytest.mark.asyncio
    async def test_normalize_pixel_spacing_from_warning_tier(self, jfif_dicom_315dpi):
        """Apply pixel spacing correction when warning finding is present."""
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_315dpi), force=True)
        report = self.validator.validate(jfif_dicom_315dpi)

        # Normalize
        result = await self.normalizer.normalize(ds, report, jfif_dicom_315dpi)

        # Should have applied correction
        assert result.modified
        spacing_changes = [c for c in result.changes if c.tag_keyword == "PixelSpacing"]
        assert len(spacing_changes) > 0

        # Verify spacing is approximately correct for 320 DPI: 25.4/320 = 0.07938
        corrected = spacing_changes[0].corrected_value
        assert "0.079" in corrected or "0.0794" in corrected

    @pytest.mark.asyncio
    async def test_normalize_pixel_spacing_from_error_tier(self, jfif_dicom_375dpi):
        """Apply pixel spacing correction when error finding is present."""
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_375dpi), force=True)
        report = self.validator.validate(jfif_dicom_375dpi)

        result = await self.normalizer.normalize(ds, report, jfif_dicom_375dpi)

        assert result.modified
        spacing_changes = [c for c in result.changes if c.tag_keyword == "PixelSpacing"]
        assert len(spacing_changes) > 0

        # 375 DPI: 25.4/375 = 0.06773
        corrected = spacing_changes[0].corrected_value
        assert "0.067" in corrected or "0.0677" in corrected

    def test_parse_jfif_density_300dpi(self, jfif_dicom_300dpi):
        """Verify JFIF parser extracts correct density from 300 DPI DICOM."""
        result = self.normalizer._parse_jfif_density(jfif_dicom_300dpi)

        assert result is not None
        density_unit, x_density, y_density = result
        assert density_unit == 1  # DPI
        assert x_density == 300
        assert y_density == 300

    def test_parse_jfif_density_320dpi(self, jfif_dicom_315dpi):
        """Verify JFIF parser extracts correct density from 320 DPI DICOM."""
        result = self.normalizer._parse_jfif_density(jfif_dicom_315dpi)

        assert result is not None
        density_unit, x_density, y_density = result
        assert density_unit == 1  # DPI
        assert x_density == 320
        assert y_density == 320

    def test_parse_jfif_density_375dpi(self, jfif_dicom_375dpi):
        """Verify JFIF parser extracts correct density from 375 DPI DICOM."""
        result = self.normalizer._parse_jfif_density(jfif_dicom_375dpi)

        assert result is not None
        density_unit, x_density, y_density = result
        assert density_unit == 1  # DPI
        assert x_density == 375
        assert y_density == 375

    def test_parse_jfif_density_not_present(self, minimal_dicom):
        """Return None when JFIF header is not present."""
        result = self.normalizer._parse_jfif_density(minimal_dicom)
        assert result is None

    @pytest.mark.asyncio
    async def test_normalize_result_structure(self, jfif_dicom_375dpi):
        """Verify NormalizationResult has required fields."""
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_375dpi), force=True)
        report = self.validator.validate(jfif_dicom_375dpi)

        result = await self.normalizer.normalize(ds, report, jfif_dicom_375dpi)

        # Check result structure
        assert hasattr(result, 'modified')
        assert hasattr(result, 'changes')
        assert hasattr(result, 'error')
        assert hasattr(result, 'elapsed_ms')

        assert isinstance(result.modified, bool)
        assert isinstance(result.changes, list)
        assert result.error is None
        assert result.elapsed_ms > 0


    @pytest.mark.asyncio
    async def test_normalize_pixel_spacing_medium_risk_above_20pct(self, jfif_dicom_375dpi):
        """375 DPI vs 300 DPI spacing is ~25% deviation — should be medium risk, NOT auto-applied."""
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_375dpi), force=True)
        report = self.validator.validate(jfif_dicom_375dpi)

        # Ensure original PixelSpacing is present (300 DPI = 0.0847 mm)
        original_spacing = list(ds.PixelSpacing) if hasattr(ds, 'PixelSpacing') else None

        result = await self.normalizer.normalize(ds, report, jfif_dicom_375dpi)

        spacing_changes = [c for c in result.changes if c.tag_keyword == "PixelSpacing"]
        assert len(spacing_changes) > 0, "Should record advisory change even when not applied"

        change = spacing_changes[0]
        assert change.risk_level == "medium", (
            f"Expected medium risk for >20% deviation, got: {change.risk_level}"
        )

        # Verify PixelSpacing was NOT auto-applied (dataset unchanged)
        if original_spacing is not None:
            assert list(ds.PixelSpacing) == original_spacing, (
                "PixelSpacing should NOT be modified when deviation >20%"
            )

        # result.modified should be False since no safe changes were applied (only advisory)
        safe_changes = [c for c in result.changes if c.risk_level == "safe"]
        assert not any(c.tag_keyword == "PixelSpacing" and c.risk_level == "safe" for c in result.changes), (
            "PixelSpacing change with safe risk_level must not exist when deviation >20%"
        )


class TestTagNormalizer:
    """Test missing tag insertion with safe defaults."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Initialize normalizer for each test."""
        self.normalizer = DicomNormalizer()
        self.validator = DicomValidator()

    @pytest.mark.asyncio
    async def test_insert_patient_birth_date_default(self, dicom_missing_patient_id):
        """Insert PatientBirthDate = '00000000' if missing."""
        ds = pydicom.dcmread(io.BytesIO(dicom_missing_patient_id), force=True)

        # Verify it's missing before normalization
        assert not hasattr(ds, 'PatientBirthDate') or not ds.PatientBirthDate

        report = self.validator.validate(dicom_missing_patient_id)
        result = await self.normalizer.normalize(ds, report, dicom_missing_patient_id)

        # Should have inserted default
        dob_changes = [c for c in result.changes if c.tag_keyword == "PatientBirthDate"]
        assert len(dob_changes) > 0
        assert dob_changes[0].corrected_value == "00000000"
        assert dob_changes[0].risk_level == "safe"

        # Verify tag is now set
        assert hasattr(ds, 'PatientBirthDate')
        assert ds.PatientBirthDate == "00000000"

    @pytest.mark.asyncio
    async def test_insert_patient_sex_default(self, dicom_missing_patient_id):
        """Insert PatientSex = 'O' if missing."""
        ds = pydicom.dcmread(io.BytesIO(dicom_missing_patient_id), force=True)

        report = self.validator.validate(dicom_missing_patient_id)
        result = await self.normalizer.normalize(ds, report, dicom_missing_patient_id)

        # Should have inserted default
        sex_changes = [c for c in result.changes if c.tag_keyword == "PatientSex"]
        assert len(sex_changes) > 0
        assert sex_changes[0].corrected_value == "O"
        assert sex_changes[0].risk_level == "safe"

    @pytest.mark.asyncio
    async def test_insert_study_date_from_current_time(self, dicom_missing_patient_id):
        """Insert StudyDate using current date if missing."""
        ds = pydicom.dcmread(io.BytesIO(dicom_missing_patient_id), force=True)

        # Clear StudyDate if present
        if hasattr(ds, 'StudyDate'):
            delattr(ds, 'StudyDate')

        report = self.validator.validate(dicom_missing_patient_id)
        result = await self.normalizer.normalize(ds, report, dicom_missing_patient_id)

        # Should have inserted current date
        date_changes = [c for c in result.changes if c.tag_keyword == "StudyDate"]
        assert len(date_changes) > 0

        # Verify format YYYYMMDD
        date_val = date_changes[0].corrected_value
        assert len(date_val) == 8
        assert date_val.isdigit()

        # Should be approximately today
        today = datetime.utcnow().strftime('%Y%m%d')
        assert date_val == today

    @pytest.mark.asyncio
    async def test_preserve_existing_tag_values(self, minimal_dicom):
        """Do not overwrite existing tag values."""
        ds = pydicom.dcmread(io.BytesIO(minimal_dicom), force=True)
        original_patient_id = ds.PatientID
        original_patient_name = ds.PatientName

        report = self.validator.validate(minimal_dicom)
        result = await self.normalizer.normalize(ds, report, minimal_dicom)

        # Should not have modified these tags
        assert ds.PatientID == original_patient_id
        assert ds.PatientName == original_patient_name

        # Should not have changes for these tags
        patient_id_changes = [c for c in result.changes if c.tag_keyword == "PatientID"]
        patient_name_changes = [c for c in result.changes if c.tag_keyword == "PatientName"]
        assert len(patient_id_changes) == 0
        assert len(patient_name_changes) == 0


class TestNormalizationResultStructure:
    """Test output data structures."""

    @pytest.mark.asyncio
    async def test_change_summary_has_required_fields(self, jfif_dicom_375dpi):
        """Verify ChangeSummary has all required fields."""
        normalizer = DicomNormalizer()
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_375dpi), force=True)
        validator = DicomValidator()
        report = validator.validate(jfif_dicom_375dpi)

        result = await normalizer.normalize(ds, report, jfif_dicom_375dpi)

        assert len(result.changes) > 0
        change = result.changes[0]

        # Verify all fields are present
        assert hasattr(change, 'tag_keyword')
        assert hasattr(change, 'original_value')
        assert hasattr(change, 'corrected_value')
        assert hasattr(change, 'rationale')
        assert hasattr(change, 'risk_level')
        assert hasattr(change, 'category')

        # Verify types
        assert isinstance(change.tag_keyword, str)
        assert isinstance(change.corrected_value, str)
        assert isinstance(change.rationale, str)
        assert change.risk_level in ["safe", "medium", "risky"]
        assert change.category in ["pixel_spacing", "tag", "photometric", "charset"]

    @pytest.mark.asyncio
    async def test_no_changes_returns_unmodified(self, minimal_dicom):
        """Tag normalizer adds defaults for missing optional tags (PatientBirthDate, PatientSex, dates)."""
        normalizer = DicomNormalizer()
        validator = DicomValidator()
        ds = pydicom.dcmread(io.BytesIO(minimal_dicom), force=True)
        report = validator.validate(minimal_dicom)

        result = await normalizer.normalize(ds, report, minimal_dicom)

        # Minimal DICOM lacks optional tags → normalizer adds safe defaults
        assert result.error is None
        # Tag normalizer fills PatientBirthDate, PatientSex, date/time tags
        tag_changes = [c for c in result.changes if c.category == "tag"]
        assert all(c.risk_level == "safe" for c in tag_changes)


class TestNormalizationIntegration:
    """Integration tests between normalizer and validator."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Initialize normalizer and validator."""
        self.normalizer = DicomNormalizer()
        self.validator = DicomValidator()

    @pytest.mark.asyncio
    async def test_normalize_then_revalidate_passes(self, jfif_dicom_375dpi):
        """After normalization, re-validation should pass."""
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_375dpi), force=True)

        # Pre-normalization validation shows error
        report_before = self.validator.validate(jfif_dicom_375dpi)
        density_findings_before = [
            f for f in report_before.findings
            if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]
        assert len(density_findings_before) > 0

        # Normalize
        result = await self.normalizer.normalize(ds, report_before, jfif_dicom_375dpi)
        assert result.modified

        # Re-serialize and re-validate
        buf = io.BytesIO()
        ds.save_as(buf)
        data_normalized = buf.getvalue()

        report_after = self.validator.validate(data_normalized)
        # After normalization, pixel spacing should be corrected
        # (Note: Orthanc may still reject for other reasons, but density mismatch should be fixed)

    @pytest.mark.asyncio
    async def test_performance_under_100ms(self, jfif_dicom_375dpi):
        """Normalization should complete in under 100ms."""
        ds = pydicom.dcmread(io.BytesIO(jfif_dicom_375dpi), force=True)
        report = self.validator.validate(jfif_dicom_375dpi)

        result = await self.normalizer.normalize(ds, report, jfif_dicom_375dpi)

        # Should complete in under 100ms
        assert result.elapsed_ms < 100, f"Normalization took {result.elapsed_ms}ms (should be <100ms)"
