"""IRB(Institutional Review Board) 승인 레지스트리.

연구용 데이터 활용(익명화 추출 등)의 근거가 되는 IRB 승인 프로토콜을 관리한다.
"""
from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class IrbApproval(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "irb_approvals"

    protocol_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    principal_investigator: Mapped[str | None] = mapped_column(String(128))
    institution: Mapped[str | None] = mapped_column(String(256))
    approved_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    # active | suspended | expired
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active", nullable=False)
    scope_note: Mapped[str | None] = mapped_column(Text)
