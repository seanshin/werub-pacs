"""Patient export API (patient-portal feature).

Two surfaces:
- /api/v1/patient-export/* : called server-to-server by the external portal with
  a patient-export service token (HIS shared secret, scope=patient-export, mrn-sealed).
- /portal-export/{token}   : one-time package pickup, token-only auth, behind the
  nginx gateway — the single inbound path the portal touches in the medical network.

Decrypt key travels only via the JWT-authed status endpoint; package bytes only via
the gateway. A leaked download token cannot decrypt the contents.
"""
import json
import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_export_service_token
from app.services.patient_export_worker import KEY_PREFIX, TOKEN_PREFIX

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/patient-export", tags=["환자 결과 추출"])
gateway = APIRouter(tags=["환자 결과 추출"])  # mounted at root for /portal-export/{token}


class ExportRequest(BaseModel):
    mrn: str = Field(..., min_length=1, max_length=64)
    study_instance_uids: list[str] | None = None
    purpose: str = Field("patient_view", max_length=64)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing service token")
    return authorization.split(" ", 1)[1]


async def _audit(db: AsyncSession, action: str, request_id: str, mrn: str | None,
                 ip: str | None, detail: str):
    """System-actor audit entry (no logged-in user — portal service call)."""
    try:
        await db.execute(text("""
            INSERT INTO audit_logs (id, user_id, username, ip_address, action,
                resource_type, resource_id, patient_id, description, created_at)
            VALUES (:id, NULL, 'patient-portal', :ip, :action, 'PatientExport',
                    :rid, :mrn, :desc, now())
        """), {"id": str(uuid.uuid4()), "ip": ip, "action": action,
               "rid": request_id, "mrn": mrn, "desc": detail})
        await db.commit()
    except Exception as e:
        # 반출 감사 공백은 규제 리스크 — warning이 아닌 error로 가시화
        logger.error(f"patient-export audit failed: {e}")


@router.post("/requests", status_code=202, summary="환자 결과 추출 요청 (포털→PACS)")
async def create_export(
    body: ExportRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: str | None = Header(None),
):
    """포털이 본인확인을 마친 환자의 결과 패키지 생성을 요청. 서비스 토큰의 mrn과
    body.mrn이 일치해야 한다(환자 범위 봉인)."""
    if not verify_export_service_token(_bearer(authorization), body.mrn):
        raise HTTPException(403, "Invalid or mismatched export token")
    if not settings.patient_export_enabled:
        raise HTTPException(503, "EXPORT_DISABLED")
    # 공개판(PE1): 상한 — 지정 스터디 수 · 환자별 시간당 요청 수
    if body.study_instance_uids and len(body.study_instance_uids) > settings.patient_export_max_studies:
        raise HTTPException(413, "TOO_MANY_STUDIES")
    _redis = request.app.state.redis
    _rk = f"pe:rate:{body.mrn}"
    _n = await _redis.incr(_rk)
    if _n == 1:
        await _redis.expire(_rk, 3600)
    if _n > settings.patient_export_max_requests_per_hour:
        raise HTTPException(429, "EXPORT_RATE_LIMITED")

    request_id = str(uuid.uuid4())
    ip = request.client.host if request.client else None
    await db.execute(text("""
        INSERT INTO patient_export_requests (id, mrn, study_uids, purpose, requester_ip)
        VALUES (:id, :mrn, :uids, :purpose, :ip)
    """), {"id": request_id, "mrn": body.mrn,
           "uids": json.dumps(body.study_instance_uids) if body.study_instance_uids else None,
           "purpose": body.purpose, "ip": ip})
    await db.commit()
    await _audit(db, "PATIENT_EXPORT_REQUESTED", request_id, body.mrn, ip,
                 f"purpose={body.purpose}")

    from app.services.patient_export_worker import build_patient_export
    build_patient_export.delay(request_id)
    return {"request_id": request_id, "status": "processing"}


@router.get("/requests/{request_id}", summary="추출 상태/복호 키 조회 (포털→PACS)")
async def get_export(
    request_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: str | None = Header(None),
):
    """상태 폴링. ready면 download_token(게이트웨이용)과 package_key(복호용)를 반환.
    토큰의 mrn이 이 요청의 mrn과 일치해야 한다."""
    token = _bearer(authorization)
    row = (await db.execute(text(
        "SELECT * FROM patient_export_requests WHERE id = :id"
    ), {"id": request_id})).mappings().first()
    if not row:
        raise HTTPException(404, "Request not found")
    if not verify_export_service_token(token, row["mrn"]):
        raise HTTPException(403, "Invalid or mismatched export token")
    if not settings.patient_export_enabled:  # 공개판(PE3): 끈 뒤에는 상태 · 키도 내주지 않는다
        raise HTTPException(503, "EXPORT_DISABLED")

    # status가 NULL(초기 INSERT default 미설정)이면 polling이 ready/failed에 안 걸려 영구 hang
    st = row["status"] or "processing"
    resp = {"request_id": request_id, "status": st,
            "study_count": row["study_count"], "package_bytes": row["package_bytes"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None}
    if st == "failed":
        resp["error"] = row["error"]
    elif st == "ready":
        redis = request.app.state.redis
        key = await redis.get(f"{KEY_PREFIX}{request_id}")
        if not key:
            resp["status"] = "expired"
        else:
            resp["package_key"] = key
            resp["download_token"] = await _find_token(redis, request_id)
    return resp


@gateway.get("/portal-export/{token}", summary="패키지 1회 수령 (게이트웨이)")
async def download_package(
    token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """암호화 패키지 스트리밍. Redis GETDEL로 1회용 보장 — 재요청은 410."""
    if not settings.patient_export_enabled:  # 공개판(PE3): 끈 뒤에는 수령도 막는다
        raise HTTPException(503, "EXPORT_DISABLED")
    redis = request.app.state.redis
    request_id = await redis.execute_command("GETDEL", f"{TOKEN_PREFIX}{token}")
    if not request_id:
        raise HTTPException(410, "Token already used or expired")

    row = (await db.execute(text(
        "SELECT package_path, mrn FROM patient_export_requests WHERE id = :id"
    ), {"id": request_id})).mappings().first()
    if not row or not row["package_path"] or not os.path.exists(row["package_path"]):
        raise HTTPException(410, "Package no longer available")

    await db.execute(text(
        "UPDATE patient_export_requests SET status='consumed', consumed_at=now() WHERE id=:id"
    ), {"id": request_id})
    await db.commit()
    ip = request.client.host if request.client else None
    await _audit(db, "PATIENT_EXPORT_DOWNLOADED", str(request_id), row["mrn"], ip,
                 "gateway pickup")

    path = row["package_path"]

    def _stream():
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 256):
                yield chunk

    return StreamingResponse(
        _stream(), media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=export_{str(request_id)[:8]}.pkg",
                 "Cache-Control": "no-store"},
    )


async def _find_token(redis, request_id: str) -> str | None:
    """Locate the live download token for a request. Token space is tiny (1h TTL,
    per-request), so SCAN is cheap and avoids storing a reverse index."""
    async for k in redis.scan_iter(match=f"{TOKEN_PREFIX}*", count=100):
        if await redis.get(k) == request_id:
            return k.split(TOKEN_PREFIX, 1)[1]
    return None
