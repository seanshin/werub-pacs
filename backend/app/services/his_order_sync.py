"""On-demand HospitalRun IMAGING order → OpenPACS worklist sync.

Replaces the disabled legacy direct-DB poll (``order_sync_task.py``), which never
worked: it joined ``prescriptions.patient_id`` (that column does not exist — the
link is ``prescriptions.encounter_id`` → ``encounters.patient_id``), filtered on
``department='RADIOLOGY'`` (the real ``OrderDepartment`` value is ``IMAGING``),
used invalid priority strings, and omitted NOT NULL worklist columns.

This module uses the VERIFIED schema path (confirmed against the live DB
2026-06-09)::

    orders → prescriptions(encounter_id) → encounters(patient_id) → patients(mrn)
    department = 'IMAGING', status IN ('ORDERED','RECEIVED')

It is triggered ON DEMAND by an admin endpoint (not a continuous poll) and reads
HospitalRun READ-ONLY via ``settings.hospitalrun_db_url`` (env, opt-in — empty
disables the feature). HospitalRun data is never modified.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.worklist import WorklistItem, ProcedureStatus, Priority
from app.models.patient_mapping import PatientMapping

logger = logging.getLogger(__name__)

# Verified read-only query (HospitalRun internal schema).
_HR_QUERY = text(
    """
    SELECT o.id::text          AS order_id,
           o.priority::text    AS priority,
           o.notes             AS notes,
           o.created_at        AS created_at,
           p.mrn               AS mrn,
           p.family_name       AS family_name,
           p.given_name        AS given_name,
           p.id::text          AS patient_uuid,
           p.date_of_birth     AS date_of_birth,
           p.gender::text      AS gender,
           ir.modality         AS modality,
           ir.body_part        AS body_part
    FROM orders o
    JOIN prescriptions pr ON pr.id = o.prescription_id
    JOIN encounters e     ON e.id = pr.encounter_id
    JOIN patients p       ON p.id = e.patient_id
    LEFT JOIN imaging_results ir ON ir.order_id = o.id
    WHERE o.department = 'IMAGING'
      AND o.status IN ('ORDERED', 'RECEIVED')
      AND o.created_at > NOW() - INTERVAL '30 days'
    ORDER BY o.created_at DESC
    LIMIT 200
    """
)

# Free-text modality (HospitalRun) → DICOM modality code.
_MODALITY_MAP = {
    "X-RAY": "CR", "XRAY": "CR", "X RAY": "CR", "RADIOGRAPH": "CR",
    "CT": "CT", "MRI": "MR", "MR": "MR", "US": "US", "ULTRASOUND": "US",
    "MAMMO": "MG", "MAMMOGRAPHY": "MG", "PET": "PT", "NM": "NM",
}

# Recognised DICOM Modality CS codes that may arrive already-normalised.
_VALID_MODALITIES = {
    "CR", "DX", "DR", "CT", "MR", "US", "MG", "PT", "NM", "XA", "RF",
    "OT", "SC", "XC", "OP", "ES", "IO", "PX", "RG",
}


def _dicom_modality(raw: str | None) -> str:
    """Map free-text modality to a valid DICOM CS code (never arbitrary text)."""
    if not raw:
        return "CR"
    u = raw.strip().upper()
    if u in _MODALITY_MAP:
        return _MODALITY_MAP[u]
    if u in _VALID_MODALITIES:
        return u
    return "OT"  # unknown free text → Other, not an invalid code


def _name(family: str | None, given: str | None, sep: str = "^") -> str:
    """Build a name without rendering literal 'None' for NULL parts."""
    return f"{family or ''}{sep}{given or ''}" if sep else f"{family or ''}{given or ''}"


async def sync_imaging_orders(hr_db_url: str, pacs_db: AsyncSession) -> dict:
    """Pull IMAGING orders from HospitalRun → worklist + patient mappings.

    Idempotent: worklist keyed by accession (order id), mappings by MRN.
    Returns a summary dict.
    """
    hr_engine = create_async_engine(hr_db_url, echo=False, pool_pre_ping=True)
    HRSession = sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
    created = mapped = skipped = 0
    try:
        async with HRSession() as hr_db:
            rows = (await hr_db.execute(_HR_QUERY)).mappings().all()

        for r in rows:
            mrn = r["mrn"]
            if not mrn:
                skipped += 1
                continue

            # --- Worklist upsert (by accession = HospitalRun order id) ---
            # Existence check is the fast path; the SAVEPOINT + IntegrityError
            # catch makes it safe against a concurrent run / double-click that
            # wins the race on the unique accession_number (so one collision
            # cannot roll back the whole batch).
            exists = await pacs_db.execute(
                select(WorklistItem.id).where(
                    WorklistItem.accession_number == r["order_id"]
                )
            )
            if exists.first():
                skipped += 1
            else:
                modality = _dicom_modality(r["modality"])
                desc = (r["notes"] or f"{modality} {r['body_part'] or ''}").strip()
                try:
                    async with pacs_db.begin_nested():
                        pacs_db.add(WorklistItem(
                            patient_id=mrn,
                            patient_name=_name(r["family_name"], r["given_name"]),
                            patient_birth_date=r["date_of_birth"],
                            patient_sex={"MALE": "M", "FEMALE": "F"}.get(r["gender"] or "", None),
                            accession_number=r["order_id"],
                            requested_procedure_id=r["order_id"],
                            requested_procedure_description=desc[:256],
                            modality=modality,
                            scheduled_station_ae_title=settings.orthanc_aet,
                            scheduled_date=(r["created_at"] or datetime.now(timezone.utc)).date(),
                            body_part_examined=(r["body_part"] or None),
                            status=ProcedureStatus.SCHEDULED,
                            priority=(Priority.STAT if (r["priority"] or "").upper() == "STAT"
                                      else Priority.ROUTINE),
                            clinical_info=r["notes"],
                        ))
                    created += 1
                except IntegrityError:
                    skipped += 1  # concurrent run inserted the same accession

            # --- Patient mapping upsert (HIS MRN ↔ DICOM PatientID) ---
            disp = _name(r["family_name"], r["given_name"], sep="")
            m = await pacs_db.execute(
                select(PatientMapping).where(PatientMapping.his_mrn == mrn)
            )
            existing_map = m.scalar_one_or_none()
            if existing_map:
                existing_map.his_patient_id = r["patient_uuid"]
                if not existing_map.his_patient_name:
                    existing_map.his_patient_name = disp
            else:
                try:
                    async with pacs_db.begin_nested():
                        pacs_db.add(PatientMapping(
                            his_mrn=mrn, his_patient_name=disp, his_patient_id=r["patient_uuid"],
                            dicom_patient_id=mrn, dicom_patient_name=disp, source="his-order-sync",
                        ))
                    mapped += 1
                except IntegrityError:
                    pass  # concurrent run created the mapping

        await pacs_db.commit()
        result = {
            "orders_seen": len(rows),
            "worklist_created": created,
            "mappings_created": mapped,
            "skipped": skipped,
        }
        logger.info("HIS order sync: %s", result)
        return result
    finally:
        await hr_engine.dispose()
