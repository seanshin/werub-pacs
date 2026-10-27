"""Store AI inference results as standards-compliant DICOM in Orthanc.

Thin wrapper over :mod:`app.services.dicom_ai_standard`, which builds a
TID 1500 Comprehensive SR (and, when a mask is available, a DICOM SEG) using
the highdicom reference library. Kept for backward-compatible call sites.
"""
import logging

from pydicom.dataset import Dataset

from app.services.dicom_ai_standard import build_ai_sr

logger = logging.getLogger(__name__)

# Segmentation / Comprehensive SR SOP Class UIDs (for reference by callers)
COMPREHENSIVE_SR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.88.33"


def create_ai_sr(
    study_instance_uid: str,
    patient_id: str,
    patient_name: str,
    modality: str,
    model_name: str,
    model_version: str,
    findings: list[dict],
    inference_time_ms: int | None = None,
    is_critical: bool = False,
    source_images: list[Dataset | bytes] | None = None,
) -> bytes:
    """Create a standard TID 1500 SR from AI results. Returns DICOM bytes.

    ``source_images`` (the analyzed image(s), as pydicom Datasets or DICOM bytes)
    is required by the standard: patient/study identity and the evidence sequence
    are derived from it. Patient/study/modality string args are retained for
    backward compatibility but are now sourced from the evidence images.
    """
    if not source_images:
        raise ValueError(
            "create_ai_sr now requires source_images (TID 1500 evidence). "
            "Pass the analyzed DICOM instance(s)."
        )
    return build_ai_sr(
        source_images=source_images,
        model_name=model_name,
        model_version=model_version,
        findings=findings,
        inference_time_ms=inference_time_ms,
        is_critical=is_critical,
    )


async def store_ai_result_as_sr(
    orthanc_client,
    study_instance_uid: str,
    patient_id: str,
    patient_name: str,
    modality: str,
    model_name: str,
    model_version: str,
    findings: list[dict],
    inference_time_ms: int | None = None,
    is_critical: bool = False,
    source_images: list[Dataset | bytes] | None = None,
) -> dict | None:
    """Create a standard DICOM SR from AI results and store it in Orthanc.

    Returns the Orthanc response dict, or None on failure.
    """
    try:
        sr_bytes = create_ai_sr(
            study_instance_uid=study_instance_uid,
            patient_id=patient_id,
            patient_name=patient_name,
            modality=modality,
            model_name=model_name,
            model_version=model_version,
            findings=findings,
            inference_time_ms=inference_time_ms,
            is_critical=is_critical,
            source_images=source_images,
        )
        resp = orthanc_client.post(
            "/instances",
            content=sr_bytes,
            headers={"Content-Type": "application/dicom"},
        )
        if resp.status_code in (200, 409):
            result = resp.json()
            logger.info(f"AI SR stored: {result.get('ID')}")
            return result
        logger.error(f"Failed to store AI SR: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"Error creating/storing AI SR: {e}")
        return None
