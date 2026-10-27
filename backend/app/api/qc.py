"""QC (Quality Control) API endpoints.

Study merge/split, Patient Reconciliation, image quality review.
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_on_write
from app.core.cache_config import CACHE_PATTERN_WORKLIST, CACHE_PATTERN_ORTHANC
from app.core.database import get_db
from app.core.exceptions import InternalServerError, NotFoundError, ValidationError
from app.core.security import RequireRole, get_current_user
from app.models.audit import AuditLog
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/qc", tags=["qc"])


class PatientUpdateRequest(BaseModel):
    """Patient reconciliation — fix incorrect patient info."""
    orthanc_study_id: str
    new_patient_id: str | None = None
    new_patient_name: str | None = None
    new_patient_birth_date: str | None = None
    new_patient_sex: str | None = None
    new_accession_number: str | None = None
    reason: str  # mandatory reason for audit


class StudyMergeRequest(BaseModel):
    """Merge multiple studies into one."""
    source_study_ids: list[str]  # Orthanc study IDs to merge
    target_study_id: str  # Orthanc study ID to merge into
    reason: str


class StudySplitRequest(BaseModel):
    """Split series from a study into a new study."""
    source_study_id: str
    series_ids: list[str]  # Orthanc series IDs to move
    reason: str


async def _log_qc_action(db: AsyncSession, user: User, action: str, resource_id: str, details: dict):
    """Record QC action in audit log."""
    log = AuditLog(
        user_id=str(user.id),
        username=user.username,
        action=action,
        resource_type="study",
        resource_id=resource_id,
        description=details.get("reason", ""),
        details=details,
    )
    db.add(log)
    await db.commit()


@router.post("/patient-reconciliation")
async def patient_reconciliation(
    body: PatientUpdateRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False))],
):
    """Fix incorrect patient information on a study.

    Updates DICOM tags via Orthanc's /modify endpoint.
    Admin or Technologist only.
    """
    client = request.app.state.http_client

    # Get current study info
    resp = await client.get(f"/studies/{body.orthanc_study_id}")
    if resp.status_code != 200:
        raise NotFoundError("Study", body.orthanc_study_id)
    original = resp.json()
    original_patient = original.get("PatientMainDicomTags", {})

    # Build modification
    replace_tags = {}
    if body.new_patient_id:
        replace_tags["PatientID"] = body.new_patient_id
    if body.new_patient_name:
        replace_tags["PatientName"] = body.new_patient_name
    if body.new_patient_birth_date:
        replace_tags["PatientBirthDate"] = body.new_patient_birth_date
    if body.new_patient_sex:
        replace_tags["PatientSex"] = body.new_patient_sex
    if body.new_accession_number:
        replace_tags["AccessionNumber"] = body.new_accession_number

    if not replace_tags:
        raise ValidationError("No fields to update")

    # Execute modification via Orthanc
    modify_resp = await client.post(
        f"/studies/{body.orthanc_study_id}/modify",
        json={
            "Replace": replace_tags,
            "KeepSource": True,  # Keep original as backup
            "Force": True,
        },
    )

    if modify_resp.status_code != 200:
        raise InternalServerError(f"Orthanc modify failed: {modify_resp.text}")

    result = modify_resp.json()

    # Audit log
    await _log_qc_action(db, user, "patient_reconciliation", body.orthanc_study_id, {
        "reason": body.reason,
        "original_patient": original_patient,
        "new_values": replace_tags,
        "new_orthanc_id": result.get("ID"),
    })

    return {
        "status": "modified",
        "original_study_id": body.orthanc_study_id,
        "new_study_id": result.get("ID"),
        "modified_tags": replace_tags,
        "original_kept": True,
        "reason": body.reason,
    }


@router.post("/merge-studies")
@invalidate_on_write(CACHE_PATTERN_WORKLIST, CACHE_PATTERN_ORTHANC)
async def merge_studies(
    body: StudyMergeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False))],
):
    """Merge multiple studies into a target study.

    Moves all series from source studies into the target study.
    Admin or Technologist only. Invalidates worklist and Orthanc metadata caches.
    """
    client = request.app.state.http_client

    # Verify target exists
    target_resp = await client.get(f"/studies/{body.target_study_id}")
    if target_resp.status_code != 200:
        raise NotFoundError("Target study", body.target_study_id)
    target = target_resp.json()
    target_uid = target.get("MainDicomTags", {}).get("StudyInstanceUID")

    moved_series = []
    failed_series = []
    for source_id in body.source_study_ids:
        if source_id == body.target_study_id:
            continue
        # Get source study
        src_resp = await client.get(f"/studies/{source_id}")
        if src_resp.status_code != 200:
            failed_series.append(source_id)  # whole source unreachable
            continue
        source = src_resp.json()

        # Modify each series to belong to target study
        for series_id in source.get("Series", []):
            modify_resp = await client.post(
                f"/series/{series_id}/modify",
                json={
                    "Replace": {"StudyInstanceUID": target_uid},
                    "Force": True,
                    "KeepSource": False,
                },
            )
            if modify_resp.status_code == 200:
                moved_series.append(series_id)
            else:
                failed_series.append(series_id)

    # Surface partial failures instead of always reporting success.
    merge_status = "merged" if not failed_series else "partial"
    await _log_qc_action(db, user, "study_merge", body.target_study_id, {
        "reason": body.reason,
        "source_studies": body.source_study_ids,
        "target_study": body.target_study_id,
        "moved_series_count": len(moved_series),
        "failed_series_count": len(failed_series),
        "status": merge_status,
    })

    return {
        "status": merge_status,
        "target_study_id": body.target_study_id,
        "source_studies": body.source_study_ids,
        "moved_series": len(moved_series),
        "failed_series": len(failed_series),
        "reason": body.reason,
    }


@router.post("/split-study")
@invalidate_on_write(CACHE_PATTERN_WORKLIST, CACHE_PATTERN_ORTHANC)
async def split_study(
    body: StudySplitRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False))],
):
    """Split series from a study into a new study.

    Creates new StudyInstanceUID and moves selected series.
    Admin or Technologist only. Invalidates worklist and Orthanc metadata caches.
    """
    client = request.app.state.http_client
    import uuid

    # Verify source exists
    src_resp = await client.get(f"/studies/{body.source_study_id}")
    if src_resp.status_code != 200:
        raise NotFoundError("Source study", body.source_study_id)

    # Generate new Study UID
    new_study_uid = f"1.2.826.0.1.3680043.8.1055.{uuid.uuid4().int % 10**16}"

    moved = []
    failed = []
    for series_id in body.series_ids:
        modify_resp = await client.post(
            f"/series/{series_id}/modify",
            json={
                "Replace": {"StudyInstanceUID": new_study_uid},
                "Force": True,
                "KeepSource": False,
            },
        )
        if modify_resp.status_code == 200:
            moved.append(series_id)
        else:
            failed.append(series_id)

    split_status = "split" if not failed else "partial"
    await _log_qc_action(db, user, "study_split", body.source_study_id, {
        "reason": body.reason,
        "source_study": body.source_study_id,
        "new_study_uid": new_study_uid,
        "moved_series": moved,
        "failed_series_count": len(failed),
        "status": split_status,
    })

    return {
        "status": split_status,
        "source_study_id": body.source_study_id,
        "new_study_uid": new_study_uid,
        "moved_series": len(moved),
        "failed_series": len(failed),
        "reason": body.reason,
    }
