"""DICOM export API — ZIP download, JPEG conversion."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/export", tags=["export"])

# 비익명 DICOM/영상 반출 — 임상 staff 전용, 반출이라 BTG 차단. RESEARCHER 제외(익명화 EP 사용).
# (이전엔 get_current_user만이라 RESEARCHER 포함 누구나 임의 study 대량 반출 가능했음.)
ExportRoles = RequireRole(
    Role.ADMIN, Role.RADIOLOGIST, Role.RESIDENT, Role.PHYSICIAN, Role.TECHNOLOGIST,
    allow_btg=False,
)


@router.get("/study/{study_id}/dicom")
@AuditLogger.log("EXPORT_INITIATED", "Export")
async def export_study_dicom(
    study_id: str,
    request: Request,
    user: Annotated[User, Depends(ExportRoles)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download study as DICOM ZIP archive."""
    client = request.app.state.http_client
    resp = await client.get(f"/studies/{study_id}/archive")
    if resp.status_code != 200:
        raise NotFoundError(resource="Study", resource_id=study_id)

    return StreamingResponse(
        iter([resp.content]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=study_{study_id[:8]}.zip"},
    )


@router.get("/series/{series_id}/dicom")
@AuditLogger.log("EXPORT_INITIATED", "Export")
async def export_series_dicom(
    series_id: str,
    request: Request,
    user: Annotated[User, Depends(ExportRoles)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download series as DICOM ZIP archive."""
    client = request.app.state.http_client
    resp = await client.get(f"/series/{series_id}/archive")
    if resp.status_code != 200:
        raise NotFoundError(resource="Series", resource_id=series_id)

    return StreamingResponse(
        iter([resp.content]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=series_{series_id[:8]}.zip"},
    )


@router.get("/instance/{instance_id}/jpeg")
@AuditLogger.log("EXPORT_INITIATED", "Export")
async def export_instance_jpeg(
    instance_id: str,
    request: Request,
    user: Annotated[User, Depends(ExportRoles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    quality: int = Query(90, ge=1, le=100),
):
    """Download single instance as JPEG image (rendered with current W/L)."""
    client = request.app.state.http_client
    resp = await client.get(f"/instances/{instance_id}/preview")
    if resp.status_code != 200:
        raise NotFoundError(resource="Instance", resource_id=instance_id)

    return StreamingResponse(
        iter([resp.content]),
        media_type="image/jpeg",
        headers={"Content-Disposition": f"attachment; filename={instance_id[:8]}.jpg"},
    )


@router.get("/instance/{instance_id}/png")
@AuditLogger.log("EXPORT_INITIATED", "Export")
async def export_instance_png(
    instance_id: str,
    request: Request,
    user: Annotated[User, Depends(ExportRoles)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Download single instance as PNG image."""
    client = request.app.state.http_client
    resp = await client.get(
        f"/instances/{instance_id}/preview",
        headers={"Accept": "image/png"},
    )
    if resp.status_code != 200:
        raise NotFoundError(resource="Instance", resource_id=instance_id)

    return StreamingResponse(
        iter([resp.content]),
        media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename={instance_id[:8]}.png"},
    )
