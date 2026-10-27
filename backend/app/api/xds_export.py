"""XDM (XDS-I) export API (xds-i-export feature).

Clinician/admin-driven export of studies as a portable IHE XDM package
(KOS + DICOM + ebRIM METADATA.XML). Internal-user driven, so JWT-authed
download (not the patient-export medical-network gateway).
"""
import json
import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User
from app.services.xds_export_worker import XDS_TOKEN_PREFIX

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/xds-export", tags=["XDS-I 패키지 export"])


class XdsExportRequest(BaseModel):
    study_instance_uids: list[str] = Field(..., min_length=1, max_length=200)
    patient_id: str | None = None


async def _audit(db, action, request_id, user, detail):
    try:
        await db.execute(text("""
            INSERT INTO audit_logs (id, user_id, username, action, resource_type,
                resource_id, description, created_at)
            VALUES (:id, NULL, :u, :a, 'XdsExport', :rid, :d, now())
        """), {"id": str(uuid.uuid4()), "u": user, "a": action, "rid": request_id, "d": detail})
        await db.commit()
    except Exception as e:
        # 반출 감사 공백은 규제 리스크 — warning이 아닌 error로 가시화
        logger.error(f"xds export audit failed: {e}")


@router.post("/requests", status_code=202, summary="XDM 패키지 생성 요청")
async def create_export(
    body: XdsExportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    request_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO xds_export_requests (id, study_uids, patient_id, requested_by)
        VALUES (:id, :uids, :pid, :by)
    """), {"id": request_id, "uids": json.dumps(body.study_instance_uids),
           "pid": body.patient_id, "by": user.username})
    await db.commit()
    await _audit(db, "XDS_EXPORT_REQUESTED", request_id, user.username,
                 f"{len(body.study_instance_uids)} studies")
    from app.services.xds_export_worker import build_xds_export
    build_xds_export.delay(request_id)
    return {"request_id": request_id, "status": "processing"}


@router.get("/requests/{request_id}", summary="XDM 생성 상태/다운로드 토큰")
async def get_export(
    request_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    row = (await db.execute(text(
        "SELECT * FROM xds_export_requests WHERE id = :id"
    ), {"id": request_id})).mappings().first()
    if not row:
        raise HTTPException(404, "Request not found")
    # Ownership scope: non-admins may only access requests they created.
    if Role(user.role) != Role.ADMIN and row["requested_by"] != user.username:
        raise HTTPException(403, "본인이 생성한 요청만 조회할 수 있습니다")
    resp = {"request_id": request_id, "status": row["status"],
            "study_count": row["study_count"], "package_bytes": row["package_bytes"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None}
    if row["status"] == "failed":
        resp["error"] = row["error"]
    elif row["status"] == "ready":
        redis = request.app.state.redis
        async for k in redis.scan_iter(match=f"{XDS_TOKEN_PREFIX}*", count=200):
            if await redis.get(k) == request_id:
                resp["download_token"] = k.split(XDS_TOKEN_PREFIX, 1)[1]
                break
    return resp


@router.get("/requests/{request_id}/download", summary="XDM ZIP 다운로드")
async def download_export(
    request_id: str,
    token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    """JWT 인증 + 다운로드 토큰 이중 확인. 패키지 스트리밍."""
    redis = request.app.state.redis
    mapped = await redis.get(f"{XDS_TOKEN_PREFIX}{token}")
    if mapped != request_id:
        raise HTTPException(410, "Token invalid or expired")
    row = (await db.execute(text(
        "SELECT package_path, requested_by FROM xds_export_requests WHERE id = :id"
    ), {"id": request_id})).mappings().first()
    if not row or not row["package_path"] or not os.path.exists(row["package_path"]):
        raise HTTPException(410, "Package no longer available")
    # Ownership scope: non-admins may only download their own packages.
    if Role(user.role) != Role.ADMIN and row["requested_by"] != user.username:
        raise HTTPException(403, "본인이 생성한 패키지만 다운로드할 수 있습니다")
    await _audit(db, "XDS_EXPORT_DOWNLOADED", request_id, user.username, "download")
    path = row["package_path"]

    def _stream():
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 256):
                yield chunk

    return StreamingResponse(
        _stream(), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=xdm_{request_id[:8]}.zip"},
    )
