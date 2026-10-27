"""IHE PIX v2 (HL7 v2) — ITI-9 Query + ITI-8 Feed. (v2.0 트랙A Step 5)

Step 2의 PIXm(FHIR)를 HL7 v2로 미러 — v2-only 상대 도메인 대비. 우리가 **PIX Manager** 역할:
MPI(identity_domains/mpi_patients/patient_identifiers)를 조회·갱신한다.

- **ITI-9 PIX Query** (QBP^Q23^QBP_Q21 → RSP^K23^RSP_K21): 소스 도메인 식별자 → 교차참조 식별자.
- **ITI-8 PIX Feed** (ADT^A01/A04/A08/A28/A31): 도메인별 식별자 upsert(교차참조 등록).
  ADT^A40(merge): prior enterprise를 survivor로 병합.

hl7_listener(동기 python-hl7 프로세스)에서 호출 — sync 세션으로 raw SQL 접근.
설계: `docs/02-design/xds-i-pix-mpi-phase1.design.md` §2.3.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import text

from app.services import hl7_service

logger = logging.getLogger("pix_hl7")

FEED_TRIGGERS = {"A01", "A04", "A05", "A08", "A28", "A31"}
MERGE_TRIGGERS = {"A40"}


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _parse_cx(cx: str) -> tuple[str, str, str]:
    """CX 문자열 → (id, namespace_id, universal_id). 형식 ID^^^NS&OID&ISO 또는 ID^^^&OID&ISO."""
    parts = cx.split("^")
    ident = parts[0].strip() if parts else ""
    aa = parts[3] if len(parts) > 3 else ""
    ns, oid = "", ""
    if aa:
        sub = aa.split("&")
        ns = sub[0].strip() if sub else ""
        oid = sub[1].strip() if len(sub) > 1 else ""
    return ident, ns, oid


def _format_cx(ident: str, namespace_id: str | None, universal_id: str | None) -> str:
    if universal_id:
        return f"{ident}^^^{namespace_id or ''}&{universal_id}&ISO"
    return f"{ident}^^^{namespace_id or ''}"


def _resolve_domain(db, namespace_id: str, universal_id: str):
    row = db.execute(text(
        "SELECT id FROM identity_domains WHERE (:oid <> '' AND universal_id = :oid) "
        "OR (:ns <> '' AND namespace_id = :ns) LIMIT 1"
    ), {"oid": universal_id or "", "ns": namespace_id or ""}).first()
    return row[0] if row else None


def _parse_requested_domains(qpd4: str) -> list[tuple[str, str]]:
    """QPD-4(What Domains Returned) → [(namespace_id, universal_id)]. 빈 값이면 전체."""
    out = []
    for rep in (qpd4 or "").split("~"):
        rep = rep.strip()
        if not rep:
            continue
        _ident, ns, oid = _parse_cx(rep)
        if ns or oid:
            out.append((ns, oid))
    return out


# ─────────────────────────── ITI-9 PIX Query ───────────────────────────
def handle_qbp(msg, db) -> str:
    """QBP^Q23 → RSP^K23. 소스 식별자의 교차참조 식별자를 PID-3 반복으로 반환."""
    sending, sfac = hl7_service._comp(msg, "MSH", 3, 1), hl7_service._comp(msg, "MSH", 4, 1)
    ctrl = hl7_service._comp(msg, "MSH", 10, 1)
    query_tag = hl7_service._comp(msg, "QPD", 2, 1)
    src_cx = hl7_service._field(msg, "QPD", 3)
    qpd4 = hl7_service._field(msg, "QPD", 4)
    ident, ns, oid = _parse_cx(src_cx)
    ts = _ts()

    def _rsp(msa: str, qak: str, pid_line: str = "") -> str:
        return (
            f"MSH|^~\\&|OPENPACS|WERUB|{sending}|{sfac}|{ts}||RSP^K23^RSP_K21|{ctrl}|P|2.5\r"
            f"MSA|{msa}|{ctrl}\r"
            f"QAK|{query_tag}|{qak}|IHE PIX Query\r"
            f"QPD|IHE PIX Query|{query_tag}|{src_cx}\r"
            + pid_line
        )

    domain_id = _resolve_domain(db, ns, oid)
    if not domain_id:
        return _rsp("AE", "AE")  # unknown source domain
    src = db.execute(text(
        "SELECT enterprise_id FROM patient_identifiers WHERE domain_id = :d AND identifier = :i LIMIT 1"
    ), {"d": domain_id, "i": ident}).first()
    if not src:
        return _rsp("AA", "NF")  # no data found (ITI-9: 200-equiv, empty)
    ent = src[0]
    rows = db.execute(text(
        "SELECT pi.identifier, d.namespace_id, d.universal_id "
        "FROM patient_identifiers pi JOIN identity_domains d ON pi.domain_id = d.id "
        "WHERE pi.enterprise_id = :e AND NOT (pi.domain_id = :d AND pi.identifier = :i)"
    ), {"e": ent, "d": domain_id, "i": ident}).all()

    requested = _parse_requested_domains(qpd4)
    cxs = []
    for r_ident, r_ns, r_oid in rows:
        if requested and not any(
            (ro and ro == (r_oid or "")) or (rn and rn == (r_ns or "")) for rn, ro in requested
        ):
            continue
        cxs.append(_format_cx(r_ident, r_ns, r_oid))
    if not cxs:
        return _rsp("AA", "NF")
    return _rsp("AA", "OK", f"PID|1||{'~'.join(cxs)}\r")


# ─────────────────────────── ITI-8 PIX Feed ───────────────────────────
def handle_adt_feed(msg, db) -> str:
    """ADT(A04/A08/…) → PID-3 식별자들을 하나의 엔터프라이즈 환자로 교차참조 등록(멱등)."""
    pid3 = hl7_service._field(msg, "PID", 3)
    name = hl7_service._field(msg, "PID", 5).split("~")[0]
    sex = hl7_service._comp(msg, "PID", 8, 1)[:2]
    birth = hl7_service._comp(msg, "PID", 7, 1)

    parsed = []
    for cx in pid3.split("~"):
        cx = cx.strip()
        if not cx:
            continue
        ident, ns, oid = _parse_cx(cx)
        if not ident:
            continue
        did = _resolve_domain(db, ns, oid)
        if did:
            parsed.append((did, ident))
    if not parsed:
        return hl7_service.build_ack(msg, "AE", "no known identity domain in PID-3")

    # 기존 엔터프라이즈 탐색(임의 식별자 매칭)
    ent = None
    for did, ident in parsed:
        row = db.execute(text(
            "SELECT enterprise_id FROM patient_identifiers WHERE domain_id = :d AND identifier = :i LIMIT 1"
        ), {"d": did, "i": ident}).first()
        if row:
            ent = row[0]
            break
    if ent is None:
        demo = {"name": name, "sex": sex, "birth_date": birth}
        ent = db.execute(text(
            "INSERT INTO mpi_patients (created_from, demographics) VALUES ('feed', CAST(:d AS jsonb)) RETURNING id"
        ), {"d": json.dumps(demo)}).first()[0]

    for did, ident in parsed:
        db.execute(text(
            "INSERT INTO patient_identifiers (enterprise_id, domain_id, identifier) "
            "VALUES (:e, :d, :i) ON CONFLICT (domain_id, identifier) DO NOTHING"
        ), {"e": ent, "d": did, "i": ident})
    db.commit()
    logger.info("PIX feed: enterprise=%s identifiers=%d", ent, len(parsed))
    return hl7_service.build_ack(msg, "AA")


def handle_adt_merge(msg, db) -> str:
    """ADT^A40 → MRG-1(prior) 엔터프라이즈를 PID-3(survivor)로 병합."""
    surv_cx = hl7_service._field(msg, "PID", 3).split("~")[0]
    prior_cx = hl7_service._field(msg, "MRG", 1).split("~")[0]
    s_id, s_ns, s_oid = _parse_cx(surv_cx)
    p_id, p_ns, p_oid = _parse_cx(prior_cx)
    s_dom = _resolve_domain(db, s_ns, s_oid)
    p_dom = _resolve_domain(db, p_ns, p_oid)
    if not s_dom or not p_dom:
        return hl7_service.build_ack(msg, "AE", "unknown domain in merge")
    surv = db.execute(text(
        "SELECT enterprise_id FROM patient_identifiers WHERE domain_id=:d AND identifier=:i LIMIT 1"
    ), {"d": s_dom, "i": s_id}).first()
    prior = db.execute(text(
        "SELECT enterprise_id FROM patient_identifiers WHERE domain_id=:d AND identifier=:i LIMIT 1"
    ), {"d": p_dom, "i": p_id}).first()
    if not surv or not prior:
        return hl7_service.build_ack(msg, "AE", "merge patient not found")
    surv_ent, prior_ent = surv[0], prior[0]
    if surv_ent != prior_ent:
        # prior의 식별자를 survivor로 재지정(충돌 시 제거), prior 엔터프라이즈 삭제
        db.execute(text(
            "UPDATE patient_identifiers SET enterprise_id=:s WHERE enterprise_id=:p "
            "AND NOT EXISTS (SELECT 1 FROM patient_identifiers x WHERE x.enterprise_id=:s "
            "AND x.domain_id=patient_identifiers.domain_id AND x.identifier=patient_identifiers.identifier)"
        ), {"s": surv_ent, "p": prior_ent})
        db.execute(text("DELETE FROM patient_identifiers WHERE enterprise_id=:p"), {"p": prior_ent})
        db.execute(text("DELETE FROM mpi_patients WHERE id=:p"), {"p": prior_ent})
    db.commit()
    logger.info("PIX merge: %s <- %s", surv_ent, prior_ent)
    return hl7_service.build_ack(msg, "AA")
