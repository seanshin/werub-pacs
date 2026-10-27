"""External e-signature service client (sign.example.org / dev http://127.0.0.1:4100/v1).

Contract pinned to the sign team's live-verified curl set (2026-06-14).
Envelope: success -> {"data": ...}; error -> {"error":{code,message,requestId}}.
Auth: header `x-api-key: <PACS_API_KEY>` for service calls; `/sign/staff` uses ONLY
the radiologist's forwarded Bearer (aud=sign), no x-api-key. Only the SHA-256 hex
(64) of the final PDF bytes is sent — never the source document.

Flows:
  A. Report STAFF sign: certificates/enroll(STAFF) → requests(signerType=STAFF,
     externalSignerRef=판독의 sub) → sign/staff(Bearer) → verify / audit-certificate
  B. Patient consent: certificates/enroll(PATIENT,PASS) → requests(signerType=PATIENT)
     → portal-tokens (or notify) → patient signs at /portal/<token> → verify / cert
"""
import hashlib
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def sha256_hex(pdf_bytes: bytes) -> str:
    """SHA-256 of the final-PDF bytes, lowercase hex (64). Both sides hash the same
    frozen bytes so the sealed documentHash matches at verify."""
    return hashlib.sha256(pdf_bytes).hexdigest()


class SignServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"sign {status}/{code}: {message}")


class SignServiceClient:
    def __init__(self):
        self.base = settings.sign_service_url.rstrip("/")
        self.api_key = settings.sign_service_api_key

    def _headers(self, *, api_key: bool = True, bearer: str | None = None) -> dict:
        h = {"accept": "application/json", "content-type": "application/json"}
        if api_key:
            h["x-api-key"] = self.api_key
        if bearer:
            h["authorization"] = f"Bearer {bearer}"
        return h

    async def _request(self, method: str, path: str, *, json: dict | None = None,
                       api_key: bool = True, bearer: str | None = None,
                       expect_bytes: bool = False) -> Any:
        url = f"{self.base}{path}"
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.request(method, url, json=json,
                                   headers=self._headers(api_key=api_key, bearer=bearer))
        if resp.status_code >= 400:
            code, message = "http_error", resp.text[:300]
            try:
                err = resp.json().get("error", {})
                code, message = err.get("code", code), err.get("message", message)
            except Exception:
                pass
            raise SignServiceError(resp.status_code, code, message)
        if expect_bytes:
            return resp.content
        body = resp.json() if resp.content else {}
        return body.get("data", body)

    # ── 1) Certificate enroll ───────────────────────────────────────────────
    async def enroll_patient(self, *, name: str, ci: str | None = None) -> dict:
        """PATIENT cert (PASS). PACS sends name (+ ci when available).
        → {serialNumber, ownerType, chainValid, x509Serial}"""
        identity: dict = {"method": "PASS"}
        if ci:
            identity["ci"] = ci
        return await self._request("POST", "/certificates/enroll", json={
            "ownerType": "PATIENT", "subjectDn": f"CN={name}", "identity": identity,
        })

    async def enroll_staff(self, *, name: str, org: str, owner_ref: str,
                           license_number: str) -> dict:
        """STAFF cert — NOT idempotent; enroll once, reuse serialNumber.
        → {certId, serialNumber, notBefore, notAfter, chainValid, x509Serial}"""
        return await self._request("POST", "/certificates/enroll", json={
            "ownerType": "STAFF", "subjectDn": f"CN={name},O={org}",
            "ownerRef": owner_ref, "licenseNumber": license_number,
            "identity": {"method": "STAFF_SSO"},
        })

    # ── 2) Create signing request ───────────────────────────────────────────
    async def create_request(self, *, idempotency_key: str, external_doc_id: str,
                             title: str, document_hash: str, participants: list[dict],
                             sign_mode: str = "APP") -> dict:
        """Seal documentHash + participants. → {requestId, status, expiresAt,
        participants:[{participantId, signerType, status}]}"""
        return await self._request("POST", "/requests", json={
            "idempotencyKey": idempotency_key, "externalDocId": external_doc_id,
            "title": title, "documentHash": document_hash, "signMode": sign_mode,
            "participants": participants,
        })

    async def upload_document(self, request_id: str, pdf: bytes) -> dict:
        """서명 대상 PDF 업로드(공개판) — 환자가 포털에서 본문을 보고 서명하게 한다.
        sign 이 SHA-256 == documentHash 를 검증한다. sign 쪽 PORTAL_DOC_PREVIEW=on 이 필요하다."""
        url = f"{self.base}/requests/{request_id}/document"
        headers = {"accept": "application/json", "content-type": "application/pdf", "x-api-key": self.api_key}
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.put(url, content=pdf, headers=headers)
        if resp.status_code >= 400:
            raise SignServiceError(resp.status_code, "document_upload_failed", resp.text[:300])
        body = resp.json() if resp.content else {}
        return body.get("data", body)

    @staticmethod
    def patient_participant(*, name: str, cert_serial: str, order: int = 1) -> dict:
        return {"signerRole": "PATIENT", "signerType": "PATIENT", "displayName": name,
                "signOrder": order, "certSerial": cert_serial,
                "requiredIdentityLevel": "PASS"}

    @staticmethod
    def proxy_participant(*, guardian_name: str, cert_serial: str, on_behalf_of: str,
                          relationship: str, order: int = 1) -> dict:
        """Guardian/proxy signs on behalf of a patient (minor/emergency). The guardian
        authenticates via PASS. relationship/onBehalfOf bind the proxy in the audit.
        # [CURL] facade channel:PROXY defines relationship/onBehalfOf; the base /requests
        # may ignore unknown fields — PACS also stores them locally either way."""
        return {"signerRole": "PROXY", "signerType": "PATIENT", "displayName": guardian_name,
                "signOrder": order, "certSerial": cert_serial,
                "requiredIdentityLevel": "PASS", "relationship": relationship,
                "onBehalfOf": on_behalf_of}

    @staticmethod
    def staff_participant(*, name: str, cert_serial: str, signer_sub: str,
                          order: int = 1) -> dict:
        return {"signerRole": "STAFF", "signerType": "STAFF", "displayName": name,
                "signOrder": order, "certSerial": cert_serial,
                "requiredIdentityLevel": "STAFF_SSO", "externalSignerRef": signer_sub}

    # ── 3) STAFF sign (Bearer only) ─────────────────────────────────────────
    async def sign_staff(self, *, participant_id: str, bearer_token: str) -> dict:
        """Forward the radiologist's aud=sign Bearer. → {requestStatus, staffSub,
        role, acr}. 401 if missing/aud≠sign."""
        return await self._request("POST", "/sign/staff", api_key=False,
                                   bearer=bearer_token, json={"participantId": participant_id})

    # ── 4) Portal tokens (patient) ──────────────────────────────────────────
    async def portal_tokens(self, request_id: str) -> list[dict]:
        """One-time portal links (48h). → [{participantId, signerRole, token, url}]"""
        return await self._request("POST", f"/requests/{request_id}/portal-tokens")

    async def notify(self, request_id: str, *, recipients: list[dict],
                     base_url: str = "https://sign.example.org") -> list[dict]:
        """Send 알림톡/SMS. recipients=[{participantId, to, channel:'ALIMTALK'|'SMS'}].
        → [{participantId, channel, result:'SENT'|'SKIP', providerMsgId?, url?, reason?}]"""
        return await self._request("POST", f"/requests/{request_id}/notify",
                                   json={"baseUrl": base_url, "recipients": recipients})

    # ── 5) Verify (poll) ────────────────────────────────────────────────────
    async def verify(self, request_id: str) -> dict:
        """→ {status, documentIntegrity, auditChainValid, signatures:[...], overall}.
        Completion gate = overall is True."""
        return await self._request("GET", f"/verify/{request_id}")

    # ── 6) Audit certificate (PAdES PDF) ────────────────────────────────────
    async def audit_certificate(self, request_id: str) -> bytes:
        return await self._request("GET", f"/requests/{request_id}/audit-certificate",
                                   expect_bytes=True)


def get_sign_client() -> SignServiceClient:
    return SignServiceClient()
