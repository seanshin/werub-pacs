"""Tenant Management API — super admin CRUD for multi-tenant PACS.

Manages organizations (hospitals/clinics) in multi-tenant mode.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenants", tags=["멀티테넌시"])


class TenantCreate(BaseModel):
    name: str              # "서울대병원"
    slug: str              # "snu"
    domain: Optional[str] = None  # "snu.openpacs.kr"
    settings: dict = {}
    storage_quota_gb: int = 100
    max_users: int = 50


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_active: Optional[bool] = None
    settings: Optional[dict] = None
    storage_quota_gb: Optional[int] = None
    max_users: Optional[int] = None


@router.post("", summary="기관 등록", status_code=201)
async def create_tenant(
    body: TenantCreate,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """새 기관(병원/클리닉)을 등록합니다. 슈퍼 관리자 전용."""
    tenant_id = str(uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(text("""
            INSERT INTO tenants (id, name, slug, domain, is_active, settings,
                storage_quota_gb, max_users, created_at, updated_at)
            VALUES (:id, :name, :slug, :domain, true, CAST(:settings AS jsonb),
                :quota, :max_users, :now, :now)
        """), {
            "id": tenant_id, "name": body.name, "slug": body.slug,
            "domain": body.domain, "settings": json.dumps(body.settings),
            "quota": body.storage_quota_gb, "max_users": body.max_users,
            "now": now,
        })
        await db.commit()
        logger.info(f"Tenant created: {body.name} ({body.slug})")
        return {"id": tenant_id, "name": body.name, "slug": body.slug}

    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, f"Slug '{body.slug}' already exists")
        raise HTTPException(500, f"Failed to create tenant: {str(e)[:100]}")


@router.get("", summary="기관 목록")
async def list_tenants(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """등록된 기관 목록을 조회합니다."""
    where = "WHERE is_active = true" if active_only else ""
    offset = (page - 1) * page_size

    result = await db.execute(text(f"""
        SELECT id, name, slug, domain, is_active, storage_quota_gb, max_users, created_at
        FROM tenants {where}
        ORDER BY name
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": offset})

    count_result = await db.execute(text(f"SELECT count(*) FROM tenants {where}"))

    return {
        "tenants": [dict(r._mapping) for r in result],
        "total": count_result.scalar(),
        "page": page,
    }


@router.get("/{tenant_id}", summary="기관 상세")
async def get_tenant(
    tenant_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """기관 상세 정보 (사용자 수, 스토리지 사용량 포함)."""
    result = await db.execute(text("""
        SELECT t.*,
            (SELECT count(*) FROM tenant_users tu WHERE tu.tenant_id = t.id) as user_count
        FROM tenants t WHERE t.id = :id
    """), {"id": tenant_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(404, "Tenant not found")
    return dict(row)


@router.put("/{tenant_id}", summary="기관 수정")
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """기관 정보를 수정합니다 (이름, 도메인, 활성화, 설정, 쿼타)."""
    updates = []
    params = {"id": tenant_id, "now": datetime.now(timezone.utc)}

    if body.name is not None:
        updates.append("name = :name")
        params["name"] = body.name
    if body.domain is not None:
        updates.append("domain = :domain")
        params["domain"] = body.domain
    if body.is_active is not None:
        updates.append("is_active = :active")
        params["active"] = body.is_active
    if body.settings is not None:
        updates.append("settings = CAST(:settings AS jsonb)")
        params["settings"] = json.dumps(body.settings)
    if body.storage_quota_gb is not None:
        updates.append("storage_quota_gb = :quota")
        params["quota"] = body.storage_quota_gb
    if body.max_users is not None:
        updates.append("max_users = :max_users")
        params["max_users"] = body.max_users

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = :now")

    await db.execute(text(f"UPDATE tenants SET {', '.join(updates)} WHERE id = :id"), params)
    await db.commit()
    return {"status": "updated", "tenant_id": tenant_id}


@router.post("/{tenant_id}/users", summary="기관에 사용자 배정")
async def assign_user_to_tenant(
    tenant_id: str,
    user_id: str = Query(...),
    role: str = Query("radiologist"),
    admin: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """사용자를 기관에 배정합니다."""
    await db.execute(text("""
        INSERT INTO tenant_users (tenant_id, user_id, role)
        VALUES (:tid, :uid, :role)
        ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = :role
    """), {"tid": tenant_id, "uid": user_id, "role": role})
    await db.commit()
    return {"status": "assigned", "tenant_id": tenant_id, "user_id": user_id, "role": role}


@router.get("/{tenant_id}/users", summary="기관 사용자 목록")
async def list_tenant_users(
    tenant_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """기관에 소속된 사용자 목록."""
    result = await db.execute(text("""
        SELECT tu.user_id, tu.role, u.username, u.full_name, u.email
        FROM tenant_users tu
        JOIN users u ON u.id = tu.user_id
        WHERE tu.tenant_id = :tid
        ORDER BY tu.role, u.username
    """), {"tid": tenant_id})
    return {"users": [dict(r._mapping) for r in result]}
