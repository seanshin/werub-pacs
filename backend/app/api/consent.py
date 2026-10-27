"""Patient consent e-signature (sign-service flow B: 영상/조영제 동의서).

PACS keeps the consent PDF; only its SHA-256 hex is sealed by the sign service.
Flow: enroll(PATIENT,PASS) → requests(signerType=PATIENT) → portal-tokens (or
notify) → patient signs at the portal → verify (overall=true) → audit-certificate.

No SSO dependency (PASS auth happens at the sign portal). Config-gated by
sign_service_enabled.
"""
import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User
from app.services.sign_service import SignServiceError, get_sign_client, sha256_hex

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/consent", tags=["환자 동의서 전자서명"])

_DDL = """
CREATE TABLE IF NOT EXISTS consent_signatures (
    request_id TEXT PRIMARY KEY,
    participant_id TEXT,
    patient_id TEXT,
    patient_name TEXT,
    consent_type TEXT,
    external_doc_id TEXT,
    document_sha256 TEXT NOT NULL,
    cert_serial TEXT,
    portal_token TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'CREATED',
    overall_valid BOOLEAN,
    signer_type TEXT NOT NULL DEFAULT 'PATIENT',  -- PATIENT(self) | PROXY(guardian)
    guardian_name TEXT,
    relationship TEXT,
    on_behalf_of TEXT,
    signed_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Proxy columns may be missing on a table created before this feature.
_DDL_ALTER = [
    "ALTER TABLE consent_signatures ADD COLUMN IF NOT EXISTS signer_type TEXT NOT NULL DEFAULT 'PATIENT'",
    "ALTER TABLE consent_signatures ADD COLUMN IF NOT EXISTS guardian_name TEXT",
    "ALTER TABLE consent_signatures ADD COLUMN IF NOT EXISTS relationship TEXT",
    "ALTER TABLE consent_signatures ADD COLUMN IF NOT EXISTS on_behalf_of TEXT",
]


def _require_enabled():
    if not settings.sign_service_enabled or not settings.sign_service_api_key:
        raise HTTPException(503, "SIGN_SERVICE_DISABLED")


async def _exec(db, sql, params, retry_ddl=True):
    try:
        return await db.execute(text(sql), params)
    except Exception:
        if not retry_ddl:
            raise
        await db.rollback()
        await db.execute(text(_DDL))
        for stmt in _DDL_ALTER:  # add proxy columns to a pre-existing table
            await db.execute(text(stmt))
        return await db.execute(text(sql), params)


@router.post("/requests", status_code=201, summary="동의서 서명요청 생성 (PDF 업로드)")
async def create_consent(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    file: UploadFile = File(..., description="동의서 PDF (freeze된 최종본)"),
    patient_id: str = Form(...),
    patient_name: str = Form(...),
    consent_type: str = Form("조영제 사용 동의서"),
    study_uid: str | None = Form(None),
    ci: str | None = Form(None),
    phone: str | None = Form(None),
    guardian_name: str | None = Form(None, description="대리 서명 시 보호자 성명 (있으면 PROXY 모드)"),
    relationship: str | None = Form(None, description="환자와의 관계 (부/모/배우자/법정대리인 등)"),
    guardian_ci: str | None = Form(None, description="보호자 CI (PASS)"),
):
    """동의서 PDF를 봉인하고 서명 포털 링크 발급. PDF 원본은 PACS 보관.
    guardian_name이 있으면 **대리 서명(PROXY)** — 미성년·응급 등 환자가 직접 서명 불가 시
    보호자가 PASS로 대신 서명(관계·on-behalf 감사 봉인)."""
    _require_enabled()
    is_proxy = bool(guardian_name)
    if is_proxy and not relationship:
        raise HTTPException(400, "PROXY consent requires 'relationship'")
    pdf = await file.read()
    if not pdf:
        raise HTTPException(400, "Empty PDF")
    document_hash = sha256_hex(pdf)
    external_doc_id = study_uid or f"CONSENT-{uuid.uuid4().hex[:12]}"

    # PACS keeps the original PDF
    try:
        os.makedirs(settings.consent_storage_path, exist_ok=True)
    except Exception as e:
        logger.warning(f"consent storage dir: {e}")

    sign = get_sign_client()
    try:
        # PROXY: the guardian is the signer; PATIENT: the patient signs for self
        signer_name = guardian_name if is_proxy else patient_name
        cert = await sign.enroll_patient(name=signer_name, ci=guardian_ci if is_proxy else ci)
        cert_serial = cert.get("serialNumber")
        if is_proxy:
            participant = sign.proxy_participant(
                guardian_name=guardian_name, cert_serial=cert_serial,
                on_behalf_of=patient_id, relationship=relationship)
        else:
            participant = sign.patient_participant(name=patient_name, cert_serial=cert_serial)
        req = await sign.create_request(
            idempotency_key=str(uuid.uuid4()),
            external_doc_id=external_doc_id,
            title=consent_type,
            document_hash=document_hash,
            participants=[participant],
        )
        request_id = req["requestId"]
        # 공개판(PS1): 환자가 본문을 보고 서명하도록 PDF 를 sign 에 올린다 — 못 올리면 서명 링크를 내보내지 않는다
        await sign.upload_document(request_id, pdf)
        participant_id = (req.get("participants") or [{}])[0].get("participantId")
        tokens = await sign.portal_tokens(request_id)
        tok = tokens[0] if tokens else {}
        portal_token = tok.get("token")
        portal_url = f"{settings.sign_portal_base_url}{tok.get('url', '')}" if tok.get("url") else None
    except SignServiceError as e:
        raise HTTPException(502, f"sign service error: {e.code} {e.message}")

    # store PDF + record
    if request_id:
        try:
            with open(os.path.join(settings.consent_storage_path, f"{request_id}.pdf"), "wb") as f:
                f.write(pdf)
        except Exception as e:
            logger.warning(f"consent pdf store: {e}")
    await _exec(db, """
        INSERT INTO consent_signatures (request_id, participant_id, patient_id, patient_name,
            consent_type, external_doc_id, document_sha256, cert_serial, portal_token,
            portal_url, status, signer_type, guardian_name, relationship, on_behalf_of, created_by)
        VALUES (:rid, :pid, :patid, :pname, :ctype, :ext, :hash, :serial, :ptok, :purl,
            :status, :stype, :gname, :rel, :obo, :by)
    """, {"rid": request_id, "pid": participant_id, "patid": patient_id, "pname": patient_name,
          "ctype": consent_type, "ext": external_doc_id, "hash": document_hash,
          "serial": cert_serial, "ptok": portal_token, "purl": portal_url,
          "status": req.get("status", "CREATED"),
          "stype": "PROXY" if is_proxy else "PATIENT",
          "gname": guardian_name, "rel": relationship,
          "obo": patient_id if is_proxy else None, "by": user.username})
    await db.commit()

    # optional 알림톡/SMS
    notified = None
    if phone and participant_id:
        try:
            notified = await sign.notify(request_id, recipients=[
                {"participantId": participant_id, "to": phone, "channel": "ALIMTALK"}])
        except SignServiceError as e:
            logger.warning(f"notify failed: {e}")

    return {"request_id": request_id, "participant_id": participant_id,
            "document_sha256": document_hash, "portal_url": portal_url,
            "status": req.get("status", "CREATED"), "notified": notified,
            "signer_type": "PROXY" if is_proxy else "PATIENT",
            "guardian_name": guardian_name, "relationship": relationship,
            "on_behalf_of": patient_id if is_proxy else None}


@router.get("/requests", summary="동의서 서명요청 목록")
async def list_consents(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    patient_id: str | None = None,
    limit: int = 100,
):
    q = "SELECT * FROM consent_signatures"
    p: dict = {"lim": min(limit, 500)}
    if patient_id:
        q += " WHERE patient_id = :pid"; p["pid"] = patient_id
    q += " ORDER BY created_at DESC LIMIT :lim"
    try:
        rows = (await db.execute(text(q), p)).mappings().all()
    except Exception:
        return {"requests": []}
    return {"requests": [dict(r) for r in rows]}


@router.get("/requests/{request_id}", summary="동의서 상태 조회 (폴링)")
async def get_consent(
    request_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
):
    _require_enabled()
    row = (await db.execute(text(
        "SELECT * FROM consent_signatures WHERE request_id = :id"), {"id": request_id})).mappings().first()
    if not row:
        raise HTTPException(404, "Consent request not found")
    try:
        v = await get_sign_client().verify(request_id)
    except SignServiceError as e:
        raise HTTPException(502, f"verify error: {e.code} {e.message}")
    overall = bool(v.get("overall"))
    status = v.get("status", row["status"])
    if status != row["status"] or overall != row["overall_valid"]:
        await db.execute(text("""
            UPDATE consent_signatures SET status = :s, overall_valid = :o,
                signed_at = CASE WHEN :o THEN NOW() ELSE signed_at END
            WHERE request_id = :id
        """), {"s": status, "o": overall, "id": request_id})
        await db.commit()
    return {"request_id": request_id, "status": status, "overall_valid": overall,
            "document_integrity": v.get("documentIntegrity"),
            "audit_chain_valid": v.get("auditChainValid"), "signatures": v.get("signatures")}


@router.post("/requests/{request_id}/notify", summary="환자 알림톡/SMS 발송")
async def notify_consent(
    request_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    phone: str = Form(...),
    channel: str = Form("ALIMTALK"),
):
    _require_enabled()
    row = (await db.execute(text(
        "SELECT participant_id FROM consent_signatures WHERE request_id = :id"),
        {"id": request_id})).mappings().first()
    if not row:
        raise HTTPException(404, "Consent request not found")
    try:
        res = await get_sign_client().notify(request_id, base_url=settings.sign_portal_base_url,
            recipients=[{"participantId": row["participant_id"], "to": phone, "channel": channel}])
    except SignServiceError as e:
        raise HTTPException(502, f"notify error: {e.code} {e.message}")
    return {"request_id": request_id, "result": res}


@router.get("/requests/{request_id}/certificate", summary="감사추적 인증서 (PAdES PDF)")
async def consent_certificate(
    request_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
):
    _require_enabled()
    try:
        pdf = await get_sign_client().audit_certificate(request_id)
    except SignServiceError as e:
        raise HTTPException(502, f"certificate error: {e.code} {e.message}")

    def _stream():
        yield pdf

    return StreamingResponse(_stream(), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="consent-audit-{request_id[:8]}.pdf"'})
