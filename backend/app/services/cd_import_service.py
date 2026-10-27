"""CD/DVD Import Service.

Handles the import workflow: upload → parse → match → import → history.
"""
import io
import json
import logging
import shutil
import zipfile
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
import pydicom
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.upload_stream import bounded_zip_extractall, bounded_zip_read
from app.services.dicomdir_parser import DicomdirParser
from app.services.dicom_validator import DicomValidator

logger = logging.getLogger(__name__)


class CDImportService:
    """Service for importing DICOM files from CD/DVD/ZIP."""

    def __init__(self, db: AsyncSession, orthanc_client: httpx.AsyncClient):
        self.db = db
        self.orthanc = orthanc_client
        self.parser = DicomdirParser()
        self.validator = DicomValidator()

    async def create_import_job(
        self,
        filename: str,
        user_id: str,
        zip_path: Optional[str] = None,
        zip_bytes: Optional[bytes] = None,
    ) -> dict:
        """Create a new import job from uploaded ZIP/folder.

        업로드 ZIP은 `zip_path`(디스크 경로)로 받는 것을 권장한다 — 전체를 RAM에
        올리지 않고 멤버 단위로 추출(대형 CD/DVD OOM 방지). `zip_bytes`는 하위호환용.

        Returns import job info with DICOMDIR parse results.
        """
        if zip_path is None and zip_bytes is None:
            raise ValueError("zip_path 또는 zip_bytes 중 하나는 필요합니다")

        job_id = str(uuid4())
        temp_dir = tempfile.mkdtemp(prefix=f"cd_import_{job_id[:8]}_")

        # ZIP 소스: 디스크 경로(스트리밍) 우선, 없으면 인메모리 bytes.
        zip_source = zip_path if zip_path is not None else io.BytesIO(zip_bytes)

        # Extract ZIP
        dicom_files = []
        dicomdir_data = None

        try:
            with zipfile.ZipFile(zip_source) as zf:
                # 상한 있는 해제 — `extractall`은 압축 해제 후 크기가 무제한이라
                # 작은 ZIP 하나로 공유 디스크를 채울 수 있었다(v13.45).
                bounded_zip_extractall(
                    zf, temp_dir,
                    max_total_bytes=settings.max_zip_extract_bytes,
                    max_member_bytes=settings.max_zip_member_bytes,
                    max_entries=settings.max_zip_entries,
                )
                all_files = zf.namelist()

                # Find DICOMDIR
                dicomdir_name = self.parser.find_dicomdir(all_files)
                if dicomdir_name:
                    dicomdir_data = bounded_zip_read(
                        zf, dicomdir_name,
                        max_bytes=settings.max_zip_member_ram_bytes,
                    )

                # Find all DICOM files
                for f in all_files:
                    full_path = os.path.join(temp_dir, f)
                    if os.path.isfile(full_path) and not f.endswith("/"):
                        dicom_files.append(full_path)
        except zipfile.BadZipFile:
            # Not a ZIP — treat as single DICOM file
            single_path = os.path.join(temp_dir, filename)
            if zip_path is not None:
                shutil.copyfile(zip_path, single_path)
            else:
                with open(single_path, "wb") as f:
                    f.write(zip_bytes)
            dicom_files.append(single_path)
        except Exception:
            # 상한 초과(413)로 중단되면 부분 해제물이 남는다 — 막으려던 디스크 점유를
            # 실패 경로가 그대로 남기면 안 되므로 지우고 올린다. 성공 경로는 보존해야
            # 한다(이후 import 단계가 temp_dir을 읽고, DB `import_history.temp_dir`에 기록).
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        # Parse DICOMDIR if found
        dicomdir_result = None
        if dicomdir_data:
            dicomdir_result = self.parser.parse(dicomdir_data)

        # If no DICOMDIR, scan files directly
        if not dicomdir_result or not dicomdir_result["patients"]:
            dicomdir_result = await self._scan_dicom_files(dicom_files)

        # Check for duplicates
        duplicate_studies = await self._check_duplicates(dicomdir_result)

        # Save job to DB
        await self.db.execute(text("""
            INSERT INTO import_history (id, filename, status, user_id, dicomdir_result,
                total_files, total_studies, total_patients, duplicate_studies, temp_dir, created_at, updated_at)
            VALUES (:id, :fn, 'pending', :uid, CAST(:dir AS jsonb), :tf, :ts, :tp, CAST(:dup AS jsonb), :td, :now, :now)
        """), {
            "id": job_id, "fn": filename, "uid": user_id,
            "dir": json.dumps(dicomdir_result, default=str),
            "tf": len(dicom_files),
            "ts": dicomdir_result.get("total_studies", 0),
            "tp": dicomdir_result.get("total_patients", 0),
            "dup": json.dumps(duplicate_studies),
            "td": temp_dir,
            "now": datetime.now(timezone.utc),
        })
        await self.db.commit()

        return {
            "id": job_id,
            "filename": filename,
            "status": "pending",
            "total_files": len(dicom_files),
            "dicomdir": dicomdir_result,
            "duplicate_studies": duplicate_studies,
        }

    async def confirm_import(self, job_id: str, skip_duplicates: bool = True,
                              normalize: bool = True) -> dict:
        """Execute import after user confirmation."""
        # Get job info
        result = await self.db.execute(text(
            "SELECT temp_dir, status, total_files FROM import_history WHERE id = :id"
        ), {"id": job_id})
        row = result.mappings().first()

        if not row:
            raise ValueError(f"Import job {job_id} not found")
        if row["status"] != "pending":
            raise ValueError(f"Import job {job_id} is {row['status']}, not pending")

        temp_dir = row["temp_dir"]
        total_files = row["total_files"]

        # Update status
        await self.db.execute(text(
            "UPDATE import_history SET status = 'importing', updated_at = :now WHERE id = :id"
        ), {"id": job_id, "now": datetime.now(timezone.utc)})
        await self.db.commit()

        # Import files
        uploaded = 0
        skipped = 0
        failed = 0
        errors = []

        for root, _, files in os.walk(temp_dir):
            for fname in files:
                filepath = os.path.join(root, fname)
                try:
                    with open(filepath, "rb") as f:
                        data = f.read()

                    # Skip non-DICOM files (DICOMDIR, etc.)
                    if len(data) < 132:
                        continue
                    # Check DICOM magic
                    if data[128:132] != b"DICM" and not fname.upper() == "DICOMDIR":
                        continue
                    if fname.upper() == "DICOMDIR":
                        continue

                    # Validate
                    if normalize:
                        report = self.validator.validate(data)
                        # Log validation but don't reject (import everything)

                    # Upload to Orthanc
                    resp = await self.orthanc.post(
                        "/instances",
                        content=data,
                        headers={"Content-Type": "application/dicom"},
                    )

                    if resp.status_code == 200:
                        uploaded += 1
                    elif resp.status_code == 409:
                        if skip_duplicates:
                            skipped += 1
                        else:
                            uploaded += 1
                    else:
                        failed += 1
                        errors.append(f"{fname}: HTTP {resp.status_code}")

                except Exception as e:
                    failed += 1
                    errors.append(f"{fname}: {str(e)[:100]}")

        # Update job status
        final_status = "completed" if failed == 0 else "completed_with_errors"
        await self.db.execute(text("""
            UPDATE import_history SET status = :status, uploaded_files = :up,
                skipped_files = :sk, failed_files = :fl,
                errors = CAST(:err AS jsonb), completed_at = :now, updated_at = :now
            WHERE id = :id
        """), {
            "id": job_id, "status": final_status,
            "up": uploaded, "sk": skipped, "fl": failed,
            "err": json.dumps(errors[:50]),
            "now": datetime.now(timezone.utc),
        })
        await self.db.commit()

        # Cleanup temp directory
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        return {
            "id": job_id,
            "status": final_status,
            "uploaded": uploaded,
            "skipped": skipped,
            "failed": failed,
            "errors": errors[:10],
        }

    async def get_history(self, page: int = 1, page_size: int = 20) -> dict:
        """Get import history list."""
        offset = (page - 1) * page_size
        result = await self.db.execute(text("""
            SELECT id, filename, status, total_files, total_studies, total_patients,
                uploaded_files, skipped_files, failed_files, user_id, created_at, completed_at
            FROM import_history
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """), {"limit": page_size, "offset": offset})

        count_result = await self.db.execute(text("SELECT count(*) FROM import_history"))
        total = count_result.scalar()

        return {
            "items": [dict(r._mapping) for r in result],
            "total": total,
            "page": page,
        }

    async def _scan_dicom_files(self, file_paths: list[str]) -> dict:
        """Scan DICOM files directly when no DICOMDIR exists."""
        patients = {}
        total_instances = 0

        for fp in file_paths:
            try:
                ds = pydicom.dcmread(fp, stop_before_pixels=True, force=True)

                pid = getattr(ds, "PatientID", "UNKNOWN")
                study_uid = getattr(ds, "StudyInstanceUID", "")
                series_uid = getattr(ds, "SeriesInstanceUID", "")

                if not study_uid:
                    continue

                if pid not in patients:
                    patients[pid] = {
                        "patient_id": pid,
                        "patient_name": str(getattr(ds, "PatientName", "")),
                        "studies": {},
                    }

                if study_uid not in patients[pid]["studies"]:
                    patients[pid]["studies"][study_uid] = {
                        "study_instance_uid": study_uid,
                        "study_date": getattr(ds, "StudyDate", ""),
                        "study_description": getattr(ds, "StudyDescription", ""),
                        "modalities": set(),
                        "series": {},
                    }

                study = patients[pid]["studies"][study_uid]
                modality = getattr(ds, "Modality", "OT")
                study["modalities"].add(modality)

                if series_uid not in study["series"]:
                    study["series"][series_uid] = {
                        "series_instance_uid": series_uid,
                        "modality": modality,
                        "series_description": getattr(ds, "SeriesDescription", ""),
                        "instance_count": 0,
                    }

                study["series"][series_uid]["instance_count"] += 1
                total_instances += 1

            except Exception:
                continue

        # Convert to list format
        patient_list = []
        for p in patients.values():
            studies = []
            for s in p["studies"].values():
                s["modalities"] = sorted(s["modalities"])
                s["series"] = list(s["series"].values())
                studies.append(s)
            p["studies"] = studies
            patient_list.append(p)

        return {
            "patients": patient_list,
            "total_instances": total_instances,
            "total_studies": sum(len(p["studies"]) for p in patient_list),
            "total_patients": len(patient_list),
        }

    async def _check_duplicates(self, dicomdir_result: dict) -> list[str]:
        """Check which studies already exist in Orthanc."""
        duplicates = []
        for patient in dicomdir_result.get("patients", []):
            for study in patient.get("studies", []):
                uid = study.get("study_instance_uid", "")
                if uid:
                    try:
                        resp = await self.orthanc.post(
                            "/tools/find",
                            json={"Level": "Study", "Query": {"StudyInstanceUID": uid}},
                        )
                        if resp.status_code == 200 and resp.json():
                            duplicates.append(uid)
                    except Exception:
                        pass
        return duplicates
