"""Prior study lookup — shared by the Prior Studies API and the prefetch worker.

Finds previous studies of the same patient via Orthanc /tools/find,
sorted most-recent first.
"""
import logging

logger = logging.getLogger(__name__)


async def find_priors(
    orthanc,
    study_uid: str,
    max_results: int = 10,
    same_modality: bool = False,
) -> dict:
    """Return prior studies for the patient owning `study_uid`.

    `orthanc` is an httpx.AsyncClient bound to the Orthanc base URL.
    Raises LookupError when the study does not exist; other Orthanc failures
    degrade to an empty prior list (reading must not break on lookup errors).
    """
    resp = await orthanc.post("/tools/find", json={
        "Level": "Study",
        "Query": {"StudyInstanceUID": study_uid},
        "Expand": True,
        "RequestedTags": ["ModalitiesInStudy"],   # MainDicomTags엔 없음 → RequestedTags로만
    })
    if resp.status_code != 200 or not resp.json():
        raise LookupError(f"Study {study_uid} not found")

    current_study = resp.json()[0]
    patient_id = current_study.get("PatientMainDicomTags", {}).get("PatientID", "")
    current_date = current_study.get("MainDicomTags", {}).get("StudyDate", "")
    current_modality = current_study.get("RequestedTags", {}).get("ModalitiesInStudy", "")

    base = {
        "study_uid": study_uid,
        "patient_id": patient_id,
        "current_date": current_date,
        "current_modality": current_modality,
        "priors": [],
    }
    if not patient_id:
        base["message"] = "PatientID not available"
        return base

    try:
        resp = await orthanc.post("/tools/find", json={
            "Level": "Study",
            "Query": {"PatientID": patient_id},
            "Expand": True,
            "RequestedTags": ["ModalitiesInStudy"],
        })
        all_studies = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        logger.error(f"Failed to find patient studies: {e}")
        return base

    priors = []
    for s in all_studies:
        s_uid = s.get("MainDicomTags", {}).get("StudyInstanceUID", "")
        if s_uid == study_uid:
            continue

        s_modality = s.get("RequestedTags", {}).get("ModalitiesInStudy", "")
        if same_modality and s_modality and current_modality and s_modality != current_modality:
            continue

        priors.append({
            "study_instance_uid": s_uid,
            "study_date": s.get("MainDicomTags", {}).get("StudyDate", ""),
            "study_description": s.get("MainDicomTags", {}).get("StudyDescription", ""),
            "modalities_in_study": s_modality,
            "accession_number": s.get("MainDicomTags", {}).get("AccessionNumber", ""),
            "series_count": len(s.get("Series", [])),
            "viewer_url": f"/werub-viewer/viewer?StudyInstanceUIDs={s_uid}",
            "compare_url": f"/werub-viewer/viewer?StudyInstanceUIDs={study_uid}&StudyInstanceUIDs={s_uid}",
        })

    priors.sort(key=lambda x: x["study_date"] or "", reverse=True)
    base["priors"] = priors[:max_results]
    return base
