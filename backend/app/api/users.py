"""User management API endpoints (admin only)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.database import get_db
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/users", tags=["auth"])


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    role: str
    department: str | None
    is_active: bool


_SORT_COLS = {"username": User.username, "email": User.email,
              "full_name": User.full_name, "role": User.role, "is_active": User.is_active}


@router.get("")
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    search: str | None = Query(None),
    role: str | None = Query(None),
    sort: str = Query("username"),
    order: str = Query("asc"),
):
    """List users — paginated, searchable, filterable. Returns {results, total}. Admin only."""
    conds = []
    if search:
        like = f"%{search.lower()}%"
        conds.append(or_(
            func.lower(User.username).like(like),
            func.lower(User.email).like(like),
            func.lower(User.full_name).like(like),
        ))
    if role:
        try:
            conds.append(User.role == Role(role))  # frontend sends the enum *value* (lowercase)
        except ValueError:
            pass  # unknown role → no filter rather than 500

    total = (await db.execute(
        select(func.count()).select_from(User).where(*conds)
    )).scalar() or 0

    col = _SORT_COLS.get(sort, User.username)
    stmt = (select(User).where(*conds)
            .order_by(col.desc() if order == "desc" else col.asc())
            .offset((page - 1) * limit).limit(limit))
    users = (await db.execute(stmt)).scalars().all()
    return {
        "results": [
            UserResponse(
                id=str(u.id), username=u.username, email=u.email,
                full_name=u.full_name, role=u.role, department=u.department,
                is_active=u.is_active,
            ).model_dump()
            for u in users
        ],
        "total": total,
    }


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Get a specific user by ID. Admin only."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError(resource="User", resource_id=user_id)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        is_active=user.is_active,
    )


@router.delete("/{user_id}", status_code=204)
@AuditLogger.log("USER_DELETED", "User")
async def delete_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Delete a user by ID. Admin only. Cannot delete yourself."""
    if str(admin.id) == user_id:
        raise PermissionDeniedError(message="Cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError(resource="User", resource_id=user_id)
    await db.delete(user)
    await db.commit()
