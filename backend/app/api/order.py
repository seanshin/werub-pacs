"""Imaging order API for HospitalRun integration.

HospitalRun creates an imaging order → OpenPACS creates a worklist entry.
"""
from datetime import date, time, datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.patient_mapping import PatientMapping
from app.models.user import User
from app.models.worklist import Priority, ProcedureStatus, WorklistItem

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


class ImagingOrder(BaseModel):
    """Imaging order from HospitalRun.

    patient_id: HIS MRN (e.g., HR-20260506-0328) — used as DICOM PatientID
    his_patient_uuid: HospitalRun internal UUID (optional, for linking)
    """
    patient_id: str  # HIS MRN → becomes DICOM PatientID
    patient_name: str
    his_patient_uuid: str | None = None  # HospitalRun internal patient UUID
    patient_birth_date: str | None = None
    patient_sex: str | None = None
    modality: str
    body_part: str | None = None
    procedure_description: str | None = None
    referring_physician: str | None = None
    clinical_info: str | None = None
    clinical_history: str | None = None  # 병력 요약
    prior_study_uid: str | None = None  # 이전 검사 참조 UID
    allergy_info: str | None = None  # 알레르기 (조영제 등)
    priority: str = "routine"  # stat, high, routine, low
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    scheduled_station_ae_title: str | None = None
    # HospitalRun reference
    hospitalrun_order_id: str | None = None


class OrderResponse(BaseModel):
    order_id: str
    worklist_id: str
    accession_number: str
    status: str
    message: str


@router.post("", response_model=OrderResponse)
async def create_imaging_order(
    order: ImagingOrder,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN))],
):
    """Create an imaging order from HospitalRun. Requires authentication.

    Automatically creates a worklist entry in OpenPACS.
    Called by HospitalRun when a doctor orders an imaging study.
    """
    # Generate accession number
    acc_num = f"ACC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}"

    # Map priority
    priority_map = {
        "stat": Priority.STAT,
        "urgent": Priority.HIGH,
        "high": Priority.HIGH,
        "routine": Priority.ROUTINE,
        "low": Priority.LOW,
    }
    mapped_priority = priority_map.get(order.priority.lower(), Priority.ROUTINE)

    # Default AE title based on modality
    ae_title = order.scheduled_station_ae_title
    if not ae_title:
        ae_map = {"CR": "CR_ROOM1", "DX": "DX_ROOM1", "CT": "CT_ROOM1", "MR": "MR_ROOM1", "US": "US_ROOM1"}
        ae_title = ae_map.get(order.modality.upper(), "DEFAULT")

    # Create worklist entry
    worklist = WorklistItem(
        patient_id=order.patient_id,
        patient_name=order.patient_name,
        patient_birth_date=datetime.strptime(order.patient_birth_date, "%Y-%m-%d").date() if order.patient_birth_date else None,
        patient_sex=order.patient_sex,
        accession_number=acc_num,
        requested_procedure_id=order.hospitalrun_order_id or acc_num,
        requested_procedure_description=order.procedure_description or f"{order.modality} {order.body_part or ''}".strip(),
        referring_physician=order.referring_physician,
        scheduled_station_ae_title=ae_title,
        modality=order.modality.upper(),
        scheduled_date=order.scheduled_date or date.today(),
        scheduled_time=order.scheduled_time,
        scheduled_procedure_step_description=order.procedure_description,
        body_part_examined=order.body_part,
        priority=mapped_priority,
        clinical_info=order.clinical_info,
        notes=f"HospitalRun Order: {order.hospitalrun_order_id}" if order.hospitalrun_order_id else None,
    )

    db.add(worklist)

    # Auto-create patient mapping (HIS MRN ↔ DICOM PatientID)
    existing_map = await db.execute(
        select(PatientMapping).where(PatientMapping.his_mrn == order.patient_id)
    )
    if not existing_map.scalar_one_or_none():
        mapping = PatientMapping(
            his_mrn=order.patient_id,
            his_patient_name=order.patient_name,
            his_patient_id=order.his_patient_uuid,
            dicom_patient_id=order.patient_id,  # MRN = DICOM PatientID
            dicom_patient_name=order.patient_name,
            source="worklist",
        )
        db.add(mapping)

    await db.commit()
    await db.refresh(worklist)

    return OrderResponse(
        order_id=order.hospitalrun_order_id or acc_num,
        worklist_id=str(worklist.id),
        accession_number=acc_num,
        status="scheduled",
        message=f"Worklist entry created: {order.modality} {order.body_part or ''} for {order.patient_name}",
    )


@router.get("/{accession_number}/status")
async def get_order_status(
    accession_number: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN))],
):
    """Get order status by accession number. Requires authentication. For HospitalRun polling."""
    result = await db.execute(
        select(WorklistItem).where(WorklistItem.accession_number == accession_number)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Order", accession_number)

    return {
        "accession_number": accession_number,
        "status": item.status,
        "patient_id": item.patient_id,
        "modality": item.modality,
        "scheduled_date": str(item.scheduled_date),
        "study_instance_uid": item.study_instance_uid,
        "has_images": item.study_instance_uid is not None,
    }
