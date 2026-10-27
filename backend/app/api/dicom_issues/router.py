"""DICOM Issue Control Center API — v9.0

Main router definition and CRUD endpoints for issues, rules, modality config,
message templates, AE profiles, and export/import.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.database import get_db
from app.core.security import ClinicalPHIReadRoles, RequireRole, get_current_user
from app.models.dicom_issue import AeTitleProfile, DicomIssueRule, DicomMessageTemplate, ModalityRenderConfig
from app.models.user import Role, User
from app.models.validation import ValidationResult

from .fix import RULE_RESOLUTION, fix_router
from .models import (
    AeProfileUpdate, IssueStatusUpdate, MessageUpdate,
    ModalityConfigCreate, ModalityConfigUpdate, RuleUpdate,
)
from .seed import SEED_RULES, seed_dicom_issue_data
from .validation import validation_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dicom-issues", tags=["dicom-issues"])

# Include sub-routers
router.include_router(fix_router)
router.include_router(validation_router)


# ─── Issue Query/Management ───────────────────────────────────────────────────

@router.get("")
async def list_issues(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalPHIReadRoles)],
    severity: str | None = Query(None, description="critical,error,warning,info"),
    category: str | None = Query(None),
    rule_code: str | None = Query(None),
    status: str | None = Query(None, description="unreviewed,acknowledged,ignored,auto_fixed,manual_fixed"),
    ae_title: str | None = Query(None),
    modality: str | None = Query(None),
    study_uid: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("severity", description="severity,created_at,rule_code"),
    order: str = Query("desc"),
):
    """List validation issues with filters."""
    q = select(ValidationResult)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = q.where(ValidationResult.created_at >= cutoff)

    if severity:
        sevs = [s.strip() for s in severity.split(",")]
        q = q.where(ValidationResult.severity.in_(sevs))
    if category:
        q = q.where(ValidationResult.category == category)
    if rule_code:
        q = q.where(ValidationResult.rule_code == rule_code)
    if status:
        q = q.where(ValidationResult.issue_status == status)
    if ae_title:
        q = q.where(ValidationResult.ae_title == ae_title)
    if modality:
        q = q.where(ValidationResult.modality == modality)
    if study_uid:
        q = q.where(ValidationResult.study_instance_uid == study_uid)

    # Count
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    severity_order = case(
        (ValidationResult.severity == "critical", 0),
        (ValidationResult.severity == "error", 1),
        (ValidationResult.severity == "warning", 2),
        (ValidationResult.severity == "info", 3),
        else_=4,
    )
    if sort == "severity":
        sort_col = severity_order if order == "asc" else severity_order.desc()
    elif sort == "rule_code":
        sort_col = ValidationResult.rule_code.asc() if order == "asc" else ValidationResult.rule_code.desc()
    else:
        sort_col = ValidationResult.created_at.asc() if order == "asc" else ValidationResult.created_at.desc()

    q = q.order_by(sort_col, ValidationResult.created_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(q)
    issues = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "issues": [
            {
                "id": str(i.id),
                "severity": i.severity,
                "category": i.category,
                "rule_code": i.rule_code,
                "message": i.message,
                "details": i.details,
                "resolution": RULE_RESOLUTION.get(i.rule_code, {}),
                "patient_name": i.patient_name,
                "patient_id": i.patient_id,
                "study_instance_uid": i.study_instance_uid,
                "study_description": i.study_description,
                "study_date": i.study_date,
                "modality": i.modality,
                "ae_title": i.ae_title,
                "manufacturer": i.manufacturer,
                "issue_status": i.issue_status,
                "auto_fixed": i.auto_fixed,
                "reviewer_note": i.reviewer_note,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None,
            }
            for i in issues
        ],
    }


@router.get("/statistics")
async def issue_statistics(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    days: int = Query(30, ge=1, le=365),
):
    """Issue statistics — severity, category, AE title, rule code, auto-fix rate."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base = ValidationResult.created_at >= cutoff

    severity_q = await db.execute(
        select(ValidationResult.severity, func.count()).where(base).group_by(ValidationResult.severity)
    )
    category_q = await db.execute(
        select(ValidationResult.category, func.count()).where(base).group_by(ValidationResult.category)
    )
    ae_q = await db.execute(
        select(ValidationResult.ae_title, func.count())
        .where(base, ValidationResult.ae_title.isnot(None))
        .group_by(ValidationResult.ae_title).order_by(func.count().desc()).limit(10)
    )
    rule_q = await db.execute(
        select(ValidationResult.rule_code, func.count())
        .where(base).group_by(ValidationResult.rule_code).order_by(func.count().desc()).limit(10)
    )
    total_q = await db.execute(select(func.count()).select_from(ValidationResult).where(base))
    auto_fixed_q = await db.execute(
        select(func.count()).select_from(ValidationResult).where(base, ValidationResult.auto_fixed == True)
    )
    status_q = await db.execute(
        select(ValidationResult.issue_status, func.count()).where(base).group_by(ValidationResult.issue_status)
    )
    # Unique studies with issues
    study_count_q = await db.execute(
        select(func.count(func.distinct(ValidationResult.study_instance_uid))).where(base)
    )

    total = total_q.scalar() or 0
    auto_fixed = auto_fixed_q.scalar() or 0

    return {
        "total_findings": total,
        "auto_fixed": auto_fixed,
        "auto_fix_rate": round(auto_fixed / total * 100, 1) if total > 0 else 0,
        "unique_studies": study_count_q.scalar() or 0,
        "by_severity": dict(severity_q.all()),
        "by_category": dict(category_q.all()),
        "by_ae_title": dict(ae_q.all()),
        "top_rules": dict(rule_q.all()),
        "by_status": dict(status_q.all()),
    }


@router.get("/trends")
async def issue_trends(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    days: int = Query(7, ge=1, le=90),
):
    """Daily issue trends."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date_trunc("day", ValidationResult.created_at).label("day"),
            ValidationResult.severity,
            func.count(),
        )
        .where(ValidationResult.created_at >= cutoff)
        .group_by("day", ValidationResult.severity)
        .order_by("day")
    )
    rows = result.all()
    trends = {}
    for day, sev, cnt in rows:
        d = day.strftime("%Y-%m-%d") if day else "unknown"
        if d not in trends:
            trends[d] = {"date": d, "critical": 0, "error": 0, "warning": 0, "info": 0, "total": 0}
        trends[d][sev] = cnt
        trends[d]["total"] += cnt

    return {"days": days, "trends": list(trends.values())}


# ─── Rule Configuration ───────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """List all validation rules with their settings."""
    result = await db.execute(
        select(DicomIssueRule).order_by(DicomIssueRule.category, DicomIssueRule.rule_code)
    )
    rules = result.scalars().all()
    if not rules:
        await seed_dicom_issue_data(db)
        result = await db.execute(
            select(DicomIssueRule).order_by(DicomIssueRule.category, DicomIssueRule.rule_code)
        )
        rules = result.scalars().all()

    return {
        "rules": [
            {
                "id": str(r.id),
                "rule_code": r.rule_code,
                "display_name": r.display_name,
                "category": r.category,
                "default_severity": r.default_severity,
                "severity": r.severity,
                "severity_locked": r.severity_locked,
                "enabled": r.enabled,
                "default_message": r.default_message,
                "custom_message": r.custom_message,
                "auto_action": r.auto_action,
                "thresholds": r.thresholds,
            }
            for r in rules
        ]
    }


@router.put("/rules/{rule_code}")
@AuditLogger.log("DICOM_RULE_UPDATE", "DicomIssueRule")
async def update_rule(
    rule_code: str,
    body: RuleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update a validation rule's settings."""
    result = await db.execute(
        select(DicomIssueRule).where(DicomIssueRule.rule_code == rule_code)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        return {"error": f"Rule {rule_code} not found"}

    if body.severity is not None:
        if rule.severity_locked:
            return {"error": f"Rule {rule_code} severity is locked and cannot be changed"}
        rule.severity = body.severity
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.custom_message is not None:
        rule.custom_message = body.custom_message if body.custom_message else None
    if body.auto_action is not None:
        rule.auto_action = body.auto_action
    if body.thresholds is not None:
        rule.thresholds = body.thresholds

    await db.commit()
    return {"ok": True, "rule_code": rule.rule_code}


@router.post("/rules/reset")
@AuditLogger.log("DICOM_RULES_RESET", "DicomIssueRule")
async def reset_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Reset all rules to defaults."""
    for rule_code, name, cat, sev, locked, msg in SEED_RULES:
        await db.execute(
            update(DicomIssueRule)
            .where(DicomIssueRule.rule_code == rule_code)
            .values(severity=sev, enabled=True, custom_message=None, auto_action="none", thresholds={})
        )
    await db.commit()
    return {"ok": True, "reset_count": len(SEED_RULES)}


# ─── Modality Render Config ──────────────────────────────────────────────────

@router.get("/modality-config")
async def list_modality_config(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List modality render configurations. Public endpoint for frontend dynamic load."""
    result = await db.execute(
        select(ModalityRenderConfig).order_by(ModalityRenderConfig.sort_order)
    )
    configs = result.scalars().all()
    if not configs:
        # Auto-seed if empty
        async with db.begin_nested():
            await seed_dicom_issue_data(db)
        result = await db.execute(
            select(ModalityRenderConfig).order_by(ModalityRenderConfig.sort_order)
        )
        configs = result.scalars().all()

    return {
        "configs": [
            {
                "modality": c.modality,
                "render_type": c.render_type,
                "display_label": c.display_label,
                "description": c.description,
                "action_text": c.action_text,
                "enabled": c.enabled,
            }
            for c in configs
        ]
    }


@router.put("/modality-config/{modality}")
@AuditLogger.log("MODALITY_CONFIG_UPDATE", "ModalityRenderConfig")
async def update_modality_config(
    modality: str,
    body: ModalityConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update modality render config."""
    result = await db.execute(
        select(ModalityRenderConfig).where(ModalityRenderConfig.modality == modality.upper())
    )
    config = result.scalar_one_or_none()
    if not config:
        return {"error": f"Modality {modality} not found"}

    if body.render_type is not None:
        config.render_type = body.render_type
    if body.display_label is not None:
        config.display_label = body.display_label
    if body.description is not None:
        config.description = body.description
    if body.action_text is not None:
        config.action_text = body.action_text
    if body.enabled is not None:
        config.enabled = body.enabled

    await db.commit()
    return {"ok": True, "modality": config.modality}


@router.post("/modality-config")
@AuditLogger.log("MODALITY_CONFIG_CREATE", "ModalityRenderConfig")
async def create_modality_config(
    body: ModalityConfigCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Add new modality render config."""
    existing = await db.execute(
        select(ModalityRenderConfig).where(ModalityRenderConfig.modality == body.modality.upper())
    )
    if existing.scalar_one_or_none():
        return {"error": f"Modality {body.modality} already exists"}

    config = ModalityRenderConfig(
        modality=body.modality.upper(),
        render_type=body.render_type,
        display_label=body.display_label,
        description=body.description,
        action_text=body.action_text,
    )
    db.add(config)
    await db.commit()
    return {"ok": True, "modality": config.modality}


# ─── Message Templates ────────────────────────────────────────────────────────

@router.get("/messages")
async def list_messages(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List message templates. Public endpoint for frontend dynamic load."""
    result = await db.execute(
        select(DicomMessageTemplate).order_by(DicomMessageTemplate.context, DicomMessageTemplate.message_key)
    )
    templates = result.scalars().all()

    return {
        "messages": [
            {
                "message_key": t.message_key,
                "context": t.context,
                "default_text": t.default_text,
                "custom_text": t.custom_text,
                "text": t.custom_text or t.default_text,
                "variables": t.variables,
            }
            for t in templates
        ]
    }


@router.put("/messages/{message_key:path}")
@AuditLogger.log("MESSAGE_TEMPLATE_UPDATE", "DicomMessageTemplate")
async def update_message(
    message_key: str,
    body: MessageUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update a message template."""
    result = await db.execute(
        select(DicomMessageTemplate).where(DicomMessageTemplate.message_key == message_key)
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        return {"error": f"Message key {message_key} not found"}

    tmpl.custom_text = body.custom_text if body.custom_text else None
    await db.commit()
    return {"ok": True, "message_key": tmpl.message_key, "text": tmpl.custom_text or tmpl.default_text}


# ─── AE Title Profiles ────────────────────────────────────────────────────────

@router.get("/ae-profiles")
async def list_ae_profiles(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """List equipment profiles."""
    result = await db.execute(
        select(AeTitleProfile).order_by(AeTitleProfile.issue_count.desc())
    )
    profiles = result.scalars().all()

    # Also gather AE titles from validation_results that don't have profiles
    ae_q = await db.execute(
        select(ValidationResult.ae_title, ValidationResult.manufacturer, func.count())
        .where(ValidationResult.ae_title.isnot(None))
        .group_by(ValidationResult.ae_title, ValidationResult.manufacturer)
        .order_by(func.count().desc()).limit(20)
    )
    known_aes = {p.ae_title for p in profiles}
    new_aes = [
        {"ae_title": ae, "manufacturer": mfr, "issue_count": cnt}
        for ae, mfr, cnt in ae_q.all() if ae and ae not in known_aes
    ]

    return {
        "profiles": [
            {
                "id": str(p.id),
                "ae_title": p.ae_title,
                "display_name": p.display_name,
                "manufacturer": p.manufacturer,
                "model_name": p.model_name,
                "issue_count": p.issue_count,
                "issue_summary": p.issue_summary,
                "rule_overrides": p.rule_overrides,
                "normalization_preset": p.normalization_preset,
                "last_received_at": p.last_received_at.isoformat() if p.last_received_at else None,
            }
            for p in profiles
        ],
        "unregistered": new_aes,
    }


@router.put("/ae-profiles/{ae_title}")
@AuditLogger.log("AE_PROFILE_UPDATE", "AeTitleProfile")
async def update_ae_profile(
    ae_title: str,
    body: AeProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update or create equipment profile."""
    result = await db.execute(
        select(AeTitleProfile).where(AeTitleProfile.ae_title == ae_title)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        profile = AeTitleProfile(ae_title=ae_title)
        db.add(profile)

    if body.display_name is not None:
        profile.display_name = body.display_name
    if body.manufacturer is not None:
        profile.manufacturer = body.manufacturer
    if body.model_name is not None:
        profile.model_name = body.model_name
    if body.rule_overrides is not None:
        profile.rule_overrides = body.rule_overrides
    if body.normalization_preset is not None:
        profile.normalization_preset = body.normalization_preset

    await db.commit()
    return {"ok": True, "ae_title": profile.ae_title}


# ─── Export/Import ────────────────────────────────────────────────────────────

@router.get("/export")
async def export_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Export all DICOM issue settings as JSON."""
    rules = (await db.execute(select(DicomIssueRule))).scalars().all()
    modalities = (await db.execute(select(ModalityRenderConfig))).scalars().all()
    messages = (await db.execute(select(DicomMessageTemplate))).scalars().all()
    profiles = (await db.execute(select(AeTitleProfile))).scalars().all()

    return {
        "version": "9.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "rules": [
            {"rule_code": r.rule_code, "severity": r.severity, "enabled": r.enabled,
             "custom_message": r.custom_message, "auto_action": r.auto_action, "thresholds": r.thresholds}
            for r in rules
        ],
        "modality_configs": [
            {"modality": m.modality, "render_type": m.render_type, "display_label": m.display_label,
             "description": m.description, "action_text": m.action_text, "enabled": m.enabled}
            for m in modalities
        ],
        "messages": [
            {"message_key": t.message_key, "custom_text": t.custom_text}
            for t in messages
        ],
        "ae_profiles": [
            {"ae_title": p.ae_title, "display_name": p.display_name, "manufacturer": p.manufacturer,
             "rule_overrides": p.rule_overrides, "normalization_preset": p.normalization_preset}
            for p in profiles
        ],
    }


@router.post("/import")
@AuditLogger.log("DICOM_SETTINGS_IMPORT", "DicomIssue")
async def import_settings(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Import DICOM issue settings from JSON."""
    data = await request.json()
    imported = {"rules": 0, "modality_configs": 0, "messages": 0, "ae_profiles": 0}

    for rule_data in data.get("rules", []):
        await db.execute(
            update(DicomIssueRule)
            .where(DicomIssueRule.rule_code == rule_data["rule_code"])
            .values(
                severity=rule_data.get("severity"),
                enabled=rule_data.get("enabled", True),
                custom_message=rule_data.get("custom_message"),
                auto_action=rule_data.get("auto_action", "none"),
                thresholds=rule_data.get("thresholds", {}),
            )
        )
        imported["rules"] += 1

    for mod_data in data.get("modality_configs", []):
        existing = await db.execute(
            select(ModalityRenderConfig).where(ModalityRenderConfig.modality == mod_data["modality"])
        )
        cfg = existing.scalar_one_or_none()
        if cfg:
            cfg.render_type = mod_data.get("render_type", cfg.render_type)
            cfg.display_label = mod_data.get("display_label", cfg.display_label)
            cfg.description = mod_data.get("description", cfg.description)
            cfg.action_text = mod_data.get("action_text", cfg.action_text)
            cfg.enabled = mod_data.get("enabled", cfg.enabled)
            imported["modality_configs"] += 1

    for msg_data in data.get("messages", []):
        await db.execute(
            update(DicomMessageTemplate)
            .where(DicomMessageTemplate.message_key == msg_data["message_key"])
            .values(custom_text=msg_data.get("custom_text"))
        )
        imported["messages"] += 1

    await db.commit()
    return {"ok": True, "imported": imported}


# ─── Issue Detail (path params MUST be last to avoid shadowing) ───────────────

@router.get("/{issue_id}")
async def get_issue(
    issue_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Get issue detail."""
    result = await db.execute(
        select(ValidationResult).where(ValidationResult.id == issue_id)
    )
    issue = result.scalar_one_or_none()
    if not issue:
        return {"error": "Issue not found"}

    return {
        "id": str(issue.id),
        "severity": issue.severity,
        "category": issue.category,
        "rule_code": issue.rule_code,
        "message": issue.message,
        "details": issue.details,
        "sop_instance_uid": issue.sop_instance_uid,
        "study_instance_uid": issue.study_instance_uid,
        "series_instance_uid": issue.series_instance_uid,
        "orthanc_id": issue.orthanc_id,
        "patient_name": issue.patient_name,
        "patient_id": issue.patient_id,
        "study_description": issue.study_description,
        "study_date": issue.study_date,
        "modality": issue.modality,
        "ae_title": issue.ae_title,
        "manufacturer": issue.manufacturer,
        "station_name": issue.station_name,
        "auto_fixed": issue.auto_fixed,
        "fix_description": issue.fix_description,
        "issue_status": issue.issue_status,
        "reviewer_note": issue.reviewer_note,
        "reviewed_at": issue.reviewed_at.isoformat() if issue.reviewed_at else None,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
    }


@router.patch("/{issue_id}/status")
@AuditLogger.log("DICOM_ISSUE_STATUS", "DicomIssue")
async def update_issue_status(
    issue_id: str,
    body: IssueStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update issue status (acknowledge, ignore, mark fixed)."""
    result = await db.execute(
        select(ValidationResult).where(ValidationResult.id == issue_id)
    )
    issue = result.scalar_one_or_none()
    if not issue:
        return {"error": "Issue not found"}

    issue.issue_status = body.status
    issue.reviewer_id = user.id
    issue.reviewer_note = body.note
    issue.reviewed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True, "id": str(issue.id), "status": issue.issue_status}
