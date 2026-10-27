"""DICOM Issue request/response Pydantic models."""
from pydantic import BaseModel


class IssueStatusUpdate(BaseModel):
    status: str  # unreviewed, acknowledged, ignored, manual_fixed
    note: str | None = None


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    severity: str | None = None
    custom_message: str | None = None
    auto_action: str | None = None
    thresholds: dict | None = None


class ModalityConfigUpdate(BaseModel):
    render_type: str | None = None
    display_label: str | None = None
    description: str | None = None
    action_text: str | None = None
    enabled: bool | None = None


class ModalityConfigCreate(BaseModel):
    modality: str
    render_type: str = "non_renderable"
    display_label: str
    description: str
    action_text: str | None = None


class MessageUpdate(BaseModel):
    custom_text: str | None = None


class AeProfileUpdate(BaseModel):
    display_name: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    rule_overrides: dict | None = None
    normalization_preset: dict | None = None
