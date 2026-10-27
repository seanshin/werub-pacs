"""External notification API — SMS/KakaoTalk for urgent findings."""
import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/external-notify", tags=["외부 알림"])


class ExternalNotifyRequest(BaseModel):
    recipient_phone: str = ""
    recipient_name: str = ""
    study_instance_uid: str
    message: str
    channel: str = "sms"  # sms, kakao, email


@router.post("/send", summary="외부 알림 발송 (SMS/카카오)")
async def send_external_notification(
    body: ExternalNotifyRequest,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    """긴급 소견 시 주치의에게 SMS/카카오톡/이메일로 알림을 발송합니다.

    현재는 로그 기록만. 실제 발송은 외부 API 연동 필요:
    - SMS: 네이버 클라우드 SMS API 또는 Twilio
    - KakaoTalk: 카카오 알림톡 API
    - Email: SMTP or SendGrid
    """
    logger.info(
        f"[ExternalNotify] {body.channel} to {body.recipient_name}({body.recipient_phone}): "
        f"{body.message[:100]}... (study: {body.study_instance_uid[:30]})"
    )

    return {
        "status": "queued",
        "channel": body.channel,
        "recipient": body.recipient_name,
        "message": "외부 알림 발송이 예약되었습니다 (실제 발송은 SMS/카카오 API 연동 후 활성화)",
        "note": "연동 필요: 네이버 SMS API, 카카오 알림톡 API, 또는 SMTP",
    }


@router.get("/channels", summary="사용 가능한 알림 채널")
async def list_channels(
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """사용 가능한 외부 알림 채널 목록."""
    return {
        "channels": [
            {"id": "sms", "name": "SMS", "status": "not_configured", "provider": "네이버 클라우드 / Twilio"},
            {"id": "kakao", "name": "카카오 알림톡", "status": "not_configured", "provider": "카카오 비즈니스"},
            {"id": "email", "name": "이메일", "status": "not_configured", "provider": "SMTP / SendGrid"},
            {"id": "websocket", "name": "웹 알림", "status": "active", "provider": "내장 WebSocket"},
        ]
    }
