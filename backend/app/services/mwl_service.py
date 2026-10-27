"""Modality Worklist (MWL) file generation.

Bridges scheduled `WorklistItem` rows to Orthanc's worklist plugin by writing
DICOM worklist files (.wl) that the plugin serves over Modality Worklist C-FIND
(SOP Class 1.2.840.10008.5.1.4.31). Modalities query these to auto-populate
patient/study info at the console — preventing the manual-entry errors that the
non-standard validation engine otherwise has to catch after the fact.

The .wl file is a DICOM dataset (no pixel data) carrying the MWL attributes,
including a Scheduled Procedure Step Sequence. UTF-8 (ISO_IR 192) is used so
Korean patient names round-trip correctly.
"""
from __future__ import annotations

import io
from datetime import date, time

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

# Modality Worklist Information Model — FIND
_MWL_SOP_CLASS = "1.2.840.10008.5.1.4.31"

# Priority enum (lowercase) -> DICOM Requested Procedure Priority (uppercase set)
_PRIORITY_MAP = {"stat": "STAT", "high": "HIGH", "routine": "ROUTINE", "low": "LOW"}


def _fmt_date(d: date | None) -> str:
    return d.strftime("%Y%m%d") if d else ""


def _fmt_time(t: time | None) -> str:
    return t.strftime("%H%M%S") if t else ""


def build_worklist_dataset(item) -> Dataset:
    """Build the MWL query-response dataset for one scheduled procedure step."""
    ds = Dataset()
    # Korean names need UTF-8
    ds.SpecificCharacterSet = "ISO_IR 192"

    # --- Patient ---
    ds.PatientName = item.patient_name or ""
    ds.PatientID = item.patient_id or ""
    ds.PatientBirthDate = _fmt_date(item.patient_birth_date)
    ds.PatientSex = item.patient_sex or ""

    # --- Study / Requested Procedure ---
    ds.AccessionNumber = item.accession_number or ""
    # StudyInstanceUID must be STABLE across syncs so the eventual C-STORE links
    # to this order. If the item has none, derive a deterministic UID from the
    # accession (same input -> same UID) rather than a random one.
    _seed = item.accession_number or str(getattr(item, "id", ""))
    ds.StudyInstanceUID = item.study_instance_uid or generate_uid(entropy_srcs=[_seed, "study"])
    ds.RequestedProcedureID = item.requested_procedure_id or ""
    ds.RequestedProcedureDescription = item.requested_procedure_description or ""
    ds.ReferringPhysicianName = item.referring_physician or ""
    ds.RequestingPhysician = item.requesting_physician or ""
    ds.RequestedProcedurePriority = _PRIORITY_MAP.get(
        str(getattr(item.priority, "value", item.priority)).lower(), "ROUTINE"
    )

    # --- Scheduled Procedure Step Sequence (Type 1) ---
    sps = Dataset()
    sps.Modality = item.modality or ""
    sps.ScheduledStationAETitle = item.scheduled_station_ae_title or ""
    sps.ScheduledProcedureStepStartDate = _fmt_date(item.scheduled_date)
    sps.ScheduledProcedureStepStartTime = _fmt_time(item.scheduled_time)
    sps.ScheduledProcedureStepDescription = (
        item.scheduled_procedure_step_description or item.requested_procedure_description or ""
    )
    sps.ScheduledProcedureStepID = item.requested_procedure_id or (item.accession_number or "")
    sps.ScheduledPerformingPhysicianName = ""
    if item.body_part_examined:
        sps.BodyPartExamined = item.body_part_examined
    ds.ScheduledProcedureStepSequence = [sps]

    return ds


def build_worklist_file(item) -> bytes:
    """Serialize a scheduled item to a DICOM worklist file (.wl) for Orthanc."""
    ds = build_worklist_dataset(item)

    _seed = item.accession_number or str(getattr(item, "id", ""))
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = _MWL_SOP_CLASS
    file_meta.MediaStorageSOPInstanceUID = generate_uid(entropy_srcs=[_seed, "sop"])
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    # Worklist files carry no preamble requirement for Orthanc's plugin, but a
    # valid Part-10 wrapper is the safest, most portable form.
    buf = io.BytesIO()
    ds.save_as(buf, write_like_original=False)
    return buf.getvalue()


def worklist_filename(item) -> str:
    """Stable .wl filename per scheduled item (accession-based)."""
    acc = (item.accession_number or str(item.id)).replace("/", "_").replace("..", "_")
    return f"{acc}.wl"
