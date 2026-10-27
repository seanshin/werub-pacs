"""HospitalRun Order → OpenPACS Worklist auto-sync.

Polls HospitalRun orders table every 30 seconds and creates
worklist items for new RADIOLOGY orders automatically.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

HR_DB_URL = "postgresql+asyncpg://hospital:secret@127.0.0.1:5432/hospitalrun"
PACS_DB_URL = "postgresql+asyncpg://openpacs:OpenPACS2026!@127.0.0.1:5432/openpacs"


async def sync_orders():
    """Sync new radiology orders from HospitalRun to OpenPACS worklist."""
    hr_engine = create_async_engine(HR_DB_URL, echo=False)
    pacs_engine = create_async_engine(PACS_DB_URL, echo=False)

    HRSession = sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
    PACSSession = sessionmaker(pacs_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with HRSession() as hr_db, PACSSession() as pacs_db:
            # Get new radiology orders not yet synced
            result = await hr_db.execute(text("""
                SELECT o.id as order_id, o.status, o.priority, o.notes, o.created_at,
                       p.mrn, p.family_name, p.given_name, p.date_of_birth, p.gender,
                       ir.modality, ir.body_part
                FROM orders o
                JOIN prescriptions pr ON pr.id = o.prescription_id
                JOIN patients p ON p.id = pr.patient_id
                LEFT JOIN imaging_results ir ON ir.order_id = o.id
                WHERE o.department = 'RADIOLOGY'
                  AND o.status IN ('ORDERED', 'RECEIVED')
                  AND o.created_at > NOW() - INTERVAL '7 days'
                ORDER BY o.created_at DESC
                LIMIT 100
            """))
            orders = result.mappings().all()

            if not orders:
                return 0

            synced = 0
            for order in orders:
                order_id = str(order["order_id"])

                # Check if already synced
                existing = await pacs_db.execute(text(
                    "SELECT id FROM worklist_items WHERE accession_number = :acc"
                ), {"acc": order_id})

                if existing.first():
                    continue  # Already synced

                # Create worklist item
                patient_name = f"{order['family_name']}^{order['given_name']}"
                modality = order.get("modality") or "CR"
                priority = "urgent" if order["priority"] == "STAT" else "routine"

                now = datetime.now(timezone.utc)
                await pacs_db.execute(text("""
                    INSERT INTO worklist_items
                        (patient_id, patient_name, modality, scheduled_date,
                         accession_number, priority, status, description, created_at, updated_at)
                    VALUES
                        (:pid, :pname, :mod, :sdate, :acc, :pri, 'scheduled', :desc, :now, :now)
                    ON CONFLICT (accession_number) DO NOTHING
                """), {
                    "pid": order["mrn"],
                    "pname": patient_name,
                    "mod": modality,
                    "sdate": now,
                    "acc": order_id,
                    "pri": priority,
                    "desc": order.get("notes") or f"{modality} {order.get('body_part', '')}".strip(),
                    "now": now,
                })
                synced += 1

            await pacs_db.commit()

            if synced > 0:
                logger.info(f"Order sync: {synced} new worklist items created from HospitalRun")
            return synced

    except Exception as e:
        logger.warning(f"Order sync failed: {e}")
        return 0
    finally:
        await hr_engine.dispose()
        await pacs_engine.dispose()


async def run_sync_loop():
    """Run sync every 30 seconds."""
    while True:
        try:
            await sync_orders()
        except Exception as e:
            logger.error(f"Order sync loop error: {e}")
        await asyncio.sleep(30)
