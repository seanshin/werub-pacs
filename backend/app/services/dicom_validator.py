"""Non-standard DICOM validation engine.

Validates DICOM files on ingestion and detects:
- Missing/malformed mandatory tags
- Transfer Syntax mismatches
- JPEG density manipulation (JFIF Xdensity/Ydensity vs Pixel Spacing)
- Character set issues (Korean patient names)
- Pixel data anomalies
"""
import io
import struct
from dataclasses import dataclass, field
from enum import Enum

import pydicom
from pydicom.errors import InvalidDicomError


class Severity(str, Enum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Category(str, Enum):
    METADATA = "metadata"
    PIXEL_DATA = "pixel_data"
    TRANSFER_SYNTAX = "transfer_syntax"
    JPEG = "jpeg"
    CHARACTER_SET = "character_set"
    UID = "uid"


@dataclass
class Finding:
    severity: Severity
    category: Category
    rule_code: str
    message: str
    details: dict = field(default_factory=dict)
    auto_fixed: bool = False
    fix_description: str | None = None


@dataclass
class ValidationReport:
    sop_instance_uid: str = ""
    study_instance_uid: str = ""
    series_instance_uid: str = ""
    ae_title: str = ""
    modality: str = ""
    manufacturer: str = ""
    station_name: str = ""
    findings: list[Finding] = field(default_factory=list)
    accepted: bool = True

    @property
    def max_severity(self) -> Severity | None:
        if not self.findings:
            return None
        # ⚠️ order는 "낮을수록 심각"(CRITICAL=0) → min()이 가장 심각한 것을 반환(정상).
        # order를 직관 방향(CRITICAL=3)으로 바꾸려면 반드시 min→max도 함께 바꿀 것.
        order = {Severity.CRITICAL: 0, Severity.ERROR: 1, Severity.WARNING: 2, Severity.INFO: 3}
        return min(self.findings, key=lambda f: order[f.severity]).severity

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.INFO)


class DicomValidator:
    """Validates DICOM instances for non-standard conformance issues."""

    # Type 1 tags that MUST be present and non-empty
    MANDATORY_TAGS = {
        (0x0008, 0x0018): "SOPInstanceUID",
        (0x0008, 0x0016): "SOPClassUID",
        (0x0020, 0x000D): "StudyInstanceUID",
        (0x0020, 0x000E): "SeriesInstanceUID",
        (0x0010, 0x0020): "PatientID",
        (0x0008, 0x0060): "Modality",
    }

    # Tags that should be present (Type 1C / Type 2)
    RECOMMENDED_TAGS = {
        (0x0010, 0x0010): "PatientName",
        (0x0010, 0x0030): "PatientBirthDate",
        (0x0008, 0x0020): "StudyDate",
        (0x0008, 0x0050): "AccessionNumber",
    }

    def validate(self, dicom_data: bytes) -> ValidationReport:
        """Validate a DICOM instance from raw bytes."""
        report = ValidationReport()

        try:
            ds = pydicom.dcmread(io.BytesIO(dicom_data), force=True)
        except (InvalidDicomError, Exception) as e:
            report.findings.append(Finding(
                severity=Severity.CRITICAL,
                category=Category.METADATA,
                rule_code="PARSE_FAILURE",
                message=f"Failed to parse DICOM file: {e}",
            ))
            report.accepted = False
            return report

        # Extract identifiers
        report.sop_instance_uid = str(getattr(ds, "SOPInstanceUID", ""))
        report.study_instance_uid = str(getattr(ds, "StudyInstanceUID", ""))
        report.series_instance_uid = str(getattr(ds, "SeriesInstanceUID", ""))
        report.ae_title = str(getattr(ds, "SourceApplicationEntityTitle", ""))
        report.modality = str(getattr(ds, "Modality", ""))
        report.manufacturer = str(getattr(ds, "Manufacturer", ""))
        report.station_name = str(getattr(ds, "StationName", ""))

        # Run all checks
        self._check_mandatory_tags(ds, report)
        self._check_recommended_tags(ds, report)
        self._check_uid_format(ds, report)
        self._check_character_set(ds, report)
        self._check_vr_conformance(ds, report)
        self._check_transfer_syntax(ds, report)
        self._check_pixel_data(ds, report)
        self._check_jpeg_density(ds, dicom_data, report)
        self._check_private_tags(ds, report)
        self._check_retired_sop_ts(ds, report)

        # Determine acceptance
        if report.critical_count > 0:
            report.accepted = False

        return report

    def _check_mandatory_tags(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check Type 1 mandatory tags."""
        for tag, name in self.MANDATORY_TAGS.items():
            if tag not in ds:
                report.findings.append(Finding(
                    severity=Severity.CRITICAL,
                    category=Category.METADATA,
                    rule_code="MISSING_MANDATORY_TAG",
                    message=f"Mandatory tag {name} ({tag[0]:04X},{tag[1]:04X}) is missing",
                    details={"tag": f"({tag[0]:04X},{tag[1]:04X})", "name": name},
                ))
            elif ds[tag].is_empty:
                report.findings.append(Finding(
                    severity=Severity.ERROR,
                    category=Category.METADATA,
                    rule_code="EMPTY_MANDATORY_TAG",
                    message=f"Mandatory tag {name} ({tag[0]:04X},{tag[1]:04X}) is empty",
                    details={"tag": f"({tag[0]:04X},{tag[1]:04X})", "name": name},
                ))

    def _check_recommended_tags(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check Type 2 / recommended tags."""
        for tag, name in self.RECOMMENDED_TAGS.items():
            if tag not in ds:
                report.findings.append(Finding(
                    severity=Severity.WARNING,
                    category=Category.METADATA,
                    rule_code="MISSING_RECOMMENDED_TAG",
                    message=f"Recommended tag {name} ({tag[0]:04X},{tag[1]:04X}) is missing",
                    details={"tag": f"({tag[0]:04X},{tag[1]:04X})", "name": name},
                ))

    def _check_uid_format(self, ds: pydicom.Dataset, report: ValidationReport):
        """Validate UID format (max 64 chars, valid characters)."""
        uid_tags = [
            ((0x0008, 0x0018), "SOPInstanceUID"),
            ((0x0020, 0x000D), "StudyInstanceUID"),
            ((0x0020, 0x000E), "SeriesInstanceUID"),
        ]
        for tag, name in uid_tags:
            if tag not in ds:
                continue
            uid = str(ds[tag].value)
            if len(uid) > 64:
                report.findings.append(Finding(
                    severity=Severity.ERROR,
                    category=Category.UID,
                    rule_code="UID_TOO_LONG",
                    message=f"{name} exceeds 64 characters ({len(uid)} chars)",
                    details={"tag": name, "length": len(uid)},
                ))
            if not all(c in "0123456789." for c in uid):
                report.findings.append(Finding(
                    severity=Severity.ERROR,
                    category=Category.UID,
                    rule_code="UID_INVALID_CHARS",
                    message=f"{name} contains invalid characters",
                    details={"tag": name, "uid": uid[:64]},
                ))

    def _check_character_set(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check Specific Character Set for non-ASCII patient names."""
        patient_name = str(getattr(ds, "PatientName", ""))
        has_non_ascii = any(ord(c) > 127 for c in patient_name)
        charset_tag = (0x0008, 0x0005)

        if has_non_ascii and charset_tag not in ds:
            report.findings.append(Finding(
                severity=Severity.ERROR,
                category=Category.CHARACTER_SET,
                rule_code="MISSING_CHARACTER_SET",
                message="Patient name contains non-ASCII characters but Specific Character Set (0008,0005) is missing",
                details={"patient_name_length": len(patient_name)},
            ))
        elif charset_tag in ds:
            charset = str(ds[charset_tag].value)
            known_charsets = [
                "ISO_IR 192", "ISO 2022 IR 149", "ISO_IR 100", "ISO_IR 101",
                "ISO 2022 IR 6", "ISO_IR 13", "GB18030", "ISO 2022 IR 87",
            ]
            if charset and not any(cs in charset for cs in known_charsets):
                report.findings.append(Finding(
                    severity=Severity.WARNING,
                    category=Category.CHARACTER_SET,
                    rule_code="UNKNOWN_CHARACTER_SET",
                    message=f"Uncommon Specific Character Set: {charset}",
                    details={"charset": charset},
                ))

    def _check_vr_conformance(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check Value Representation conformance for common tags."""
        # Date tags (VR=DA) should be YYYYMMDD
        date_tags = [(0x0008, 0x0020, "StudyDate"), (0x0008, 0x0021, "SeriesDate")]
        for group, elem, name in date_tags:
            tag = (group, elem)
            if tag in ds and ds[tag].value:
                val = str(ds[tag].value)
                if len(val) != 8 or not val.isdigit():
                    report.findings.append(Finding(
                        severity=Severity.WARNING,
                        category=Category.METADATA,
                        rule_code="INVALID_DATE_FORMAT",
                        message=f"{name} has invalid date format: '{val}' (expected YYYYMMDD)",
                        details={"tag": name, "value": val},
                    ))

        # Integer String tags (VR=IS)
        is_tags = [(0x0020, 0x0013, "InstanceNumber"), (0x0020, 0x0011, "SeriesNumber")]
        for group, elem, name in is_tags:
            tag = (group, elem)
            if tag in ds and ds[tag].value:
                val = str(ds[tag].value).strip()
                try:
                    int(val)
                except ValueError:
                    report.findings.append(Finding(
                        severity=Severity.WARNING,
                        category=Category.METADATA,
                        rule_code="INVALID_IS_VALUE",
                        message=f"{name} has non-integer value: '{val}'",
                        details={"tag": name, "value": val},
                    ))

    def _check_transfer_syntax(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check Transfer Syntax declaration."""
        ts = getattr(ds, "file_meta", None)
        if ts is None:
            report.findings.append(Finding(
                severity=Severity.ERROR,
                category=Category.TRANSFER_SYNTAX,
                rule_code="MISSING_FILE_META",
                message="File Meta Information is missing",
            ))
            return

        ts_uid = str(getattr(ts, "TransferSyntaxUID", ""))
        if not ts_uid:
            report.findings.append(Finding(
                severity=Severity.ERROR,
                category=Category.TRANSFER_SYNTAX,
                rule_code="MISSING_TRANSFER_SYNTAX",
                message="Transfer Syntax UID is missing from file meta",
            ))
            return

        # Check Bits Allocated/Stored consistency
        bits_allocated = getattr(ds, "BitsAllocated", None)
        bits_stored = getattr(ds, "BitsStored", None)
        if bits_allocated and bits_stored:
            if bits_stored > bits_allocated:
                report.findings.append(Finding(
                    severity=Severity.ERROR,
                    category=Category.PIXEL_DATA,
                    rule_code="BITS_STORED_GT_ALLOCATED",
                    message=f"BitsStored ({bits_stored}) > BitsAllocated ({bits_allocated})",
                    details={"bits_allocated": bits_allocated, "bits_stored": bits_stored},
                ))

    def _check_pixel_data(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check pixel data related tags."""
        if (0x7FE0, 0x0010) not in ds:
            return  # No pixel data (might be SR, PR, etc.)

        # Check Photometric Interpretation
        photometric = str(getattr(ds, "PhotometricInterpretation", ""))
        valid_photometric = [
            "MONOCHROME1", "MONOCHROME2", "RGB", "YBR_FULL", "YBR_FULL_422",
            "YBR_ICT", "YBR_RCT", "PALETTE COLOR",
        ]
        if photometric and photometric not in valid_photometric:
            report.findings.append(Finding(
                severity=Severity.WARNING,
                category=Category.PIXEL_DATA,
                rule_code="UNKNOWN_PHOTOMETRIC",
                message=f"Unknown Photometric Interpretation: '{photometric}'",
                details={"photometric": photometric},
            ))

        # Check Rows/Columns
        rows = getattr(ds, "Rows", None)
        cols = getattr(ds, "Columns", None)
        if rows is None or cols is None:
            report.findings.append(Finding(
                severity=Severity.ERROR,
                category=Category.PIXEL_DATA,
                rule_code="MISSING_IMAGE_DIMENSIONS",
                message="Rows or Columns tag is missing for image with pixel data",
            ))

    def _check_jpeg_density(self, ds: pydicom.Dataset, raw_data: bytes, report: ValidationReport):
        """Check JPEG density (DPI/DPM) vs DICOM Pixel Spacing.

        This is a critical check: some devices/software manipulate JPEG density
        values during compression, causing measurement errors if Pixel Spacing
        is derived from JPEG headers instead of DICOM tags.
        """
        if (0x7FE0, 0x0010) not in ds:
            return

        ts = getattr(ds.file_meta, "TransferSyntaxUID", "") if hasattr(ds, "file_meta") else ""
        ts = str(ts)

        # Only check JPEG compressed transfer syntaxes
        jpeg_syntaxes = [
            "1.2.840.10008.1.2.4.50",   # JPEG Baseline
            "1.2.840.10008.1.2.4.51",   # JPEG Extended
            "1.2.840.10008.1.2.4.57",   # JPEG Lossless NH
            "1.2.840.10008.1.2.4.70",   # JPEG Lossless SV1
        ]
        if ts not in jpeg_syntaxes:
            return

        # Extract DICOM Pixel Spacing
        pixel_spacing = getattr(ds, "PixelSpacing", None)
        imager_pixel_spacing = getattr(ds, "ImagerPixelSpacing", None)

        # Find JFIF header in pixel data to extract density
        jfif_info = self._parse_jfif_density(raw_data)
        if jfif_info is None:
            return

        density_unit, x_density, y_density = jfif_info

        # Report JFIF density info
        if density_unit != 0:  # 0 = no unit (aspect ratio only)
            unit_names = {1: "DPI", 2: "dots/cm"}
            unit_name = unit_names.get(density_unit, f"unknown({density_unit})")

            # 비표준 PixelSpacing(VM=1·문자열)에서 [1] 인덱싱은 IndexError → 검증기 자체가
            # 죽음(비표준 검증이 핵심 가치인데 역설). VM<2면 단일값을 양축에 적용.
            if pixel_spacing:
                if len(pixel_spacing) >= 2:
                    dicom_x_mm = float(pixel_spacing[1])  # column spacing
                    dicom_y_mm = float(pixel_spacing[0])  # row spacing
                else:
                    dicom_x_mm = dicom_y_mm = float(pixel_spacing[0])

                # Convert JFIF density to mm spacing for comparison
                if density_unit == 1:  # DPI → mm
                    jfif_x_mm = 25.4 / x_density if x_density > 0 else 0
                    jfif_y_mm = 25.4 / y_density if y_density > 0 else 0
                elif density_unit == 2:  # dots/cm → mm
                    jfif_x_mm = 10.0 / x_density if x_density > 0 else 0
                    jfif_y_mm = 10.0 / y_density if y_density > 0 else 0
                else:
                    jfif_x_mm = 0
                    jfif_y_mm = 0

                if jfif_x_mm > 0 and jfif_y_mm > 0:
                    x_diff = abs(dicom_x_mm - jfif_x_mm) / dicom_x_mm * 100
                    y_diff = abs(dicom_y_mm - jfif_y_mm) / dicom_y_mm * 100

                    # 3-tier severity: <5% OK, 5-20% WARNING, >20% ERROR
                    if x_diff > 20 or y_diff > 20:
                        severity = Severity.ERROR
                    elif x_diff > 5 or y_diff > 5:
                        severity = Severity.WARNING
                    else:
                        severity = None  # Within acceptable tolerance

                    if severity is not None:
                        report.findings.append(Finding(
                            severity=severity,
                            category=Category.JPEG,
                            rule_code="JPEG_DENSITY_MISMATCH",
                            message=(
                                f"JPEG density ({x_density}x{y_density} {unit_name}) "
                                f"does not match DICOM Pixel Spacing "
                                f"({dicom_y_mm:.4f}x{dicom_x_mm:.4f} mm). "
                                f"Difference: X={x_diff:.1f}%, Y={y_diff:.1f}%. "
                                f"Measurements may be inaccurate!"
                            ),
                            details={
                                "jfif_density_unit": density_unit,
                                "jfif_x_density": x_density,
                                "jfif_y_density": y_density,
                                "jfif_x_mm": round(jfif_x_mm, 4),
                                "jfif_y_mm": round(jfif_y_mm, 4),
                                "dicom_x_mm": round(dicom_x_mm, 4),
                                "dicom_y_mm": round(dicom_y_mm, 4),
                                "x_diff_pct": round(x_diff, 1),
                                "y_diff_pct": round(y_diff, 1),
                            },
                        ))
            else:
                report.findings.append(Finding(
                    severity=Severity.WARNING,
                    category=Category.JPEG,
                    rule_code="JPEG_DENSITY_NO_PIXEL_SPACING",
                    message=(
                        f"JPEG has density info ({x_density}x{y_density} {unit_name}) "
                        f"but DICOM Pixel Spacing tag is missing. Cannot cross-validate."
                    ),
                    details={
                        "jfif_density_unit": density_unit,
                        "jfif_x_density": x_density,
                        "jfif_y_density": y_density,
                    },
                ))

        # Check for unusual density values
        if x_density == 1 and y_density == 1 and density_unit == 1:
            report.findings.append(Finding(
                severity=Severity.INFO,
                category=Category.JPEG,
                rule_code="JPEG_DEFAULT_DENSITY",
                message="JPEG uses default 1x1 DPI density (likely placeholder, not actual calibration)",
            ))

        # Check aspect ratio mismatch
        if x_density != y_density and density_unit == 0:
            report.findings.append(Finding(
                severity=Severity.WARNING,
                category=Category.JPEG,
                rule_code="JPEG_NONSQUARE_ASPECT",
                message=f"JPEG has non-square aspect ratio: {x_density}:{y_density}",
                details={"x_density": x_density, "y_density": y_density},
            ))

    def _parse_jfif_density(self, raw_data: bytes) -> tuple[int, int, int] | None:
        """Extract density info from JFIF header in DICOM pixel data.

        Returns (density_unit, x_density, y_density) or None.
        density_unit: 0=no unit, 1=DPI, 2=dots/cm
        """
        # Search for JFIF marker: FF D8 FF E0 xx xx 4A 46 49 46 00
        jfif_sig = b"\x4A\x46\x49\x46\x00"  # "JFIF\0"
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

    def _check_private_tags(self, ds: pydicom.Dataset, report: ValidationReport):
        """Log private tags (vendor-specific)."""
        private_groups = set()
        for elem in ds:
            if elem.tag.group % 2 == 1 and elem.tag.group > 0x0008:
                private_groups.add(elem.tag.group)

        if private_groups:
            report.findings.append(Finding(
                severity=Severity.INFO,
                category=Category.METADATA,
                rule_code="PRIVATE_TAGS_PRESENT",
                message=f"Contains private tags in {len(private_groups)} group(s)",
                details={"private_groups": [f"({g:04X},xxxx)" for g in sorted(private_groups)]},
            ))

    # Retired SOP Class UID → current mapping
    RETIRED_SOP_MAP = {
        "1.2.840.10008.5.1.4.1.1.6":   "1.2.840.10008.5.1.4.1.1.6.1",     # US Image (Retired → current)
        "1.2.840.10008.5.1.4.1.1.12.3": "1.2.840.10008.5.1.4.1.1.12.2",    # XA Biplane (Retired → XA)
        "1.2.840.10008.5.1.4.1.1.1.1.1":"1.2.840.10008.5.1.4.1.1.1.1",     # Digital X-Ray Presentation (Retired)
        "1.2.840.10008.5.1.4.1.1.3":   "1.2.840.10008.5.1.4.1.1.3.1",      # US Multi-frame (Retired → current)
        "1.2.840.10008.5.1.4.1.1.12.1.1":"1.2.840.10008.5.1.4.1.1.12.1",   # Enhanced XA (Retired)
    }

    RETIRED_TS = {
        "1.2.840.10008.1.2.2",     # Explicit VR Big Endian (Retired)
        "1.2.840.10008.1.2.1.99",  # Deflated Explicit VR LE (rarely supported)
    }

    def _check_retired_sop_ts(self, ds: pydicom.Dataset, report: ValidationReport):
        """Check for retired SOP Class UIDs and Transfer Syntaxes."""
        # SOP Class
        sop_class = str(getattr(ds, "SOPClassUID", ""))
        if sop_class in self.RETIRED_SOP_MAP:
            current = self.RETIRED_SOP_MAP[sop_class]
            report.findings.append(Finding(
                severity=Severity.WARNING,
                category=Category.TRANSFER_SYNTAX,
                rule_code="RETIRED_SOP_CLASS",
                message=f"Retired SOP Class UID: {sop_class} — viewer may fail to render",
                details={
                    "retired_sop": sop_class,
                    "current_sop": current,
                },
            ))

        # Transfer Syntax
        ts = ""
        if hasattr(ds, "file_meta") and ds.file_meta:
            ts = str(getattr(ds.file_meta, "TransferSyntaxUID", ""))
        if ts in self.RETIRED_TS:
            report.findings.append(Finding(
                severity=Severity.WARNING,
                category=Category.TRANSFER_SYNTAX,
                rule_code="RETIRED_TRANSFER_SYNTAX",
                message=f"Retired Transfer Syntax: {ts} — decoder may not be available",
                details={"retired_ts": ts, "recommended": "1.2.840.10008.1.2.1"},
            ))
