"""HospitalRun patient-merge reconciliation.

HospitalRun supports patient record merges (``patients.merged_into_id`` points
from the merged-away record to the surviving record). When that happens, imaging
previously stored under the OLD MRN must consolidate under the SURVIVING patient
so that a patient chart shows a single, complete imaging history.

This reconciler (read-only on HospitalRun):
  1. finds merged-away patients and their surviving target,
  2. re-tags any Orthanc studies stored under the old MRN to the surviving
     patient identity (in-place modify, original replaced),
  3. upserts a ``patient_mappings`` row so the old MRN keeps resolving — now to
     the surviving DICOM PatientID (``source='merge'``).

Triggered on demand by an admin endpoint. Idempotent: once a study carries the
surviving MRN it is no longer found under the old MRN, so re-runs are no-ops.
Verified-safe even with zero merges (current data: 0).
"""
import logging

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.patient_mapping import PatientMapping
from app.services.his_order_sync import _name

logger = logging.getLogger(__name__)

_MERGED_QUERY = text(
    """
    SELECT old.mrn               AS old_mrn,
           surv.mrn              AS surv_mrn,
           surv.id::text         AS surv_uuid,
           surv.family_name      AS family_name,
           surv.given_name       AS given_name,
           to_char(surv.date_of_birth, 'YYYYMMDD') AS dob,
           CASE surv.gender::text WHEN 'MALE' THEN 'M'
                                  WHEN 'FEMALE' THEN 'F' ELSE '' END AS sex
    FROM patients old
    JOIN patients surv ON surv.id = old.merged_into_id
    WHERE old.merged_into_id IS NOT NULL
      AND old.mrn IS NOT NULL
      AND surv.mrn IS NOT NULL
    """
)


async def reconcile_merged_patients(hr_db_url: str, pacs_db: AsyncSession,
                                    orthanc) -> dict:
    """Consolidate imaging of merged-away patients under the surviving MRN.

    ``orthanc`` is an httpx.AsyncClient configured with the Orthanc base_url and
    auth (e.g. ``request.app.state.http_client``).
    """
    hr_engine = create_async_engine(hr_db_url, echo=False, pool_pre_ping=True)
    HRSession = sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
    merges = 0
    studies_retagged = 0
    mappings_updated = 0
    failed = 0
    details = []
    DETAILS_CAP = 100
    try:
        async with HRSession() as hr_db:
            rows = (await hr_db.execute(_MERGED_QUERY)).mappings().all()

        for r in rows:
            old_mrn, surv_mrn = r["old_mrn"], r["surv_mrn"]
            if old_mrn == surv_mrn:
                continue
            merges += 1
            name = _name(r["family_name"], r["given_name"])

            # 1. Re-tag Orthanc studies stored under the old MRN
            retagged_here = 0
            found_here = 0
            retag_error = False
            try:
                resp = await orthanc.post("/tools/find", json={
                    "Level": "Study", "Query": {"PatientID": old_mrn},
                })
                study_ids = resp.json() if resp.status_code == 200 else []
                found_here = len(study_ids)
                for sid in study_ids:
                    mresp = await orthanc.post(f"/studies/{sid}/modify", json={
                        "Replace": {
                            "PatientID": surv_mrn,
                            "PatientName": name,
                            "PatientBirthDate": r["dob"] or "",
                            "PatientSex": r["sex"] or "",
                            "SpecificCharacterSet": "ISO_IR 192",
                        },
                        "Force": True, "KeepSource": False, "Synchronous": True,
                    })
                    if mresp.status_code in (200, 201):
                        retagged_here += 1
                    else:
                        retag_error = True
            except Exception as e:  # Orthanc hiccup — record, continue
                retag_error = True
                logger.warning("merge re-tag failed for %s->%s: %s",
                               old_mrn, surv_mrn, e)
            studies_retagged += retagged_here

            # If studies existed under the old MRN but were not all re-tagged,
            # the merge is NOT reconciled — leave the mapping untouched so a
            # re-run retries, and report it as failed (don't show false success).
            if retag_error or retagged_here < found_here:
                failed += 1
                if len(details) < DETAILS_CAP:
                    details.append({
                        "old_mrn": old_mrn, "surv_mrn": surv_mrn,
                        "found": found_here, "retagged": retagged_here,
                        "status": "partial_failed",
                    })
                continue

            # 2. Re-tag succeeded (or nothing to move): old MRN now resolves to
            #    the surviving DICOM PatientID.
            disp = _name(r["family_name"], r["given_name"], sep="")
            m = await pacs_db.execute(
                select(PatientMapping).where(PatientMapping.his_mrn == old_mrn)
            )
            existing = m.scalar_one_or_none()
            if existing:
                existing.dicom_patient_id = surv_mrn
                existing.dicom_patient_name = disp
                existing.source = "merge"
            else:
                pacs_db.add(PatientMapping(
                    his_mrn=old_mrn, his_patient_name=disp,
                    his_patient_id=r["surv_uuid"],
                    dicom_patient_id=surv_mrn, dicom_patient_name=disp,
                    source="merge",
                ))
            mappings_updated += 1
            if len(details) < DETAILS_CAP:
                details.append({"old_mrn": old_mrn, "surv_mrn": surv_mrn,
                                "found": found_here, "retagged": retagged_here,
                                "status": "ok"})

        await pacs_db.commit()
        result = {
            "merges_found": merges,
            "studies_retagged": studies_retagged,
            "mappings_updated": mappings_updated,
            "failed": failed,
            "details": details,
            "details_truncated": merges > DETAILS_CAP,
        }
        logger.info("Patient-merge reconcile: %s", {k: v for k, v in result.items() if k != "details"})
        return result
    finally:
        await hr_engine.dispose()
