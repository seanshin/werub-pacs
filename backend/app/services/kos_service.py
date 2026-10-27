"""Key Object Selection (KOS) document generation.

Builds a standard DICOM Key Object Selection Document (SOP Class
1.2.840.10008.5.1.4.1.1.88.59) referencing radiologist-marked "key images" so
they are discoverable by any DICOM viewer. Fills the conformance-statement gap
where KOS was accepted (Storage SCP) but not generated.
"""
from __future__ import annotations

import io

from highdicom.ko import KeyObjectSelection, KeyObjectSelectionDocument
from pydicom import dcmread
from pydicom.uid import generate_uid

try:
    from pydicom.sr.codedict import codes
    _DEFAULT_TITLE = codes.DCM.OfInterest  # (113000, DCM, "Of Interest")
except Exception:  # pragma: no cover - fallback if code lookup changes
    import highdicom as hd
    _DEFAULT_TITLE = hd.sr.CodedConcept("113000", "DCM", "Of Interest")


def build_kos(
    referenced_dicom_bytes: list[bytes],
    *,
    description: str | None = None,
    title=None,
    series_number: int = 9100,
    instance_number: int = 1,
) -> bytes:
    """Build a KOS document referencing the given (key image) DICOM instances.

    All referenced instances must belong to the same study.
    """
    datasets = [dcmread(io.BytesIO(b)) for b in referenced_dicom_bytes]
    if not datasets:
        raise ValueError("KOS requires at least one referenced image")

    content = KeyObjectSelection(
        document_title=title or _DEFAULT_TITLE,
        referenced_objects=datasets,
        description=description,
    )
    kos = KeyObjectSelectionDocument(
        evidence=datasets,
        content=content,
        series_instance_uid=generate_uid(),
        series_number=series_number,
        sop_instance_uid=generate_uid(),
        instance_number=instance_number,
        manufacturer="OpenPACS",
        institution_name="WeRU.B",
    )

    buf = io.BytesIO()
    kos.save_as(buf)
    return buf.getvalue()
