"""외부 기관 승인 계정 관리 — 반복 의뢰 시 사전 승인된 계정."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/external-accounts", tags=["외부 계정"])


class ExternalAccountCreate(BaseModel):
    institution_name: str
    physician_name: str
    physician_email: str
    specialties: str | None = None  # e.g. "chest, neuro"
    notes: str | None = None


@router.post("", summary="외부 기관 계정 등록", status_code=201)
async def create_external_account(
    body: ExternalAccountCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """반복 의뢰용 외부 기관/전문의 계정을 등록합니다."""
    result = await db.execute(text("""
        INSERT INTO external_accounts
            (institution_name, physician_name, physician_email, specialties, notes, created_by)
        VALUES (:inst, :phys, :email, :spec, :notes, :user)
        RETURNING id
    """), {
        "inst": body.institution_name, "phys": body.physician_name,
        "email": body.physician_email, "spec": body.specialties,
        "notes": body.notes, "user": user.username,
    })
    await db.commit()
    row = result.mappings().first()
    return {"id": str(row["id"]), **body.model_dump()}


@router.get("", summary="외부 기관 계정 목록")
async def list_external_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
):
    """등록된 외부 기관/전문의 목록을 조회합니다."""
    result = await db.execute(text("""
        SELECT id, institution_name, physician_name, physician_email,
               specialties, notes, is_active, created_at
        FROM external_accounts ORDER BY institution_name
    """))
    return {"accounts": [dict(r._mapping) for r in result]}


@router.put("/{account_id}/toggle", summary="외부 계정 활성/비활성")
async def toggle_external_account(
    account_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """외부 기관 계정을 활성/비활성 전환합니다."""
    result = await db.execute(text("""
        UPDATE external_accounts SET is_active = NOT is_active WHERE id = :id RETURNING id, is_active
    """), {"id": account_id})
    await db.commit()
    row = result.mappings().first()
    if not row:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("ExternalAccount", account_id)
    return {"id": account_id, "is_active": row["is_active"]}


@router.delete("/{account_id}", summary="외부 계정 삭제")
async def delete_external_account(
    account_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """외부 기관 계정을 삭제합니다."""
    await db.execute(text("DELETE FROM external_accounts WHERE id = :id"), {"id": account_id})
    await db.commit()
    return {"status": "deleted"}
