"""Standalone Modality Worklist (MWL) SCP — pynetdicom.

Answers Modality Worklist C-FIND (SOP 1.2.840.10008.5.1.4.31) directly from the
`worklist_items` table — no Orthanc worklist plugin required. Runs as its own
container/process on a dedicated DICOM port (separate from Orthanc's store port).
Modalities point their MWL query at this AE to auto-populate patient/study info,
preventing the manual-entry errors that the validation engine catches after.

Reuses `mwl_service.build_worklist_dataset` for the response dataset.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind,
    StorageCommitmentPushModel,
)

from app.core.config import settings
from app.models.worklist import ProcedureStatus, WorklistItem
from app.services import mpps_service, storage_commitment_service
from app.services.mwl_service import build_worklist_dataset
from app.services.storage_commitment_service import STORAGE_COMMITMENT_INSTANCE_UID

logger = logging.getLogger("mwl_scp")

AE_TITLE = os.environ.get("MWL_AE_TITLE", "OPENPACS-MWL")
MWL_PORT = int(os.environ.get("MWL_PORT", "4243"))
MWL_BIND = os.environ.get("MWL_BIND", "127.0.0.1")

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


def _qval(ds, key) -> str:
    v = getattr(ds, key, None)
    return "" if v is None else str(v)


def _matches(item, q) -> bool:
    """Common MWL C-FIND matching keys. Empty query value = universal match."""
    pid = _qval(q, "PatientID")
    if pid and pid != (item.patient_id or ""):
        return False
    acc = _qval(q, "AccessionNumber")
    if acc and acc != (item.accession_number or ""):
        return False

    sps_seq = getattr(q, "ScheduledProcedureStepSequence", None)
    if sps_seq and len(sps_seq) > 0:
        sps = sps_seq[0]
        mod = _qval(sps, "Modality")
        if mod and mod != (item.modality or ""):
            return False
        aet = _qval(sps, "ScheduledStationAETitle")
        if aet and aet != (item.scheduled_station_ae_title or ""):
            return False
        d = _qval(sps, "ScheduledProcedureStepStartDate")
        if d:
            item_d = item.scheduled_date.strftime("%Y%m%d") if item.scheduled_date else ""
            if "-" in d:  # date range YYYYMMDD-YYYYMMDD
                parts = (d.split("-") + [""])[:2]
                lo, hi = parts[0], parts[1]
                if lo and item_d < lo:
                    return False
                if hi and item_d > hi:
                    return False
            elif d != item_d:
                return False
    return True


def handle_find(event):
    """C-FIND handler — yields (status, dataset) for each matching scheduled item."""
    try:
        query = event.identifier
    except Exception as e:  # malformed identifier
        logger.warning("MWL C-FIND: bad identifier: %s", e)
        yield 0xC000, None
        return

    db = _session()
    matches = 0
    try:
        items = (
            db.query(WorklistItem)
            .filter(WorklistItem.status == ProcedureStatus.SCHEDULED)
            .all()
        )
        for item in items:
            if event.is_cancelled:
                yield 0xFE00, None  # Sub-operations terminated due to Cancel
                return
            try:
                if _matches(item, query):
                    yield 0xFF00, build_worklist_dataset(item)  # Pending + match
                    matches += 1
            except Exception as e:
                logger.warning("MWL build/match error for item: %s", e)
        try:
            who = event.assoc.requestor.ae_title
        except Exception:
            who = "?"
        logger.info("MWL C-FIND from %s -> %d matches", who, matches)
    finally:
        db.close()


def handle_n_create(event):
    """MPPS N-CREATE — modality reports a procedure step started (IN PROGRESS)."""
    db = _session()
    try:
        ds = event.attribute_list
        uid = str(event.request.AffectedSOPInstanceUID)
        status, _ = mpps_service.apply_n_create(db, uid, ds)
        return status, ds
    except Exception as e:
        logger.error("MPPS N-CREATE error: %s", e)
        return 0x0110, None  # Processing failure
    finally:
        db.close()


def handle_n_set(event):
    """MPPS N-SET — modality reports the step COMPLETED / DISCONTINUED."""
    db = _session()
    try:
        ds = event.attribute_list
        uid = str(event.request.RequestedSOPInstanceUID)
        status = mpps_service.apply_n_set(db, uid, ds)
        return status, ds
    except Exception as e:
        logger.error("MPPS N-SET error: %s", e)
        return 0x0110, None
    finally:
        db.close()


def _send_commitment_report(assoc, event_type, report):
    """Send the Storage Commitment N-EVENT-REPORT back on the same association,
    after the N-ACTION response has gone out."""
    time.sleep(0.3)
    try:
        assoc.send_n_event_report(
            report, event_type, StorageCommitmentPushModel, STORAGE_COMMITMENT_INSTANCE_UID
        )
        logger.info("Storage Commitment N-EVENT-REPORT sent (event_type=%d)", event_type)
    except Exception as e:
        logger.error("Storage Commitment N-EVENT-REPORT failed: %s", e)


def handle_n_action(event):
    """Storage Commitment N-ACTION — modality requests commitment of SOP instances."""
    try:
        req = event.action_information
        txn = str(getattr(req, "TransactionUID", "") or "")
        committed, failed = storage_commitment_service.check_instances(
            getattr(req, "ReferencedSOPSequence", None)
        )
        event_type, report = storage_commitment_service.build_event_report(txn, committed, failed)
        threading.Thread(
            target=_send_commitment_report,
            args=(event.assoc, event_type, report),
            daemon=True,
        ).start()
        return 0x0000, None  # N-ACTION accepted; result follows via N-EVENT-REPORT
    except Exception as e:
        logger.error("Storage Commitment N-ACTION error: %s", e)
        return 0x0110, None


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    ae = AE(ae_title=AE_TITLE)
    ae.add_supported_context(ModalityWorklistInformationFind)
    ae.add_supported_context(ModalityPerformedProcedureStep)
    # SCP receives N-ACTION and sends N-EVENT-REPORT back (role reversal) on the
    # same association, so negotiate both roles.
    ae.add_supported_context(StorageCommitmentPushModel, scu_role=True, scp_role=True)
    handlers = [
        (evt.EVT_C_FIND, handle_find),
        (evt.EVT_N_CREATE, handle_n_create),
        (evt.EVT_N_SET, handle_n_set),
        (evt.EVT_N_ACTION, handle_n_action),
    ]
    logger.info(
        "MWL+MPPS+StgCmt SCP listening: AE=%s on %s:%d "
        "(C-FIND worklist, N-CREATE/N-SET MPPS, N-ACTION Storage Commitment)",
        AE_TITLE, MWL_BIND, MWL_PORT,
    )
    ae.start_server((MWL_BIND, MWL_PORT), evt_handlers=handlers)


if __name__ == "__main__":
    main()
