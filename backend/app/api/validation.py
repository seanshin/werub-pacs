"""DICOM validation API endpoints."""
import asyncio
import hashlib
import json
import logging
from typing import Annotated

import pydicom
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.cache import get_cache_manager
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User
from app.models.validation import ValidationResult, ValidationSummary
from app.services.dicom_validator import DicomValidator, ValidationReport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/validation", tags=["validation"])

validator = DicomValidator()

# 24-hour TTL for validation result cache
_VALIDATION_CACHE_TTL = 86400


def serialize_validation_report(report: ValidationReport) -> dict:
    """Convert a ValidationReport into the API response dict.

    Pure function (no I/O) so the response contract can be unit-tested.
    """
    return {
        "sop_instance_uid": report.sop_instance_uid,
        "study_instance_uid": report.study_instance_uid,
        "modality": report.modality,
        "manufacturer": report.manufacturer,
        "accepted": report.accepted,
        "max_severity": report.max_severity.value if report.max_severity else None,
        "counts": {
            "critical": report.critical_count,
            "error": report.error_count,
            "warning": report.warning_count,
            "info": report.info_count,
        },
        "findings": [
            {
                "severity": f.severity.value,
                "category": f.category.value,
                "rule_code": f.rule_code,
                "message": f.message,
                "details": f.details,
                "auto_fixed": f.auto_fixed,
            }
            for f in report.findings
        ],
    }


async def _persist_validation(report: ValidationReport, db: AsyncSession):
    """Save validation findings to DB (async, non-blocking)."""
    try:
        # Extract patient info from report
        for f in report.findings:
            db.add(ValidationResult(
                sop_instance_uid=report.sop_instance_uid,
                study_instance_uid=report.study_instance_uid,
                series_instance_uid=report.series_instance_uid,
                ae_title=report.ae_title or None,
                modality=report.modality or None,
                manufacturer=report.manufacturer or None,
                station_name=report.station_name or None,
                severity=f.severity.value,
                category=f.category.value,
                rule_code=f.rule_code,
                message=f.message,
                details=f.details,
                auto_fixed=f.auto_fixed,
                fix_description=f.fix_description,
                issue_status="auto_fixed" if f.auto_fixed else "unreviewed",
            ))

        # Upsert summary
        from sqlalchemy import select
        existing = await db.execute(
            select(ValidationSummary).where(
                ValidationSummary.sop_instance_uid == report.sop_instance_uid
            )
        )
        summary = existing.scalar_one_or_none()
        if summary:
            summary.critical_count = report.critical_count
            summary.error_count = report.error_count
            summary.warning_count = report.warning_count
            summary.info_count = report.info_count
            summary.max_severity = report.max_severity.value if report.max_severity else None
            summary.accepted = report.accepted
        else:
            db.add(ValidationSummary(
                sop_instance_uid=report.sop_instance_uid,
                study_instance_uid=report.study_instance_uid,
                critical_count=report.critical_count,
                error_count=report.error_count,
                warning_count=report.warning_count,
                info_count=report.info_count,
                max_severity=report.max_severity.value if report.max_severity else None,
                accepted=report.accepted,
                ae_title=report.ae_title or None,
                modality=report.modality or None,
            ))

        await db.commit()
        logger.debug(f"Persisted {len(report.findings)} findings for {report.sop_instance_uid}")
    except Exception as e:
        logger.warning(f"Failed to persist validation results: {e}")
        await db.rollback()


@router.post("/validate", response_model=None)
@AuditLogger.log("DICOM_VALIDATION", "DicomFile")
async def validate_dicom(
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False))],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Validate a DICOM file for non-standard conformance issues.

    Upload a DICOM file and receive a detailed validation report including:
    - Missing/malformed mandatory tags
    - JPEG density vs Pixel Spacing mismatch detection
    - Transfer Syntax and character set issues

    Results are cached in Redis for 24 hours and persisted to DB.
    """
    data = await file.read()

    # Compute content hash for cache key (SOP Instance UID not yet known before parsing)
    content_hash = hashlib.sha256(data).hexdigest()[:24]
    cache_key = f"pacs:validation:{content_hash}"

    cache_mgr = get_cache_manager()

    # Try cache first
    try:
        cached_raw = await cache_mgr.get(cache_key)
        if cached_raw:
            logger.debug(f"Validation cache HIT: {cache_key}")
            return json.loads(cached_raw)
    except Exception as e:
        logger.warning(f"Validation cache read error for {cache_key}: {e}")

    report = validator.validate(data)

    result = serialize_validation_report(report)

    # Cache result keyed by content hash (24 h TTL)
    try:
        await cache_mgr.set(cache_key, json.dumps(result, default=str), ttl=_VALIDATION_CACHE_TTL)
        logger.debug(f"Validation cache SET: {cache_key}")
    except Exception as e:
        logger.warning(f"Validation cache write error for {cache_key}: {e}")

    # Persist to DB (non-blocking, uses own session)
    if report.findings:
        async def _persist_bg():
            from app.core.database import async_session
            if async_session:
                async with async_session() as bg_db:
                    await _persist_validation(report, bg_db)
        asyncio.create_task(_persist_bg())

    return result


@router.post("/validate-batch", response_model=None)
@AuditLogger.log("DICOM_VALIDATION", "DicomFile")
async def validate_dicom_batch(
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False))],
    files: list[UploadFile] = File(...),
):
    """Validate multiple DICOM files at once."""
    results = []
    for file in files:
        data = await file.read()
        report = validator.validate(data)
        results.append({
            "filename": file.filename,
            "sop_instance_uid": report.sop_instance_uid,
            "accepted": report.accepted,
            "max_severity": report.max_severity.value if report.max_severity else None,
            "counts": {
                "critical": report.critical_count,
                "error": report.error_count,
                "warning": report.warning_count,
                "info": report.info_count,
            },
        })

    total = len(results)
    accepted = sum(1 for r in results if r["accepted"])
    return {
        "total": total,
        "accepted": accepted,
        "rejected": total - accepted,
        "results": results,
    }
