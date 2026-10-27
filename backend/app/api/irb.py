"""IRB 승인 레지스트리 API.

연구용 데이터 활용의 근거가 되는 IRB 승인 프로토콜 CRUD. 만료일이 지난 승인은
조회 시 status='expired'로 표기한다.
"""
import logging
from datetime import date
from typing import Annotated
from uuid import UUID as PyUUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.irb import IrbApproval
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/irb", tags=["IRB 승인"])

ReadRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.RESEARCHER)
WriteRoles = RequireRole(Role.ADMIN)


class IrbCreate(BaseModel):
    protocol_number: str
    title: str
    principal_investigator: str | None = None
    institution: str | None = None
    approved_at: date | None = None
    expires_at: date | None = None
    scope_note: str | None = None


class IrbUpdate(BaseModel):
    title: str | None = None
    principal_investigator: str | None = None
    institution: str | None = None
    approved_at: date | None = None
    expires_at: date | None = None
    status: str | None = None
    scope_note: str | None = None


def _serialize(a: IrbApproval) -> dict:
    today = date.today()
    # Derive effective status: expired overrides active when past expiry.
    eff = a.status
    if a.status == "active" and a.expires_at and a.expires_at < today:
        eff = "expired"
    days_left = (a.expires_at - today).days if a.expires_at else None
    return {
        "id": str(a.id),
        "protocol_number": a.protocol_number,
        "title": a.title,
        "principal_investigator": a.principal_investigator,
        "institution": a.institution,
        "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "status": a.status,
        "effective_status": eff,
        "days_left": days_left,
        "scope_note": a.scope_note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("", summary="IRB 승인 목록")
async def list_irb(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
    status: str | None = Query(None, description="active|suspended|expired 필터"),
):
    rows = await db.execute(select(IrbApproval).order_by(IrbApproval.approved_at.desc().nullslast()))
    items = [_serialize(a) for a in rows.scalars().all()]
    if status:
        items = [i for i in items if i["effective_status"] == status]
    summary = {
        "total": len(items),
        "active": sum(1 for i in items if i["effective_status"] == "active"),
        "expiring_soon": sum(1 for i in items if i["days_left"] is not None and 0 <= i["days_left"] <= 30),
        "expired": sum(1 for i in items if i["effective_status"] == "expired"),
    }
    return {"summary": summary, "items": items}


@router.post("", summary="IRB 승인 등록", status_code=201)
async def create_irb(
    body: IrbCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    existing = await db.execute(
        select(IrbApproval).where(IrbApproval.protocol_number == body.protocol_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "이미 등록된 프로토콜 번호입니다.")
    a = IrbApproval(**body.model_dump())
    db.add(a)
    await db.commit()
    await db.refresh(a)
    logger.info(f"IRB approval created: {a.protocol_number} by {user.username}")
    return _serialize(a)


@router.put("/{irb_id}", summary="IRB 승인 수정")
async def update_irb(
    irb_id: PyUUID,
    body: IrbUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    a = await db.get(IrbApproval, irb_id)
    if not a:
        raise HTTPException(404, "IRB 승인을 찾을 수 없습니다.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    await db.commit()
    await db.refresh(a)
    return _serialize(a)


@router.delete("/{irb_id}", summary="IRB 승인 삭제")
async def delete_irb(
    irb_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    a = await db.get(IrbApproval, irb_id)
    if not a:
        raise HTTPException(404, "IRB 승인을 찾을 수 없습니다.")
    await db.delete(a)
    await db.commit()
    return {"status": "deleted", "id": str(irb_id)}
