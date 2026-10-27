"""외부 의뢰/자문 포털 API — 토큰 기반 공개 접근, 법적 동의, 의견 제출.

인증 불필요 — 토큰으로 접근 제어.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/consult-portal", tags=["외부 포털"])

TOKEN_EXPIRY_DAYS = 7


# ── Schemas ──

class ConsentSubmit(BaseModel):
    consult_token: str
    agreed_terms: list[str]  # ['phi', 'confidentiality', 'medical_law', 'data_policy', 'legal_scope']
    respondent_name: str
    respondent_institution: str | None = None
    ip_address: str | None = None


class OpinionSubmit(BaseModel):
    consult_token: str
    findings: str | None = None
    impression: str | None = None
    opinion: str | None = None
    respondent_name: str


# ── Token generation (called internally from external_consult / second_opinion) ──

def generate_consult_token() -> str:
    return secrets.token_urlsafe(32)


# ── 1. 토큰으로 의뢰 정보 조회 (인증 불필요) ──

@router.get("/view", summary="토큰으로 의뢰 정보 조회")
async def view_consult(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """외부 전문의가 토큰으로 의뢰 정보를 조회합니다. 인증 불필요."""
    # Try external_consults first
    result = await db.execute(text("""
        SELECT ec.*, 'external_consult' as consult_kind
        FROM external_consults ec
        WHERE ec.access_token = :token AND ec.status != 'cancelled'
    """), {"token": token})
    row = result.mappings().first()

    if not row:
        # Try second_opinions
        result = await db.execute(text("""
            SELECT so.*, 'second_opinion' as consult_kind
            FROM second_opinions so
            WHERE so.access_token = :token AND so.status != 'cancelled'
        """), {"token": token})
        row = result.mappings().first()

    if not row:
        raise HTTPException(404, "유효하지 않거나 만료된 링크입니다.")

    data = dict(row)

    # Check expiry
    created = data.get("created_at")
    if created and (datetime.now(timezone.utc) - created).days > TOKEN_EXPIRY_DAYS:
        raise HTTPException(410, "링크가 만료되었습니다. 의뢰 기관에 새 링크를 요청하세요.")

    # Check consent status
    consent = await db.execute(text("""
        SELECT id FROM consult_consents WHERE consult_token = :token LIMIT 1
    """), {"token": token})
    data["consent_given"] = consent.first() is not None

    # Remove sensitive internal fields
    for key in ["requested_by_id", "share_link_id"]:
        data.pop(key, None)

    return data


# ── 2. 법적 동의 제출 ──

@router.post("/consent", summary="법적 동의 제출")
async def submit_consent(
    body: ConsentSubmit,
    db: AsyncSession = Depends(get_db),
):
    """외부 전문의가 법적 동의에 서명합니다."""
    required = {'phi', 'confidentiality', 'medical_law', 'data_policy', 'legal_scope'}
    agreed = set(body.agreed_terms)
    if not required.issubset(agreed):
        missing = required - agreed
        raise HTTPException(400, f"모든 항목에 동의해야 합니다. 미동의: {', '.join(missing)}")

    # Verify token exists
    result = await db.execute(text("""
        SELECT id FROM external_consults WHERE access_token = :token
        UNION ALL
        SELECT id FROM second_opinions WHERE access_token = :token
        LIMIT 1
    """), {"token": body.consult_token})
    if not result.first():
        raise HTTPException(404, "유효하지 않은 토큰입니다.")

    await db.execute(text("""
        INSERT INTO consult_consents
            (consult_token, respondent_name, respondent_institution,
             agreed_terms, ip_address, consented_at)
        VALUES (:token, :name, :inst, :terms, :ip, NOW())
    """), {
        "token": body.consult_token,
        "name": body.respondent_name,
        "inst": body.respondent_institution,
        "terms": ",".join(body.agreed_terms),
        "ip": body.ip_address,
    })
    await db.commit()

    return {"status": "consented", "respondent": body.respondent_name}


# ── 3. 의견 제출 (동의 완료 후) ──

@router.post("/respond", summary="외부 전문의 의견 제출")
async def submit_response(
    body: OpinionSubmit,
    db: AsyncSession = Depends(get_db),
):
    """외부 전문의가 의견을 제출합니다. 법적 동의 완료 필수."""
    # Verify consent
    consent = await db.execute(text(
        "SELECT id FROM consult_consents WHERE consult_token = :token LIMIT 1"
    ), {"token": body.consult_token})
    if not consent.first():
        raise HTTPException(403, "법적 동의를 먼저 완료해야 합니다.")

    # Try external_consults
    result = await db.execute(text("""
        UPDATE external_consults
        SET external_findings = :findings, external_impression = :impression,
            status = 'completed', responded_at = NOW(), updated_at = NOW()
        WHERE access_token = :token AND status IN ('requested', 'in_progress')
        RETURNING id, study_instance_uid
    """), {
        "findings": body.findings or body.opinion,
        "impression": body.impression,
        "token": body.consult_token,
    })
    row = result.mappings().first()

    if not row:
        # Try second_opinions
        result = await db.execute(text("""
            UPDATE second_opinions
            SET response = :response, status = 'completed', responded_at = NOW()
            WHERE access_token = :token AND status = 'pending'
            RETURNING id, study_instance_uid
        """), {
            "response": body.opinion or body.findings,
            "token": body.consult_token,
        })
        row = result.mappings().first()

    await db.commit()

    if not row:
        raise HTTPException(404, "이미 응답이 완료되었거나 유효하지 않은 토큰입니다.")

    # Notify requester
    try:
        from app.api.notification import create_notification
        await create_notification(
            db, type="consult_response",
            title="외부 의견 도착",
            message=f"{body.respondent_name}님의 의견이 도착했습니다.",
            urgency="normal", target_role="radiologist",
            study_instance_uid=row["study_instance_uid"],
        )
    except Exception:
        pass

    return {"status": "completed", "message": "의견이 제출되었습니다. 감사합니다."}
