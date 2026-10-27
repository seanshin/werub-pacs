"""HL7 v2 parsing, mapping and message construction.

Lenient parsing (python-hl7) of inbound HL7 v2 messages and mapping to the PACS
worklist, plus ACK and outbound ORU construction. Pairs with the DIMSE workflow
standards (MWL/MPPS) to complete the RIS loop: HL7 ORM -> worklist_items -> MWL.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time

import hl7

logger = logging.getLogger("hl7")


def parse(raw: str):
    """Parse an HL7 v2 message string (CR-delimited). Lenient."""
    return hl7.parse(raw.replace("\n", "\r"))


def _field(msg, seg: str, fnum: int) -> str:
    try:
        return str(msg.segment(seg)[fnum])
    except Exception:
        return ""


def _comp(msg, seg: str, fnum: int, cnum: int = 1) -> str:
    """Field component, first repetition. 1-based field/component indices."""
    raw = _field(msg, seg, fnum)
    if not raw:
        return ""
    rep = raw.split("~")[0]
    parts = rep.split("^")
    return parts[cnum - 1] if len(parts) >= cnum else ""


def message_type(msg) -> str:
    """MSH-9 message type, e.g. 'ORM^O01' -> 'ORM'."""
    return _comp(msg, "MSH", 9, 1).upper()


def _parse_hl7_date(s: str):
    s = (s or "").strip()
    if len(s) >= 8:
        try:
            return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        except Exception:
            return None
    return None


def _parse_hl7_time(s: str):
    s = (s or "").strip()
    if len(s) >= 12:
        try:
            return time(int(s[8:10]), int(s[10:12]), int(s[12:14]) if len(s) >= 14 else 0)
        except Exception:
            return None
    return None


def orm_to_worklist(msg) -> dict:
    """Map an ORM/OMG/OMI imaging order to WorklistItem fields.

    PID·accession은 **edge 공백만 trim**(컷오버 ② 정합 정책, 2026-07-14 LIS 합의) —
    Orthanc PatientID 매칭이 후행공백에 엄격해 사고성 공백이 미매칭을 유발.
    선행0·하이픈·내부 공백은 보존(불투명 문자열).
    """
    pid = _comp(msg, "PID", 3, 1).strip()
    name = _field(msg, "PID", 5).split("~")[0]  # XPN ~ DICOM PN (Family^Given)
    birth = _parse_hl7_date(_comp(msg, "PID", 7, 1))
    sex = _comp(msg, "PID", 8, 1)[:2]

    accession = (_comp(msg, "OBR", 3, 1) or _comp(msg, "ORC", 3, 1) or _comp(msg, "ORC", 2, 1)).strip()
    proc_id = _comp(msg, "OBR", 4, 1) or accession
    proc_desc = _comp(msg, "OBR", 4, 2) or _comp(msg, "OBR", 4, 1)
    modality = (_comp(msg, "OBR", 24, 1) or "OT").upper()[:16]
    referring = _field(msg, "OBR", 16).split("~")[0] or _field(msg, "ORC", 12).split("~")[0]

    when = _comp(msg, "OBR", 27, 4) or _comp(msg, "OBR", 7, 1) or _comp(msg, "OBR", 6, 1)
    sched_date = _parse_hl7_date(when) or date.today()
    sched_time = _parse_hl7_time(when)

    return {
        "patient_id": pid or "UNKNOWN",
        "patient_name": name or "UNKNOWN",
        "patient_birth_date": birth,
        "patient_sex": sex or None,
        "accession_number": accession or f"HL7-{datetime.now():%Y%m%d%H%M%S}",
        "requested_procedure_id": proc_id or "1",
        "requested_procedure_description": proc_desc or None,
        "referring_physician": referring or None,
        "scheduled_station_ae_title": (modality or "ANY")[:16],
        "modality": modality,
        "scheduled_date": sched_date,
        "scheduled_time": sched_time,
        "scheduled_procedure_step_description": proc_desc or None,
    }


def build_ack(msg, code: str = "AA", text: str = "") -> str:
    """Build an HL7 ACK echoing the inbound message's control id."""
    sending, sfac = _comp(msg, "MSH", 3, 1), _comp(msg, "MSH", 4, 1)
    recv, rfac = _comp(msg, "MSH", 5, 1), _comp(msg, "MSH", 6, 1)
    ctrl = _comp(msg, "MSH", 10, 1)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return (
        f"MSH|^~\\&|{recv}|{rfac}|{sending}|{sfac}|{ts}||ACK|{ctrl}|P|2.3\r"
        f"MSA|{code}|{ctrl}|{text}\r"
    )


def _hl7_escape(s: str) -> str:
    """K7: HL7 v2 이스케이프 — 판독문 특수문자(측정값 12.3^cm 등)가 필드 구분자와 충돌해
    세그먼트가 깨지는 것 방지. 이스케이프 문자 `\\` 먼저 처리 후 나머지. 줄바꿈은 `\\.br\\`."""
    if not s:
        return ""
    s = s.replace("\\", "\\E\\")
    s = (s.replace("|", "\\F\\").replace("^", "\\S\\")
          .replace("~", "\\R\\").replace("&", "\\T\\"))
    return s.replace("\r\n", "\\.br\\").replace("\n", "\\.br\\").replace("\r", "\\.br\\")


def build_oru(*, patient_id, patient_name, accession, study_desc, findings, impression,
              sending_app="OPENPACS", sending_fac="WERUB", receiving_app="HIS",
              receiving_fac="HOSPITAL") -> str:
    """Build an outbound ORU^R01 carrying the radiology report."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    ctrl = f"OPENPACS{ts}"
    text = _hl7_escape(findings or "")
    if impression:
        text += "\\.br\\" + _hl7_escape(impression or "")
    return (
        f"MSH|^~\\&|{sending_app}|{sending_fac}|{receiving_app}|{receiving_fac}|{ts}||ORU^R01|{ctrl}|P|2.3\r"
        f"PID|1||{patient_id}||{patient_name}\r"
        f"OBR|1||{accession}|{study_desc}||{ts}|{ts}\r"
        f"OBX|1|FT|REPORT||{text}||||||F\r"
    )
