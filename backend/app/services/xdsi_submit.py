"""XDS-I.b ITI-41 Provide & Register Imaging Document Set-b (RAD-68) 제출 클라이언트.

v12.2 XDM *export*가 만든 ebRIM METADATA(`xds_metadata`)와 KOS 매니페스트(`kos_service`)를
재사용해, SOAP 1.2 + MTOM/XOP 메시지를 조립하고 Document Repository로 POST한다.

XDM(ZIP에 담기)과의 차이는 **전송 계층뿐** — 동일 ebRIM SubmissionSet/DocumentEntry를
SubmitObjectsRequest로 감싸고 KOS를 MTOM 바이너리로 첨부한다.

- `build_iti41_message(...)` : 순수 함수 — (content_type, body_bytes) 반환. stdlib만 사용
  (ElementTree + 수동 multipart) → deps 없이 단위 검증 가능.
- `submit(...)`             : httpx 비동기 POST + RegistryResponse 파싱.

구조적 최소적합 — IHE Gazelle 인증 아님(v12.2와 동일 톤).
설계: `docs/02-design/xds-i-pix-mpi-phase1.design.md`
"""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from app.services.xds_metadata import (
    RIM_NS,
    DocEntry,
    Submission,
    build_metadata_xml,
)

# 네임스페이스
SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
WSA = "http://www.w3.org/2005/08/addressing"
XDSB = "urn:ihe:iti:xds-b:2007"
LCM = "urn:oasis:names:tc:ebxml-regrep:xsd:lcm:3.0"
XOP = "http://www.w3.org/2004/08/xop/include"

ITI41_ACTION = "urn:ihe:iti:2007:ProvideAndRegisterDocumentSet-b"


def format_affinity_cx(value: str, universal_id: str | None, namespace_id: str = "") -> str:
    """HL7 CX 형식 affinity-domain patient id: value^^^&universal_id&ISO."""
    if universal_id:
        return f"{value}^^^&{universal_id}&ISO"
    return f"{value}^^^{namespace_id}"


def build_iti41_message(
    *,
    kos_bytes: bytes,
    submission: Submission,
    doc: DocEntry,
    message_id: str | None = None,
) -> tuple[str, bytes]:
    """ITI-41 Provide & Register Document Set-b MTOM 메시지 조립.

    Returns (content_type_header, body_bytes) — httpx `content=body, headers={...}`로 POST.
    """
    message_id = message_id or f"urn:uuid:{uuid.uuid4()}"
    content_id = f"{uuid.uuid4()}@openpacs"

    # ── SOAP 엔벨로프(문자열 조립: MTOM 루트 파트는 정확한 바이트가 필요) ──
    ET.register_namespace("soap", SOAP_ENV)
    ET.register_namespace("wsa", WSA)
    ET.register_namespace("xdsb", XDSB)
    ET.register_namespace("lcm", LCM)
    ET.register_namespace("rim", RIM_NS)
    ET.register_namespace("xop", XOP)

    env = ET.Element(f"{{{SOAP_ENV}}}Envelope")
    header = ET.SubElement(env, f"{{{SOAP_ENV}}}Header")
    ET.SubElement(header, f"{{{WSA}}}Action", {"{http://www.w3.org/2003/05/soap-envelope}mustUnderstand": "1"}).text = ITI41_ACTION
    ET.SubElement(header, f"{{{WSA}}}MessageID").text = message_id
    ET.SubElement(header, f"{{{WSA}}}To").text = "urn:xdsb:repository"

    body = ET.SubElement(env, f"{{{SOAP_ENV}}}Body")
    pnr = ET.SubElement(body, f"{{{XDSB}}}ProvideAndRegisterDocumentSetRequest")
    sor = ET.SubElement(pnr, f"{{{LCM}}}SubmitObjectsRequest")

    # 재사용: ebRIM RegistryObjectList (XDM export와 동일) → SubmitObjectsRequest 안에 삽입
    rim_bytes = build_metadata_xml(submission, [doc])
    rim_root = ET.fromstring(rim_bytes)  # <rim:RegistryObjectList>
    sor.append(rim_root)

    # Document(바이너리 첨부 참조) — id는 DocumentEntry의 doc_id와 일치해야 registry가 연결
    document = ET.SubElement(pnr, f"{{{XDSB}}}Document", {"id": doc.doc_id})
    ET.SubElement(document, f"{{{XOP}}}Include", {"href": f"cid:{content_id}"})

    soap_bytes = ET.tostring(env, encoding="utf-8", xml_declaration=True)

    # ── MTOM/XOP multipart/related 수동 조립 ──
    boundary = f"MIMEBoundary_{uuid.uuid4().hex}"
    root_ct = f'application/xop+xml; charset=UTF-8; type="application/soap+xml"'
    parts: list[bytes] = []

    def _part(headers: dict, payload: bytes):
        h = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        parts.append(f"--{boundary}\r\n{h}\r\n".encode("utf-8") + payload + b"\r\n")

    _part(
        {
            "Content-Type": root_ct,
            "Content-Transfer-Encoding": "binary",
            "Content-ID": "<root.message@openpacs>",
        },
        soap_bytes,
    )
    _part(
        {
            "Content-Type": "application/dicom",
            "Content-Transfer-Encoding": "binary",
            "Content-ID": f"<{content_id}>",
        },
        kos_bytes,
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body_bytes = b"".join(parts)

    content_type = (
        f'multipart/related; boundary="{boundary}"; type="application/xop+xml"; '
        f'start="<root.message@openpacs>"; start-info="application/soap+xml"; '
        f'action="{ITI41_ACTION}"'
    )
    return content_type, body_bytes


def parse_registry_response(text: str) -> tuple[bool, str]:
    """RegistryResponse status 파싱 → (success, status_uri).

    ebXML RegistryResponse status: ...:Success | ...:Failure.
    """
    if not text:
        return False, ""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # 관대한 폴백 — 문자열에 Success가 있으면 성공으로 간주(모의 스텁 등)
        return ("Success" in text and "Failure" not in text), text[:200]
    status = root.attrib.get("status", "")
    if not status:
        for el in root.iter():
            if "status" in el.attrib:
                status = el.attrib["status"]
                break
    return status.endswith("Success"), status


async def submit(endpoint: str, content_type: str, body: bytes, *, timeout: float = 30.0) -> tuple[bool, str]:
    """Repository로 ITI-41 메시지 POST. (success, response_text) 반환."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            endpoint,
            content=body,
            headers={"Content-Type": content_type, "SOAPAction": f'"{ITI41_ACTION}"'},
        )
    ok, _status = parse_registry_response(resp.text)
    return (ok and resp.status_code < 400), resp.text
