"""Supplier-specific DICOM normalization implementations."""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any, Dict

from app.models.batch_job import NormalizationConfig


@dataclass
class NormalizationChange:
    """Record of a single normalization change."""
    tag: str  # DICOM tag (e.g., "0008,0020")
    original: Any
    corrected: Any
    rationale: str
    risk_level: str  # "safe" or "medium"


# ─── 캐논 정규화 change 스키마 (v2 "승인=적용"의 단일 출처) ───────────────────────
# NormalizationReview.reviewed_changes 엔벨로프:
#   {"schema_version": CHANGE_SCHEMA_VERSION, "changes": [change, ...]}
# 각 change(= NormalizationChange 직렬화):
#   {"tag": "GGGG,EEEE"(적용 대상, 16진 — 필수), "original": 표시/감사, "corrected": 적용할 새 값(필수),
#    "rationale": 사유, "risk_level": "safe"|"medium"}
# VR은 적용 시 엔진(_guess_vr_for_tag)이 태그에서 추론 — 저장 안 함.
# 적용 레벨은 현재 per-instance(스터디 레벨 태그도 인스턴스마다 적용) — level은 향후 확장.
# ★레거시(요약 dict: {charset_fixed, missing_tags_added, ...})는 이 스키마가 아님 → is_applicable_change=False.
CHANGE_SCHEMA_VERSION = 1
_CANON_TAG_RE = re.compile(r"^[0-9A-Fa-f]{4},[0-9A-Fa-f]{4}$")


def is_applicable_change(change: object) -> bool:
    """캐논 스키마로 DICOM 적용 가능한 change인가 — 적용 대상 태그(GGGG,EEEE) + 새 값(corrected) 존재.

    표시문자열 태그(예: "PixelSpacing (0028,0030)")·요약 dict(레거시)는 False.
    """
    if not isinstance(change, dict):
        return False
    return bool(_CANON_TAG_RE.match(str(change.get("tag", "")))) and change.get("corrected") is not None


def _extract_private_tags(file_data: Dict[str, Any], group: int) -> Dict[str, Any]:
    """
    Extract vendor-specific private tags from a given group.

    Args:
        file_data: Full DICOM tags dict including private tags
        group: Private group number (e.g., 0x0019 for Siemens group 19)

    Returns:
        Dict of private tag key -> value for tags in the given group
    """
    prefix = f"{group:04X},"
    return {k: v for k, v in file_data.items() if k.startswith(prefix)}


class SupplierNormalizer(ABC):
    """Abstract base for supplier-specific DICOM normalization."""

    def __init__(self, config: NormalizationConfig, supplier: str):
        """
        Initialize normalizer.

        Args:
            config: NormalizationConfig for this modality
            supplier: Supplier name (siemens, ge, philips, default)
        """
        self.config = config
        self.supplier = supplier
        self.modality = config.modality

    @abstractmethod
    def detect_supplier(self, file_data: Dict[str, Any]) -> str:
        """
        Detect the equipment supplier from DICOM file.

        Args:
            file_data: Extracted DICOM tags dict

        Returns:
            Detected supplier name
        """
        pass

    @abstractmethod
    def normalize(self, file_data: Dict[str, Any]) -> list[NormalizationChange]:
        """
        Apply supplier-specific normalization rules.

        Args:
            file_data: DICOM tags dict (keys like "0008,0020")

        Returns:
            List of NormalizationChange objects
        """
        pass

    def _is_algorithm_enabled(self, algo_name: str) -> bool:
        """Check if algorithm is enabled in config."""
        return self.config.algorithms.get(algo_name, False)

    def _get_risk_handling(self, risk_level: str) -> str:
        """
        Get how to handle changes of given risk level.

        Returns:
            "auto", "manual", or "reject"
        """
        return self.config.risk_tiers.get(risk_level, "reject")


class SiemensNormalizer(SupplierNormalizer):
    """Handle Siemens-specific DICOM deviations."""

    def detect_supplier(self, file_data: Dict[str, Any]) -> str:
        """Detect Siemens from manufacturer field."""
        manufacturer = file_data.get("0008,0070", "").upper()  # Manufacturer
        if "SIEMENS" in manufacturer:
            return "siemens"
        return "unknown"

    def normalize(self, file_data: Dict[str, Any]) -> list[NormalizationChange]:
        """
        Apply Siemens-specific normalizations.

        Key issues:
        - InstanceCreationDate might be missing or wrong
        - PhotometricInterpretation issues with certain modalities
        - Pixel spacing inconsistencies in CT
        - Vendor private tags in group 0019 (PixelSpacing, PhotometricInterpretation)
        """
        changes = []

        # 1. Extract Siemens vendor-specific private tags (group 0019)
        # Design Section 5.3: Siemens stores critical imaging params in private group 0019
        if self._is_algorithm_enabled("pixel_spacing"):
            # Tag (0019,1008): Vendor-specific PixelSpacing (overrides standard 0028,0030)
            siemens_pixel_spacing = file_data.get("0019,1008")
            if siemens_pixel_spacing is not None:
                std_pixel_spacing = file_data.get("0028,0030")
                if not std_pixel_spacing:
                    file_data["0028,0030"] = siemens_pixel_spacing
                    changes.append(NormalizationChange(
                        tag="0028,0030",
                        original=None,
                        corrected=str(siemens_pixel_spacing),
                        rationale="Siemens: Extracted PixelSpacing from private tag (0019,1008)",
                        risk_level="safe"
                    ))

        if self._is_algorithm_enabled("photometric"):
            # Tag (0019,1010): Vendor-specific PhotometricInterpretation inference
            siemens_photometric_hint = file_data.get("0019,1010")
            if siemens_photometric_hint is not None and not file_data.get("0028,0004"):
                # Siemens encodes photometric info; map to standard DICOM values
                photometric = self._map_siemens_photometric(siemens_photometric_hint)
                if photometric:
                    file_data["0028,0004"] = photometric
                    changes.append(NormalizationChange(
                        tag="0028,0004",
                        original=None,
                        corrected=photometric,
                        rationale="Siemens: Inferred PhotometricInterpretation from private tag (0019,1010)",
                        risk_level="medium"
                    ))

        # 2. Instance Creation Date (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            if not file_data.get("0008,0012"):  # InstanceCreationDate
                file_data["0008,0012"] = file_data.get("0008,0020", "")  # StudyDate
                changes.append(NormalizationChange(
                    tag="0008,0012",
                    original=None,
                    corrected=file_data["0008,0012"],
                    rationale="Siemens: Added missing InstanceCreationDate from StudyDate",
                    risk_level="safe"
                ))

        # 3. Instance Creation Time (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            if not file_data.get("0008,0013"):  # InstanceCreationTime
                file_data["0008,0013"] = file_data.get("0008,0030", "000000")  # StudyTime
                changes.append(NormalizationChange(
                    tag="0008,0013",
                    original=None,
                    corrected=file_data["0008,0013"],
                    rationale="Siemens: Added missing InstanceCreationTime from StudyTime",
                    risk_level="safe"
                ))

        # 4. Manufacturer Model Name (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            if not file_data.get("0008,1090"):  # ManufacturerModelName
                # Common Siemens models - guess based on modality
                model = self._get_siemens_model_for_modality(file_data.get("0008,0060", ""))
                if model:
                    file_data["0008,1090"] = model
                    changes.append(NormalizationChange(
                        tag="0008,1090",
                        original=None,
                        corrected=model,
                        rationale="Siemens: Added manufacturer model based on modality",
                        risk_level="safe"
                    ))

        return changes

    def _map_siemens_photometric(self, hint: Any) -> Optional[str]:
        """
        Map Siemens private tag (0019,1010) photometric hint to standard DICOM value.

        Args:
            hint: Raw value from Siemens private tag

        Returns:
            Standard DICOM PhotometricInterpretation string or None
        """
        hint_str = str(hint).upper().strip()
        # Siemens commonly uses numeric codes or short strings
        if hint_str in ("RGB", "3", "COLOR"):
            return "RGB"
        if hint_str in ("MONO", "MONOCHROME", "1", "2", "MONOCHROME1"):
            return "MONOCHROME2"
        # Fallback: if hint contains 'YBR', treat as YBR_FULL
        if "YBR" in hint_str:
            return "YBR_FULL"
        return None

    def _get_siemens_model_for_modality(self, modality: str) -> Optional[str]:
        """Guess common Siemens model by modality."""
        models = {
            "CT": "SOMATOM",
            "MR": "MAGNETOM",
            "US": "ACUSON",
            "XC": "AXIOM",
        }
        return models.get(modality, "SIEMENS")


class GENormalizer(SupplierNormalizer):
    """Handle GE-specific DICOM deviations."""

    def detect_supplier(self, file_data: Dict[str, Any]) -> str:
        """Detect GE from manufacturer field."""
        manufacturer = file_data.get("0008,0070", "").upper()  # Manufacturer
        if "GE" in manufacturer or "GENERAL ELECTRIC" in manufacturer:
            return "ge"
        return "unknown"

    def normalize(self, file_data: Dict[str, Any]) -> list[NormalizationChange]:
        """
        Apply GE-specific normalizations.

        Key issues:
        - Series Date/Time sometimes inconsistent
        - Photometric interpretation missing in some sequences
        - Patient orientation edge cases
        - GE private tags in group 0019 and 0021 encode imaging parameters
        """
        changes = []

        # 1. Extract GE vendor-specific private tags
        # GE stores modality-specific data in private groups 0009, 0019, 0021, 0043
        if self._is_algorithm_enabled("pixel_spacing"):
            # GE private group 0019 may contain pixel spacing override
            ge_pixel_spacing = file_data.get("0019,1004") or file_data.get("0019,100C")
            if ge_pixel_spacing is not None and not file_data.get("0028,0030"):
                file_data["0028,0030"] = ge_pixel_spacing
                changes.append(NormalizationChange(
                    tag="0028,0030",
                    original=None,
                    corrected=str(ge_pixel_spacing),
                    rationale="GE: Extracted PixelSpacing from GE private tag",
                    risk_level="safe"
                ))

        if self._is_algorithm_enabled("photometric"):
            # GE: infer PhotometricInterpretation from JPEG SOF marker in pixel data
            if not file_data.get("0028,0004"):
                # Check if pixel data is available for JPEG SOF marker inspection
                pixel_data = file_data.get("7FE0,0010")
                photometric = None

                if pixel_data is not None:
                    photometric = self._infer_photometric_from_jpeg(pixel_data)

                # Fallback: infer from SamplesPerPixel
                if photometric is None:
                    spp = file_data.get("0028,0002", 1)
                    try:
                        photometric = "RGB" if int(spp) == 3 else "MONOCHROME2"
                    except (TypeError, ValueError):
                        photometric = "MONOCHROME2"

                handling = self._get_risk_handling("medium")
                if handling == "auto":
                    file_data["0028,0004"] = photometric
                    changes.append(NormalizationChange(
                        tag="0028,0004",
                        original=None,
                        corrected=photometric,
                        rationale=f"GE: Inferred PhotometricInterpretation={photometric} from JPEG markers/SamplesPerPixel",
                        risk_level="medium"
                    ))
                else:
                    changes.append(NormalizationChange(
                        tag="0028,0004",
                        original=None,
                        corrected=photometric,
                        rationale=f"GE: Inferred PhotometricInterpretation={photometric} (requires manual review)",
                        risk_level="medium"
                    ))

        # 2. Series Date consistency (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            study_date = file_data.get("0008,0020")  # StudyDate
            series_date = file_data.get("0008,0021")  # SeriesDate

            if study_date and not series_date:
                file_data["0008,0021"] = study_date
                changes.append(NormalizationChange(
                    tag="0008,0021",
                    original=None,
                    corrected=study_date,
                    rationale="GE: Added missing SeriesDate from StudyDate",
                    risk_level="safe"
                ))

        # 3. Series Time consistency (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            study_time = file_data.get("0008,0030")  # StudyTime
            series_time = file_data.get("0008,0031")  # SeriesTime

            if study_time and not series_time:
                file_data["0008,0031"] = study_time
                changes.append(NormalizationChange(
                    tag="0008,0031",
                    original=None,
                    corrected=study_time,
                    rationale="GE: Added missing SeriesTime from StudyTime",
                    risk_level="safe"
                ))

        return changes

    def _infer_photometric_from_jpeg(self, pixel_data: Any) -> Optional[str]:
        """
        Attempt to infer PhotometricInterpretation by inspecting JPEG SOF markers.

        JPEG SOF0/SOF2 marker encodes the number of components:
        - 1 component -> MONOCHROME2
        - 3 components -> YCbCr (which DICOM represents as YBR_FULL_422) or RGB

        Args:
            pixel_data: Raw pixel data bytes or encapsulated sequence

        Returns:
            Standard DICOM PhotometricInterpretation string or None
        """
        try:
            # Handle encapsulated pixel data (pydicom sequence)
            if hasattr(pixel_data, '__iter__') and not isinstance(pixel_data, (bytes, bytearray)):
                # Flatten first fragment
                raw = b"".join(bytes(frag) for frag in pixel_data if frag)
            else:
                raw = bytes(pixel_data)

            # Scan for JPEG SOF markers: FF C0 (SOF0) or FF C2 (SOF2)
            for i in range(len(raw) - 8):
                if raw[i] == 0xFF and raw[i + 1] in (0xC0, 0xC1, 0xC2, 0xC3):
                    # SOF marker found: [marker(2)][length(2)][precision(1)][height(2)][width(2)][components(1)]
                    num_components = raw[i + 9]
                    if num_components == 1:
                        return "MONOCHROME2"
                    elif num_components == 3:
                        return "YBR_FULL_422"
                    break
        except Exception:
            pass
        return None


class PhilipsNormalizer(SupplierNormalizer):
    """Handle Philips-specific DICOM deviations."""

    def detect_supplier(self, file_data: Dict[str, Any]) -> str:
        """Detect Philips from manufacturer field."""
        manufacturer = file_data.get("0008,0070", "").upper()  # Manufacturer
        if "PHILIPS" in manufacturer:
            return "philips"
        return "unknown"

    def normalize(self, file_data: Dict[str, Any]) -> list[NormalizationChange]:
        """
        Apply Philips-specific normalizations.

        Key issues:
        - Content date/time sometimes duplicated
        - Pixel spacing issues in certain modalities
        - Missing series descriptions
        - Philips private tags in group 2001 encode imaging parameters
        - JPEG compression artifacts from non-standard Philips export
        """
        changes = []

        # 1. Extract Philips vendor-specific private tags (primary group: 2001)
        # Philips uses groups 2001, 2005, 2050 for private imaging metadata
        if self._is_algorithm_enabled("pixel_spacing"):
            # Philips private group 2001 may carry pixel size
            philips_pixel_size = file_data.get("2001,1026") or file_data.get("2001,1024")
            if philips_pixel_size is not None and not file_data.get("0028,0030"):
                file_data["0028,0030"] = philips_pixel_size
                changes.append(NormalizationChange(
                    tag="0028,0030",
                    original=None,
                    corrected=str(philips_pixel_size),
                    rationale="Philips: Extracted PixelSpacing from Philips private tag (2001,102x)",
                    risk_level="safe"
                ))

        if self._is_algorithm_enabled("photometric"):
            # Detect JPEG artifacts from Philips non-standard export
            # Philips MR systems sometimes export JPEG-compressed data without proper
            # PhotometricInterpretation, causing display issues
            jpeg_artifact = self._detect_philips_jpeg_artifact(file_data)
            if jpeg_artifact and not file_data.get("0028,0004"):
                file_data["0028,0004"] = jpeg_artifact
                changes.append(NormalizationChange(
                    tag="0028,0004",
                    original=None,
                    corrected=jpeg_artifact,
                    rationale="Philips: Corrected PhotometricInterpretation based on JPEG artifact detection",
                    risk_level="medium"
                ))

        # 2. Content Date (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            if not file_data.get("0008,0023"):  # ContentDate
                file_data["0008,0023"] = file_data.get("0008,0020", "")  # StudyDate
                changes.append(NormalizationChange(
                    tag="0008,0023",
                    original=None,
                    corrected=file_data["0008,0023"],
                    rationale="Philips: Added missing ContentDate from StudyDate",
                    risk_level="safe"
                ))

        # 3. Content Time (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            if not file_data.get("0008,0033"):  # ContentTime
                file_data["0008,0033"] = file_data.get("0008,0030", "000000")  # StudyTime
                changes.append(NormalizationChange(
                    tag="0008,0033",
                    original=None,
                    corrected=file_data["0008,0033"],
                    rationale="Philips: Added missing ContentTime from StudyTime",
                    risk_level="safe"
                ))

        # 4. Series Description (Safe)
        if self._is_algorithm_enabled("missing_tags"):
            if not file_data.get("0008,103e"):  # SeriesDescription
                modality = file_data.get("0008,0060", "UNKNOWN")
                description = f"{modality} Series"
                file_data["0008,103e"] = description
                changes.append(NormalizationChange(
                    tag="0008,103e",
                    original=None,
                    corrected=description,
                    rationale="Philips: Added generic SeriesDescription",
                    risk_level="safe"
                ))

        return changes

    def _detect_philips_jpeg_artifact(self, file_data: Dict[str, Any]) -> Optional[str]:
        """
        Detect Philips-specific JPEG artifact and suggest correct PhotometricInterpretation.

        Philips MR/CT systems sometimes write JPEG-compressed pixel data with
        mismatched or missing PhotometricInterpretation. This method checks for
        signals indicating the presence of this artifact.

        Args:
            file_data: DICOM tags dict

        Returns:
            Suggested PhotometricInterpretation or None if no artifact detected
        """
        # Check transfer syntax for JPEG-based encoding
        transfer_syntax = file_data.get("0002,0010", "")
        jpeg_transfer_syntaxes = {
            "1.2.840.10008.1.2.4.50",   # JPEG Baseline
            "1.2.840.10008.1.2.4.51",   # JPEG Extended
            "1.2.840.10008.1.2.4.57",   # JPEG Lossless
            "1.2.840.10008.1.2.4.70",   # JPEG Lossless SV1
        }

        is_jpeg = str(transfer_syntax) in jpeg_transfer_syntaxes

        if is_jpeg:
            # For JPEG-encoded Philips data, SamplesPerPixel is the reliable indicator
            spp = file_data.get("0028,0002", 1)
            try:
                spp_int = int(spp)
            except (TypeError, ValueError):
                spp_int = 1

            if spp_int == 1:
                return "MONOCHROME2"
            elif spp_int == 3:
                # JPEG baseline uses YCbCr in DICOM
                return "YBR_FULL_422"

        return None


class DefaultNormalizer(SupplierNormalizer):
    """Fallback normalizer for unknown suppliers."""

    def detect_supplier(self, file_data: Dict[str, Any]) -> str:
        """Always returns 'default'."""
        return "default"

    def normalize(self, file_data: Dict[str, Any]) -> list[NormalizationChange]:
        """
        Apply basic DICOM normalizations for any supplier.

        Handles standard missing mandatory fields.
        """
        changes = []

        # Standard DICOM 1.0 missing fields
        if self._is_algorithm_enabled("missing_tags"):
            # Patient Birth Date (Safe - use placeholder if missing)
            if not file_data.get("0010,0030"):  # PatientBirthDate
                file_data["0010,0030"] = "00000000"
                changes.append(NormalizationChange(
                    tag="0010,0030",
                    original=None,
                    corrected="00000000",
                    rationale="Default: Added placeholder PatientBirthDate",
                    risk_level="safe"
                ))

            # Patient Sex (Safe - use 'O' for other)
            if not file_data.get("0010,0040"):  # PatientSex
                file_data["0010,0040"] = "O"
                changes.append(NormalizationChange(
                    tag="0010,0040",
                    original=None,
                    corrected="O",
                    rationale="Default: Added placeholder PatientSex",
                    risk_level="safe"
                ))

            # Study Date (Safe - from acquisition)
            if not file_data.get("0008,0020"):  # StudyDate
                acq_date = file_data.get("0008,0022", "")  # AcquisitionDate
                if acq_date:
                    file_data["0008,0020"] = acq_date
                    changes.append(NormalizationChange(
                        tag="0008,0020",
                        original=None,
                        corrected=acq_date,
                        rationale="Default: Added StudyDate from AcquisitionDate",
                        risk_level="safe"
                    ))

            # Study Time (Safe - from acquisition)
            if not file_data.get("0008,0030"):  # StudyTime
                acq_time = file_data.get("0008,0032", "000000")  # AcquisitionTime
                file_data["0008,0030"] = acq_time
                changes.append(NormalizationChange(
                    tag="0008,0030",
                    original=None,
                    corrected=acq_time,
                    rationale="Default: Added StudyTime from AcquisitionTime",
                    risk_level="safe"
                ))

        return changes


def get_normalizer_for_supplier(
    supplier: str,
    config: NormalizationConfig,
) -> SupplierNormalizer:
    """
    Factory function to get appropriate normalizer.

    Args:
        supplier: Supplier name (siemens, ge, philips, default)
        config: NormalizationConfig for modality

    Returns:
        Appropriate SupplierNormalizer instance
    """
    normalizers = {
        "siemens": SiemensNormalizer,
        "ge": GENormalizer,
        "philips": PhilipsNormalizer,
        "default": DefaultNormalizer,
    }

    normalizer_class = normalizers.get(supplier.lower(), DefaultNormalizer)
    return normalizer_class(config, supplier)
