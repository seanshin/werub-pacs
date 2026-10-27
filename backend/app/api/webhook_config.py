"""Webhook configuration API.

Manage webhook endpoints for external notification delivery (Slack, Teams, generic).
"""
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_async_db
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhook"])


class WebhookEntry(BaseModel):
    id: Optional[str] = None
    name: str
    url: str
    type: str = "generic"  # slack, teams, generic
    enabled: bool = True
    events: list[str] = ["all"]  # all, sla_warning, sla_critical, retake_request, urgent_reading, report_signed, ai_critical
    min_urgency: str = "normal"  # normal, urgent, critical
    headers: dict = {}


class WebhookConfigPayload(BaseModel):
    webhooks: list[WebhookEntry]


@router.get("/config")
async def get_webhook_config(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Get webhook configuration. Admin only."""
    try:
        result = await db.execute(
            text("SELECT value FROM openpacs_config WHERE key = 'webhook_config'")
        )
        row = result.scalar_one_or_none()
        if row:
            data = json.loads(row) if isinstance(row, str) else row
            return data
    except Exception:
        pass
    return {"webhooks": []}


@router.put("/config")
async def update_webhook_config(
    payload: WebhookConfigPayload,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Update webhook configuration. Admin only."""
    for wh in payload.webhooks:
        if not wh.id:
            wh.id = f"wh-{uuid.uuid4().hex[:8]}"

    data = payload.model_dump()
    value_json = json.dumps(data, ensure_ascii=False)

    # openpacs_config table is created at startup (core/schema_migrations).
    await db.execute(text("""
        INSERT INTO openpacs_config (key, value, updated_by)
        VALUES ('webhook_config', :val, :user)
        ON CONFLICT (key) DO UPDATE SET value = :val, updated_by = :user, updated_at = NOW()
    """), {"val": value_json, "user": user.username})
    await db.commit()

    logger.info("Webhook config updated by %s: %d webhooks", user.username, len(payload.webhooks))
    return {"status": "ok", "message": f"Webhook 설정 저장됨 ({len(payload.webhooks)}개)"}


@router.post("/test")
async def test_webhook(
    webhook: WebhookEntry,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Send a test message to a webhook endpoint. Admin only."""
    import httpx

    test_payload = {
        "event": "test",
        "title": "WeRU.B PACS Webhook 테스트",
        "message": f"Webhook 연동 테스트 메시지입니다. ({user.username})",
        "urgency": "normal",
        "source": "WeRU.B PACS",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if webhook.type == "slack":
                resp = await client.post(webhook.url, json={
                    "text": f"*WeRU.B PACS Webhook 테스트*\n연동이 정상적으로 설정되었습니다. ({user.username})",
                })
            elif webhook.type == "teams":
                resp = await client.post(webhook.url, json={
                    "@type": "MessageCard", "@context": "http://schema.org/extensions",
                    "themeColor": "3b82f6",
                    "summary": "WeRU.B PACS Webhook 테스트",
                    "sections": [{"activityTitle": "Webhook 테스트", "text": f"연동이 정상적으로 설정되었습니다. ({user.username})"}],
                })
            else:
                headers = webhook.headers.copy()
                headers["Content-Type"] = "application/json"
                resp = await client.post(webhook.url, json=test_payload, headers=headers)

            return {
                "status": "ok" if resp.status_code < 300 else "fail",
                "http_status": resp.status_code,
                "message": "테스트 발송 성공" if resp.status_code < 300 else f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"status": "fail", "message": str(e)}
