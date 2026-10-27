"""DICOM Issue validation — scan endpoint, revalidation."""
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User
from app.models.validation import ValidationResult, ValidationSummary

from .fix import RULE_RESOLUTION, _cascade_fix_sop, _find_orthanc_id

logger = logging.getLogger(__name__)

validation_router = APIRouter()


@validation_router.post("/scan")
async def scan_existing_studies(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    limit: int = Query(50, ge=1, le=200),
    auto_fix: bool = Query(False, description="Auto-fix fixable issues after scan"),
):
    """Scan existing Orthanc studies, validate, and optionally auto-fix.

    Finds studies not yet validated (no records in validation_results) and validates them.
    If auto_fix=true, automatically fixes all fixable issues using cascade fix.
    """
    client = request.app.state.http_client
    from app.services.dicom_validator import DicomValidator

    validator = DicomValidator()

    # Get all study IDs from Orthanc
    try:
        resp = await client.get("/studies", params={"since": 0, "limit": limit})
        study_ids = resp.json() if resp.status_code == 200 and isinstance(resp.json(), list) else []
    except Exception as e:
        return {"error": f"Failed to fetch studies: {e}"}

    # Find already-validated study UIDs
    existing_q = await db.execute(
        select(func.distinct(ValidationResult.study_instance_uid))
    )
    validated_uids = {row[0] for row in existing_q.all()}

    scanned = 0
    issues_found = 0
    skipped = 0

    for study_id in study_ids:
        try:
            sr = await client.get(f"/studies/{study_id}")
            if sr.status_code != 200:
                continue
            study_data = sr.json()
            study_uid = study_data.get("MainDicomTags", {}).get("StudyInstanceUID", "")
            patient_tags = study_data.get("PatientMainDicomTags", {})

            if study_uid in validated_uids:
                skipped += 1
                continue

            series_ids = study_data.get("Series", [])
            instances_validated = 0
            raw_date = study_data.get("MainDicomTags", {}).get("StudyDate", "")
            study_date_val = raw_date[:8] if raw_date else None
            study_desc_val = (study_data.get("MainDicomTags", {}).get("StudyDescription") or "")[:256] or None
            patient_name_val = (patient_tags.get("PatientName") or "")[:256] or None
            patient_id_val = (patient_tags.get("PatientID") or "")[:64] or None

            for series_id in series_ids[:5]:
                try:
                    series_resp = await client.get(f"/series/{series_id}")
                    if series_resp.status_code != 200:
                        continue
                    series_data = series_resp.json()
                    instance_ids = series_data.get("Instances", [])

                    for inst_id in instance_ids[:1]:
                        try:
                            file_resp = await client.get(f"/instances/{inst_id}/file")
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
                                    fix_description=f.fix_description,
                                    issue_status="auto_fixed" if f.auto_fixed else "unreviewed",
                                ))
                                issues_found += 1

                                # Alert for critical/error issues
                                if f.severity.value in ("critical", "error"):
                                    try:
                                        from app.services.alert_service import alert_dicom_issue_critical
                                        import asyncio
                                        asyncio.create_task(alert_dicom_issue_critical(
                                            study_uid=study_uid,
                                            patient_name=patient_name_val or "-",
                                            rule_code=f.rule_code,
                                            message_text=f.message,
                                            severity=f.severity.value,
                                            modality=report.modality or "",
                                        ))
                                    except Exception:
                                        pass

                            await db.flush()

                            existing_sum = await db.execute(
                                select(ValidationSummary).where(
                                    ValidationSummary.sop_instance_uid == report.sop_instance_uid
                                )
                            )
                            if not existing_sum.scalar_one_or_none():
                                db.add(ValidationSummary(
                                    sop_instance_uid=report.sop_instance_uid,
                                    study_instance_uid=report.study_instance_uid,
                                    critical_count=report.critical_count,
                                    error_count=report.error_count,
                                    warning_count=report.warning_count,
                                    info_count=report.info_count,
                                    max_severity=report.max_severity.value if report.max_severity else None,
                                    accepted=report.accepted,
                                    ae_title=(report.ae_title or "")[:16] or None,
                                    modality=(report.modality or "")[:16] or None,
                                ))

                            instances_validated += 1
                        except Exception as e:
                            logger.warning(f"Failed to validate instance {inst_id}: {e}")
                            await db.rollback()
                            continue
                except Exception:
                    continue

            if instances_validated > 0:
                scanned += 1
                await db.commit()

        except Exception as e:
            logger.warning(f"Failed to scan study {study_id}: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            continue

    try:
        await db.commit()
    except Exception:
        await db.rollback()

    # Auto-fix if requested
    auto_fixed_count = 0
    if auto_fix and issues_found > 0:
        # Get all unreviewed issues with fixable rules
        fixable_q = await db.execute(
            select(ValidationResult).where(
                ValidationResult.issue_status == "unreviewed",
            ).order_by(ValidationResult.created_at)
        )
        fixable_issues = fixable_q.scalars().all()
        seen = set()
        for fi in fixable_issues:
            if fi.sop_instance_uid in seen:
                continue
            fixable_rules = [i.rule_code for i in fixable_issues
                             if i.sop_instance_uid == fi.sop_instance_uid
                             and RULE_RESOLUTION.get(i.rule_code, {}).get("auto_fixable", False)]
            if not fixable_rules:
                continue
            seen.add(fi.sop_instance_uid)
            oid = fi.orthanc_id or await _find_orthanc_id(client, fi.sop_instance_uid)
            if not oid:
                continue
            try:
                r = await _cascade_fix_sop(fi.sop_instance_uid, oid, client, db, user, fixable_rules)
                if r.get("fixed"):
                    auto_fixed_count += 1
            except Exception as e:
                logger.warning(f"Auto-fix during scan failed: {e}")
                try: await db.rollback()
                except Exception: pass

    return {
        "ok": True,
        "scanned_studies": scanned,
        "skipped_already_validated": skipped,
        "issues_found": issues_found,
        "auto_fixed": auto_fixed_count,
        "total_orthanc_studies": len(study_ids),
    }


@validation_router.post("/{issue_id}/revalidate")
async def revalidate_issue(
    issue_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Re-validate by fetching DICOM from Orthanc."""
    result = await db.execute(
        select(ValidationResult).where(ValidationResult.id == issue_id)
    )
    issue = result.scalar_one_or_none()
    if not issue:
        return {"error": "Issue not found"}

    if not issue.orthanc_id and not issue.sop_instance_uid:
        return {"error": "No Orthanc reference to re-validate"}

    client = request.app.state.http_client
    orthanc_id = issue.orthanc_id

    if not orthanc_id:
        try:
            resp = await client.post("/tools/find", json={
                "Level": "Instance",
                "Query": {"SOPInstanceUID": issue.sop_instance_uid},
            })
            ids = resp.json() if resp.status_code == 200 else []
            orthanc_id = ids[0] if ids else None
        except Exception:
            pass

    if not orthanc_id:
        return {"error": "Instance not found in Orthanc"}

    try:
        resp = await client.get(f"/instances/{orthanc_id}/file")
        if resp.status_code != 200:
            return {"error": f"Failed to fetch from Orthanc: {resp.status_code}"}

        from app.services.dicom_validator import DicomValidator
        validator = DicomValidator()
        report = validator.validate(resp.content)

        matching = [f for f in report.findings if f.rule_code == issue.rule_code]
        if matching:
            issue.issue_status = "unreviewed"
            issue.message = matching[0].message
            issue.details = matching[0].details
            issue.severity = matching[0].severity.value
        else:
            issue.issue_status = "auto_fixed"
            issue.reviewer_note = "재검증 결과 이슈가 해소되었습니다."
            issue.reviewed_at = datetime.now(timezone.utc)

        await db.commit()
        return {
            "ok": True,
            "still_present": len(matching) > 0,
            "total_findings": len(report.findings),
            "status": issue.issue_status,
        }
    except Exception as e:
        logger.error(f"Revalidation failed: {e}")
        return {"error": f"Revalidation failed: {str(e)}"}
