"""Study comments API — technologists and radiologists can add notes to studies.

메모는 DB(`study_comments` 테이블)에 영속화한다 — 이전 프로세스 내 전역 리스트(S12)는
4워커 간 불일치·재시작 시 소실 문제가 있었다. 테이블은 `_DDL`을
`core/schema_migrations`가 부팅 시 1회 생성(retake/teaching 선례).
"""
import logging
import uuid
from typing import Annotated
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/studies", tags=["촬영 메모"])

# 부팅 마이그레이션 DDL (schema_migrations 수집). 서버에 이미 존재하던 스키마와 정합
# (author_id FK·author_name·author_role) — 신규 설치도 동일 테이블 생성.
_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS study_comments (
        id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        study_instance_uid VARCHAR(128) NOT NULL,
        comment            TEXT NOT NULL,
        comment_type       VARCHAR(32) DEFAULT 'general',
        author_id          UUID REFERENCES users(id),
        author_name        VARCHAR(256),
        author_role        VARCHAR(32),
        created_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_study_comments_study ON study_comments(study_instance_uid)",
]


class CommentCreate(BaseModel):
    study_instance_uid: str
    comment: str
    comment_type: str = "general"  # general, quality_issue, technologist_note, clinical_info


def _row_dict(r) -> dict:
    return {
        "id": str(r.id),
        "study_instance_uid": r.study_instance_uid,
        "comment": r.comment,
        "comment_type": r.comment_type,
        "author": r.author_name,
        "author_role": r.author_role,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/{study_uid}/comments", summary="메모 추가", status_code=201)
async def add_comment(
    study_uid: str,
    body: CommentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
):
    """Study에 촬영 메모/코멘트를 추가합니다."""
    cid = str(uuid.uuid4())
    row = (await db.execute(text("""
        INSERT INTO study_comments (id, study_instance_uid, comment, comment_type, author_id, author_name, author_role)
        VALUES (:id, :suid, :comment, :ctype, :aid, :aname, :role)
        RETURNING id, study_instance_uid, comment, comment_type, author_name, author_role, created_at
    """), {
        "id": cid,
        "suid": study_uid,
        "comment": body.comment,
        "ctype": body.comment_type,
        "aid": str(user.id),
        "aname": user.full_name or user.username,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
    })).first()
    await db.commit()
    return _row_dict(row)


@router.get("/{study_uid}/comments", summary="메모 조회")
async def get_comments(
    study_uid: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
):
    """Study의 메모 목록을 조회합니다."""
    rows = (await db.execute(text("""
        SELECT id, study_instance_uid, comment, comment_type, author_name, author_role, created_at
        FROM study_comments WHERE study_instance_uid = :suid ORDER BY created_at
    """), {"suid": study_uid})).all()
    return {"comments": [_row_dict(r) for r in rows], "total": len(rows)}


@router.delete("/{study_uid}/comments/{comment_id}", summary="메모 삭제")
async def delete_comment(
    study_uid: str,
    comment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """메모를 삭제합니다 (관리자 전용)."""
    await db.execute(
        text("DELETE FROM study_comments WHERE id = :id"), {"id": comment_id}
    )
    await db.commit()
    return {"status": "deleted"}
