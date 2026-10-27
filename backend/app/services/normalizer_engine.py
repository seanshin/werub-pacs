"""Main DICOM normalization engine orchestrating supplier-specific normalizers."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
import io

from sqlalchemy.ext.asyncio import AsyncSession
import pydicom
from pydicom.errors import InvalidDicomError

from app.models.batch_job import BatchJobFile, NormalizationConfig
from app.services.supplier_normalizer import (
    get_normalizer_for_supplier,
    NormalizationChange,
)
from app.services.config_service import ConfigService
from app.core.exceptions import DicomNormalizationError as DicomProcessingError

# ---------------------------------------------------------------------------
# DICOM magic byte constants
# ---------------------------------------------------------------------------
# Standard DICOM Part 10 files have a 128-byte preamble followed by "DICM".
_DICOM_PREAMBLE_LEN = 128
_DICOM_MAGIC = b"DICM"
_DICOM_MAGIC_OFFSET = _DICOM_PREAMBLE_LEN


def validate_dicom_magic_bytes(data: bytes, filename: str = "<unknown>") -> None:
    """Raise :class:`DicomProcessingError` if *data* lacks the DICOM magic bytes.

    The DICOM standard (PS 3.10 §7.1) requires all Part 10 files to contain
    the four bytes ``DICM`` at offset 128.  Files produced by non-standard
    devices may omit this preamble; pydicom can still parse them with
    ``force=True``, but we surface the issue here so callers can decide
    whether to proceed or reject.

    Args:
        data: Raw file bytes to check.
        filename: Filename used in the error message.

    Raises:
        DicomProcessingError: When the DICOM magic bytes are absent.
    """
    if len(data) < _DICOM_MAGIC_OFFSET + 4:
        raise DicomProcessingError(
            f"File '{filename}' is too short to be a valid DICOM file "
            f"(need ≥132 bytes, got {len(data)})",
            details={"filename": filename, "size": len(data)},
        )
    magic = data[_DICOM_MAGIC_OFFSET: _DICOM_MAGIC_OFFSET + 4]
    if magic != _DICOM_MAGIC:
        raise DicomProcessingError(
            f"File '{filename}' is missing the DICOM magic bytes at offset 128 "
            f"(found {magic!r}, expected b'DICM')",
            details={"filename": filename, "found_magic": magic.hex()},
        )


def has_dicom_magic_bytes(data: bytes) -> bool:
    """Return *True* when *data* contains the standard DICOM magic bytes.

    Unlike :func:`validate_dicom_magic_bytes`, this function does **not**
    raise; it is intended for use in conditional checks.

    Args:
        data: Raw file bytes to inspect.

    Returns:
        ``True`` if the DICM preamble is present, ``False`` otherwise.
    """
    return (
        len(data) >= _DICOM_MAGIC_OFFSET + 4
        and data[_DICOM_MAGIC_OFFSET: _DICOM_MAGIC_OFFSET + 4] == _DICOM_MAGIC
    )


@dataclass
class NormalizationResult:
    """Result of normalizing a single DICOM file."""
    file_id: str
    filename: str
    applied: bool  # Whether normalization was actually applied to file
    detected_supplier: str
    changes: list[dict]  # List of NormalizationChange serialized
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return asdict(self)


class NormalizerEngine:
    """Orchestrate DICOM normalization across suppliers and algorithms."""

    def __init__(self, session: AsyncSession):
        """
        Initialize engine.

        Args:
            session: Database session for config lookups
        """
        self.session = session

    async def normalize_dicom(
        self,
        file_id: str,
        filename: str,
        dicom_bytes: bytes,
        modality: str,
        auto_normalize: bool = False,
    ) -> NormalizationResult:
        """
        Normalize a DICOM file using supplier-specific rules.

        Args:
            file_id: BatchJobFile ID
            filename: Original filename
            dicom_bytes: Raw DICOM file bytes
            modality: DICOM modality (CT, MR, etc.)
            auto_normalize: Whether to apply SAFE changes automatically

        Returns:
            NormalizationResult with changes and status
        """
        start_time = datetime.now(timezone.utc)

        try:
            # 1. Validate DICOM magic bytes (preamble check before parse)
            if not has_dicom_magic_bytes(dicom_bytes):
                # Non-standard DICOM: log a warning and attempt to parse anyway
                # (some legacy devices omit the preamble but produce valid datasets)
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"File '{filename}' is missing DICOM magic bytes — "
                    "attempting to parse as implicit-VR DICOM (force=True)"
                )

            # 2. Load DICOM file
            try:
                dcm = pydicom.dcmread(io.BytesIO(dicom_bytes), force=True)
            except InvalidDicomError as e:
                return NormalizationResult(
                    file_id=file_id,
                    filename=filename,
                    applied=False,
                    detected_supplier="unknown",
                    changes=[],
                    error=f"Invalid DICOM file: {str(e)}",
                    elapsed_ms=self._elapsed_ms(start_time),
                )

            # 3. Extract relevant DICOM tags
            file_data = self._extract_dicom_tags(dcm)

            # 4. Get modality configuration
            config = await ConfigService.get_modality_config(
                self.session,
                modality,
                use_cache=True,
            )

            if not config:
                # Use default settings
                config = self._get_default_config(modality)

            # 5. Detect supplier
            detected_supplier = self._detect_supplier(file_data, dcm)

            # 6. Get appropriate normalizer
            normalizer = get_normalizer_for_supplier(detected_supplier, config)

            # 7. Apply normalization
            changes = normalizer.normalize(file_data)

            # 8. Determine which changes to apply
            applied_changes = []
            actually_applied = False

            if auto_normalize:
                for change in changes:
                    handling = config.risk_tiers.get(change.risk_level, "reject")

                    if handling == "auto":
                        # Apply the change to the file
                        self._apply_change_to_dicom(dcm, change)
                        applied_changes.append(change)
                        actually_applied = True
                    else:
                        # Log but don't apply
                        applied_changes.append(change)
            else:
                # auto_normalize=false: log all changes but don't apply
                applied_changes = changes

            # 9. Convert changes to serializable format
            serialized_changes = [
                {
                    "tag": c.tag,
                    "original": str(c.original) if c.original is not None else None,
                    "corrected": str(c.corrected) if c.corrected is not None else None,
                    "rationale": c.rationale,
                    "risk_level": c.risk_level,
                }
                for c in applied_changes
            ]

            return NormalizationResult(
                file_id=file_id,
                filename=filename,
                applied=actually_applied,
                detected_supplier=detected_supplier,
                changes=serialized_changes,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        except Exception as e:
            return NormalizationResult(
                file_id=file_id,
                filename=filename,
                applied=False,
                detected_supplier="unknown",
                changes=[],
                error=f"Normalization error: {str(e)}",
                elapsed_ms=self._elapsed_ms(start_time),
            )

    def _extract_dicom_tags(self, dcm: pydicom.Dataset) -> dict:
        """
        Extract relevant DICOM tags as a dict, including vendor-specific private tags.

        Args:
            dcm: Loaded DICOM dataset

        Returns:
            Dict with tag numbers as keys (e.g., "0008,0020")
        """
        tags = {}

        # List of standard tags to extract (covering common fields)
        tag_list = [
            # Patient
            (0x0010, 0x0010),  # PatientName
            (0x0010, 0x0020),  # PatientID
            (0x0010, 0x0030),  # PatientBirthDate
            (0x0010, 0x0040),  # PatientSex
            # Study
            (0x0008, 0x0020),  # StudyDate
            (0x0008, 0x0030),  # StudyTime
            (0x0008, 0x0050),  # AccessionNumber
            (0x0008, 0x1030),  # StudyDescription
            # Series
            (0x0008, 0x0021),  # SeriesDate
            (0x0008, 0x0031),  # SeriesTime
            (0x0008, 0x103e),  # SeriesDescription
            (0x0020, 0x000e),  # SeriesInstanceUID
            (0x0008, 0x0060),  # Modality
            # Instance
            (0x0008, 0x0012),  # InstanceCreationDate
            (0x0008, 0x0013),  # InstanceCreationTime
            (0x0008, 0x0022),  # AcquisitionDate
            (0x0008, 0x0032),  # AcquisitionTime
            (0x0008, 0x0023),  # ContentDate
            (0x0008, 0x0033),  # ContentTime
            (0x0020, 0x000d),  # StudyInstanceUID
            (0x0020, 0x0010),  # PatientOrientation
            # Equipment
            (0x0008, 0x0070),  # Manufacturer
            (0x0008, 0x1090),  # ManufacturerModelName
            (0x0008, 0x1010),  # StationName
            # Image
            (0x0028, 0x0002),  # SamplesPerPixel
            (0x0028, 0x0004),  # PhotometricInterpretation
            (0x0028, 0x0008),  # NumberOfFrames
            (0x0028, 0x0030),  # PixelSpacing
            (0x7FE0, 0x0010),  # PixelData (for JPEG marker inspection)
        ]

        # Extract standard tags
        for group, element in tag_list:
            tag = (group, element)
            if tag in dcm:
                value = dcm[tag].value
                # Convert to string-friendly format
                tags[f"{group:04X},{element:04X}"] = value

        # Extract vendor-specific private tags (critical for supplier normalizers)
        # Siemens: group 0019, 0021
        # GE: group 0009, 0019, 0021, 0043
        # Philips: group 2001, 2005
        # K8: 39만회(6그룹×65536) 전수 순회 → 실제 존재 element 단일 순회(인스턴스당 수십회)
        private_groups = {0x0009, 0x0019, 0x0021, 0x0043, 0x2001, 0x2005}

        for elem in dcm:
            if elem.tag.group in private_groups:
                try:
                    tags[f"{elem.tag.group:04X},{elem.tag.element:04X}"] = elem.value
                except Exception:
                    continue

        return tags

    def _detect_supplier(self, file_data: dict, dcm: pydicom.Dataset) -> str:
        """
        Detect equipment supplier from DICOM file.

        Args:
            file_data: Extracted tags dict
            dcm: Full DICOM dataset (fallback)

        Returns:
            Supplier name (siemens, ge, philips, default)
        """
        # Check Manufacturer field
        manufacturer = file_data.get("0008,0070", "").upper()

        if "SIEMENS" in manufacturer:
            return "siemens"
        elif "GE" in manufacturer or "GENERAL ELECTRIC" in manufacturer:
            return "ge"
        elif "PHILIPS" in manufacturer or "KONINKLIJKE" in manufacturer:
            return "philips"

        # Fallback to default
        return "default"

    def _apply_change_to_dicom(
        self,
        dcm: pydicom.Dataset,
        change: NormalizationChange,
    ) -> None:
        """
        Apply a single normalization change to DICOM file.

        Args:
            dcm: DICOM dataset to modify
            change: NormalizationChange to apply
        """
        # Parse tag (e.g., "0008,0020" -> (0x0008, 0x0020))
        parts = change.tag.split(",")
        group = int(parts[0], 16)
        element = int(parts[1], 16)
        tag = (group, element)

        # Set the tag value
        if tag in dcm:
            # Update existing
            dcm[tag].value = change.corrected
        else:
            # Add new tag
            # Determine VR based on tag
            vr = self._guess_vr_for_tag(tag)
            dcm.add_new(tag, vr, change.corrected)

    def _guess_vr_for_tag(self, tag: tuple) -> str:
        """
        Guess Value Representation for a tag.

        Args:
            tag: DICOM tag tuple (group, element)

        Returns:
            VR string (e.g., "DA", "TM", "UI", "LO")
        """
        group, element = tag

        # Date tags
        if element in (0x0020, 0x0021, 0x0022, 0x0023):
            return "DA"
        # Time tags
        if element in (0x0030, 0x0031, 0x0032, 0x0033):
            return "TM"
        # UID tags
        if element in (0x000d, 0x000e):
            return "UI"
        # Default to Long String
        return "LO"

    def _get_default_config(self, modality: str) -> NormalizationConfig:
        """
        Create default config when none exists in database.

        Args:
            modality: DICOM modality

        Returns:
            Default NormalizationConfig
        """
        return NormalizationConfig(
            modality=modality,
            algorithms={
                "pixel_spacing": True,
                "missing_tags": True,
                "photometric": False,
                "charset": True,
            },
            risk_tiers={
                "safe": "auto",
                "medium": "manual",
                "risky": "reject",
            },
        )

    @staticmethod
    def _elapsed_ms(start_time: datetime) -> float:
        """Calculate elapsed time in milliseconds."""
        elapsed = datetime.now(timezone.utc) - start_time
        return elapsed.total_seconds() * 1000.0
