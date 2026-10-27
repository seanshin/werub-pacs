"""DICOM anonymization/de-identification API.

Based on DICOM Supplement 142 Basic Application Level Confidentiality Profile.
Removes or replaces PHI (Protected Health Information) from DICOM data.
"""
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.database import get_db
from app.core.exceptions import InternalServerError, NotFoundError
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/anonymize", tags=["anonymize"])

# DICOM tags handled by the Basic Profile. INFORMATIONAL ONLY — we no longer pass these
# to Orthanc's /anonymize "Remove" (it rejects keywords outside its dictionary, e.g.
# "MedicalRecordLocator" → 500). Orthanc's built-in DICOM Supp 142 profile removes all of
# these (and more) by default. Kept here to document the PHI categories we rely on it to strip.
TAGS_TO_REMOVE = [
    "PatientBirthDate", "PatientBirthTime", "PatientAddress",
    "PatientTelephoneNumbers", "PatientMotherBirthName",
    "MedicalRecordLocator", "EthnicGroup", "Occupation",
    "AdditionalPatientHistory", "PatientComments",
    "ResponsiblePerson", "ResponsibleOrganization",
    "OtherPatientIDs", "OtherPatientNames",
    "ReferringPhysicianAddress", "ReferringPhysicianTelephoneNumbers",
    "PhysiciansOfRecord", "PerformingPhysicianName",
    "NameOfPhysiciansReadingStudy", "OperatorsName",
    "InstitutionAddress", "InstitutionalDepartmentName",
    "StationName",
]

TAGS_TO_REPLACE = {
    "PatientName": "ANONYMIZED",
    "PatientID": None,  # Will be hashed
    "InstitutionName": "ANONYMIZED",
    "ReferringPhysicianName": "ANONYMIZED",
}


class AnonymizeRequest(BaseModel):
    study_id: str  # Orthanc study ID
    keep_study_date: bool = False
    keep_modality: bool = True
    keep_body_part: bool = True
    custom_patient_id: str | None = None  # If None, hash original
    output_format: str = "dicom"  # dicom or json


def _hash_id(original_id: str, salt: str | None = None) -> str:
    """Generate consistent anonymized ID from original. Uses deployment-specific salt."""
    if salt is None:
        from app.core.config import settings
        salt = settings.secret_key[:32]
    return hashlib.sha256(f"{salt}:{original_id}".encode()).hexdigest()[:16].upper()


@router.post("/study/{study_id}")
@AuditLogger.log("STUDY_ANONYMIZE", "DicomStudy")
async def anonymize_study(
    study_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RESEARCHER, allow_btg=False))],
    keep_study_date: bool = Query(False),
    custom_patient_id: str | None = Query(None),
):
    """Anonymize a study via Orthanc's built-in anonymization.

    Creates a new anonymized copy of the study in Orthanc.
    Admin or Researcher only.
    """
    client = request.app.state.http_client

    # Verify study exists
    resp = await client.get(f"/studies/{study_id}")
    if resp.status_code != 200:
        raise NotFoundError(resource="Study", resource_id=study_id)

    original = resp.json()
    original_pid = original.get("PatientMainDicomTags", {}).get("PatientID", "")
    anon_pid = custom_patient_id or _hash_id(original_pid)

    # Build Orthanc anonymization config
    replace_tags = {
        "PatientID": anon_pid,
        "PatientName": f"ANON-{anon_pid}",
    }
    keep_tags = []
    if keep_study_date:
        keep_tags.extend(["StudyDate", "StudyTime", "SeriesDate", "SeriesTime"])

    # Execute via Orthanc /studies/{id}/anonymize.
    # Orthanc applies the DICOM Supp 142 Basic Profile by default (removes/blanks all
    # standard PHI). We do NOT pass an explicit "Remove" list: Orthanc rejects keywords
    # not in its dictionary (e.g. "MedicalRecordLocator" → 500 "Unknown DICOM tag"),
    # which previously broke every anonymize endpoint. Replace overrides Patient ID/Name.
    anon_resp = await client.post(
        f"/studies/{study_id}/anonymize",
        json={
            "Replace": replace_tags,
            "Keep": keep_tags,
            "KeepSource": True,
            "Force": True,
        },
    )

    if anon_resp.status_code != 200:
        raise InternalServerError(message=f"Anonymization failed: {anon_resp.text[:200]}")

    result = anon_resp.json()
    new_study_id = result.get("ID")

    # Get info about anonymized study
    new_study = await client.get(f"/studies/{new_study_id}")
    new_info = new_study.json() if new_study.status_code == 200 else {}

    return {
        "status": "anonymized",
        "original_study_id": study_id,
        "anonymized_study_id": new_study_id,
        "anonymized_patient_id": anon_pid,
        "original_patient_id": original_pid,
        "series_count": len(new_info.get("Series", [])),
        "deidentification": "Orthanc DICOM Supp 142 Basic Profile",
        "tags_replaced": list(replace_tags.keys()),
        "viewer_url": f"/viewer/?StudyInstanceUIDs={new_info.get('MainDicomTags', {}).get('StudyInstanceUID', '')}",
    }


@router.get("/study/{study_id}/download")
async def download_anonymized_study(
    study_id: str,
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RESEARCHER, allow_btg=False))],
):
    """Download anonymized study as DICOM ZIP archive.

    First anonymizes, then returns ZIP download.
    """
    client = request.app.state.http_client

    # Anonymize into a TEMPORARY copy. A1 fix: this is a GET download path —
    # KeepSource MUST be True so a browser prefetch/retry/double-click can never
    # destroy the original study (medical-record loss). We delete the temporary
    # anonymized copy after streaming so it doesn't accumulate in Orthanc.
    anon_resp = await client.post(
        f"/studies/{study_id}/anonymize",
        json={
            "Replace": {"PatientName": "ANON", "PatientID": _hash_id(study_id)},
            # Orthanc default Supp 142 profile removes PHI. No explicit "Remove" — its
            # keyword validation rejects non-dictionary names (e.g. MedicalRecordLocator → 500).
            "KeepSource": True,
            "Force": True,
        },
    )
    if anon_resp.status_code != 200:
        raise InternalServerError(message="Anonymization failed")

    new_id = anon_resp.json().get("ID")

    # Download as ZIP, then drop the temporary anonymized copy.
    try:
        zip_resp = await client.get(f"/studies/{new_id}/archive")
        if zip_resp.status_code != 200:
            raise InternalServerError(message="Archive download failed")
        content = zip_resp.content
    finally:
        # Best-effort cleanup of the temp anon study (never touches the source).
        try:
            await client.delete(f"/studies/{new_id}")
        except Exception:
            pass

    return StreamingResponse(
        iter([content]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=anon_{new_id[:8]}.zip"},
    )


class BatchAnonymizeRequest(BaseModel):
    study_uids: list[str]
    keep_study_date: bool = False
    custom_prefix: str = "ANON"


@router.post("/batch", summary="배치 익명화")
@AuditLogger.log("BATCH_ANONYMIZE", "DicomStudy")
async def batch_anonymize(
    body: BatchAnonymizeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RESEARCHER, allow_btg=False))],
):
    """여러 Study를 한번에 익명화합니다. 연구용 데이터 추출에 사용."""
    client = request.app.state.http_client
    results = []

    for uid in body.study_uids[:50]:  # Max 50 at once
        # Find Orthanc study ID
        resp = await client.post("/tools/find", json={
            "Level": "Study",
            "Query": {"StudyInstanceUID": uid},
        })
        if resp.status_code != 200 or not resp.json():
            results.append({"study_uid": uid, "status": "not_found"})
            continue

        orthanc_id = resp.json()[0]
        study_resp = await client.get(f"/studies/{orthanc_id}")
        if study_resp.status_code != 200:
            results.append({"study_uid": uid, "status": "error"})
            continue

        original = study_resp.json()
        original_pid = original.get("PatientMainDicomTags", {}).get("PatientID", "")
        anon_pid = _hash_id(original_pid)

        replace_tags = {
            "PatientID": anon_pid,
            "PatientName": f"{body.custom_prefix}-{anon_pid[:8]}",
        }
        keep_tags = ["StudyDate", "StudyTime"] if body.keep_study_date else []

        anon_resp = await client.post(
            f"/studies/{orthanc_id}/anonymize",
            json={
                "Replace": replace_tags,
                "Keep": keep_tags,
                # Orthanc default Supp 142 profile removes PHI (no explicit Remove — see above).
                "KeepSource": True,
                "Force": True,
            },
        )

        if anon_resp.status_code == 200:
            new_id = anon_resp.json().get("ID", "")
            results.append({
                "study_uid": uid,
                "status": "anonymized",
                "anonymized_id": new_id,
                "anonymized_pid": anon_pid,
            })
        else:
            results.append({"study_uid": uid, "status": "failed"})

    success = sum(1 for r in results if r["status"] == "anonymized")
    return {
        "total": len(body.study_uids),
        "processed": len(results),
        "success": success,
        "failed": len(results) - success,
        "results": results,
    }


@router.get("/history", summary="익명화 이력")
async def anonymize_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RESEARCHER, allow_btg=False))],
    limit: int = Query(50, ge=1, le=200),
):
    """최근 익명화 작업 이력을 감사 로그에서 조회합니다."""
    from sqlalchemy import text
    result = await db.execute(text("""
        SELECT id, action, resource_type, resource_id, username AS user_name,
               details, created_at
        FROM audit_logs
        WHERE action IN ('STUDY_ANONYMIZE', 'BATCH_ANONYMIZE')
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"limit": limit})

    return {"history": [dict(r._mapping) for r in result]}
