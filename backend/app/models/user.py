"""User model with RBAC roles."""
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class Role(str, PyEnum):
    ADMIN = "admin"
    RADIOLOGIST = "radiologist"
    RESIDENT = "resident"
    PHYSICIAN = "physician"
    TECHNOLOGIST = "technologist"
    RESEARCHER = "researcher"
    # 외부 연동 서비스 계정 — read-only 최소권한(QIDO/WADO 조회만).
    # RequireRole은 deny-by-default라 이 역할은 STOW·리포트·관리·삭제 등 모든
    # 게이트 엔드포인트에서 자동 차단되고, get_current_user 읽기(QIDO)만 통과한다.
    SERVICE = "service"


class User(Base, UUIDMixin, TimestampMixin):
    """PACS user with role-based access control."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(Enum(Role, name="role_enum"), nullable=False, default=Role.PHYSICIAN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    department: Mapped[str | None] = mapped_column(String(128))
