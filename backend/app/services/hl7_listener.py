"""HL7 v2 MLLP listener.

Standalone TCP service (MLLP framing) that receives inbound HL7 v2 messages and
routes them: ORM imaging orders -> worklist_items (then served via MWL), ADT ->
accepted (patient upsert is future work). Replies with an HL7 ACK. Runs as its
own container, mirroring the mwl-scp pattern.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading

from app.core.config import settings
from app.models.worklist import ProcedureStatus, WorklistItem
from app.services import hl7_service

logger = logging.getLogger("hl7_listener")

HL7_BIND = os.environ.get("HL7_BIND", "127.0.0.1")
HL7_PORT = int(os.environ.get("HL7_PORT", "2575"))

# 무인증 MLLP가 worklist를 변조하는 표면 축소용 opt-in 게이트 2종 (비우면 종전 동작).
# HL7_ALLOWED_PEERS: 접속 허용 소스 IP/CIDR 목록(콤마) — accept 시점 차단.
# HL7_ALLOWED_FACILITIES: MSH-3(송신 앱)/MSH-4(송신 기관) 허용 목록(콤마) — AR ACK 거부.
_ALLOWED_PEERS = [
    ipaddress.ip_network(p.strip(), strict=False)
    for p in os.environ.get("HL7_ALLOWED_PEERS", "").split(",")
    if p.strip()
]
_ALLOWED_FACILITIES = {
    f.strip().upper()
    for f in os.environ.get("HL7_ALLOWED_FACILITIES", "").split(",")
    if f.strip()
}


def _peer_allowed(peer_ip: str) -> bool:
    if not _ALLOWED_PEERS:
        return True
    try:
        ip = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(ip in net for net in _ALLOWED_PEERS)


def _sender_allowed(msg) -> bool:
    if not _ALLOWED_FACILITIES:
        return True
    sending_app = hl7_service._comp(msg, "MSH", 3, 1).upper()
    sending_fac = hl7_service._comp(msg, "MSH", 4, 1).upper()
    return sending_app in _ALLOWED_FACILITIES or sending_fac in _ALLOWED_FACILITIES

VT, FS, CR = b"\x0b", b"\x1c", b"\x0d"

_engine = None


def _session():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        url = settings.database_url.replace("+asyncpg", "")
        if "postgresql://" in url and "+psycopg2" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg2://")
        _engine = create_engine(url, pool_size=1, max_overflow=2, pool_pre_ping=True)
    from sqlalchemy.orm import Session
    return Session(_engine)


# ORC-1 취소 계열 오더 컨트롤 (HL7 Table 0119)
_CANCEL_CONTROLS = {"CA", "OC", "DC", "CR"}  # Cancel/Order-cancelled/Discontinue/Cancelled-as-requested
# CANCELLED 항목 재활성은 명시적 신규/변경 오더만 — 그 외 컨트롤(빈값 포함)의 재전송/리플레이가
# 취소를 되돌리지 못하게 함.
_REACTIVATE_CONTROLS = {"NW", "XO"}  # New order / Change order


def _handle_orm(msg) -> str:
    order_control = hl7_service._comp(msg, "ORC", 1, 1).upper()
    data = hl7_service.orm_to_worklist(msg)
    db = _session()
    try:
        existing = (
            db.query(WorklistItem)
            .filter(WorklistItem.accession_number == data["accession_number"])
            .first()
        )
        # 취소 오더(ORC-1=CA 등) → 워크리스트 항목을 CANCELLED로 (삭제 아님, 감사 보존).
        # 스캐너 MWL 서빙(.wl)이 배선되면 status=SCHEDULED만 서빙하므로 취소분은 자동 제외.
        if order_control in _CANCEL_CONTROLS:
            if existing is None:
                action = "cancel-noop(항목 없음)"
            elif existing.status == ProcedureStatus.SCHEDULED:
                existing.status = ProcedureStatus.CANCELLED
                db.commit()
                action = "cancelled"
            elif existing.status == ProcedureStatus.CANCELLED:
                action = "cancel-noop(이미 취소)"
            else:
                # 수행 중/완료된 검사의 늦은 취소 — 수행 상태(MPPS)를 덮어쓰지 않음(BI 집계 보존)
                action = f"cancel-ignored(status={existing.status.name})"
            logger.info("HL7 ORM cancel(%s) -> %s: %s", order_control, action, data["accession_number"])
            return hl7_service.build_ack(msg, "AA")

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            if existing.status == ProcedureStatus.CANCELLED:
                if order_control in _REACTIVATE_CONTROLS:
                    existing.status = ProcedureStatus.SCHEDULED
                    action = "updated+reactivated"
                else:
                    action = "updated(취소 유지, ORC-1=%s)" % (order_control or "-")
            else:
                action = "updated"
        else:
            db.add(WorklistItem(status=ProcedureStatus.SCHEDULED, **data))
            action = "created"
        db.commit()
        logger.info(
            "HL7 ORM -> worklist %s: %s (%s)", action, data["accession_number"], data["modality"]
        )
        return hl7_service.build_ack(msg, "AA")
    except Exception as e:
        db.rollback()
        logger.error("HL7 ORM handling error: %s", e)
        return hl7_service.build_ack(msg, "AE", str(e)[:80])
    finally:
        db.close()


def handle_message(raw: str) -> str:
    try:
        msg = hl7_service.parse(raw)
    except Exception as e:
        logger.warning("HL7 parse error: %s", e)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"MSH|^~\\&|OPENPACS|WERUB|||{ts}||ACK||P|2.3\rMSA|AR||parse error\r"

    if not _sender_allowed(msg):
        logger.warning(
            "HL7 message rejected (sender not allowed): app=%s fac=%s",
            hl7_service._comp(msg, "MSH", 3, 1), hl7_service._comp(msg, "MSH", 4, 1),
        )
        return hl7_service.build_ack(msg, "AR", "sender not allowed")

    mtype = hl7_service.message_type(msg)
    if mtype in ("ORM", "OMG", "OMI"):
        return _handle_orm(msg)
    # IHE PIX v2 (Step 5): ITI-9 Query(QBP) / ITI-8 Feed(ADT feed/merge)
    if mtype == "QBP":
        from app.services import pix_hl7
        return _pix(pix_hl7.handle_qbp, msg)
    if mtype == "ADT":
        from app.services import pix_hl7
        trig = hl7_service._comp(msg, "MSH", 9, 2).upper()
        if trig in pix_hl7.FEED_TRIGGERS:
            return _pix(pix_hl7.handle_adt_feed, msg)
        if trig in pix_hl7.MERGE_TRIGGERS:
            return _pix(pix_hl7.handle_adt_merge, msg)
    logger.info("HL7 %s received (accepted, no-op)", mtype or "?")
    return hl7_service.build_ack(msg, "AA")


def _pix(handler, msg) -> str:
    """PIX 핸들러를 동기 세션과 함께 실행(에러 시 AE ACK)."""
    db = _session()
    try:
        return handler(msg, db)
    except Exception as e:
        db.rollback()
        logger.error("PIX handling error: %s", e)
        return hl7_service.build_ack(msg, "AE", str(e)[:80])
    finally:
        db.close()


def _handle_conn(conn):
    buf = b""
    try:
        while True:
            data = conn.recv(8192)
            if not data:
                break
            buf += data
            while VT in buf:
                start = buf.index(VT)
                fs_at = buf.find(FS, start)
                if fs_at == -1:
                    break  # message not fully received yet
                raw = buf[start + 1:fs_at].decode("utf-8", errors="replace")
                consume_to = fs_at + 1
                if buf[consume_to:consume_to + 1] == CR:
                    consume_to += 1
                buf = buf[consume_to:]
                resp = handle_message(raw)
                conn.sendall(VT + resp.encode("utf-8") + FS + CR)
    except Exception as e:
        logger.warning("HL7 connection error: %s", e)
    finally:
        conn.close()


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HL7_BIND, HL7_PORT))
    s.listen(5)
    logger.info(
        "HL7 MLLP listener: %s:%d (inbound ORM->worklist, ADT accepted)", HL7_BIND, HL7_PORT
    )
    if _ALLOWED_PEERS:
        logger.info("HL7 peer allowlist active: %s", [str(n) for n in _ALLOWED_PEERS])
    if _ALLOWED_FACILITIES:
        logger.info("HL7 sender allowlist active: %s", sorted(_ALLOWED_FACILITIES))
    while True:
        conn, addr = s.accept()
        if not _peer_allowed(addr[0]):
            logger.warning("HL7 connection rejected (peer not allowed): %s", addr[0])
            conn.close()
            continue
        threading.Thread(target=_handle_conn, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
