"""HospitalRun Integration Service.

Syncs data between HospitalRun (hospitalrun DB) and OpenPACS (openpacs DB).
- Patient lookup: HR patients → DICOM patient matching
- Order sync: HR imaging orders → OpenPACS worklist
- Result callback: OpenPACS report → HR imaging_results

Uses direct DB access to hospitalrun DB (read-only for patients/orders,
write to imaging_results for report sync).
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# HospitalRun DB connection (read + limited write)
HR_DB_URL = "postgresql+asyncpg://hospital:secret@127.0.0.1:5432/hospitalrun"

_hr_engine = None
_hr_session_factory = None


def get_hr_engine():
    global _hr_engine, _hr_session_factory
    if _hr_engine is None:
        _hr_engine = create_async_engine(HR_DB_URL, echo=False, pool_size=5, max_overflow=5)
        _hr_session_factory = sessionmaker(_hr_engine, class_=AsyncSession, expire_on_commit=False)
    return _hr_engine, _hr_session_factory


class HospitalRunSyncService:
    """Sync service between HospitalRun and OpenPACS."""

    async def search_hr_patients(self, query: str, limit: int = 20) -> list[dict]:
        """Search HospitalRun patients by name or MRN."""
        _, SessionFactory = get_hr_engine()
        async with SessionFactory() as db:
            result = await db.execute(text("""
                SELECT id, mrn, family_name, given_name, date_of_birth, gender, phone
                FROM patients
                WHERE (family_name ILIKE :q OR given_name ILIKE :q OR mrn ILIKE :q)
                  AND valid_to IS NULL
                ORDER BY family_name, given_name
                LIMIT :limit
            """), {"q": f"%{query}%", "limit": limit})
            return [dict(r._mapping) for r in result]

    async def get_hr_patient(self, patient_id: str) -> Optional[dict]:
        """Get HospitalRun patient by ID or MRN."""
        _, SessionFactory = get_hr_engine()
        async with SessionFactory() as db:
            result = await db.execute(text("""
                SELECT id, mrn, family_name, given_name, date_of_birth, gender,
                       phone, email, blood_type, insurance_type, insurance_number
                FROM patients
                WHERE (id::text = :pid OR mrn = :pid) AND valid_to IS NULL
                LIMIT 1
            """), {"pid": patient_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def get_pending_imaging_orders(self, limit: int = 50) -> list[dict]:
        """Get pending imaging orders from HospitalRun.

        Returns orders with department='IMAGING' and status in (ORDERED, RECEIVED, IN_PROGRESS).
        (HR 실 스키마: department='IMAGING', prescriptions→encounters→patients 조인 — his_order_sync 검증본 기준.)
        """
        _, SessionFactory = get_hr_engine()
        async with SessionFactory() as db:
            result = await db.execute(text("""
                SELECT o.id as order_id, o.status, o.priority, o.notes, o.created_at,
                       p.id as patient_id, p.mrn, p.family_name, p.given_name,
                       p.date_of_birth, p.gender,
                       ir.modality, ir.body_part, ir.status as imaging_status
                FROM orders o
                JOIN prescriptions pr ON pr.id = o.prescription_id
                JOIN encounters e ON e.id = pr.encounter_id
                JOIN patients p ON p.id = e.patient_id
                LEFT JOIN imaging_results ir ON ir.order_id = o.id
                WHERE o.department = 'IMAGING'
                  AND o.status IN ('ORDERED', 'RECEIVED', 'IN_PROGRESS')
                ORDER BY
                  CASE o.priority WHEN 'STAT' THEN 0 WHEN 'URGENT' THEN 1 ELSE 2 END,
                  o.created_at
                LIMIT :limit
            """), {"limit": limit})
            return [dict(r._mapping) for r in result]

    async def sync_report_to_hr(self, order_id: str, patient_id: str,
                                 finding: str, impression: str,
                                 modality: str, radiologist_id: Optional[str] = None) -> dict:
        """Push OpenPACS report back to HospitalRun imaging_results.

        Called when a radiologist signs a report in OpenPACS.
        """
        _, SessionFactory = get_hr_engine()
        async with SessionFactory() as db:
            now = datetime.now(timezone.utc)

            # Check if imaging_result already exists for this order
            existing = await db.execute(text(
                "SELECT id FROM imaging_results WHERE order_id = :oid"
            ), {"oid": order_id})
            row = existing.first()

            if row:
                # Update existing
                await db.execute(text("""
                    UPDATE imaging_results
                    SET finding = :finding, impression = :impression,
                        status = 'REPORTED', reported_at = :now,
                        radiologist_id = :rad_id
                    WHERE order_id = :oid
                """), {
                    "finding": finding, "impression": impression,
                    "now": now, "rad_id": radiologist_id, "oid": order_id,
                })
                logger.info(f"Updated HR imaging_result for order {order_id}")
            else:
                # Create new
                from uuid import uuid4
                await db.execute(text("""
                    INSERT INTO imaging_results (id, order_id, patient_id, modality,
                        finding, impression, status, reported_at, created_at)
                    VALUES (:id, :oid, :pid, :mod, :finding, :impression, 'REPORTED', :now, :now)
                """), {
                    "id": str(uuid4()), "oid": order_id, "pid": patient_id,
                    "mod": modality, "finding": finding, "impression": impression,
                    "now": now,
                })
                logger.info(f"Created HR imaging_result for order {order_id}")

            # Update order status to COMPLETED
            await db.execute(text("""
                UPDATE orders SET status = 'COMPLETED', completed_at = :now, updated_at = :now
                WHERE id = :oid AND status != 'COMPLETED'
            """), {"oid": order_id, "now": now})

            await db.commit()
            return {"order_id": order_id, "status": "synced", "synced_at": now.isoformat()}

    async def get_sync_stats(self) -> dict:
        """Get sync statistics."""
        _, SessionFactory = get_hr_engine()
        async with SessionFactory() as db:
            patients = await db.execute(text("SELECT count(*) FROM patients WHERE valid_to IS NULL"))
            orders = await db.execute(text("SELECT count(*) FROM orders WHERE department = 'IMAGING'"))
            pending = await db.execute(text(
                "SELECT count(*) FROM orders WHERE department = 'IMAGING' AND status IN ('ORDERED', 'RECEIVED')"
            ))
            reported = await db.execute(text(
                "SELECT count(*) FROM imaging_results WHERE status = 'REPORTED'"
            ))
            return {
                "hr_patients": patients.scalar(),
                "hr_radiology_orders": orders.scalar(),
                "hr_pending_orders": pending.scalar(),
                "hr_reported_results": reported.scalar(),
            }
