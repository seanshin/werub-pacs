"""Report STAFF e-signature (sign-service flow A: 판독보고서 전자서명).

The radiologist finalizes a report, then signs it via the external sign service.
The *final report PDF* (frontend-rendered, the exact bytes the radiologist views)
is uploaded; PACS seals only its SHA-256. The radiologist's **aud=sign** Bearer
(obtained from the hospital common SSO) is passed in `X-Sign-Token` and forwarded
to /v1/sign/staff — PACS does not verify it (the sign service does, and binds it to
externalSignerRef=sub to block impersonation).

Flow: enroll(STAFF) or reuse cert serial → requests(signerType=STAFF,
externalSignerRef=sub) → sign/staff(Bearer) → verify (overall) → audit-certificate.
Config-gated by sign_service_enabled.
"""
import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User
from app.services.sign_service import SignServiceError, get_sign_client, sha256_hex

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["판독보고서 전자서명"])

_DDL_SIG = """
CREATE TABLE IF NOT EXISTS report_esignatures (
    report_id TEXT PRIMARY KEY,
    request_id TEXT,
    participant_id TEXT,
    signer_sub TEXT,
    signer_name TEXT,
    cert_serial TEXT,
    document_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CREATED',
    request_status TEXT,
    overall_valid BOOLEAN,
    role TEXT,
    acr TEXT,
    assurance_level TEXT,
    hsm_anchored BOOLEAN DEFAULT false,
    ca_key_custody TEXT,
    ca_key_custody_provider TEXT,
    signed_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
# 기존 운영 테이블(구 스키마)용 멱등 마이그레이션 — HSM attestation 봉인 컬럼.
# assuranceLevel/hsm은 CA 키관리(SOFTWARE→KMS시 HSM_ANCHORED) 반영. ca_key_custody*는
# sign이 v12.6 회신으로 verify에 추가한 부가 attestation(감사 상세).
_SIG_COLUMNS = (
    ("assurance_level", "TEXT"),
    ("hsm_anchored", "BOOLEAN DEFAULT false"),
    ("ca_key_custody", "TEXT"),
    ("ca_key_custody_provider", "TEXT"),
)


async def _ensure_sig_columns(db):
    for col, typ in _SIG_COLUMNS:
        try:
            await db.execute(text(
                f"ALTER TABLE report_esignatures ADD COLUMN IF NOT EXISTS {col} {typ}"))
        except Exception:
            await db.rollback()
    await db.commit()
_DDL_CERT = """
CREATE TABLE IF NOT EXISTS staff_sign_certs (
    signer_sub TEXT PRIMARY KEY,
    cert_serial TEXT NOT NULL,
    license_number TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _require_enabled():
    if not settings.sign_service_enabled or not settings.sign_service_api_key:
        raise HTTPException(503, "SIGN_SERVICE_DISABLED")


async def _exec(db, sql, params, ddl=_DDL_SIG):
    try:
        return await db.execute(text(sql), params)
    except Exception:
        await db.rollback()
        await db.execute(text(ddl))
        return await db.execute(text(sql), params)


async def _resolve_cert_serial(db, sign, *, claims: dict, name: str) -> str:
    """Prefer the token's sign_cert_serial; else reuse a cached enrollment; else
    enroll once (STAFF enroll is not idempotent) and cache."""
    serial = claims.get("sign_cert_serial")
    if serial:
        return serial
    sub = claims.get("sub")
    row = (await db.execute(text(
        "SELECT cert_serial FROM staff_sign_certs WHERE signer_sub = :s"), {"s": sub})).mappings().first()
    if row:
        return row["cert_serial"]
    cert = await sign.enroll_staff(
        name=name, org="영상의학과", owner_ref=sub or "unknown",
        license_number=claims.get("license_number") or "")
    serial = cert.get("serialNumber")
    await _exec(db, """
        INSERT INTO staff_sign_certs (signer_sub, cert_serial, license_number)
        VALUES (:s, :c, :l) ON CONFLICT (signer_sub) DO UPDATE SET cert_serial = :c
    """, {"s": sub, "c": serial, "l": claims.get("license_number")}, ddl=_DDL_CERT)
    await db.commit()
    return serial


@router.post("/{report_id}/esign", status_code=201, summary="판독보고서 STAFF 전자서명")
async def esign_report(
    report_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN, allow_btg=False)),
    file: UploadFile = File(..., description="최종 보고서 PDF (프론트 렌더, 서명자가 본 바이트)"),
    x_sign_token: str | None = Header(None, description="판독의 aud=sign Bearer 토큰"),
):
    """확정된 보고서를 sign 서비스로 STAFF 서명. PDF 원본은 PACS 보관, 해시만 봉인."""
    _require_enabled()
    if not x_sign_token:
        raise HTTPException(400, "X-Sign-Token (aud=sign) required")
    pdf = await file.read()
    if not pdf:
        raise HTTPException(400, "Empty PDF")
    document_hash = sha256_hex(pdf)

    # report must be FINAL; signer = the report's signer (or admin)
    rpt = (await db.execute(text(
        "SELECT id, status, signed_by_id, signed_by_name, study_instance_uid "
        "FROM reports WHERE id = :id"), {"id": report_id})).mappings().first()
    if not rpt:
        raise HTTPException(404, "Report not found")
    if str(rpt["status"]).upper() != "FINAL":
        raise HTTPException(409, "Report must be FINAL before e-signing")
    if Role(user.role) != Role.ADMIN and rpt["signed_by_id"] and str(rpt["signed_by_id"]) != str(user.id):
        raise HTTPException(403, "본인이 확정한 보고서만 서명할 수 있습니다")

    # claims from the aud=sign token (unverified read — sign service verifies)
    try:
        claims = jwt.get_unverified_claims(x_sign_token)
    except Exception:
        raise HTTPException(400, "Invalid X-Sign-Token")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(400, "Sign token missing sub")
    signer_name = claims.get("name") or rpt["signed_by_name"] or user.full_name

    sign = get_sign_client()
    try:
        cert_serial = await _resolve_cert_serial(db, sign, claims=claims, name=signer_name)
        req = await sign.create_request(
            idempotency_key=f"report-{report_id}",
            external_doc_id=rpt["study_instance_uid"] or f"REPORT-{report_id}",
            title="판독보고서", document_hash=document_hash,
            participants=[sign.staff_participant(name=signer_name, cert_serial=cert_serial, signer_sub=sub)],
        )
        request_id = req["requestId"]
        participant_id = (req.get("participants") or [{}])[0].get("participantId")
        signed = await sign.sign_staff(participant_id=participant_id, bearer_token=x_sign_token)
        v = await sign.verify(request_id)
    except SignServiceError as e:
        raise HTTPException(502, f"sign service error: {e.code} {e.message}")

    overall = bool(v.get("overall"))
    # HSM 앵커 봉인 — sign verify가 assuranceLevel(SOFTWARE/HSM_ANCHORED)을 반환.
    # PACS는 키/HSM 미보유 → sign이 보고한 보증수준을 그대로 봉인·표시한다.
    assurance = v.get("assuranceLevel") or signed.get("assuranceLevel")
    hsm_anchored = assurance == "HSM_ANCHORED"
    # 부가 attestation (sign이 verify에 추가) — CA 키관리 custody/provider. HSM 판정은
    # 반드시 assuranceLevel로(서명키 keyCustody는 설계상 SOFT라 HSM 영영 안 잡힘 — sign 확인).
    ca_custody = v.get("caKeyCustody")
    ca_provider = v.get("caKeyCustodyProvider")
    try:
        os.makedirs(settings.consent_storage_path, exist_ok=True)
        with open(os.path.join(settings.consent_storage_path, f"report-{report_id}.pdf"), "wb") as f:
            f.write(pdf)
    except Exception as e:
        logger.warning(f"report pdf store: {e}")

    await _ensure_sig_columns(db)
    await _exec(db, """
        INSERT INTO report_esignatures (report_id, request_id, participant_id, signer_sub,
            signer_name, cert_serial, document_sha256, status, request_status, overall_valid,
            role, acr, assurance_level, hsm_anchored, ca_key_custody, ca_key_custody_provider,
            signed_at, created_by)
        VALUES (:rid, :req, :pid, :sub, :name, :serial, :hash, :status, :rstatus, :overall,
            :role, :acr, :assurance, :hsm, :cacust, :caprov, CASE WHEN :overall THEN NOW() END, :by)
        ON CONFLICT (report_id) DO UPDATE SET request_id=:req, participant_id=:pid,
            status=:status, request_status=:rstatus, overall_valid=:overall,
            assurance_level=:assurance, hsm_anchored=:hsm,
            ca_key_custody=:cacust, ca_key_custody_provider=:caprov,
            -- 재검증 overall=false 시 기존 유효 서명시각 보존(ELSE 누락→NULL 덮어쓰기 방지)
            signed_at=CASE WHEN :overall THEN NOW() ELSE report_esignatures.signed_at END
    """, {"rid": report_id, "req": request_id, "pid": participant_id, "sub": sub,
          "name": signer_name, "serial": cert_serial, "hash": document_hash,
          "status": v.get("status", "SIGNED"), "rstatus": signed.get("requestStatus"),
          "overall": overall, "role": signed.get("role"), "acr": signed.get("acr"),
          "assurance": assurance, "hsm": hsm_anchored, "cacust": ca_custody, "caprov": ca_provider,
          "by": user.username})
    await db.commit()

    return {"report_id": report_id, "request_id": request_id,
            "request_status": signed.get("requestStatus"), "overall_valid": overall,
            "document_integrity": v.get("documentIntegrity"),
            "assurance_level": assurance, "hsm_anchored": hsm_anchored,
            "ca_key_custody": ca_custody, "ca_key_custody_provider": ca_provider,
            "signer_sub": sub, "role": signed.get("role"), "acr": signed.get("acr")}


@router.get("/{report_id}/esign", summary="보고서 서명 상태 조회")
async def get_report_esign(
    report_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN, Role.PHYSICIAN)),
):
    # 테이블 부재(서명 이력 0) 시 404 — 미생성 테이블 SELECT는 500을 던진다
    if not (await db.execute(text(
            "SELECT to_regclass('public.report_esignatures') IS NOT NULL"))).scalar():
        raise HTTPException(404, "No e-signature for this report")
    row = (await db.execute(text(
        "SELECT * FROM report_esignatures WHERE report_id = :id"), {"id": report_id})).mappings().first()
    if not row:
        raise HTTPException(404, "No e-signature for this report")
    if settings.sign_service_enabled and row["request_id"]:
        try:
            v = await get_sign_client().verify(row["request_id"])
            return {**dict(row), "live_status": v.get("status"), "live_overall": v.get("overall"),
                    "live_assurance_level": v.get("assuranceLevel"),
                    "live_hsm_anchored": v.get("assuranceLevel") == "HSM_ANCHORED",
                    "live_ca_key_custody": v.get("caKeyCustody"),
                    "live_ca_key_custody_provider": v.get("caKeyCustodyProvider")}
        except SignServiceError:
            pass
    return dict(row)


@router.get("/{report_id}/esign/certificate", summary="보고서 감사추적 인증서 (PAdES PDF)")
async def report_esign_certificate(
    report_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN, Role.PHYSICIAN)),
):
    _require_enabled()
    if not (await db.execute(text(
            "SELECT to_regclass('public.report_esignatures') IS NOT NULL"))).scalar():
        raise HTTPException(404, "No e-signature for this report")
    row = (await db.execute(text(
        "SELECT request_id FROM report_esignatures WHERE report_id = :id"), {"id": report_id})).mappings().first()
    if not row or not row["request_id"]:
        raise HTTPException(404, "No e-signature for this report")
    try:
        pdf = await get_sign_client().audit_certificate(row["request_id"])
    except SignServiceError as e:
        raise HTTPException(502, f"certificate error: {e.code} {e.message}")
    return StreamingResponse(iter([pdf]), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="report-sign-audit-{report_id[:8]}.pdf"'})
