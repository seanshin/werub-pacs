"""Data migration API — import from external PACS or local files."""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User
from app.services.dicom_validator import DicomValidator

router = APIRouter(prefix="/api/v1/migration", tags=["migration"])
validator = DicomValidator()


class MigrationStats(BaseModel):
    total: int = 0
    uploaded: int = 0
    validated: int = 0
    rejected: int = 0
    errors: list[str] = []


@router.post("/upload-batch")
async def upload_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    skip_validation: bool = Query(False),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Upload multiple DICOM files with validation.

    For bulk migration from CD/DVD or file export.
    """
    stats = MigrationStats(total=len(files))
    results = []

    for file in files:
        data = await file.read()
        entry = {"filename": file.filename, "status": "pending"}

        # Validate
        if not skip_validation:
            report = validator.validate(data)
            entry["validation"] = {
                "accepted": report.accepted,
                "max_severity": report.max_severity.value if report.max_severity else None,
                "findings_count": len(report.findings),
            }
            stats.validated += 1

            if not report.accepted:
                entry["status"] = "rejected"
                entry["reason"] = [f.message for f in report.findings if f.severity.value == "critical"]
                stats.rejected += 1
                results.append(entry)
                continue

        # Upload to Orthanc
        try:
            resp = await request.app.state.http_client.post(
                "/instances",
                content=data,
                headers={"Content-Type": "application/dicom"},
            )
            if resp.status_code in (200, 409):
                result = resp.json()
                entry["status"] = "stored" if resp.status_code == 200 else "duplicate"
                entry["orthanc_id"] = result.get("ID")
                entry["study_uid"] = result.get("ParentStudy")
                stats.uploaded += 1
            else:
                entry["status"] = "error"
                entry["reason"] = resp.text[:200]
                stats.errors.append(f"{file.filename}: {resp.status_code}")
        except Exception as e:
            entry["status"] = "error"
            entry["reason"] = str(e)[:200]
            stats.errors.append(f"{file.filename}: {str(e)[:100]}")

        results.append(entry)

    return {
        "stats": stats.model_dump(),
        "results": results,
    }


@router.get("/verify")
async def verify_migration(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Verify migration completeness — compare Orthanc statistics."""
    resp = await request.app.state.http_client.get("/statistics")
    orthanc_stats = resp.json()

    return {
        "orthanc": {
            "patients": orthanc_stats.get("CountPatients"),
            "studies": orthanc_stats.get("CountStudies"),
            "series": orthanc_stats.get("CountSeries"),
            "instances": orthanc_stats.get("CountInstances"),
            "disk_size_mb": orthanc_stats.get("TotalDiskSizeMB"),
        },
        "status": "Use these numbers to compare with source PACS counts",
    }
