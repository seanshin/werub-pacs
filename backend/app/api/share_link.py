"""One-time shareable link for external consultation — Redis-backed with TTL."""
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import _log_audit_entry
from app.api.physician_portal import _can_access_study  # ADMIN/RAD=전체, PHYSICIAN=본인 의뢰 study만
from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/share", tags=["영상 공유"])
logger = logging.getLogger(__name__)

SHARE_LINK_PREFIX = "share_link:"


class ShareLinkCreate(BaseModel):
    study_instance_uid: str
    expires_hours: int = 24
    note: str = ""


@router.post("", summary="공유 링크 생성", status_code=201)
async def create_share_link(
    body: ShareLinkCreate,
    request: Request,
    # 외부 공유(무인증 뷰어 링크 발급) — BTG 우회 차단.
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """1회용 영상 공유 링크를 생성합니다.

    외부 의사와 협진 시 사용. 지정된 시간 후 자동 만료.
    """
    # 접근 스코프 — 임의 study_uid 무인증 링크 발급 방지(PHYSICIAN은 본인 의뢰 study만).
    if not await _can_access_study(db, user, body.study_instance_uid):
        raise ForbiddenError("본인이 의뢰한 환자의 study만 공유할 수 있습니다.")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=body.expires_hours)
    created_by = user.full_name if hasattr(user, 'full_name') else ''

    link_data = {
        "study_uid": body.study_instance_uid,
        "created_by": created_by,
        "created_by_id": str(user.id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at.isoformat(),
        "note": body.note,
        "accessed": False,
    }

    redis = request.app.state.redis
    key = f"{SHARE_LINK_PREFIX}{token}"
    await redis.setex(key, body.expires_hours * 3600, json.dumps(link_data))

    logger.info("Share link created", extra={
        "token": token[:8] + "...",
        "study_uid": body.study_instance_uid,
        "created_by": created_by,
        "expires_hours": body.expires_hours,
    })

    # 공유 링크는 **무인증 외부 열람 자격**이다 — 발급 기록이 감사에 없으면 "이 영상이
    # 언제 누구에 의해 외부로 열렸나"를 사후에 답할 수 없다. 링크 자체는 Redis TTL로
    # 사라지므로 감사 로그가 유일한 영구 기록이 된다.
    # ★토큰 전문은 싣지 않는다(감사 로그가 자격증명 저장소가 되면 안 된다) — 로거와
    #   같은 8자 접두만 남겨 대조에 쓴다.
    await _log_audit_entry(
        db=db, operation="SHARE_LINK_CREATED", resource_type="ShareLink",
        status="SUCCESS", user_id=str(user.id), username=user.username,
        resource_id=token[:8],
        study_instance_uid=body.study_instance_uid,
        details={"token_prefix": token[:8], "expires_hours": body.expires_hours,
                 "expires_at": expires_at.isoformat(), "note": body.note},
    )

    return {
        "token": token,
        "url": f"/werub-viewer/viewer?StudyInstanceUIDs={body.study_instance_uid}&shareToken={token}",
        "expires_at": expires_at.isoformat(),
        "expires_hours": body.expires_hours,
    }


@router.get("/verify/{token}", summary="공유 링크 검증")
async def verify_share_link(token: str, request: Request):
    """공유 링크의 유효성을 검증합니다. 인증 불필요."""
    redis = request.app.state.redis
    key = f"{SHARE_LINK_PREFIX}{token}"
    raw = await redis.get(key)

    if not raw:
        raise HTTPException(404, "유효하지 않은 공유 링크입니다")

    link = json.loads(raw)

    # Mark as accessed
    link["accessed"] = True
    ttl = await redis.ttl(key)
    if ttl > 0:
        await redis.setex(key, ttl, json.dumps(link))

    logger.info("Share link accessed", extra={
        "token": token[:8] + "...",
        "study_uid": link["study_uid"],
    })

    return {
        "valid": True,
        "study_uid": link["study_uid"],
        "viewer_url": f"/werub-viewer/viewer?StudyInstanceUIDs={link['study_uid']}",
        "created_by": link["created_by"],
        "note": link["note"],
    }


@router.get("", summary="내 공유 링크 목록")
async def list_share_links(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
):
    """내가 생성한 공유 링크 목록을 조회합니다."""
    redis = request.app.state.redis
    user_id = str(user.id)
    my_links = []

    async for key in redis.scan_iter(f"{SHARE_LINK_PREFIX}*", count=100):
        raw = await redis.get(key)
        if raw:
            link = json.loads(raw)
            if link.get("created_by_id") == user_id:
                token = key.replace(SHARE_LINK_PREFIX, "") if isinstance(key, str) else key.decode().replace(SHARE_LINK_PREFIX, "")
                my_links.append({"token": token, **link})

    return {"links": my_links, "total": len(my_links)}


@router.delete("/{token}", summary="공유 링크 취소")
async def revoke_share_link(
    token: str,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)),
    db: AsyncSession = Depends(get_db),
):
    """공유 링크를 취소합니다. 본인이 생성한 링크만(관리자는 전체)."""
    redis = request.app.state.redis
    key = f"{SHARE_LINK_PREFIX}{token}"

    raw = await redis.get(key)
    if not raw:
        raise HTTPException(404, "공유 링크를 찾을 수 없습니다")
    # 소유자 스코프: 본인이 생성한 링크만(목록 EP와 동일 기준). ADMIN은 전체 취소 가능.
    link = json.loads(raw)
    if user.role != Role.ADMIN and link.get("created_by_id") != str(user.id):
        raise HTTPException(403, "본인이 생성한 공유 링크만 취소할 수 있습니다")

    await redis.delete(key)
    logger.info("Share link revoked", extra={
        "token": token[:8] + "...",
        "revoked_by": user.username,
    })

    # 취소도 남긴다 — 발급만 기록하면 "지금 열려 있는 링크"를 감사로 재구성할 수 없다.
    # 남의 링크를 관리자가 취소한 경우가 특히 기록될 가치가 있다.
    await _log_audit_entry(
        db=db, operation="SHARE_LINK_REVOKED", resource_type="ShareLink",
        status="SUCCESS", user_id=str(user.id), username=user.username,
        resource_id=token[:8],
        study_instance_uid=link.get("study_uid"),
        details={"token_prefix": token[:8],
                 "created_by_id": link.get("created_by_id"),
                 "revoked_other_users_link":
                     link.get("created_by_id") not in (None, str(user.id))},
    )

    return {"status": "revoked"}
