"""Standards-compliant DICOM encoding of AI results (SR + SEG).

Builds international-standard DICOM objects for AI inference output using the
`highdicom` reference library:

- **SR**: Comprehensive SR (1.2.840.10008.5.1.4.1.1.88.33) following **TID 1500**
  (Measurement Report) — AI algorithm as Device Observer (TID 1004), per-finding
  measurement groups with DCM-coded confidence (Probability, DCM 122157) and
  source-image references, and a Current Requested Procedure Evidence Sequence
  linking back to the analyzed images.
- **SEG**: Segmentation (1.2.840.10008.5.1.4.1.1.66.4) with proper segment
  descriptors, algorithm identification, and source-image / frame-of-reference
  linkage.

Replaces the earlier hand-rolled, non-conformant builders (fabricated DCM code
values, no TID template, no evidence sequence). Concepts without a standard
DICOM code are encoded under the private coding scheme ``99OPENPACS`` — the
DICOM-conformant mechanism for local concepts (PS3.16), rather than mislabeling
real DCM codes.
"""
from __future__ import annotations

import io
import logging
from typing import Sequence

import numpy as np
from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.sr.codedict import codes
from pydicom.uid import generate_uid

import highdicom as hd

logger = logging.getLogger(__name__)

PRIVATE_SCHEME = "99OPENPACS"
_MANUFACTURER = "WeRU.B PACS"

# Severity → private coded value (no standard DICOM context group fits AI severity)
_SEVERITY_CODES = {
    "critical": ("CRIT", "Critical finding"),
    "warning": ("WARN", "Warning"),
    "normal": ("NORMAL", "Normal"),
    "info": ("INFO", "Information"),
}


# Type-2 (present, may be empty) attributes highdicom copies from evidence.
# Real DICOM normally carries these, but C-STORE images of varying conformance
# may omit them — ensure they exist so standard-object creation never crashes.
_TYPE2_DEFAULTS = {
    "AccessionNumber": "",
    "StudyID": "",
    "StudyDate": "",
    "StudyTime": "",
    "ReferringPhysicianName": "",
}


def _as_source_datasets(source_images: Sequence[Dataset | bytes]) -> list[Dataset]:
    """Accept pydicom Datasets or raw DICOM bytes; return Datasets with the
    Type-2 attributes highdicom requires ensured present."""
    out: list[Dataset] = []
    for s in source_images:
        ds = s if isinstance(s, Dataset) else dcmread(io.BytesIO(s))
        for attr, default in _TYPE2_DEFAULTS.items():
            if attr not in ds:
                setattr(ds, attr, default)
        out.append(ds)
    return out


def build_ai_sr(
    source_images: Sequence[Dataset | bytes],
    model_name: str,
    model_version: str,
    findings: list[dict],
    inference_time_ms: int | None = None,
    is_critical: bool = False,
    sop_instance_uid: str | None = None,
    series_instance_uid: str | None = None,
) -> bytes:
    """Build a TID 1500 Comprehensive SR from AI findings. Returns DICOM bytes.

    Args:
        source_images: analyzed source image(s) (pydicom Dataset or DICOM bytes).
            Patient/Study identity and the evidence sequence are derived from these.
        model_name / model_version: the AI algorithm (encoded as Device Observer).
        findings: list of dicts with keys description, confidence (0-1), severity.
    """
    if not source_images:
        raise ValueError("build_ai_sr requires at least one source image (TID 1500 evidence)")
    sources = _as_source_datasets(source_images)
    ref = sources[0]

    observer = hd.sr.ObserverContext(
        observer_type=codes.DCM.Device,
        observer_identifying_attributes=hd.sr.DeviceObserverIdentifyingAttributes(
            uid=hd.UID(),
            name=model_name,
            manufacturer_name=_MANUFACTURER,
            model_name=f"{model_name} v{model_version}",
        ),
    )
    observation_context = hd.sr.ObservationContext(observer_device_context=observer)
    algorithm_id = hd.sr.AlgorithmIdentification(name=model_name, version=model_version)

    # TID 1500 requires at least one measurement group; represent "no findings"
    # truthfully rather than emitting an empty/invalid report.
    effective_findings = findings or [
        {"description": "No significant findings reported", "severity": "normal"}
    ]

    groups: list[hd.sr.MeasurementsAndQualitativeEvaluations] = []
    for finding in effective_findings:
        description = str(finding.get("description", "AI finding"))
        confidence = float(finding.get("confidence", 0) or 0)
        severity = str(finding.get("severity", "info")).lower()
        sev_value, sev_meaning = _SEVERITY_CODES.get(severity, _SEVERITY_CODES["info"])

        evaluations = [
            hd.sr.QualitativeEvaluation(
                name=hd.sr.CodedConcept("110001", PRIVATE_SCHEME, "Severity"),
                value=hd.sr.CodedConcept(sev_value, PRIVATE_SCHEME, sev_meaning),
            )
        ]
        # Encode confidence as DCM-coded Probability (%) only when meaningful.
        measurements = None
        if confidence > 0:
            measurements = [
                hd.sr.Measurement(
                    name=codes.DCM.Probability,
                    value=round(confidence * 100, 1),
                    unit=codes.UCUM.Percent,
                )
            ]
        groups.append(
            hd.sr.MeasurementsAndQualitativeEvaluations(
                tracking_identifier=hd.sr.TrackingIdentifier(
                    uid=hd.UID(), identifier=description[:64]
                ),
                finding_type=codes.DCM.Finding,
                algorithm_id=algorithm_id,
                measurements=measurements,
                qualitative_evaluations=evaluations,
                source_images=[
                    hd.sr.SourceImageForMeasurementGroup(
                        referenced_sop_class_uid=ref.SOPClassUID,
                        referenced_sop_instance_uid=ref.SOPInstanceUID,
                    )
                ],
            )
        )

    report = hd.sr.MeasurementReport(
        observation_context=observation_context,
        procedure_reported=hd.sr.CodedConcept("363679005", "SCT", "Imaging"),
        imaging_measurements=groups,
        title=codes.DCM.ImagingMeasurementReport,
    )

    sr_doc = hd.sr.ComprehensiveSR(
        evidence=sources,
        content=report[0],
        # Deterministic UIDs (derived from the job) when provided → a retried
        # inference re-creates the SAME SR, which Orthanc dedups (409) instead of
        # storing a duplicate. Falls back to random for ad-hoc callers.
        series_instance_uid=series_instance_uid or generate_uid(),
        series_number=9000,
        sop_instance_uid=sop_instance_uid or generate_uid(),
        instance_number=1,
        manufacturer=_MANUFACTURER,
        is_complete=True,
        is_verified=False,
        institution_name="WeRU.B AI",
    )
    buf = io.BytesIO()
    sr_doc.save_as(buf)
    buf.seek(0)
    logger.info(
        "Built standard TID 1500 SR",
        extra={"model": model_name, "findings": len(findings), "is_critical": is_critical},
    )
    return buf.read()


def build_text_sr(
    source_images: Sequence[Dataset | bytes],
    findings: str = "",
    impression: str = "",
    title: str = "AI 판독 리포트",
    manufacturer_model: str = "WeRU.B Reading",
) -> bytes:
    """Build a standards-compliant Comprehensive SR (free-text) from a manual/AI
    reading. Returns DICOM bytes.

    Unlike :func:`build_ai_sr` (TID 1500 measurement report), this encodes free
    radiology text (findings/impression) as TEXT content items — the right
    structure for the viewer's "save as SR" action, which has no spatial
    measurements. UTF-8 (ISO_IR 192) is forced so Korean text survives.
    """
    if not source_images:
        raise ValueError("build_text_sr requires at least one source image (evidence)")
    sources = _as_source_datasets(source_images)

    rel = hd.sr.RelationshipTypeValues.CONTAINS
    items = []
    if findings:
        items.append(hd.sr.TextContentItem(name=codes.DCM.Finding, value=findings, relationship_type=rel))
    if impression:
        items.append(
            hd.sr.TextContentItem(
                name=hd.sr.CodedConcept("IMPRESSION", PRIVATE_SCHEME, "Impression"),
                value=impression,
                relationship_type=rel,
            )
        )
    if not items:
        items.append(hd.sr.TextContentItem(name=codes.DCM.Finding, value="(내용 없음)", relationship_type=rel))

    container = hd.sr.ContainerContentItem(name=hd.sr.CodedConcept("126000", "DCM", "Imaging Report"))
    container.ContentSequence = items

    doc = hd.sr.ComprehensiveSR(
        evidence=sources,
        content=container,
        series_instance_uid=generate_uid(),
        series_number=9001,
        sop_instance_uid=generate_uid(),
        instance_number=1,
        manufacturer=_MANUFACTURER,
        is_complete=True,
        is_verified=False,
        institution_name="WeRU.B AI",
    )
    doc.SpecificCharacterSet = "ISO_IR 192"  # UTF-8 — preserve Korean
    if title:
        doc.SeriesDescription = title
    buf = io.BytesIO()
    doc.save_as(buf)
    buf.seek(0)
    logger.info("Built standard text SR", extra={"has_findings": bool(findings)})
    return buf.read()


def build_ai_seg(
    source_images: Sequence[Dataset | bytes],
    mask: np.ndarray,
    model_name: str,
    model_version: str,
    segment_label: str = "AI Segmentation",
    segmented_property_category=None,
    segmented_property_type=None,
) -> bytes:
    """Build a standards-compliant DICOM SEG from a binary/label mask.

    Args:
        source_images: source image(s) the mask was computed on.
        mask: (rows, cols) or (frames, rows, cols) integer/boolean mask.
        segmented_property_category/type: SCT coded concepts describing the
            segmented structure (defaults to abnormal-structure / lesion).
    """
    if not source_images:
        raise ValueError("build_ai_seg requires at least one source image")
    sources = _as_source_datasets(source_images)

    category = segmented_property_category or codes.SCT.MorphologicallyAbnormalStructure
    ptype = segmented_property_type or codes.SCT.Lesion

    seg = hd.seg.Segmentation(
        source_images=sources,
        pixel_array=mask.astype(np.uint8),
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=[
            hd.seg.SegmentDescription(
                segment_number=1,
                segment_label=segment_label,
                segmented_property_category=category,
                segmented_property_type=ptype,
                algorithm_type=hd.seg.SegmentAlgorithmTypeValues.AUTOMATIC,
                algorithm_identification=hd.content.AlgorithmIdentificationSequence(
                    name=model_name,
                    family=codes.DCM.ArtificialIntelligence,
                    version=model_version,
                ),
            )
        ],
        series_instance_uid=generate_uid(),
        series_number=9100,
        sop_instance_uid=generate_uid(),
        instance_number=1,
        manufacturer=_MANUFACTURER,
        manufacturer_model_name=model_name,
        software_versions=model_version,
        device_serial_number="WERUB-AI-PIPELINE",
        content_label="AI_SEG",
    )
    buf = io.BytesIO()
    seg.save_as(buf)
    buf.seek(0)
    logger.info("Built standard SEG", extra={"model": model_name, "label": segment_label})
    return buf.read()
