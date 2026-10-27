"""Patient ID mapping API — HIS MRN ↔ DICOM PatientID."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import _log_audit_entry
from app.core.database import get_db
from app.core.exceptions import ConflictError
from app.core.security import RequireRole, get_current_user
from app.models.patient_mapping import PatientMapping
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/patient-mappings", tags=["patients"])


class MappingCreate(BaseModel):
    his_mrn: str
    his_patient_name: str | None = None
    his_patient_id: str | None = None
    dicom_patient_id: str | None = None  # defaults to his_mrn if not set
    source: str = "manual"


@router.get("")
async def list_mappings(
    db: Annotated[AsyncSession, Depends(get_db)],
    # 이름↔MRN↔DICOM PHI 연계표 — 운영 전용. RESEARCHER 등 열거 차단(P2 결정).
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST))],
    his_mrn: str | None = Query(None),
    dicom_patient_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """List patient ID mappings."""
    query = select(PatientMapping).order_by(PatientMapping.created_at.desc())
    if his_mrn:
        query = query.where(PatientMapping.his_mrn == his_mrn)
    if dicom_patient_id:
        query = query.where(PatientMapping.dicom_patient_id == dicom_patient_id)

    result = await db.execute(query.limit(limit))
    mappings = result.scalars().all()

    return {
        "count": len(mappings),
        "mappings": [
            {
                "id": str(m.id),
                "his_mrn": m.his_mrn,
                "his_patient_name": m.his_patient_name,
                "his_patient_id": m.his_patient_id,
                "dicom_patient_id": m.dicom_patient_id,
                "dicom_patient_name": m.dicom_patient_name,
                "source": m.source,
                "created_at": m.created_at.isoformat(),
            }
            for m in mappings
        ],
    }


@router.post("")
async def create_mapping(
    body: MappingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    # 환자 매핑 생성 = 데이터 귀속 변경. 잘못되면 환자 섞임이라 응급 우회 대상이 아니다.
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False))],
):
    """Create a patient ID mapping manually."""
    existing = await db.execute(
        select(PatientMapping).where(PatientMapping.his_mrn == body.his_mrn)
    )
    if existing.scalar_one_or_none():
        raise ConflictError(message="MRN mapping already exists")

    mapping = PatientMapping(
        his_mrn=body.his_mrn,
        his_patient_name=body.his_patient_name,
        his_patient_id=body.his_patient_id,
        dicom_patient_id=body.dicom_patient_id or body.his_mrn,
        source=body.source,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)

    # 데이터 귀속(HIS MRN ↔ DICOM PatientID) 변경은 잘못되면 환자 섞임으로 이어진다 —
    # v13.44에서 BTG까지 막은 민감도인데 기록이 없었다. 환자 **이름은 싣지 않는다**
    # (감사 로그의 PHI 최소화 — 식별자만으로 추적 가능).
    await _log_audit_entry(
        db=db, operation="PATIENT_MAPPING_CREATED", resource_type="PatientMapping",
        status="SUCCESS", user_id=str(user.id), username=user.username,
        resource_id=str(mapping.id),
        patient_id=mapping.dicom_patient_id,
        details={
            "his_mrn": mapping.his_mrn,
            "dicom_patient_id": mapping.dicom_patient_id,
            "source": mapping.source,
        },
    )

    return {
        "id": str(mapping.id),
        "his_mrn": mapping.his_mrn,
        "dicom_patient_id": mapping.dicom_patient_id,
        "status": "created",
    }


@router.get("/resolve/{patient_id}")
async def resolve_patient_id(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST))],
):
    """Resolve any patient ID (MRN, HIS UUID, DICOM ID) to all known IDs."""
    result = await db.execute(
        select(PatientMapping).where(
            (PatientMapping.his_mrn == patient_id) |
            (PatientMapping.his_patient_id == patient_id) |
            (PatientMapping.dicom_patient_id == patient_id)
        )
    )
    mapping = result.scalar_one_or_none()

    if not mapping:
        return {
            "resolved": False,
            "input": patient_id,
            "his_mrn": patient_id,
            "dicom_patient_id": patient_id,
            "message": "No mapping found — using input as both HIS and DICOM ID",
        }

    return {
        "resolved": True,
        "input": patient_id,
        "his_mrn": mapping.his_mrn,
        "his_patient_id": mapping.his_patient_id,
        "his_patient_name": mapping.his_patient_name,
        "dicom_patient_id": mapping.dicom_patient_id,
        "dicom_patient_name": mapping.dicom_patient_name,
        "source": mapping.source,
    }
