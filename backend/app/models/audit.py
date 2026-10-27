"""Audit log model."""
from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class AuditAction(str):
    """감사 액션 어휘 — **값은 대문자 NAME으로 통일**한다(v13.47).

    이전에는 이 클래스만 소문자 값(`view`·`ai_inference`…)이었고 나머지 코드는
    대문자 문자열을 직접 썼다. 그 결과 라이브 43종 중 2종이 소문자로 남아
    (`view` 319행 — 최다 액션, `ai_inference` 1행) **감사 UI의 action 필터가
    대문자로 조회하면 최다 액션을 통째로 놓쳤다.**

    ★기존 소문자 행은 소급 정정하지 않는다 — `audit_logs`는 append-only 트리거
    보호(v13.30)이고 추정 기입은 신뢰성을 훼손한다. 대신 **조회 측을 대소문자
    무관하게** 만들어(`_apply_audit_filters`) 과거·현재 행이 한 필터로 잡히게 했다.
    """
    VIEW = "VIEW"
    EXPORT = "EXPORT"
    DELETE = "DELETE"
    MODIFY = "MODIFY"
    UPLOAD = "UPLOAD"
    AI_INFERENCE = "AI_INFERENCE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    VALIDATION = "VALIDATION"
    DICOM_NORMALIZED_PIXEL_SPACING = "DICOM_NORMALIZED_PIXEL_SPACING"
    DICOM_NORMALIZED_TAGS = "DICOM_NORMALIZED_TAGS"
    DICOM_NORMALIZED_PHOTOMETRIC = "DICOM_NORMALIZED_PHOTOMETRIC"
    DICOM_NORMALIZED_CHARSET = "DICOM_NORMALIZED_CHARSET"


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """Audit log for all PACS operations."""

    __tablename__ = "audit_logs"

    # Who
    user_id: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    # What
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))
    # SUCCESS / FAILED — persisted so the audit UI's status filter works
    # (previously only emitted to ATNA, never stored). Defaults SUCCESS for
    # existing rows and direct creations that don't set it.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="SUCCESS", server_default="SUCCESS")

    # Context
    study_instance_uid: Mapped[str | None] = mapped_column(String(128), index=True)
    patient_id: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)
