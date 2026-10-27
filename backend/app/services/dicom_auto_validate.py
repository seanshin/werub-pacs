"""Celery beat task: Auto-validate new DICOM studies every 5 minutes.

Scans Orthanc for studies not yet in validation_results,
runs DicomValidator, saves findings, and optionally auto-fixes.
"""
import hashlib
import logging

import httpx

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_orthanc_client():
    return httpx.Client(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_username, settings.orthanc_password),
        timeout=60.0,
    )


_sync_engine = None


def _get_sync_db():
    """Synchronous DB session for Celery tasks (cached bounded-pool engine).
    A NEW create_engine per call leaks pooled connections that are never
    disposed → idle connections accumulate over hours. Cache the engine once."""
    global _sync_engine
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    if _sync_engine is None:
        sync_url = settings.database_url.replace("+asyncpg", "")
        if "postgresql://" in sync_url and "+psycopg2" not in sync_url:
            sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
        _sync_engine = create_engine(sync_url, pool_size=2, max_overflow=3,
                                     pool_pre_ping=True, pool_recycle=1800)
    return Session(_sync_engine)


@celery_app.task(name="app.services.dicom_auto_validate.auto_validate_new_studies", bind=True, max_retries=1)
def auto_validate_new_studies(self):
    """Periodic task: scan unvalidated studies and record issues."""
    from app.services.dicom_validator import DicomValidator
    from app.models.validation import ValidationResult, ValidationSummary
    from app.services.beat_lock import acquire_beat_lock, release_beat_lock

    if not acquire_beat_lock("dicom_auto_validate"):
        logger.info("dicom_auto_validate: previous run still active, skipping")
        return {"skipped": "locked"}

    client = _get_orthanc_client()
    db = _get_sync_db()
    validator = DicomValidator()

    try:
        # Get recent studies from Orthanc
        resp = client.get("/studies", params={"since": 0, "limit": 50})
        if resp.status_code != 200:
            logger.warning("Failed to fetch studies from Orthanc")
            return {"error": "Orthanc unavailable"}

        study_ids = resp.json() if isinstance(resp.json(), list) else []

        # Find already-validated study UIDs
        from sqlalchemy import select, func
        existing = db.execute(
            select(func.distinct(ValidationResult.study_instance_uid))
        )
        validated_uids = {row[0] for row in existing.all()}

        scanned = 0
        issues_found = 0

        for study_id in study_ids:
            try:
                sr = client.get(f"/studies/{study_id}")
                if sr.status_code != 200:
                    continue
                study_data = sr.json()
                study_uid = study_data.get("MainDicomTags", {}).get("StudyInstanceUID", "")
                patient_tags = study_data.get("PatientMainDicomTags", {})

                if study_uid in validated_uids:
                    continue

                raw_date = study_data.get("MainDicomTags", {}).get("StudyDate", "")
                study_date_val = raw_date[:8] if raw_date else None
                study_desc_val = (study_data.get("MainDicomTags", {}).get("StudyDescription") or "")[:256] or None
                patient_name_val = (patient_tags.get("PatientName") or "")[:256] or None
                patient_id_val = (patient_tags.get("PatientID") or "")[:64] or None

                series_ids = study_data.get("Series", [])
                for series_id in series_ids[:3]:
                    try:
                        series_resp = client.get(f"/series/{series_id}")
                        if series_resp.status_code != 200:
                            continue
                        instance_ids = series_resp.json().get("Instances", [])

                        for inst_id in instance_ids[:1]:
                            try:
                                file_resp = client.get(f"/instances/{inst_id}/file")
                                if file_resp.status_code != 200:
                                    continue

                                report = validator.validate(file_resp.content)

                                for f in report.findings:
                                    db.add(ValidationResult(
                                        sop_instance_uid=report.sop_instance_uid,
                                        study_instance_uid=report.study_instance_uid,
                                        series_instance_uid=report.series_instance_uid,
                                        orthanc_id=inst_id,
                                        ae_title=(report.ae_title or "")[:16] or None,
                                        modality=(report.modality or "")[:16] or None,
                                        manufacturer=(report.manufacturer or "")[:64] or None,
                                        station_name=(report.station_name or "")[:64] or None,
                                        patient_name=patient_name_val,
                                        patient_id=patient_id_val,
                                        study_description=study_desc_val,
                                        study_date=study_date_val,
                                        severity=f.severity.value,
                                        category=f.category.value,
                                        rule_code=f.rule_code,
                                        message=f.message[:2000] if f.message else "",
                                        details=f.details,
                                        auto_fixed=f.auto_fixed,
                                        issue_status="unreviewed",
                                    ))
                                    issues_found += 1

                                db.flush()
                            except Exception as e:
                                logger.debug(f"Validate instance {inst_id} failed: {e}")
                                db.rollback()
                                continue
                    except Exception:
                        continue

                scanned += 1
                db.commit()

            except Exception as e:
                logger.debug(f"Scan study {study_id} failed: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

        logger.info(f"Auto-validate: scanned={scanned}, issues={issues_found}")
        return {"scanned": scanned, "issues_found": issues_found}

    except Exception as e:
        logger.error(f"Auto-validate task failed: {e}")
        return {"error": str(e)}
    finally:
        release_beat_lock("dicom_auto_validate")
        db.close()
        client.close()
