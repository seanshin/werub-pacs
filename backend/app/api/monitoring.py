"""Alertmanager webhook receiver (pacs-fundamentals 2축).

Prometheus alert rules → alertmanager → 이 웹훅 → admin 알림센터(notifications).
백엔드 자신이 죽으면 이 경로도 죽으므로 backend-down은 email receiver(운영에서
SMTP 확보 시 alertmanager에 추가)가 담당 — 그 전까지 in-app 경로가 최선의 채널.

인증: default-off 토큰 게이트(HIS inbound 서비스키와 동형) — 미설정 시 503, 설정 시
`Authorization: Bearer <token>` 헤더 상수시간 비교. **헤더 사용 이유**: URL 쿼리 토큰은
gunicorn access-log(--access-logfile -)에 평문으로 축적된다(alertmanager는 v0.27부터
webhook http_config.authorization 표준 지원). 레거시 `?token=` 쿼리도 하위호환 허용하나
비권장.
"""
import hmac
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/monitoring", tags=["Monitoring"])

_URGENCY = {"critical": "critical", "warning": "urgent"}


@router.post("/alerts-webhook", status_code=202)
async def alertmanager_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str = Query(""),
    authorization: str = Header(""),
):
    if not settings.alertmanager_webhook_token:
        raise HTTPException(503, "alerts webhook disabled")
    # Authorization: Bearer <token> 우선, 레거시 ?token= 폴백
    presented = authorization[7:] if authorization.lower().startswith("bearer ") else token
    if not hmac.compare_digest(presented, settings.alertmanager_webhook_token):
        raise HTTPException(403, "invalid token")

    payload = await request.json()
    created = 0
    for alert in (payload.get("alerts") or [])[:20]:
        labels = alert.get("labels") or {}
        ann = alert.get("annotations") or {}
        name = labels.get("alertname", "unknown")
        status = alert.get("status", "firing")
        severity = labels.get("severity", "warning")
        summary = ann.get("summary") or ann.get("description") or name
        prefix = "[해제] " if status == "resolved" else ""
        await db.execute(text("""
            INSERT INTO notifications (id, type, title, message, urgency, target_role,
                study_instance_uid, action_url, is_read, acknowledged, created_at)
            VALUES (:id, 'monitoring_alert', :title, :msg, :urgency, 'admin',
                    NULL, '/pacs-admin/notifications', false, false, NOW())
        """), {
            "id": str(uuid.uuid4()),
            "title": f"{prefix}모니터링: {name}",
            "msg": f"{prefix}{summary}"[:500],
            "urgency": "normal" if status == "resolved" else _URGENCY.get(severity, "urgent"),
        })
        created += 1
    await db.commit()
    logger.warning(f"alertmanager webhook: {created} notification(s) created")
    return {"accepted": created}
