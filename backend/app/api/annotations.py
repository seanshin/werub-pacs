"""Annotations API — save/restore measurements and key images.

Persists viewer annotations (measurements, ROIs, key images) in DB
so they survive browser sessions and can be shared between users.

★2026-08-03: 여기 있던 `POST /{study_uid}/share`(교육용 공유 링크)를 제거했다.
  · `share_link.py`에 **제대로 가드된 동일 기능**이 이미 있다(v13.8: 역할 제한 +
    allow_btg=False + `_can_access_study` 소유자 스코프). 이쪽은 `get_current_user`만
    있어 **아무 인증 사용자나 임의 study의 링크를 `anonymize=false`로** 만들 수 있었다.
  · 게다가 기록하던 `shared_links` 테이블을 **읽는 코드가 없어** 토큰이 소비 불가였다
    — 즉 동작하지 않는 링크를 돌려주는 죽은 중복본이었다(30일 로그·nginx 이력 호출 0회).
  · 그대로 두면 누구든 토큰 소비 경로를 붙이는 순간 **무권한 PHI 공유 경로가 즉시
    활성화**되는 잠재 함정이라 남기지 않았다. 공유가 필요하면 `share_link.py`를 쓴다.
  (테이블 `shared_links`는 0행이며 삭제하지 않았다 — DB 객체 제거는 별건.)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ClinicalPHIReadRoles
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/studies", tags=["Annotations"])


class AnnotationSave(BaseModel):
    measurements: list = []
    key_images: list = []
    notes: Optional[str] = None


@router.get("/{study_uid}/annotations", summary="저장된 주석/측정 조회")
async def get_annotations(
    study_uid: str,
    user: User = Depends(ClinicalPHIReadRoles),
    db: AsyncSession = Depends(get_db),
):
    """스터디에 저장된 측정값, 키 이미지, 주석을 조회합니다."""
    result = await db.execute(text("""
        SELECT id, study_uid, user_id, measurements, key_images, notes, created_at, updated_at
        FROM study_annotations
        WHERE study_uid = :uid
        ORDER BY updated_at DESC LIMIT 1
    """), {"uid": study_uid})
    row = result.mappings().first()

    if not row:
        return {"study_uid": study_uid, "measurements": [], "key_images": [], "notes": None}

    return dict(row)


@router.post("/{study_uid}/annotations", summary="주석/측정 저장")
async def save_annotations(
    study_uid: str,
    body: AnnotationSave,
    user: User = Depends(ClinicalPHIReadRoles),
    db: AsyncSession = Depends(get_db),
):
    """측정값, 키 이미지, 주석을 저장합니다.

    뷰어에서 측정한 값을 DB에 저장하여 다음 세션에서 복원합니다.
    """
    import json
    now = datetime.now(timezone.utc)
    user_id = str(user.id) if hasattr(user, 'id') else ""

    # Upsert
    existing = await db.execute(text(
        "SELECT id FROM study_annotations WHERE study_uid = :uid AND user_id = :user"
    ), {"uid": study_uid, "user": user_id})

    if existing.first():
        await db.execute(text("""
            UPDATE study_annotations
            SET measurements = CAST(:meas AS jsonb), key_images = CAST(:keys AS jsonb),
                notes = :notes, updated_at = :now
            WHERE study_uid = :uid AND user_id = :user
        """), {
            "meas": json.dumps(body.measurements),
            "keys": json.dumps(body.key_images),
            "notes": body.notes, "now": now,
            "uid": study_uid, "user": user_id,
        })
    else:
        from uuid import uuid4
        await db.execute(text("""
            INSERT INTO study_annotations (id, study_uid, user_id, measurements, key_images, notes, created_at, updated_at)
            VALUES (:id, :uid, :user, CAST(:meas AS jsonb), CAST(:keys AS jsonb), :notes, :now, :now)
        """), {
            "id": str(uuid4()), "uid": study_uid, "user": user_id,
            "meas": json.dumps(body.measurements),
            "keys": json.dumps(body.key_images),
            "notes": body.notes, "now": now,
        })

    await db.commit()
    logger.info(f"Annotations saved for study {study_uid}: {len(body.measurements)} measurements, {len(body.key_images)} key images")

    return {"status": "saved", "study_uid": study_uid,
            "measurements": len(body.measurements), "key_images": len(body.key_images)}
