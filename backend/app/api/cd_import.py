"""CD/DVD Import API — upload, parse DICOMDIR, patient matching, bulk import."""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.core.upload_stream import spool_upload_to_disk
from app.models.user import Role, User
from app.services.cd_import_service import CDImportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/import", tags=["CD Import"])


@router.post("/cd", summary="CD/DVD ZIP 업로드 + DICOMDIR 파싱")
async def upload_cd(
    request: Request,
    file: UploadFile = File(..., description="ZIP 파일 또는 DICOM 파일"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """CD/DVD 영상을 ZIP으로 업로드합니다.

    1. ZIP 파일 업로드 (DICOMDIR 포함 가능)
    2. DICOMDIR 자동 파싱 → 환자/스터디 목록 반환
    3. 중복 스터디 자동 감지

    Response: Import job ID + DICOMDIR 파싱 결과
    """
    # 대형 CD/DVD ZIP(최대 5GB)을 RAM에 통째로 올리지 않고 청크로 디스크에 스풀.
    zip_path, _size = await spool_upload_to_disk(
        file, max_bytes=settings.max_streaming_upload_bytes, suffix=".zip"
    )

    service = CDImportService(db=db, orthanc_client=request.app.state.http_client)

    try:
        result = service.create_import_job(
            zip_path=zip_path,
            filename=file.filename or "upload.zip",
            user_id=str(user.id) if hasattr(user, 'id') else user.get("id", ""),
        )
        # Handle both sync and async
        if hasattr(result, '__await__'):
            result = await result

        logger.info(f"CD import job created: {result['id']}, {result['total_files']} files")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CD import upload failed: {e}")
        raise HTTPException(500, f"Import failed: {str(e)[:200]}")
    finally:
        # 스풀된 ZIP 임시파일 정리(서비스가 temp_dir로 이미 추출 완료).
        try:
            os.unlink(zip_path)
        except OSError:
            pass


@router.get("/cd/{job_id}", summary="Import 작업 상태 조회")
async def get_import_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import 작업의 현재 상태를 조회합니다."""
    result = await db.execute(text(
        "SELECT * FROM import_history WHERE id = :id"
    ), {"id": job_id})
    row = result.mappings().first()

    if not row:
        raise HTTPException(404, "Import job not found")

    return dict(row)


@router.get("/cd/{job_id}/dicomdir", summary="DICOMDIR 파싱 결과 조회")
async def get_dicomdir(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DICOMDIR 파싱 결과 (환자/스터디/시리즈 목록)를 반환합니다."""
    result = await db.execute(text(
        "SELECT dicomdir_result, duplicate_studies FROM import_history WHERE id = :id"
    ), {"id": job_id})
    row = result.mappings().first()

    if not row:
        raise HTTPException(404, "Import job not found")

    import json
    return {
        "dicomdir": json.loads(row["dicomdir_result"]) if isinstance(row["dicomdir_result"], str) else row["dicomdir_result"],
        "duplicate_studies": json.loads(row["duplicate_studies"]) if isinstance(row["duplicate_studies"], str) else row["duplicate_studies"],
    }


@router.post("/cd/{job_id}/confirm", summary="Import 실행 확인")
async def confirm_import(
    request: Request,
    job_id: str,
    skip_duplicates: bool = Query(True, description="중복 스터디 건너뛰기"),
    normalize: bool = Query(True, description="비표준 DICOM 검증"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """환자 매칭 확인 후 실제 Import를 실행합니다.

    모든 DICOM 파일을 Orthanc에 업로드하고 결과를 반환합니다.
    """
    service = CDImportService(db=db, orthanc_client=request.app.state.http_client)

    try:
        result = await service.confirm_import(
            job_id=job_id,
            skip_duplicates=skip_duplicates,
            normalize=normalize,
        )
        logger.info(f"CD import completed: {job_id}, uploaded={result['uploaded']}, skipped={result['skipped']}")
        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"CD import execution failed: {e}")
        raise HTTPException(500, f"Import execution failed: {str(e)[:200]}")


@router.get("/history", summary="Import 이력 목록")
async def get_import_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CD Import 이력을 조회합니다."""
    service = CDImportService(db=db, orthanc_client=None)
    return await service.get_history(page=page, page_size=page_size)
