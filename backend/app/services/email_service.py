"""이메일 발송 서비스 — SMTP 또는 로그 모드.

환경변수 SMTP_HOST가 설정되면 실제 발송, 없으면 로그만 기록.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@example.org")
BASE_URL = os.getenv("BASE_URL", "https://his.example.org")


def send_consult_email(
    to_email: str,
    subject: str,
    portal_url: str,
    consult_type: str,
    requester_name: str,
    reason: str,
    urgency: str = "routine",
) -> bool:
    """의뢰/자문 포털 링크 이메일 발송."""
    full_url = f"{BASE_URL}{portal_url}"

    urgency_label = {"stat": "STAT (긴급)", "urgent": "긴급", "routine": "일반"}.get(urgency, urgency)
    type_label = {
        "external_read": "외부 판독 의뢰",
        "subspecialty": "세부전공 자문",
        "teleradiology": "원격판독 의뢰",
        "second_opinion": "세컨드 오피니언 요청",
    }.get(consult_type, consult_type)

    html = f"""
    <div style="font-family: 'Apple SD Gothic Neo', sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: linear-gradient(135deg, #3B82F6, #1D4ED8); padding: 24px; border-radius: 12px 12px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 20px;">WeRU.B PACS — {type_label}</h1>
      </div>
      <div style="background: white; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
        <p style="color: #374151;">{requester_name}님이 판독 자문을 요청했습니다.</p>

        <div style="background: #F3F4F6; padding: 16px; border-radius: 8px; margin: 16px 0;">
          <p style="margin: 4px 0; font-size: 14px;"><strong>유형:</strong> {type_label}</p>
          <p style="margin: 4px 0; font-size: 14px;"><strong>긴급도:</strong> {urgency_label}</p>
          <p style="margin: 4px 0; font-size: 14px;"><strong>사유:</strong> {reason}</p>
        </div>

        <p style="color: #6B7280; font-size: 13px;">아래 링크를 통해 영상을 확인하고 의견을 제출해 주세요. 링크는 7일간 유효합니다.</p>

        <div style="text-align: center; margin: 24px 0;">
          <a href="{full_url}" style="background: #3B82F6; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px;">
            영상 확인 및 의견 작성
          </a>
        </div>

        <p style="color: #9CA3AF; font-size: 11px; margin-top: 24px;">
          본 이메일은 WeRU.B PACS 시스템에서 자동 발송되었습니다.<br>
          문의: {SMTP_FROM}
        </p>
      </div>
    </div>
    """

    if not SMTP_HOST:
        logger.info(f"[EMAIL-LOG] To: {to_email} | Subject: {subject} | URL: {full_url}")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(f"판독 자문 요청\n\n{reason}\n\n링크: {full_url}", "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        logger.info(f"[EMAIL-SENT] To: {to_email} | Subject: {subject}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL-FAIL] To: {to_email} | Error: {e}")
        return False
