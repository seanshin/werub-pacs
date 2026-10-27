"""방사선량 관리 및 CD 내보내기 API.

CT 선량 추출(CTDIvol, DLP, kVp), 누적선량, DRL 초과 알림, DICOM ZIP 내보내기.
NOTE: dose_records 테이블이 아직 없으므로 마이그레이션 필요:
  CREATE TABLE dose_records (
      id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
      study_instance_uid TEXT NOT NULL,
      patient_id TEXT NOT NULL,
      modality TEXT,
      ctdi_vol FLOAT, dlp FLOAT, kvp FLOAT,
      body_part TEXT, exam_description TEXT,
      extracted_at TIMESTAMPTZ DEFAULT now(),
      extracted_by TEXT
  );
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dose", tags=["방사선량 관리"])

# ── CD export 임시 저장 ──
_cd_jobs: dict[str, dict] = {}


class DoseRecord(BaseModel):
    """추출된 선량 정보."""
    study_instance_uid: str
    patient_id: str
    modality: str | None = None
    ctdi_vol: float | None = None
    dlp: float | None = None
    kvp: float | None = None
    body_part: str | None = None


# ── 1. 선량 추출 ──
@router.post("/extract/{study_uid}", summary="DICOM 태그에서 선량 추출")
async def extract_dose(
    study_uid: str,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """Study의 DICOM 태그에서 방사선량 정보를 추출하여 저장합니다.

    - (0018,0060) kVp
    - (0018,9345) CTDIvol
    - (0018,9346) DLP (CT Dose Length Product Total)
    """
    client = request.app.state.http_client

    # Orthanc에서 study 조회 (A2 fix: /tools/find is POST — httpx .get has no json=)
    resp = await client.post(f"/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid}, "Expand": True
    })
    studies = resp.json()
    if not studies:
        return {"error": "Study not found in Orthanc"}

    study = studies[0]
    orthanc_id = study["ID"]
    patient_id = study.get("PatientMainDicomTags", {}).get("PatientID", "UNKNOWN")

    # 첫 번째 instance에서 dose 태그 추출
    instances_resp = await client.get(f"/studies/{orthanc_id}/instances")
    instances = instances_resp.json()
    if not instances:
        return {"error": "No instances in study"}

    tags_resp = await client.get(f"/instances/{instances[0]['ID']}/simplified-tags")
    tags = tags_resp.json()

    kvp = float(tags["KVP"]) if "KVP" in tags else None
    ctdi = float(tags.get("CTDIvol", 0)) if tags.get("CTDIvol") else None
    dlp_val = float(tags.get("DLP", 0)) if tags.get("DLP") else None
    modality = tags.get("Modality", "")
    body_part = tags.get("BodyPartExamined", "")

    await db.execute(text("""
        INSERT INTO dose_records (study_instance_uid, patient_id, modality,
            ctdi_vol, dlp, kvp, body_part, extracted_by)
        VALUES (:suid, :pid, :mod, :ctdi, :dlp, :kvp, :bp, :user)
    """), {"suid": study_uid, "pid": patient_id, "mod": modality,
           "ctdi": ctdi, "dlp": dlp_val, "kvp": kvp, "bp": body_part,
           "user": user.username})
    await db.commit()

    return {"study_uid": study_uid, "kvp": kvp, "ctdi_vol": ctdi, "dlp": dlp_val,
            "modality": modality, "body_part": body_part}


# ── 2. 환자 누적 선량 ──
@router.get("/patient/{patient_id}", summary="환자 누적 선량 조회")
async def patient_dose_history(
    patient_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """환자의 누적 방사선량 이력을 조회합니다."""
    result = await db.execute(text("""
        SELECT study_instance_uid, modality, ctdi_vol, dlp, kvp,
               body_part, extracted_at
        FROM dose_records WHERE patient_id = :pid
        ORDER BY extracted_at DESC
    """), {"pid": patient_id})
    rows = [dict(r._mapping) for r in result]
    cumulative_dlp = sum(r.get("dlp") or 0 for r in rows)
    return {"patient_id": patient_id, "cumulative_dlp_mGycm": cumulative_dlp,
            "records": rows}


# ── 3. 기간 선량 통계 ──
@router.get("/statistics", summary="기간별 선량 통계")
async def dose_statistics(
    from_date: str = Query(None), to_date: str = Query(None),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """모달리티별, 월별 선량 통계를 반환합니다."""
    now = datetime.now(timezone.utc)
    if not from_date:
        from_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = now.strftime("%Y-%m-%d")

    by_modality = await db.execute(text("""
        SELECT modality, count(*) as count, avg(ctdi_vol) as avg_ctdi,
               avg(dlp) as avg_dlp
        FROM dose_records
        WHERE extracted_at >= :f AND extracted_at <= :t::date + 1
        GROUP BY modality ORDER BY count DESC
    """), {"f": from_date, "t": to_date})

    by_month = await db.execute(text("""
        SELECT to_char(extracted_at, 'YYYY-MM') as month, count(*) as count,
               avg(dlp) as avg_dlp
        FROM dose_records
        WHERE extracted_at >= :f AND extracted_at <= :t::date + 1
        GROUP BY month ORDER BY month
    """), {"f": from_date, "t": to_date})

    return {"by_modality": [dict(r._mapping) for r in by_modality],
            "by_month": [dict(r._mapping) for r in by_month]}


# ── 4. DRL 초과 알림 ──
DRL_THRESHOLDS = {
    "CHEST_CT": {"ctdi_vol": 15.0, "dlp": 400},
    "ABDOMEN_CT": {"ctdi_vol": 25.0, "dlp": 600},
}

@router.get("/drl-alerts", summary="DRL 초과 알림 목록")
async def drl_alerts(
    from_date: str = Query(None),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """진단참고수준(DRL)을 초과한 검사 목록을 반환합니다.

    기본 기준: Chest CT CTDIvol>15mGy, Abdomen CT DLP>600mGy·cm
    """
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    result = await db.execute(text("""
        SELECT study_instance_uid, patient_id, modality, body_part,
               ctdi_vol, dlp, extracted_at
        FROM dose_records
        WHERE extracted_at >= :f
          AND (ctdi_vol > 15 OR dlp > 600)
        ORDER BY extracted_at DESC
    """), {"f": from_date})
    return {"alerts": [dict(r._mapping) for r in result]}


# ── 5. CD 패키지 생성 ──
@router.post("/export/cd-package/{study_uid}", summary="CD용 DICOM ZIP 생성")
async def create_cd_package(
    study_uid: str,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, allow_btg=False)),
):
    """Orthanc에서 Study의 DICOM ZIP 아카이브를 다운로드하여 CD 패키지를 생성합니다."""
    client = request.app.state.http_client
    job_id = str(uuid.uuid4())
    _cd_jobs[job_id] = {"status": "processing", "study_uid": study_uid}

    resp = await client.post(f"/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid}
    })
    ids = resp.json()
    if not ids:
        _cd_jobs[job_id] = {"status": "error", "message": "Study not found"}
        return {"job_id": job_id, "status": "error"}

    orthanc_id = ids[0] if isinstance(ids[0], str) else ids[0]["ID"]
    archive_resp = await client.get(f"/studies/{orthanc_id}/archive")
    if archive_resp.status_code == 200:
        _cd_jobs[job_id] = {"status": "completed", "size_bytes": len(archive_resp.content),
                            "study_uid": study_uid}
    else:
        _cd_jobs[job_id] = {"status": "error", "message": "Archive generation failed"}

    return {"job_id": job_id, "status": _cd_jobs[job_id]["status"]}


# ── 6. CD 패키지 상태 ──
@router.get("/export/cd-package/{job_id}/status", summary="CD 패키지 생성 상태")
async def cd_package_status(
    job_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, allow_btg=False)),
):
    """CD 패키지 생성 작업의 진행 상태를 확인합니다."""
    job = _cd_jobs.get(job_id)
    if not job:
        return {"error": "Job not found", "job_id": job_id}
    return {"job_id": job_id, **job}
