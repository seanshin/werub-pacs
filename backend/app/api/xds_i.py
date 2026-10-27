"""XDS-I.b Phase 1 API — ITI-41 Provide & Register 제출 트리거 + 이력 (v2.0 트랙 A).

study → KOS 매니페스트 생성 → affinity-domain 환자ID 매핑(MPI) → ebRIM+SOAP+MTOM 조립 →
Document Repository로 POST. 외부 반출(PHI)이므로 default-off 게이트 + allow_btg=False + 감사.

- `POST /api/v1/xds-i/submit`      : 제출 트리거(동기 — 리뷰=1 study, 대량은 Step D celery 보류)
- `GET  /api/v1/xds-i/submissions` : 제출 이력
- `GET  /api/v1/xds-i/submissions/{id}` : 상세

설계: `docs/02-design/xds-i-pix-mpi-phase1.design.md`
"""
import io
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import _log_audit_entry
from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole
from app.models.mpi import IdentityDomain, PatientIdentifier, XdsiSubmission
from app.models.user import Role, User
from app.services.kos_service import build_kos
from app.services.xds_metadata import DEFAULT_CODES, DocEntry, Submission
from app.services.xdsi_submit import build_iti41_message, format_affinity_cx, submit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/xds-i", tags=["XDS-I.b 제출"])

# 외부 반출 → BTG 차단
SubmitRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)
MAX_KOS_INSTANCES = 200


class SubmitRequest(BaseModel):
    study_instance_uid: str
    affinity_system: str                      # 타깃 affinity domain (urn:oid:.. or namespace_id)
    affinity_patient_id: str | None = None    # 미지정 시 MPI로 로컬 PatientID→affinity 교차참조
    target_endpoint: str | None = None        # 미지정 시 settings.xdsi_repository_endpoint


async def _resolve_domain(db: AsyncSession, system: str) -> IdentityDomain | None:
    oid = system[8:] if system.startswith("urn:oid:") else None
    return (await db.execute(
        select(IdentityDomain).where(
            (IdentityDomain.namespace_id == system)
            | (IdentityDomain.universal_id == (oid or system))
        )
    )).scalars().first()


async def _fetch_study_instances(client, study_uid: str) -> tuple[str, list[bytes]]:
    """Orthanc에서 study 인스턴스 바이트 수집(캡). (patient_id, [bytes]) 반환."""
    found = await client.post("/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid}, "Expand": True,
    })
    items = found.json() if found.status_code == 200 else []
    if not items:
        return "", []
    oid = items[0]["ID"]
    patient_id = items[0].get("PatientMainDicomTags", {}).get("PatientID", "")
    out: list[bytes] = []
    sr = await client.get(f"/studies/{oid}")
    if sr.status_code != 200:
        return patient_id, out
    for series_id in sr.json().get("Series", []):
        ser = await client.get(f"/series/{series_id}")
        if ser.status_code != 200:
            continue
        for inst_id in ser.json().get("Instances", []):
            if len(out) >= MAX_KOS_INSTANCES:
                return patient_id, out
            f = await client.get(f"/instances/{inst_id}/file")
            if f.status_code == 200:
                out.append(f.content)
    return patient_id, out


async def _derive_affinity_id(db, local_patient_id: str, affinity_domain: IdentityDomain) -> str | None:
    """로컬 PatientID → (로컬 도메인) enterprise → affinity 도메인 식별자(MPI 교차참조)."""
    from app.models.mpi import LOCAL_NAMESPACE_ID
    local = (await db.execute(
        select(IdentityDomain).where(IdentityDomain.namespace_id == LOCAL_NAMESPACE_ID)
    )).scalar_one_or_none()
    if not local or not local_patient_id:
        return None
    src = (await db.execute(
        select(PatientIdentifier).where(
            PatientIdentifier.domain_id == local.id,
            PatientIdentifier.identifier == local_patient_id,
        )
    )).scalar_one_or_none()
    if not src:
        return None
    tgt = (await db.execute(
        select(PatientIdentifier).where(
            PatientIdentifier.enterprise_id == src.enterprise_id,
            PatientIdentifier.domain_id == affinity_domain.id,
        )
    )).scalar_one_or_none()
    return tgt.identifier if tgt else None


@router.post("/submit", status_code=202, summary="ITI-41 Provide & Register 제출")
async def submit_study(
    body: SubmitRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(SubmitRoles)],
):
    if not settings.xdsi_submit_enabled:
        raise HTTPException(503, "XDS-I 제출이 비활성(XDSI_SUBMIT_ENABLED). affinity domain 규약 확정 후 활성화하세요.")
    endpoint = body.target_endpoint or settings.xdsi_repository_endpoint
    if not endpoint:
        raise HTTPException(400, "target_endpoint 미지정(XDSI_REPOSITORY_ENDPOINT 미설정)")

    affinity_domain = await _resolve_domain(db, body.affinity_system)
    if not affinity_domain:
        raise HTTPException(400, f"미등록 affinity domain: {body.affinity_system}")

    client = request.app.state.http_client
    local_patient_id, instances = await _fetch_study_instances(client, body.study_instance_uid)
    if not instances:
        raise HTTPException(404, "study 인스턴스를 찾을 수 없습니다")

    # affinity 환자ID: 명시 우선, 없으면 MPI 교차참조 유도
    affinity_pid = body.affinity_patient_id or await _derive_affinity_id(db, local_patient_id, affinity_domain)
    if not affinity_pid:
        raise HTTPException(409, "affinity 도메인 환자 식별자를 확인할 수 없습니다(MPI 교차참조 없음). affinity_patient_id를 명시하세요.")

    # KOS 매니페스트 생성 + SOP UID 추출
    kos_bytes = build_kos(instances, description=f"XDS-I manifest {body.study_instance_uid}")
    try:
        from pydicom import dcmread
        kos_uid = str(dcmread(io.BytesIO(kos_bytes), stop_before_pixels=True).SOPInstanceUID)
    except Exception:
        from pydicom.uid import generate_uid
        kos_uid = str(generate_uid())

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d%H%M%S")
    from pydicom.uid import generate_uid
    submission_uid = str(generate_uid())
    source_oid = settings.xdsi_source_oid or affinity_domain.universal_id or "OPENPACS"
    cx = format_affinity_cx(affinity_pid, affinity_domain.universal_id, affinity_domain.namespace_id)

    sub = Submission(
        submission_time=ts, patient_id=cx, source_id=source_oid,
        unique_id=submission_uid, codes=dict(DEFAULT_CODES),
    )
    doc = DocEntry(
        doc_id="Document01", file_ref="kos.dcm", unique_id=kos_uid,
        creation_time=ts, title=f"Imaging Study Manifest (KOS) {body.study_instance_uid}",
    )

    # 이력 행 선기록(PENDING)
    row = XdsiSubmission(
        study_instance_uid=body.study_instance_uid, target_endpoint=endpoint,
        affinity_domain_id=affinity_domain.id, affinity_patient_id=affinity_pid,
        submission_set_uid=submission_uid, kos_sop_uid=kos_uid, status="PENDING",
        created_by_id=user.id, created_by_name=user.full_name or user.username,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # ITI-41 조립 + 제출
    content_type, message = build_iti41_message(kos_bytes=kos_bytes, submission=sub, doc=doc)
    ok, resp_text = False, ""
    try:
        ok, resp_text = await submit(endpoint, content_type, message)
    except Exception as e:
        resp_text = f"submit error: {e}"
        logger.error(f"ITI-41 submit failed: {e}")

    row.status = "SUBMITTED" if ok else "FAILED"
    row.registry_response = (resp_text or "")[:4000]
    row.submitted_at = datetime.now(timezone.utc)
    await db.commit()

    await _log_audit_entry(
        db, "XDSI_SUBMIT", "XdsiSubmission", "SUCCESS" if ok else "FAILED",
        str(user.id), user.full_name or user.username,
        {"study_instance_uid": body.study_instance_uid, "endpoint": endpoint,
         "affinity_system": body.affinity_system, "submission_set_uid": submission_uid,
         "status": row.status},
    )

    return {
        "submission_id": str(row.id),
        "status": row.status,
        "submission_set_uid": submission_uid,
        "kos_sop_uid": kos_uid,
        "instances": len(instances),
        "registry_response": (resp_text or "")[:500],
    }


def _sub_dict(r: XdsiSubmission) -> dict:
    return {
        "id": str(r.id),
        "study_instance_uid": r.study_instance_uid,
        "target_endpoint": r.target_endpoint,
        "affinity_patient_id": r.affinity_patient_id,
        "submission_set_uid": r.submission_set_uid,
        "kos_sop_uid": r.kos_sop_uid,
        "status": r.status,
        "created_by": r.created_by_name,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "created_at": r.created_at.isoformat(),
    }


@router.get("/submissions", summary="제출 이력")
async def list_submissions(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
    study_instance_uid: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    q = select(XdsiSubmission).order_by(XdsiSubmission.created_at.desc())
    if study_instance_uid:
        q = q.where(XdsiSubmission.study_instance_uid == study_instance_uid)
    rows = (await db.execute(q.limit(limit))).scalars().all()
    return {"count": len(rows), "submissions": [_sub_dict(r) for r in rows]}


@router.get("/submissions/{submission_id}", summary="제출 상세")
async def get_submission(
    submission_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
):
    r = (await db.execute(
        select(XdsiSubmission).where(XdsiSubmission.id == submission_id)
    )).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Submission not found")
    d = _sub_dict(r)
    d["registry_response"] = r.registry_response
    return d
