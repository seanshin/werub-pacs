"""Report template model."""
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDMixin


class ReportTemplate(Base, UUIDMixin, TimestampMixin):
    """Structured report template by modality/body part."""

    __tablename__ = "report_templates"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    modality: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    body_part: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(256))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Template content
    sections: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Example: [{"name": "폐야", "key": "lung", "type": "text", "default": "이상 소견 없음"}, ...]

    impression_template: Mapped[str | None] = mapped_column(Text)
    normal_template: Mapped[str | None] = mapped_column(Text)

    # Shortcuts / macros
    macros: Mapped[dict | None] = mapped_column(JSONB)
    # Example: {"nl": "이상 소견 없음", "nfx": "골절 소견 없음"}
