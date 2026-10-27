"""Patient result-view portal token.

환자 본인이 웹에서 자기 검사·확정 판독문을 열람하는 포털(/pacs-admin/patient-view)의
접근 토큰. 업로드 포털(PatientUploadToken)과 달리 **PHI 읽기**를 여는 토큰이므로:
- 토큰은 SHA-256 해시로만 저장(발급 응답에 1회 노출)
- 만료 + 명시적 폐기(revoked) + 사용 카운트
- 기능 전체가 default-off 게이트(settings.patient_view_enabled)
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDMixin


class PatientViewToken(Base, UUIDMixin):
    """Token for the patient result-view portal."""

    __tablename__ = "patient_view_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_name: Mapped[str | None] = mapped_column(String(256))
    memo: Mapped[str | None] = mapped_column(String(256))  # 발급 사유/식별 메모(스태프용)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


# startup 마이그레이션 러너(core/schema_migrations)가 부팅 시 1회 실행
_DDL = (
    """
    CREATE TABLE IF NOT EXISTS patient_view_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        token_hash VARCHAR(64) NOT NULL UNIQUE,
        patient_id VARCHAR(64) NOT NULL,
        patient_name VARCHAR(256),
        memo VARCHAR(256),
        expires_at TIMESTAMPTZ NOT NULL,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        use_count INTEGER NOT NULL DEFAULT 0,
        last_used_at TIMESTAMPTZ,
        created_by UUID NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pvt_patient ON patient_view_tokens (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_pvt_expires ON patient_view_tokens (expires_at)",
)
