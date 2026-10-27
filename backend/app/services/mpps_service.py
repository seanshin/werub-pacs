"""MPPS (Modality Performed Procedure Step) — N-CREATE / N-SET logic.

Drives worklist status from modality notifications, completing the worklist
loop started by the MWL SCP:
- N-CREATE ("IN PROGRESS"): mark the scheduled step IN_PROGRESS + record start
  time / performing station, and remember the MPPS SOP Instance UID so the later
  N-SET can be linked back.
- N-SET ("COMPLETED" / "DISCONTINUED"): set the final status + end time.

Matching: N-CREATE links to a worklist item via ScheduledStepAttributesSequence
(AccessionNumber, fallback StudyInstanceUID); N-SET via the stored MPPS UID.
Unmatched notifications are accepted (success) but not linked — never reject the
modality's procedure step over a bookkeeping miss.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.worklist import ProcedureStatus, WorklistItem

logger = logging.getLogger("mpps")

SUCCESS = 0x0000


def _parse_dt(date_str, time_str):
    """DICOM DA (YYYYMMDD) + TM (HHMMSS[.ffffff]) -> aware datetime (UTC)."""
    try:
        d = (str(date_str) or "").strip()
        if not d:
            return None
        t = (str(time_str) or "").strip().split(".")[0]
        t = (t + "000000")[:6]
        return datetime.strptime(d + t, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _sps_attr(ds, key):
    seq = getattr(ds, "ScheduledStepAttributesSequence", None)
    if seq and len(seq) > 0:
        v = getattr(seq[0], key, None)
        return None if v is None else str(v)
    return None


def apply_n_create(db, mpps_sop_uid: str, ds):
    """Handle MPPS N-CREATE. Returns (status_code, item_or_None)."""
    acc = _sps_attr(ds, "AccessionNumber")
    item = None
    if acc:
        item = (
            db.query(WorklistItem)
            .filter(WorklistItem.accession_number == acc)
            .first()
        )
    if item is None:
        suid = _sps_attr(ds, "StudyInstanceUID")
        if suid:
            item = (
                db.query(WorklistItem)
                .filter(WorklistItem.study_instance_uid == suid)
                .first()
            )
    if item is None:
        logger.warning("MPPS N-CREATE: no worklist match (acc=%s) — accepted, unlinked", acc)
        return SUCCESS, None

    item.status = ProcedureStatus.IN_PROGRESS
    item.performed_start_time = _parse_dt(
        getattr(ds, "PerformedProcedureStepStartDate", ""),
        getattr(ds, "PerformedProcedureStepStartTime", ""),
    ) or datetime.now(timezone.utc)
    station = str(getattr(ds, "PerformedStationAETitle", "") or item.scheduled_station_ae_title or "")
    item.performed_station_ae_title = station[:16]
    item.mpps_sop_instance_uid = mpps_sop_uid
    db.commit()
    logger.info("MPPS N-CREATE: %s -> IN_PROGRESS (mpps=%s)", item.accession_number, mpps_sop_uid)
    return SUCCESS, item


def apply_n_set(db, mpps_sop_uid: str, ds):
    """Handle MPPS N-SET. Returns status_code."""
    item = (
        db.query(WorklistItem)
        .filter(WorklistItem.mpps_sop_instance_uid == mpps_sop_uid)
        .first()
    )
    if item is None:
        logger.warning("MPPS N-SET: no item for mpps=%s — accepted, no update", mpps_sop_uid)
        return SUCCESS

    st = str(getattr(ds, "PerformedProcedureStepStatus", "") or "").upper()
    if "DISCONTINUED" in st:
        item.status = ProcedureStatus.DISCONTINUED
    elif "COMPLETED" in st:
        item.status = ProcedureStatus.COMPLETED
    # "IN PROGRESS" N-SET (series updates) leaves status unchanged.

    end = _parse_dt(
        getattr(ds, "PerformedProcedureStepEndDate", ""),
        getattr(ds, "PerformedProcedureStepEndTime", ""),
    )
    if item.status in (ProcedureStatus.COMPLETED, ProcedureStatus.DISCONTINUED):
        item.performed_end_time = end or datetime.now(timezone.utc)
    db.commit()
    logger.info("MPPS N-SET: %s -> %s", item.accession_number, getattr(item.status, "value", item.status))
    return SUCCESS
