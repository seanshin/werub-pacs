"""Storage Commitment Push Model — N-ACTION processing + N-EVENT-REPORT build.

Completes the DIMSE workflow standards (MWL + MPPS + Storage Commitment). A
modality asks the PACS to confirm a set of SOP instances are safely stored
(N-ACTION); we check each against Orthanc and report back which are committed and
which failed (N-EVENT-REPORT).

SOP Class:        Storage Commitment Push Model  1.2.840.10008.1.20.1
Well-known inst:  1.2.840.10008.1.20.1.1
"""
from __future__ import annotations

import logging
import os

import httpx
from pydicom.dataset import Dataset

logger = logging.getLogger("storage_commitment")

STORAGE_COMMITMENT_INSTANCE_UID = "1.2.840.10008.1.20.1.1"

# DICOM failure reason: No Such Object Instance
FAILURE_NO_SUCH_INSTANCE = 0x0112

# Read from env directly (this module runs inside the standalone mwl-scp DIMSE
# process, which has no DATABASE_URL, so it can't import the settings singleton).
# No hardcoded secret default — ORTHANC_PASSWORD must come from the environment.
_ORTHANC_URL = os.environ.get("ORTHANC_URL", "http://127.0.0.1:8042")
_ORTHANC_USER = os.environ.get("ORTHANC_USERNAME", "admin")
_ORTHANC_PASS = os.environ.get("ORTHANC_PASSWORD", "")


def _exists_in_orthanc(sop_instance_uid: str) -> bool:
    """True if the SOP Instance UID is present in Orthanc."""
    try:
        with httpx.Client(timeout=8) as c:
            r = c.post(
                f"{_ORTHANC_URL}/tools/lookup",
                content=sop_instance_uid,
                auth=(_ORTHANC_USER, _ORTHANC_PASS),
            )
            if r.status_code != 200:
                return False
            for hit in r.json():
                if hit.get("Type") == "Instance":
                    return True
            return False
    except Exception as e:
        logger.warning("Orthanc lookup failed for %s: %s", sop_instance_uid, e)
        return False


def check_instances(referenced_sop_seq):
    """Split the referenced instances into (committed, failed) lists of
    (sop_class_uid, sop_instance_uid)."""
    committed, failed = [], []
    for item in referenced_sop_seq or []:
        sc = str(getattr(item, "ReferencedSOPClassUID", "") or "")
        si = str(getattr(item, "ReferencedSOPInstanceUID", "") or "")
        if si and _exists_in_orthanc(si):
            committed.append((sc, si))
        else:
            failed.append((sc, si))
    return committed, failed


def build_event_report(transaction_uid: str, committed, failed):
    """Return (event_type_id, dataset). event_type 1 = all committed, 2 = some failed."""
    report = Dataset()
    report.TransactionUID = transaction_uid

    ref_seq = []
    for sc, si in committed:
        d = Dataset()
        d.ReferencedSOPClassUID = sc
        d.ReferencedSOPInstanceUID = si
        ref_seq.append(d)
    if ref_seq:
        report.ReferencedSOPSequence = ref_seq

    if failed:
        fseq = []
        for sc, si in failed:
            d = Dataset()
            d.ReferencedSOPClassUID = sc
            d.ReferencedSOPInstanceUID = si
            d.FailureReason = FAILURE_NO_SUCH_INSTANCE
            fseq.append(d)
        report.FailedSOPSequence = fseq

    event_type = 2 if failed else 1
    logger.info(
        "Storage Commitment: txn=%s committed=%d failed=%d (event_type=%d)",
        transaction_uid, len(committed), len(failed), event_type,
    )
    return event_type, report
