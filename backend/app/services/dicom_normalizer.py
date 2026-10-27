"""DICOM normalization service for Phase 3 — Auto-correction of non-standard DICOM files."""
import io
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pydicom
from pydicom.dataset import Dataset

from app.services.dicom_validator import DicomValidator, ValidationReport, Severity


@dataclass
class ChangeSummary:
    """Record of a single correction applied during normalization."""
    tag_keyword: str  # e.g., "PixelSpacing", "PatientBirthDate"
    original_value: Optional[str]  # Original value (None if tag was missing)
    corrected_value: str  # New value after normalization
    rationale: str  # Human-readable explanation of correction
    risk_level: str  # "safe", "medium", "risky"
    category: str  # "pixel_spacing", "tag", "photometric", "charset"


@dataclass
class NormalizationResult:
    """Output from normalization process."""
    modified: bool  # True if any corrections were applied
    changes: list[ChangeSummary] = field(default_factory=list)  # List of corrections
    error: Optional[str] = None  # Error message if normalization failed
    elapsed_ms: float = 0.0  # Processing time in milliseconds


class DicomNormalizer:
    """Normalize DICOM datasets by correcting safely detectable issues.

    Safe corrections (auto-apply):
    - Pixel Spacing from JPEG JFIF density
    - Missing recommended tags (defaults)

    Medium-risk corrections (log, no auto-apply):
    - PhotometricInterpretation inference
    - Character set detection
    """

    def __init__(self):
        self.validator = DicomValidator()

    async def normalize(
        self,
        ds: Dataset,
        validation_report: ValidationReport,
        raw_data: Optional[bytes] = None,
        audit_logger=None,
    ) -> NormalizationResult:
        """Normalize DICOM dataset based on validation findings.

        Args:
            ds: pydicom Dataset to normalize
            validation_report: Output from DicomValidator.validate()
            raw_data: Original DICOM binary data (needed for JFIF parsing)
            audit_logger: Optional audit logger for tracking corrections

        Returns:
            NormalizationResult with all corrections applied
        """
        start = time.time()
        result = NormalizationResult(modified=False)

        try:
            # Apply safe corrections in order
            self._normalize_pixel_spacing(ds, validation_report, raw_data, result)
            self._normalize_tags(ds, validation_report, result)

            # Medium-risk corrections: log but don't auto-apply
            self._check_photometric(ds, validation_report, result)
            self._check_charset(ds, validation_report, result)

            result.elapsed_ms = (time.time() - start) * 1000
            return result
        except Exception as e:
            result.error = f"Normalization failed: {str(e)}"
            return result

    def _parse_jfif_density(self, raw_data: bytes) -> Optional[tuple[int, int, int]]:
        """Extract density info from JFIF header in DICOM pixel data.

        Returns:
            (density_unit, x_density, y_density) tuple or None
            - density_unit: 0=no unit, 1=DPI, 2=dots/cm
            - x_density, y_density: Density values as integers
        """
        if not raw_data:
            return None

        # Search for JFIF marker: 4A 46 49 46 00 ("JFIF\0")
        jfif_sig = b"\x4A\x46\x49\x46\x00"
        pos = raw_data.find(jfif_sig)
        if pos < 0:
            return None

        # JFIF header structure after signature:
        # 2 bytes version, 1 byte density_unit, 2 bytes Xdensity, 2 bytes Ydensity
        offset = pos + len(jfif_sig)
        if offset + 7 > len(raw_data):
            return None

        try:
            # Skip version (2 bytes)
            density_unit = raw_data[offset + 2]
            x_density = struct.unpack(">H", raw_data[offset + 3:offset + 5])[0]
            y_density = struct.unpack(">H", raw_data[offset + 5:offset + 7])[0]
            return (density_unit, x_density, y_density)
        except (struct.error, IndexError):
            return None

    def _normalize_pixel_spacing(
        self,
        ds: Dataset,
        report: ValidationReport,
        raw_data: Optional[bytes],
        result: NormalizationResult,
    ) -> None:
        """Normalize Pixel Spacing from JPEG JFIF density.

        Risk Level: SAFE

        Algorithm:
        1. Find JPEG_DENSITY_MISMATCH finding
        2. Extract DPI from JFIF header
        3. Calculate PixelSpacing: 25.4 / DPI (if DPI unit) or 10 / density (if dots/cm)
        4. Update dataset if missing or incorrect
        """
        # Find JPEG density findings
        density_findings = [
            f for f in report.findings
            if f.rule_code == "JPEG_DENSITY_MISMATCH"
        ]

        if not density_findings:
            return

        # Try to parse JFIF density from raw data
        jfif_info = None
        if raw_data:
            jfif_info = self._parse_jfif_density(raw_data)

        if not jfif_info:
            return

        density_unit, x_density, y_density = jfif_info

        # Validate density values
        if x_density <= 0 or y_density <= 0:
            return

        # Convert density to mm based on unit
        # Unit 1 = DPI (dots per inch)
        # Unit 2 = dots per cm
        # 비정방 픽셀(Xdensity≠Ydensity) 분리 계산 — x값으로 양축을 채우면 측정 오류
        # (본 프로젝트가 막으려는 바로 그 오류). PixelSpacing 순서는 [row(y), col(x)].
        if density_unit == 1:  # DPI
            calculated_spacing = round(25.4 / x_density, 4)
            calculated_spacing_y = round(25.4 / y_density, 4)
        elif density_unit == 2:  # dots/cm
            calculated_spacing = round(10.0 / x_density, 4)
            calculated_spacing_y = round(10.0 / y_density, 4)
        else:
            return

        # Store original value if present
        original_spacing = None
        original_spacing_mm = None
        if hasattr(ds, 'PixelSpacing') and ds.PixelSpacing:
            try:
                original_spacing_mm = float(ds.PixelSpacing[0])
                original_spacing = str([float(v) for v in ds.PixelSpacing])
            except (ValueError, TypeError):
                pass

        # Determine risk level based on deviation from existing PixelSpacing
        # original_spacing_mm은 PixelSpacing[0]=row(y) → 같은 축(y)으로 비교해야 정합.
        risk_level = "safe"
        if original_spacing_mm is not None and original_spacing_mm > 0:
            deviation_pct = abs(calculated_spacing_y - original_spacing_mm) / original_spacing_mm * 100
            if deviation_pct > 20:
                risk_level = "medium"

        if risk_level == "medium":
            # Log as advisory — do NOT auto-apply when deviation exceeds 20%
            result.changes.append(ChangeSummary(
                tag_keyword="PixelSpacing",
                original_value=original_spacing,
                corrected_value=str([calculated_spacing_y, calculated_spacing]),  # [y, x]
                rationale=(
                    f"JFIF {x_density}x{y_density} DPI suggests [{calculated_spacing_y}, {calculated_spacing}] mm "
                    f"but deviation from existing spacing is >20% — NOT auto-applied"
                ),
                risk_level="medium",
                category="pixel_spacing",
            ))
            return

        # Apply correction (safe: deviation <= 20% or no existing spacing)
        # [row(y), col(x)] — 비정방 픽셀 정확 반영
        ds.PixelSpacing = [calculated_spacing_y, calculated_spacing]

        result.changes.append(ChangeSummary(
            tag_keyword="PixelSpacing",
            original_value=original_spacing,
            corrected_value=str([calculated_spacing_y, calculated_spacing]),  # [row(y), col(x)]
            rationale=f"Calculated from JPEG JFIF density {x_density}x{y_density} → [y={calculated_spacing_y}, x={calculated_spacing}] mm",
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
        """Insert default values for missing recommended tags.

        Risk Level: SAFE

        Defaults applied:
        - PatientBirthDate: "00000000" (unknown DoB per DICOM standard)
        - PatientSex: "O" (other per DICOM standard)
        - StudyDate, SeriesDate, ContentDate: Current date
        - SeriesTime, InstanceCreationTime: Current time
        """
        # Simple defaults (don't overwrite existing values)
        simple_defaults = {
            'PatientBirthDate': '00000000',
            'PatientSex': 'O',
        }

        for tag, default_val in simple_defaults.items():
            if not hasattr(ds, tag) or not getattr(ds, tag):
                setattr(ds, tag, default_val)
                result.changes.append(ChangeSummary(
                    tag_keyword=tag,
                    original_value=None,
                    corrected_value=default_val,
                    rationale=f"Default for unknown {tag} (DICOM standard)",
                    risk_level="safe",
                    category="tag",
                ))
                result.modified = True

        # Date/time defaults: use current UTC time
        now = datetime.utcnow()
        date_str = now.strftime('%Y%m%d')
        time_str = now.strftime('%H%M%S')

        date_tags = ['StudyDate', 'SeriesDate', 'ContentDate', 'InstanceCreationDate']
        for tag in date_tags:
            if not hasattr(ds, tag) or not getattr(ds, tag):
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

        time_tags = ['SeriesTime', 'InstanceCreationTime']
        for tag in time_tags:
            if not hasattr(ds, tag) or not getattr(ds, tag):
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
        """Check if PhotometricInterpretation can be inferred.

        Risk Level: MEDIUM (not auto-applied)

        Inference:
        - SamplesPerPixel=1 → MONOCHROME2
        - SamplesPerPixel=3 → RGB
        """
        findings = [
            f for f in report.findings
            if f.rule_code == "MISSING_PHOTOMETRIC_INTERPRETATION"
        ]
        if not findings or not hasattr(ds, 'SamplesPerPixel'):
            return

        samples = ds.SamplesPerPixel
        inferred = None
        if samples == 1:
            inferred = "MONOCHROME2"
        elif samples == 3:
            inferred = "RGB"

        if inferred:
            result.changes.append(ChangeSummary(
                tag_keyword="PhotometricInterpretation",
                original_value=None,
                corrected_value=inferred,
                rationale=f"Inferred from SamplesPerPixel={samples}",
                risk_level="medium",  # Not auto-applied
                category="photometric",
            ))

    def _check_charset(
        self,
        ds: Dataset,
        report: ValidationReport,
        result: NormalizationResult,
    ) -> None:
        """Check if character set can be inferred.

        Risk Level: MEDIUM (not auto-applied)

        Detection:
        - Try to decode PatientName as UTF-8 → ISO_IR 192
        """
        findings = [
            f for f in report.findings
            if f.rule_code == "MISSING_CHARSET"
        ]
        if not findings or not hasattr(ds, 'PatientName'):
            return

        try:
            patient_name = str(ds.PatientName)
            # Try UTF-8 encoding
            patient_name.encode('utf-8').decode('utf-8')
            charset = "ISO_IR 192"  # UTF-8
            result.changes.append(ChangeSummary(
                tag_keyword="SpecificCharacterSet",
                original_value=None,
                corrected_value=charset,
                rationale=f"Detected UTF-8 encoding in PatientName",
                risk_level="medium",  # Not auto-applied
                category="charset",
            ))
        except (UnicodeDecodeError, UnicodeEncodeError, AttributeError):
            pass
