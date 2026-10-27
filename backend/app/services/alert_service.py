"""Alert Service — centralized notification dispatch for PACS events.

Creates DB notifications + broadcasts via WebSocket + sends email for critical events.

Event types:
- sla_warning: SLA warning threshold exceeded
- sla_critical: SLA critical threshold exceeded
- retake_request: New retake request from HIS or radiologist
- urgent_reading: Urgent/STAT reading request
- report_signed: Report signed (notify ordering physician)
- ai_critical: AI detected critical finding
- his_request: HIS integration request received
"""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Email Configuration ───
# TODO: Move to openpacs_config table or environment variables
EMAIL_CONFIG = {
    "enabled": False,  # Set True when SMTP is configured
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "from_address": "noreply@example.org",
    "from_name": "WeRU.B PACS",
}


async def send_alert(
    event_type: str,
    title: str,
    message: str,
    urgency: str = "normal",
    target_role: Optional[str] = None,
    target_username: Optional[str] = None,
    study_instance_uid: Optional[str] = None,
    patient_id: Optional[str] = None,
    action_url: Optional[str] = None,
    email_to: Optional[str] = None,
    extra_data: Optional[dict] = None,
    patient_name: Optional[str] = None,
):
    """Send alert: DB notification + WebSocket broadcast + optional email.

    Args:
        event_type: Alert type (sla_warning, retake_request, etc.)
        title: Short title
        message: Detail message
        urgency: normal | urgent | critical
        target_role: Target role for notification (radiologist, admin, technologist)
        target_username: Specific user
        study_instance_uid: Related study
        patient_id: Related patient
        action_url: URL to navigate on click
        email_to: Email address for email notification
        extra_data: Additional data for the notification
        patient_name: Patient display name embedded in title/message, if any.
            Used ONLY to mask it in outbound webhook payloads (external SaaS
            may be the destination) — internal DB/WS notifications keep the
            original text.
    """
    # 1. Create DB notification
    db_id = await _create_db_notification(
        event_type, title, message, urgency,
        target_role, target_username,
        study_instance_uid, patient_id, action_url, extra_data,
    )

    # 2. WebSocket broadcast
    await _broadcast_ws(
        event_type, title, message, urgency,
        target_role, target_username,
        study_instance_uid, patient_id, action_url, db_id,
    )

    # 3. Email for urgent/critical — run the blocking SMTP in a thread so it
    #    never stalls the event loop (latent: only when email is enabled).
    if email_to and urgency in ("urgent", "critical"):
        await asyncio.to_thread(_send_email, email_to, title, message, event_type, urgency)
    elif urgency == "critical" and not email_to:
        await asyncio.to_thread(_send_email_to_role, "admin", title, message, event_type)

    # 4. Webhook dispatch
    await _dispatch_webhooks(event_type, title, message, urgency,
        study_instance_uid, patient_id, action_url, target_role, extra_data,
        patient_name=patient_name)

    logger.info("Alert sent: [%s] %s → role=%s user=%s urgency=%s",
                event_type, title, target_role, target_username, urgency)

    return db_id


async def _create_db_notification(
    event_type, title, message, urgency,
    target_role, target_username,
    study_instance_uid, patient_id, action_url, extra_data,
) -> Optional[str]:
    """Insert notification into DB."""
    try:
        from app.core.database import async_session
        if async_session is None:
            return None

        from app.models.notification import Notification

        async with async_session() as db:
            n = Notification(
                type=event_type,
                title=title,
                message=message,
                urgency=urgency,
                target_role=target_role,
                target_username=target_username,
                study_instance_uid=study_instance_uid,
                patient_id=patient_id,
                action_url=action_url,
                data=extra_data,
            )
            db.add(n)
            await db.commit()
            await db.refresh(n)
            return str(n.id)
    except Exception as e:
        logger.error("Failed to create DB notification: %s", e)
        return None


async def _broadcast_ws(
    event_type, title, message, urgency,
    target_role, target_username,
    study_instance_uid, patient_id, action_url, notification_id,
):
    """Broadcast notification via WebSocket."""
    try:
        from app.api.websocket import manager

        payload = {
            "type": "notification",
            "event": event_type,
            "title": title,
            "message": message,
            "urgency": urgency,
            "target_role": target_role,
            "target_username": target_username,
            "study_instance_uid": study_instance_uid,
            "patient_id": patient_id,
            "action_url": action_url,
            "notification_id": notification_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.broadcast(payload)
    except Exception as e:
        logger.debug("WebSocket broadcast failed: %s", e)


def _send_email(to: str, subject: str, body: str, event_type: str, urgency: str = "normal"):
    """Send email notification (sync, fire-and-forget)."""
    if not EMAIL_CONFIG.get("enabled"):
        logger.debug("Email disabled, skipping: %s → %s", subject, to)
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[WeRU.B PACS] [{urgency.upper()}] {subject}"
        msg["From"] = f"{EMAIL_CONFIG['from_name']} <{EMAIL_CONFIG['from_address']}>"
        msg["To"] = to

        html = f"""
        <html>
        <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: {'#dc2626' if urgency == 'critical' else '#f59e0b' if urgency == 'urgent' else '#3b82f6'}; color: white; padding: 16px 24px; border-radius: 12px 12px 0 0;">
                <h2 style="margin: 0;">{subject}</h2>
                <p style="margin: 4px 0 0; opacity: 0.9; font-size: 14px;">{event_type} | {urgency.upper()}</p>
            </div>
            <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
                <p style="font-size: 15px; line-height: 1.6; color: #334155;">{body}</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 16px 0;">
                <p style="font-size: 12px; color: #94a3b8;">
                    WeRU.B PACS | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
                </p>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(EMAIL_CONFIG["smtp_host"], EMAIL_CONFIG["smtp_port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["smtp_user"], EMAIL_CONFIG["smtp_password"])
            server.send_message(msg)

        logger.info("Email sent: %s → %s", subject, to)
    except Exception as e:
        logger.error("Email send failed: %s", e)


def _send_email_to_role(role: str, subject: str, body: str, event_type: str):
    """Look up users by role and send email (placeholder)."""
    # TODO: Fetch user emails from DB by role
    logger.debug("Email to role %s skipped (not configured)", role)


# ─── Convenience functions for specific event types ───

async def alert_sla_warning(study_uid: str, modality: str, elapsed_min: int, threshold_min: int):
    """SLA warning threshold exceeded."""
    await send_alert(
        event_type="sla_warning",
        title=f"SLA 경고: {modality} 판독 지연",
        message=f"{modality} 검사가 {elapsed_min}분 경과했습니다 (경고 임계값: {threshold_min}분). 판독을 진행해 주세요.",
        urgency="urgent",
        target_role="radiologist",
        study_instance_uid=study_uid,
        action_url=f"/pacs-admin/reading/view?study={study_uid}",
    )


async def alert_sla_critical(study_uid: str, modality: str, elapsed_min: int, threshold_min: int):
    """SLA critical threshold exceeded."""
    await send_alert(
        event_type="sla_critical",
        title=f"SLA 위험: {modality} 판독 심각 지연",
        message=f"{modality} 검사가 {elapsed_min}분 경과했습니다 (위험 임계값: {threshold_min}분). 즉시 판독이 필요합니다.",
        urgency="critical",
        target_role="radiologist",
        study_instance_uid=study_uid,
        action_url=f"/pacs-admin/reading/view?study={study_uid}",
    )
    # Also notify admin
    await send_alert(
        event_type="sla_critical",
        title=f"SLA 위험 에스컬레이션: {modality}",
        message=f"{modality} 검사 {elapsed_min}분 경과 (임계값 {threshold_min}분). 판독의 배정 확인 필요.",
        urgency="critical",
        target_role="admin",
        study_instance_uid=study_uid,
    )


async def alert_retake_request(patient_name: str, reason: str, requested_by: str,
                                accession: str = "", urgency: str = "routine"):
    """New retake request."""
    urg = "urgent" if urgency in ("urgent", "stat") else "normal"
    await send_alert(
        event_type="retake_request",
        title=f"재촬영 요청: {patient_name}",
        message=f"{requested_by}이(가) 재촬영을 요청했습니다. 사유: {reason}",
        urgency=urg,
        target_role="technologist",
        action_url="/pacs-admin/retake",
        extra_data={"accession": accession, "reason": reason},
        patient_name=patient_name,
    )


async def alert_urgent_reading(patient_id: str, reason: str, requesting_physician: str,
                                study_uid: str = "", department: str = ""):
    """Urgent/STAT reading request."""
    await send_alert(
        event_type="urgent_reading",
        title=f"긴급 판독 요청: {patient_id}",
        message=f"{requesting_physician} ({department})이(가) 긴급 판독을 요청했습니다. 사유: {reason}",
        urgency="critical",
        target_role="radiologist",
        study_instance_uid=study_uid,
        patient_id=patient_id,
        action_url=f"/pacs-admin/reading/view?study={study_uid}" if study_uid else "/pacs-admin/reading",
    )


async def alert_report_signed(study_uid: str, patient_name: str, radiologist: str,
                               ordering_physician: str = ""):
    """Report signed — notify ordering physician."""
    await send_alert(
        event_type="report_signed",
        title=f"판독 완료: {patient_name}",
        message=f"{radiologist}이(가) 판독을 완료하고 서명했습니다.",
        urgency="normal",
        target_username=ordering_physician if ordering_physician else None,
        target_role="physician" if not ordering_physician else None,
        study_instance_uid=study_uid,
        action_url=f"/pacs-admin/reading/view?study={study_uid}",
        patient_name=patient_name,
    )


async def alert_ai_critical(study_uid: str, patient_id: str, model_name: str, finding: str):
    """AI detected critical/urgent finding."""
    await send_alert(
        event_type="ai_critical",
        title=f"AI 긴급 소견: {patient_id}",
        message=f"{model_name}이(가) 긴급 소견을 감지했습니다: {finding[:200]}",
        urgency="critical",
        target_role="radiologist",
        study_instance_uid=study_uid,
        patient_id=patient_id,
        action_url=f"/pacs-admin/reading/view?study={study_uid}",
    )


async def alert_dicom_issue_critical(
    study_uid: str, patient_name: str, rule_code: str, message_text: str,
    severity: str = "critical", modality: str = "",
):
    """DICOM critical/error issue detected — notify admin + technologist."""
    urgency = "critical" if severity == "critical" else "urgent"
    await send_alert(
        event_type="dicom_issue",
        title=f"DICOM 이슈: {rule_code} ({severity.upper()})",
        message=f"환자 {patient_name}, {modality} — {message_text[:200]}",
        urgency=urgency,
        target_role="admin",
        study_instance_uid=study_uid,
        action_url="/pacs-admin/dicom-issues",
        extra_data={"rule_code": rule_code, "severity": severity, "modality": modality},
        patient_name=patient_name,
    )


async def alert_dicom_auto_fix(study_uid: str, fixed_count: int, resolved_count: int):
    """DICOM auto-fix completed — notify admin."""
    await send_alert(
        event_type="dicom_auto_fix",
        title=f"DICOM 자동수정 완료: {fixed_count}건 수정, {resolved_count}건 해소",
        message=f"Study {study_uid[:30]}... 에 대한 자동수정이 완료되었습니다.",
        urgency="normal",
        target_role="admin",
        study_instance_uid=study_uid,
        action_url="/pacs-admin/dicom-issues",
    )


async def alert_upload_pending(source: str, patient_name: str, file_count: int):
    """New upload awaiting approval — notify admin/technologist."""
    source_labels = {"patient_portal": "환자 포털", "kiosk": "키오스크", "admin": "관리자"}
    await send_alert(
        event_type="upload_pending",
        title=f"업로드 승인 대기: {source_labels.get(source, source)}",
        message=f"{patient_name}님이 {file_count}개 파일을 업로드했습니다. 승인이 필요합니다.",
        urgency="normal",
        target_role="admin",
        action_url="/pacs-admin/upload-queue",
        patient_name=patient_name,
    )


# ─── Webhook Dispatch ───

def _mask_name(name: str) -> str:
    """홍길동 → 홍*동. Webhook destinations can be external SaaS (Slack/Teams)."""
    if not name:
        return name
    if len(name) <= 1:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def _mask_id(pid: str) -> str:
    """P2026-0008 → ******0008 (keep last 4)."""
    if not pid:
        return pid
    if len(pid) <= 4:
        return "*" * len(pid)
    return "*" * (len(pid) - 4) + pid[-4:]


async def _dispatch_webhooks(event_type: str, title: str, message: str, urgency: str,
                              study_uid: str = None, patient_id: str = None,
                              action_url: str = None, target_role: str = None,
                              extra_data: dict = None, patient_name: str = None):
    """Send webhook to all configured endpoints matching this event."""
    import httpx
    import json as json_mod

    # Load webhook config from DB
    webhooks = await _load_webhook_config()
    if not webhooks:
        return

    # PHI masking for outbound payloads (default ON — destinations are
    # operator-configured arbitrary URLs, possibly external SaaS). Internal
    # DB/WS notifications are unaffected; only the webhook copy is masked.
    from app.core.config import settings
    if getattr(settings, "webhook_mask_phi", True):
        if patient_name:
            masked = _mask_name(patient_name)
            title = title.replace(patient_name, masked)
            message = message.replace(patient_name, masked)
        if patient_id:
            masked_id = _mask_id(patient_id)
            title = title.replace(patient_id, masked_id)
            message = message.replace(patient_id, masked_id)
            patient_id = masked_id

    payload = {
        "event": event_type,
        "title": title,
        "message": message,
        "urgency": urgency,
        "study_instance_uid": study_uid,
        "patient_id": patient_id,
        "action_url": action_url,
        "target_role": target_role,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "WeRU.B PACS",
    }
    if extra_data:
        payload["data"] = extra_data

    for wh in webhooks:
        if not wh.get("enabled", True):
            continue
        # Filter by event types
        events = wh.get("events", [])
        if events and event_type not in events and "all" not in events:
            continue
        # Filter by minimum urgency
        min_urgency = wh.get("min_urgency", "normal")
        urgency_order = {"normal": 0, "urgent": 1, "critical": 2}
        if urgency_order.get(urgency, 0) < urgency_order.get(min_urgency, 0):
            continue

        url = wh.get("url", "")
        wh_type = wh.get("type", "generic")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if wh_type == "slack":
                    # Slack Incoming Webhook format
                    color = "#dc2626" if urgency == "critical" else "#f59e0b" if urgency == "urgent" else "#3b82f6"
                    slack_payload = {
                        "attachments": [{
                            "color": color,
                            "title": title,
                            "text": message,
                            "fields": [
                                {"title": "Event", "value": event_type, "short": True},
                                {"title": "Urgency", "value": urgency.upper(), "short": True},
                            ],
                            "footer": "WeRU.B PACS",
                            "ts": int(datetime.now(timezone.utc).timestamp()),
                        }]
                    }
                    if patient_id:
                        slack_payload["attachments"][0]["fields"].append(
                            {"title": "Patient", "value": patient_id, "short": True})
                    await client.post(url, json=slack_payload)

                elif wh_type == "teams":
                    # Microsoft Teams Incoming Webhook format
                    color = "dc2626" if urgency == "critical" else "f59e0b" if urgency == "urgent" else "3b82f6"
                    teams_payload = {
                        "@type": "MessageCard",
                        "@context": "http://schema.org/extensions",
                        "themeColor": color,
                        "summary": title,
                        "sections": [{
                            "activityTitle": title,
                            "activitySubtitle": f"{event_type} | {urgency.upper()}",
                            "text": message,
                            "facts": [
                                {"name": "Event", "value": event_type},
                                {"name": "Urgency", "value": urgency.upper()},
                            ],
                        }],
                    }
                    if patient_id:
                        teams_payload["sections"][0]["facts"].append(
                            {"name": "Patient", "value": patient_id})
                    await client.post(url, json=teams_payload)

                else:
                    # Generic JSON webhook
                    headers = wh.get("headers", {})
                    headers["Content-Type"] = "application/json"
                    await client.post(url, json=payload, headers=headers)

            logger.debug("Webhook sent: %s → %s", event_type, url[:50])
        except Exception as e:
            logger.error("Webhook failed: %s → %s: %s", event_type, url[:50], e)


async def _load_webhook_config() -> list:
    """Load webhook configuration from openpacs_config."""
    try:
        from app.core.database import async_session
        if async_session is None:
            return []

        import json as json_mod
        from sqlalchemy import text

        async with async_session() as db:
            result = await db.execute(
                text("SELECT value FROM openpacs_config WHERE key = 'webhook_config'")
            )
            row = result.scalar_one_or_none()
            if row:
                data = json_mod.loads(row) if isinstance(row, str) else row
                return data.get("webhooks", [])
    except Exception:
        pass
    return []
