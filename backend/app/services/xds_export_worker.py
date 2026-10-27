"""XDM (XDS-I) export builder (xds-i-export feature).

Assembles a portable IHE XDM package: per-study KOS manifest + DICOM + an ebRIM
METADATA.XML, so a receiving XDS/XDM-capable site can ingest it — no live
Registry needed. Reuses Orthanc archive + kos_service + the export staging dir.
"""
import io
import logging
import os
import time
import uuid
import zipfile
from datetime import datetime, timezone, timedelta

import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_orthanc_client
from app.services.dicom_auto_validate import _get_sync_db
from app.services.kos_service import build_kos
from app.services import xds_metadata as xm
from app.services.patient_export_worker import STAGING_DIR, TTL_SECONDS

logger = logging.getLogger(__name__)

XDS_TOKEN_PREFIX = "pacs:xds:token:"   # download_token -> request_id
MAX_INSTANCES_PER_STUDY = 2000


def _get_redis():
    return sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _study_instances(orthanc, oid: str) -> list[bytes]:
    """Fetch DICOM bytes for a study's instances (capped)."""
    out = []
    sr = orthanc.get(f"/studies/{oid}")
    if sr.status_code != 200:
        return out
    for series_id in sr.json().get("Series", []):
        ser = orthanc.get(f"/series/{series_id}")
        if ser.status_code != 200:
            continue
        for inst_id in ser.json().get("Instances", []):
            if len(out) >= MAX_INSTANCES_PER_STUDY:
                return out
            f = orthanc.get(f"/instances/{inst_id}/file")
            if f.status_code == 200:
                out.append(f.content)
    return out


@celery_app.task(name="app.services.xds_export_worker.build_xds_export",
                 bind=True, max_retries=1, default_retry_delay=60)
def build_xds_export(self, request_id: str):
    db = _get_sync_db()
    if not db:
        return {"status": "failed", "error": "no_db"}
    row = db.execute(text(
        "SELECT study_uids, patient_id FROM xds_export_requests WHERE id = :id"
    ), {"id": request_id}).mappings().first()
    if not row:
        return {"status": "failed", "error": "request_not_found"}

    study_uids = row["study_uids"] or []
    orthanc = _get_orthanc_client()
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d%H%M%S")
    docs = []
    patient_id = row["patient_id"] or ""
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            doc_n = 0
            for suid in study_uids:
                # resolve Orthanc study id
                found = orthanc.post("/tools/find", json={
                    "Level": "Study", "Query": {"StudyInstanceUID": suid}, "Expand": True,
                })
                items = found.json() if found.status_code == 200 else []
                if not items:
                    continue
                oid = items[0]["ID"]
                if not patient_id:
                    patient_id = items[0].get("PatientMainDicomTags", {}).get("PatientID", "")
                instances = _study_instances(orthanc, oid)
                if not instances:
                    continue
                # KOS manifest for this study
                try:
                    kos = build_kos(instances, description=f"XDS-I manifest {suid}")
                except Exception as e:
                    logger.warning(f"KOS build failed for {suid}: {e}")
                    continue
                doc_n += 1
                doc_id = f"Document{doc_n:02d}"
                fname = f"DOC{doc_n:05d}.dcm"
                zf.writestr(f"IHE_XDM/SUBSET01/{fname}", kos)
                # KOS SOP UID for uniqueId
                import pydicom
                kos_uid = pydicom.dcmread(io.BytesIO(kos), stop_before_pixels=True).SOPInstanceUID
                docs.append(xm.DocEntry(doc_id=doc_id, file_ref=fname,
                                        unique_id=str(kos_uid), creation_time=ts))
                # DICOM payload (offline self-contained)
                arc = orthanc.get(f"/studies/{oid}/archive")
                if arc.status_code == 200:
                    safe = suid.replace(".", "_")[:60]
                    zf.writestr(f"DICOM/{safe}/dicom.zip", arc.content)

            if not docs:
                _mark_failed(db, request_id, "no_studies_or_kos")
                return {"status": "failed", "error": "no_documents"}

            sub = xm.Submission(submission_time=ts, patient_id=patient_id or "UNKNOWN",
                                source_id=f"1.2.826.0.1.3680043.openpacs.{ts}",
                                unique_id=f"1.2.826.0.1.3680043.openpacs.ss.{ts}")
            metadata = xm.build_metadata_xml(sub, docs)
            zf.writestr("IHE_XDM/SUBSET01/METADATA.XML", metadata)
            zf.writestr("README.TXT",
                        ("OpenPACS XDM (IHE Cross-Enterprise Document Media Interchange)\n"
                         f"Generated: {now.isoformat()}\nStudies: {len(docs)}\n"
                         f"Patient: {patient_id}\n\n"
                         "IHE_XDM/SUBSET01/METADATA.XML = ebRIM submission metadata\n"
                         "IHE_XDM/SUBSET01/DOC*.dcm     = KOS manifests (XDS-I)\n"
                         "DICOM/<studyUID>/dicom.zip    = referenced DICOM instances\n\n"
                         "Note: structurally minimal-conformant; not IHE Gazelle certified.\n")
                        .encode("utf-8"))
            zf.writestr("INDEX.HTM",
                        (f"<html><body><h2>OpenPACS XDM Export</h2>"
                         f"<p>Studies: {len(docs)} · Patient: {patient_id}</p></body></html>")
                        .encode("utf-8"))

        os.makedirs(STAGING_DIR, exist_ok=True)
        pkg_path = os.path.join(STAGING_DIR, f"xds_{request_id}.zip")
        with open(pkg_path, "wb") as f:
            f.write(buf.getvalue())
        pkg_bytes = os.path.getsize(pkg_path)
        token = uuid.uuid4().hex + uuid.uuid4().hex
        _get_redis().set(f"{XDS_TOKEN_PREFIX}{token}", request_id, ex=TTL_SECONDS)
        expires = now + timedelta(seconds=TTL_SECONDS)
        db.execute(text("""
            UPDATE xds_export_requests
            SET status='ready', study_count=:n, package_path=:p, package_bytes=:b,
                patient_id=:pid, ready_at=now(), expires_at=:e
            WHERE id=:id
        """), {"n": len(docs), "p": pkg_path, "b": pkg_bytes, "pid": patient_id,
               "e": expires, "id": request_id})
        db.commit()
        logger.info(f"xds export {request_id} ready: {len(docs)} studies, {pkg_bytes}B")
        return {"status": "ready", "studies": len(docs), "bytes": pkg_bytes, "token": token}
    except Exception as e:
        logger.error(f"build_xds_export {request_id} failed: {e}")
        _mark_failed(db, request_id, str(e)[:200])
        return {"status": "failed", "error": str(e)[:200]}
    finally:
        orthanc.close()
        db.close()


def _mark_failed(db, request_id: str, err: str):
    try:
        db.execute(text("UPDATE xds_export_requests SET status='failed', error=:e WHERE id=:id"),
                   {"e": err, "id": request_id})
        db.commit()
    except Exception:
        pass
