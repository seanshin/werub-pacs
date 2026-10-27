"""IHE ATNA audit emitter (EMR-CERT interoperability I010 / 진료정보교류 감사로그).

Emits IHE ATNA audit messages — DICOM Audit Message format (RFC 3881 / DICOM
PS3.15 A.5) wrapped in an RFC 5424 syslog frame — to an Audit Record Repository
(ARR). This complements the existing DB `audit_logs` (which is unaffected); ATNA
is the *standard wire format* the 진료정보교류 표준 (고시 2021-171) requires for
cross-institution exchange.

Design:
- Config-gated (`atna_enabled`, default False) — no-op until an ARR endpoint exists.
- Best-effort, fully guarded: a failed/slow emit never breaks the main operation
  (audit emission runs in a thread with a short timeout, all exceptions swallowed).
- Transports: udp (RFC 5426), tcp, tls (RFC 5425). TLS uses the system trust store.

Standards: IHE ITI TF-2 (ATNA), RFC 3881 (audit message), RFC 5424/5425/5426 (syslog).
"""
import asyncio
import logging
import socket
import ssl
from datetime import datetime, timezone
from xml.sax.saxutils import quoteattr

from app.core.config import settings

logger = logging.getLogger(__name__)

# DICOM event code mapping (DCM, PS3.15). Default = Application Activity.
_EVENT_APP_ACTIVITY = ("110100", "Application Activity")
_EVENT_AUTH = ("110114", "User Authentication")
_EVENT_QUERY = ("110112", "Query")
_EVENT_EXPORT = ("110106", "Export")
_EVENT_IMPORT = ("110107", "Import")


def _classify(operation: str) -> tuple[tuple[str, str], str]:
    """Map an operation name to (DICOM EventID, EventActionCode C/R/U/D/E)."""
    op = (operation or "").upper()
    if any(k in op for k in ("LOGIN", "LOGOUT", "AUTH")):
        return _EVENT_AUTH, "E"
    if any(k in op for k in ("EXPORT", "DOWNLOAD")):
        return _EVENT_EXPORT, "R"
    if any(k in op for k in ("IMPORT", "UPLOAD", "STORE")):
        return _EVENT_IMPORT, "C"
    if any(k in op for k in ("QUERY", "SEARCH", "VIEW", "LIST")):
        return _EVENT_QUERY, "R"
    if "DELETE" in op or "REMOVE" in op:
        return _EVENT_APP_ACTIVITY, "D"
    if any(k in op for k in ("CREATE", "REGISTER", "ADD")):
        return _EVENT_APP_ACTIVITY, "C"
    if any(k in op for k in ("UPDATE", "EDIT", "MODIFY", "SIGN", "FINALIZE")):
        return _EVENT_APP_ACTIVITY, "U"
    return _EVENT_APP_ACTIVITY, "E"


def build_audit_message(
    operation: str,
    status: str,
    username: str,
    user_id: str | None = None,
    patient_id: str | None = None,
    source_ip: str | None = None,
    resource_type: str | None = None,
) -> str:
    """Build a DICOM Audit Message (RFC 3881) XML string."""
    (event_code, event_text), action = _classify(operation)
    outcome = "0" if (status or "").upper() in ("SUCCESS", "OK", "") else "4"  # 0=success, 4=minor failure
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    site = settings.atna_enterprise_site_id or ""

    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<AuditMessage>"]
    parts.append(
        f'<EventIdentification EventActionCode="{action}" '
        f'EventDateTime="{now}" EventOutcomeIndicator="{outcome}">'
        f'<EventID csd-code="{event_code}" codeSystemName="DCM" '
        f'originalText={quoteattr(event_text)}/>'
        f'<EventTypeCode csd-code="OP" codeSystemName="OpenPACS" '
        f'originalText={quoteattr(operation or "")}/>'
        f"</EventIdentification>"
    )
    # ActiveParticipant — the human user (requestor)
    net_attr = f' NetworkAccessPointID={quoteattr(source_ip)} NetworkAccessPointTypeCode="2"' if source_ip else ""
    parts.append(
        f'<ActiveParticipant UserID={quoteattr(username or user_id or "unknown")} '
        f'UserIsRequestor="true"{net_attr}>'
        f'<RoleIDCode csd-code="110153" codeSystemName="DCM" originalText="Source"/>'
        f"</ActiveParticipant>"
    )
    # AuditSourceIdentification — this system
    site_attr = f' AuditEnterpriseSiteID={quoteattr(site)}' if site else ""
    parts.append(
        f'<AuditSourceIdentification AuditSourceID={quoteattr(settings.atna_source_id)}{site_attr}/>'
    )
    # ParticipantObject — the patient (type=1 person, role=1 patient)
    if patient_id:
        parts.append(
            f'<ParticipantObjectIdentification ParticipantObjectID={quoteattr(patient_id)} '
            f'ParticipantObjectTypeCode="1" ParticipantObjectTypeCodeRole="1">'
            f'<ParticipantObjectIDTypeCode csd-code="2" codeSystemName="RFC-3881" '
            f'originalText="Patient Number"/>'
            f"</ParticipantObjectIdentification>"
        )
    parts.append("</AuditMessage>")
    return "".join(parts)


def _syslog_frame(message: str) -> bytes:
    """Wrap the audit XML in an RFC 5424 syslog frame. Facility=13(log audit),
    Severity=5(notice) → PRI=109."""
    pri = 13 * 8 + 5
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    host = socket.gethostname()[:255] or "-"
    header = f"<{pri}>1 {ts} {host} {settings.atna_source_id} - IHE+RFC3881 - "
    return (header + message).encode("utf-8")


def _send_sync(payload: bytes) -> None:
    """Blocking send over the configured transport. Caller runs this off-thread."""
    host, port = settings.atna_host, settings.atna_port
    transport = (settings.atna_transport or "udp").lower()
    if transport == "udp":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            s.sendto(payload, (host, port))
        return
    # tcp / tls — RFC 5425 octet-counted framing
    framed = f"{len(payload)} ".encode("utf-8") + payload
    raw = socket.create_connection((host, port), timeout=2.0)
    try:
        sock = raw
        if transport == "tls":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw, server_hostname=host)
        sock.settimeout(2.0)
        sock.sendall(framed)
        sock.close()
    finally:
        try:
            raw.close()
        except Exception:
            pass


async def emit_atna(
    operation: str,
    status: str = "SUCCESS",
    username: str = "",
    user_id: str | None = None,
    patient_id: str | None = None,
    source_ip: str | None = None,
    resource_type: str | None = None,
) -> bool:
    """Emit one ATNA audit message. No-op when disabled; never raises.
    Returns True if sent, False otherwise."""
    if not settings.atna_enabled:
        return False
    try:
        msg = build_audit_message(
            operation, status, username, user_id, patient_id, source_ip, resource_type
        )
        await asyncio.wait_for(asyncio.to_thread(_send_sync, _syslog_frame(msg)), timeout=3.0)
        return True
    except Exception as e:  # audit emission must never break the caller
        logger.warning(f"ATNA emit failed (non-fatal): {e}")
        return False
