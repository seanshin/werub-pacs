"""Patient-centric API for HospitalRun integration.

Provides patient-based imaging data lookup, reading status,
and report results for embedding in HospitalRun patient charts.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.audit import AuditLog, AuditAction
from app.models.patient_mapping import PatientMapping
from app.services.korean_search import is_chosung_query, matches_chosung
from app.models.report import Report, ReportStatus
from app.models.user import User, Role

router = APIRouter(prefix="/api/v1/patients", tags=["환자 포털"])

# Identified patient imaging is clinical PHI. Restrict to clinical roles only;
# RESEARCHER is excluded (research access must go through anonymized / IRB path),
# except via the system-wide Break-the-Glass override (which is audit-logged).
# RESIDENT inherits RADIOLOGIST access via RequireRole.
ClinicalAccess = RequireRole(
    Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, Role.TECHNOLOGIST
)


@router.get("/{patient_id}/studies", summary="환자별 검사 목록")
async def get_patient_studies(
    patient_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalAccess)],
    limit: int = Query(50, ge=1, le=200),
):
    """Get all imaging studies for a patient.

    Designed for HospitalRun patient chart integration.
    Returns studies with reading status and report summary.

    Access: clinical roles only (admin/radiologist/resident/physician/technologist).
    Every access is audit-logged as PHI view.
    """
    client = request.app.state.http_client

    # Audit: PHI access by patient identifier
    db.add(AuditLog(
        user_id=str(user.id), username=user.username,
        ip_address=request.client.host if request.client else None,
        action=AuditAction.VIEW, resource_type="PatientStudies",
        resource_id=patient_id, patient_id=patient_id,
        description=f"{user.username} viewed studies for patient {patient_id}",
        details={"break_the_glass": getattr(request.state, "break_the_glass", False)},
    ))
    await db.commit()

    # Resolve patient_id: could be HIS MRN or HIS UUID
    dicom_pid = patient_id
    mapping_result = await db.execute(
        select(PatientMapping).where(
            (PatientMapping.his_mrn == patient_id) |
            (PatientMapping.his_patient_id == patient_id)
        )
    )
    mapping = mapping_result.scalar_one_or_none()
    if mapping:
        dicom_pid = mapping.dicom_patient_id

    # Search Orthanc by resolved DICOM PatientID
    resp = await client.post("/tools/find", json={
        "Level": "Study",
        "Query": {"PatientID": dicom_pid},
        "Expand": True,
        # N+1 fix: get modality/instance counts in the one find call instead of a
        # per-series GET /series/{id} loop.
        "RequestedTags": ["ModalitiesInStudy", "NumberOfStudyRelatedInstances"],
    })
    orthanc_studies = resp.json() if resp.status_code == 200 else []

    # Get reports for this patient
    report_result = await db.execute(
        select(Report).where(Report.patient_id == patient_id)
    )
    reports = {r.study_instance_uid: r for r in report_result.scalars().all()}

    studies = []
    for study in orthanc_studies:
        main_tags = study.get("MainDicomTags", {})
        patient_tags = study.get("PatientMainDicomTags", {})
        study_uid = main_tags.get("StudyInstanceUID", "")

        # Determine reading status
        report = reports.get(study_uid)
        if report:
            read_status = report.status
            read_info = {
                "report_id": str(report.id),
                "status": report.status,
                "author": report.author_name,
                "signed_at": report.signed_at.isoformat() if report.signed_at else None,
                "impression": report.impression[:200] if report.impression else None,
                "urgency": report.urgency,
            }
        else:
            read_status = "unread"
            read_info = None

        # Counts from RequestedTags (single find call — no per-series N+1).
        series_list = study.get("Series", [])
        req_tags = study.get("RequestedTags", {})
        modalities = {m for m in (req_tags.get("ModalitiesInStudy", "") or "").split("\\") if m}
        try:
            instance_count = int(req_tags.get("NumberOfStudyRelatedInstances") or 0)
        except (ValueError, TypeError):
            instance_count = 0

        studies.append({
            "orthanc_id": study.get("ID"),
            "study_instance_uid": study_uid,
            "study_date": main_tags.get("StudyDate"),
            "study_time": main_tags.get("StudyTime"),
            "study_description": main_tags.get("StudyDescription"),
            "accession_number": main_tags.get("AccessionNumber"),
            "referring_physician": main_tags.get("ReferringPhysicianName"),
            "institution": main_tags.get("InstitutionName"),
            "modalities": list(modalities),
            "series_count": len(series_list),
            "instance_count": instance_count,
            "patient_name": patient_tags.get("PatientName"),
            "patient_birth_date": patient_tags.get("PatientBirthDate"),
            "patient_sex": patient_tags.get("PatientSex"),
            # Reading status
            "read_status": read_status,
            "report": read_info,
            # Viewer link
            "viewer_url": f"/viewer/?StudyInstanceUIDs={study_uid}",
        })

    # Sort by date descending
    studies.sort(key=lambda s: s.get("study_date") or "", reverse=True)

    return {
        "patient_id": patient_id,
        "patient_name": studies[0]["patient_name"] if studies else None,
        "total_studies": len(studies),
        "unread_count": sum(1 for s in studies if s["read_status"] == "unread"),
        "studies": studies[:limit],
    }


@router.get("/search", summary="환자 검색 (초성 지원)")
async def search_patients(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalAccess)],
    name: str = Query(..., min_length=1, description="환자명 또는 초성 (예: ㅎㄱㄷ)"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search patients by name or Korean initial consonants (초성).

    Examples:
    - name=홍길동 → exact/partial match
    - name=ㅎㄱㄷ → chosung match (홍길동)
    - name=ㄱ → all patients with 김, 강, 고, etc.
    """
    client = request.app.state.http_client
    use_chosung = is_chosung_query(name)

    if use_chosung:
        # Fetch all patients, then filter by chosung
        resp = await client.get("/patients", params={"since": 0, "limit": 200})
        patient_ids = resp.json() if resp.status_code == 200 and isinstance(resp.json(), list) else []

        results = []
        for pid in patient_ids:
            pr = await client.get(f"/patients/{pid}")
            if pr.status_code == 200:
                p = pr.json()
                pname = p.get("MainDicomTags", {}).get("PatientName", "")
                if matches_chosung(pname, name):
                    results.append({
                        "orthanc_id": p.get("ID"),
                        "patient_id": p.get("MainDicomTags", {}).get("PatientID"),
                        "patient_name": pname,
                        "studies_count": len(p.get("Studies", [])),
                    })
            if len(results) >= limit:
                break
    else:
        # Server-side search
        resp = await client.post("/tools/find", json={
            "Level": "Patient",
            "Query": {"PatientName": f"*{name}*"},
            "Expand": True,
            "Limit": limit,
        })
        patients = resp.json() if resp.status_code == 200 else []
        results = [
            {
                "orthanc_id": p.get("ID"),
                "patient_id": p.get("MainDicomTags", {}).get("PatientID"),
                "patient_name": p.get("MainDicomTags", {}).get("PatientName"),
                "studies_count": len(p.get("Studies", [])),
            }
            for p in patients
        ]

    return {"query": name, "is_chosung": use_chosung, "count": len(results), "patients": results}


@router.get("/{patient_id}/reports", summary="환자별 판독 리포트 목록")
async def get_patient_reports(
    patient_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalAccess)],
):
    """Get all reading reports for a patient.

    Access: clinical roles only; access is audit-logged as PHI view.
    """
    db.add(AuditLog(
        user_id=str(user.id), username=user.username,
        ip_address=request.client.host if request.client else None,
        action=AuditAction.VIEW, resource_type="PatientReports",
        resource_id=patient_id, patient_id=patient_id,
        description=f"{user.username} viewed reports for patient {patient_id}",
    ))
    await db.commit()
    result = await db.execute(
        select(Report)
        .where(Report.patient_id == patient_id)
        .order_by(Report.created_at.desc())
    )
    reports = result.scalars().all()

    return {
        "patient_id": patient_id,
        "total_reports": len(reports),
        "reports": [
            {
                "id": str(r.id),
                "study_instance_uid": r.study_instance_uid,
                "study_date": r.study_date,
                "modality": r.modality,
                "study_description": r.study_description,
                "status": r.status,
                "urgency": r.urgency,
                "findings": r.findings,
                "impression": r.impression,
                "recommendation": r.recommendation,
                "author_name": r.author_name,
                "signed_at": r.signed_at.isoformat() if r.signed_at else None,
                "signed_by_name": r.signed_by_name,
                "created_at": r.created_at.isoformat(),
                "viewer_url": f"/viewer/?StudyInstanceUIDs={r.study_instance_uid}",
            }
            for r in reports
        ],
    }
