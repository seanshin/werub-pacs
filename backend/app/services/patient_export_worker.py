"""Patient export packaging worker (patient-portal feature).

Builds an encrypted package of a patient's DICOM studies + final reports for the
external portal to collect. Runs on a dedicated `export` queue (worker must list
it in -Q, per the v11.5 unrouted-queue lesson). Decrypt key and download token
live only in Redis, separate from the package bytes (key via the JWT-authed
status endpoint, package via the one-time gateway).
"""
import io
import json
import logging
import os
import time
import uuid
import zipfile
from datetime import datetime, timezone, timedelta

import httpx
import redis as sync_redis
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session, _get_orthanc_client

logger = logging.getLogger(__name__)

STAGING_DIR = os.environ.get("PATIENT_EXPORT_STAGING", "/app/export-staging")
TOKEN_PREFIX = "pacs:pexport:token:"   # download_token -> request_id
KEY_PREFIX = "pacs:pexport:key:"       # request_id -> fernet key
TTL_SECONDS = 3600                      # download window
STAGING_TTL_HOURS = 24

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _audit(db, action: str, request_id: str, mrn: str | None, detail: str):
    """System-actor audit (Celery sync context). Mirrors api.patient_export._audit
    so the full export lifecycle (REQUESTED/READY/DOWNLOADED/EXPIRED) is traceable —
    legally required for a PHI export feature."""
    try:
        db.execute(text("""
            INSERT INTO audit_logs (id, user_id, username, action, resource_type,
                resource_id, patient_id, description, created_at)
            VALUES (:id, NULL, 'patient-portal', :action, 'PatientExport',
                    :rid, :mrn, :desc, now())
        """), {"id": str(uuid.uuid4()), "action": action, "rid": request_id,
               "mrn": mrn, "desc": detail})
        db.commit()
    except Exception as e:
        # 반출 감사 공백은 규제 리스크 — warning이 아닌 error로 가시화
        logger.error(f"patient-export worker audit failed: {e}")


def _report_html(r: dict) -> str:
    """Minimal standalone report HTML — mirrors report_pdf._generate_report_html
    but driven by a plain row dict (Celery sync context, no ORM)."""
    signed = (
        f"{r.get('signed_by_name')} ({r['signed_at']:%Y-%m-%d %H:%M})"
        if r.get("signed_at") else "미서명"
    )
    urgency_labels = {"normal": "정상", "non_urgent": "비긴급 이상", "urgent": "긴급"}

    def sec(title, content, cls=""):
        return (f'<div class="section"><h3>{title}</h3>'
                f'<div class="section-content {cls}">{content}</div></div>') if content else ""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  body {{ font-family:'Noto Sans KR',sans-serif; margin:40px; color:#333; font-size:14px; }}
  h1 {{ font-size:22px; border-bottom:2px solid #2563eb; padding-bottom:8px; color:#1e3a5f; }}
  .info-table {{ width:100%; border-collapse:collapse; margin-bottom:20px; }}
  .info-table td {{ padding:6px 12px; border:1px solid #ddd; }}
  .info-table td:first-child {{ background:#f8f9fa; font-weight:bold; width:120px; }}
  .section h3 {{ font-size:14px; color:#2563eb; border-left:3px solid #2563eb; padding-left:8px; }}
  .section-content {{ background:#f8f9fa; padding:12px; border-radius:4px; white-space:pre-wrap; line-height:1.6; }}
  .impression {{ background:#ecfdf5; border-left:4px solid #16a34a; }}
  .footer {{ margin-top:30px; border-top:1px solid #ddd; padding-top:10px; font-size:12px; color:#888; }}
  .disclaimer {{ font-size:11px; color:#999; margin-top:20px; padding:8px; background:#fefce8; border-radius:4px; }}
</style></head><body>
<h1>판독 리포트</h1>
<table class="info-table">
  <tr><td>환자명</td><td>{r.get('patient_name') or '-'}</td><td>환자번호</td><td>{r.get('patient_id') or '-'}</td></tr>
  <tr><td>모달리티</td><td>{r.get('modality') or '-'}</td><td>검사일</td><td>{r.get('study_date') or '-'}</td></tr>
  <tr><td>검사설명</td><td>{r.get('study_description') or '-'}</td><td>접수번호</td><td>{r.get('accession_number') or '-'}</td></tr>
  <tr><td>긴급도</td><td>{urgency_labels.get(r.get('urgency'), r.get('urgency') or '정상')}</td><td>상태</td><td>{r.get('status')}</td></tr>
</table>
{sec('임상 정보', r.get('clinical_info'))}
{sec('소견 (Findings)', r.get('findings') or '-')}
{sec('결론 (Impression)', r.get('impression') or '-', 'impression')}
{sec('권고 사항', r.get('recommendation'))}
<div class="footer"><p>OpenPACS — 판독 리포트</p><p>Study UID: {r.get('study_instance_uid')}</p>
<p>생성일: {datetime.now():%Y-%m-%d %H:%M:%S}</p></div>
<div class="disclaimer">본 리포트는 환자 본인 제공용입니다. 무단 복제 및 배포를 금합니다.</div>
</body></html>"""


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def build_patient_export(self, request_id: str):
    """Package one patient-export request: DICOM archives + final reports +
    manifest -> zip -> Fernet-encrypted file. Marks the row ready/failed."""
    db = _get_db_session()
    if not db:
        logger.error("build_patient_export: no DB session")
        return {"status": "failed", "error": "no_db"}

    row = db.execute(text(
        "SELECT mrn, study_uids, purpose FROM patient_export_requests WHERE id = :id"
    ), {"id": request_id}).mappings().first()
    if not row:
        return {"status": "failed", "error": "request_not_found"}

    mrn = row["mrn"]
    requested_uids = row["study_uids"]  # JSONB -> list | None
    orthanc = _get_orthanc_client()
    try:
        # MRN -> patient studies (v11.2 confirmed MRN == DICOM PatientID)
        found = orthanc.post("/tools/find", json={
            "Level": "Study", "Query": {"PatientID": mrn}, "Expand": True,
        })
        studies = found.json() if found.status_code == 200 else []
        if requested_uids:
            wanted = set(requested_uids)
            studies = [s for s in studies
                       if s.get("MainDicomTags", {}).get("StudyInstanceUID") in wanted]

        if not studies:
            _mark_failed(db, request_id, "no_studies")
            return {"status": "failed", "error": "no_studies"}
        if len(studies) > settings.patient_export_max_studies:  # 공개판(PE1): 「전 스터디」도 상한 안에서만
            _mark_failed(db, request_id, "too_many_studies")
            return {"status": "failed", "error": "too_many_studies"}

        # Final/addendum reports for this patient.
        # NOTE: SQLAlchemy Enum stores the member NAME, so the column holds
        # 'FINAL'/'ADDENDUM' (uppercase), not the lowercase values.
        reports = db.execute(text("""
            SELECT * FROM reports
            WHERE patient_id = :mrn AND status IN ('FINAL', 'ADDENDUM')
        """), {"mrn": mrn}).mappings().all()
        reports_by_study = {}
        for rep in reports:
            reports_by_study.setdefault(rep["study_instance_uid"], dict(rep))

        manifest = {
            "mrn": mrn, "purpose": row["purpose"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "studies": [],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in studies:
                oid = s["ID"]
                tags = s.get("MainDicomTags", {})
                suid = tags.get("StudyInstanceUID", oid)
                arc = orthanc.get(f"/studies/{oid}/archive")
                if arc.status_code != 200:
                    logger.warning(f"archive failed for {oid}: {arc.status_code}")
                    continue
                safe = suid.replace(".", "_")[:60]
                zf.writestr(f"studies/{safe}/dicom.zip", arc.content)
                entry = {
                    "study_instance_uid": suid,
                    "study_date": tags.get("StudyDate"),
                    "description": tags.get("StudyDescription"),
                    "modalities": tags.get("ModalitiesInStudy"),
                    "has_report": suid in reports_by_study,
                }
                rep = reports_by_study.get(suid)
                if rep:
                    zf.writestr(f"studies/{safe}/report.html",
                                _report_html(rep).encode("utf-8"))
                manifest["studies"].append(entry)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))

        plaintext = buf.getvalue()
        key = Fernet.generate_key()
        token = uuid.uuid4().hex + uuid.uuid4().hex
        os.makedirs(STAGING_DIR, exist_ok=True)
        pkg_path = os.path.join(STAGING_DIR, f"{request_id}.pkg")
        with open(pkg_path, "wb") as f:
            f.write(Fernet(key).encrypt(plaintext))
        pkg_bytes = os.path.getsize(pkg_path)

        r = _get_redis()
        r.set(f"{TOKEN_PREFIX}{token}", request_id, ex=TTL_SECONDS)
        r.set(f"{KEY_PREFIX}{request_id}", key.decode(), ex=TTL_SECONDS)

        expires = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
        db.execute(text("""
            UPDATE patient_export_requests
            SET status='ready', study_count=:n, package_path=:p, package_bytes=:b,
                ready_at=now(), expires_at=:e
            WHERE id=:id
        """), {"n": len(manifest["studies"]), "p": pkg_path, "b": pkg_bytes,
               "e": expires, "id": request_id})
        db.commit()
        _audit(db, "PATIENT_EXPORT_READY", request_id, mrn,
               f"{len(manifest['studies'])} studies, {pkg_bytes}B")
        logger.info(f"patient export {request_id} ready: {len(manifest['studies'])} studies, {pkg_bytes}B")
        return {"status": "ready", "studies": len(manifest["studies"]), "bytes": pkg_bytes}
    except Exception as e:
        logger.error(f"build_patient_export {request_id} failed: {e}")
        _mark_failed(db, request_id, str(e)[:200])
        return {"status": "failed", "error": str(e)[:200]}
    finally:
        orthanc.close()
        db.close()


def _mark_failed(db, request_id: str, err: str):
    try:
        db.execute(text(
            "UPDATE patient_export_requests SET status='failed', error=:e WHERE id=:id"
        ), {"e": err, "id": request_id})
        db.commit()
    except Exception:
        pass


@celery_app.task(bind=True, max_retries=0)
def cleanup_patient_exports(self):
    """Hourly: delete staged packages past STAGING_TTL_HOURS and mark them expired."""
    db = _get_db_session()
    if not db:
        return {"cleaned": 0}
    cleaned = 0
    try:
        rows = db.execute(text("""
            SELECT id, package_path, mrn FROM patient_export_requests
            WHERE status IN ('ready', 'consumed')
              AND created_at < now() - make_interval(hours => :h)
        """), {"h": STAGING_TTL_HOURS}).mappings().all()
        for row in rows:
            p = row["package_path"]
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError as e:
                    logger.warning(f"cleanup remove failed {p}: {e}")
            db.execute(text(
                "UPDATE patient_export_requests SET status='expired', package_path=NULL WHERE id=:id"
            ), {"id": row["id"]})
            _audit(db, "PATIENT_EXPORT_EXPIRED", str(row["id"]), row.get("mrn"),
                   "staging package purged")
            cleaned += 1
        db.commit()
        if cleaned:
            logger.info(f"patient export cleanup: {cleaned} expired")
        return {"cleaned": cleaned}
    finally:
        db.close()
