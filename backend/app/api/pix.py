"""PIX/MPI API — 교차기관 환자 식별자 교차참조 (v2.0 트랙 A, EMR I002 갭).

- 식별 도메인(assigning authority) 관리
- MPI 엔터프라이즈 환자 + 도메인별 식별자 등록(교차참조)
- PIXm(ITI-83) `$ihe-pix` 질의: 소스 도메인 식별자 → 타깃 도메인 교차참조 식별자
- 로컬 백필: 기존 patient_mappings(DICOM PatientID) → 로컬 도메인 식별자 흡수(멱등)

FHIR system 표기 규약: `urn:oid:{universal_id}` 또는 도메인 `namespace_id`.
설계: `docs/02-design/xds-i-pix-mpi-phase1.design.md`
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import RequireRole
from app.models.mpi import (
    LOCAL_NAMESPACE_ID,
    IdentityDomain,
    MpiPatient,
    PatientIdentifier,
)
from app.models.patient_mapping import PatientMapping
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/pix", tags=["PIX/MPI 환자식별"])

# 관리/등록은 ADMIN(+TECH), 외부반출 아님이나 identity 조작이라 BTG 차단
AdminRoles = RequireRole(Role.ADMIN, allow_btg=False)
WriteRoles = RequireRole(Role.ADMIN, Role.TECHNOLOGIST, allow_btg=False)
# PIXm 질의는 운영 스태프(RESEARCHER 제외) — 특정 식별자 1건 조회(열거 아님)
QueryRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)


def _domain_dict(d: IdentityDomain) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "namespace_id": d.namespace_id,
        "universal_id": d.universal_id,
        "universal_type": d.universal_type,
        "is_local": d.is_local,
        "is_affinity": d.is_affinity,
        # FHIR system URI (OID 우선, 없으면 namespace)
        "system": f"urn:oid:{d.universal_id}" if d.universal_id else d.namespace_id,
    }


async def _resolve_domain(db: AsyncSession, system: str) -> IdentityDomain | None:
    """FHIR system 문자열(urn:oid:.. 또는 namespace_id)로 도메인 조회."""
    if not system:
        return None
    oid = system[8:] if system.startswith("urn:oid:") else None
    q = select(IdentityDomain).where(
        (IdentityDomain.namespace_id == system)
        | (IdentityDomain.universal_id == (oid or system))
    )
    return (await db.execute(q)).scalars().first()


# ─────────────────────────── 도메인 관리 ───────────────────────────
class DomainCreate(BaseModel):
    name: str
    namespace_id: str
    universal_id: str | None = None
    universal_type: str = "ISO"
    is_affinity: bool = False


@router.get("/domains")
async def list_domains(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(QueryRoles)],
):
    rows = (await db.execute(select(IdentityDomain).order_by(IdentityDomain.created_at))).scalars().all()
    return {"count": len(rows), "domains": [_domain_dict(d) for d in rows]}


@router.post("/domains")
async def create_domain(
    body: DomainCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(AdminRoles)],
):
    dup = (await db.execute(
        select(IdentityDomain).where(IdentityDomain.namespace_id == body.namespace_id)
    )).scalar_one_or_none()
    if dup:
        raise ConflictError(message="Domain namespace_id already exists")
    d = IdentityDomain(
        name=body.name,
        namespace_id=body.namespace_id,
        universal_id=body.universal_id,
        universal_type=body.universal_type,
        is_local=False,
        is_affinity=body.is_affinity,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return _domain_dict(d)


# ─────────────────────────── MPI 환자 / 식별자 ───────────────────────────
class IdentifierIn(BaseModel):
    system: str          # FHIR system (urn:oid:.. or namespace_id)
    identifier: str      # 해당 도메인의 환자 ID


class PatientCreate(BaseModel):
    identifiers: list[IdentifierIn]
    demographics: dict | None = None   # {name, sex, birth_date} 최소치
    created_from: str = "local"


async def _link_identifier(db: AsyncSession, enterprise_id, system: str, identifier: str) -> PatientIdentifier:
    domain = await _resolve_domain(db, system)
    if not domain:
        raise ValidationError(message=f"Unknown identity domain: {system}")
    existing = (await db.execute(
        select(PatientIdentifier).where(
            PatientIdentifier.domain_id == domain.id,
            PatientIdentifier.identifier == identifier,
        )
    )).scalar_one_or_none()
    if existing:
        if existing.enterprise_id != enterprise_id:
            raise ConflictError(message="Identifier already cross-referenced to another patient")
        return existing
    pid = PatientIdentifier(enterprise_id=enterprise_id, domain_id=domain.id, identifier=identifier)
    db.add(pid)
    return pid


@router.post("/patients")
async def create_mpi_patient(
    body: PatientCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    """엔터프라이즈 환자 생성 + 도메인별 식별자 교차참조 등록."""
    if not body.identifiers:
        raise ValidationError(message="At least one identifier required")
    patient = MpiPatient(created_from=body.created_from, demographics=body.demographics)
    db.add(patient)
    await db.flush()  # patient.id
    for ident in body.identifiers:
        await _link_identifier(db, patient.id, ident.system, ident.identifier)
    await db.commit()
    await db.refresh(patient)
    return await _patient_dict(db, patient.id)


@router.post("/patients/{enterprise_id}/identifiers")
async def add_identifier(
    enterprise_id: str,
    body: IdentifierIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    patient = (await db.execute(select(MpiPatient).where(MpiPatient.id == enterprise_id))).scalar_one_or_none()
    if not patient:
        raise NotFoundError(message="MPI patient not found")
    await _link_identifier(db, patient.id, body.system, body.identifier)
    await db.commit()
    return await _patient_dict(db, patient.id)


async def _patient_dict(db: AsyncSession, enterprise_id) -> dict:
    idents = (await db.execute(
        select(PatientIdentifier, IdentityDomain)
        .join(IdentityDomain, PatientIdentifier.domain_id == IdentityDomain.id)
        .where(PatientIdentifier.enterprise_id == enterprise_id)
    )).all()
    patient = (await db.execute(select(MpiPatient).where(MpiPatient.id == enterprise_id))).scalar_one()
    return {
        "enterprise_id": str(enterprise_id),
        "created_from": patient.created_from,
        "demographics": patient.demographics,
        "identifiers": [
            {
                "system": f"urn:oid:{dom.universal_id}" if dom.universal_id else dom.namespace_id,
                "domain": dom.name,
                "identifier": pid.identifier,
            }
            for pid, dom in idents
        ],
    }


@router.get("/patients/{enterprise_id}")
async def get_mpi_patient(
    enterprise_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(QueryRoles)],
):
    patient = (await db.execute(select(MpiPatient).where(MpiPatient.id == enterprise_id))).scalar_one_or_none()
    if not patient:
        raise NotFoundError(message="MPI patient not found")
    return await _patient_dict(db, enterprise_id)


# ─────────────────────────── PIXm Query (ITI-83) ───────────────────────────
@router.get("/Patient/$ihe-pix")
async def pixm_query(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(QueryRoles)],
    sourceIdentifier: str = Query(..., description="system|value (FHIR Identifier)"),
    targetSystem: str | None = Query(None, description="타깃 도메인 system (미지정 시 전체 교차참조)"),
):
    """소스 도메인 식별자 → 교차참조된 타깃 도메인 식별자. FHIR Parameters 응답.

    미매칭 시 200 + 빈 parameter (ITI-83: 404 아님).
    """
    if "|" not in sourceIdentifier:
        raise ValidationError(message="sourceIdentifier must be 'system|value'")
    src_system, src_value = sourceIdentifier.split("|", 1)
    src_domain = await _resolve_domain(db, src_system)
    if not src_domain:
        raise ValidationError(message=f"Unknown source domain: {src_system}")

    # 소스 식별자 → enterprise_id
    src = (await db.execute(
        select(PatientIdentifier).where(
            PatientIdentifier.domain_id == src_domain.id,
            PatientIdentifier.identifier == src_value,
        )
    )).scalar_one_or_none()
    if not src:
        return {"resourceType": "Parameters", "parameter": []}

    # 교차참조 식별자(소스 자신 제외), targetSystem 필터
    q = (
        select(PatientIdentifier, IdentityDomain)
        .join(IdentityDomain, PatientIdentifier.domain_id == IdentityDomain.id)
        .where(
            PatientIdentifier.enterprise_id == src.enterprise_id,
            PatientIdentifier.id != src.id,
        )
    )
    rows = (await db.execute(q)).all()
    params = []
    for pid, dom in rows:
        system = f"urn:oid:{dom.universal_id}" if dom.universal_id else dom.namespace_id
        if targetSystem and system != targetSystem and dom.namespace_id != targetSystem:
            continue
        params.append({
            "name": "targetIdentifier",
            "valueIdentifier": {"system": system, "value": pid.identifier},
        })
    return {
        "resourceType": "Parameters",
        "enterprise_id": str(src.enterprise_id),
        "parameter": params,
    }


# ─────────────────────────── 로컬 백필 ───────────────────────────
@router.post("/admin/backfill-local")
async def backfill_local(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(AdminRoles)],
    limit: int = Query(5000, ge=1, le=50000),
):
    """기존 patient_mappings의 DICOM PatientID를 로컬 도메인 식별자로 흡수(멱등).

    이미 로컬 도메인에 등록된 식별자는 건너뜀. 각 미등록 DICOM ID마다
    엔터프라이즈 환자 1명 + 로컬 식별자 1개 생성.
    """
    local = (await db.execute(
        select(IdentityDomain).where(IdentityDomain.namespace_id == LOCAL_NAMESPACE_ID)
    )).scalar_one_or_none()
    if not local:
        raise NotFoundError(message="Local identity domain missing (migration not run)")

    # 이미 흡수된 로컬 식별자 집합
    existing = set((await db.execute(
        select(PatientIdentifier.identifier).where(PatientIdentifier.domain_id == local.id)
    )).scalars().all())

    mappings = (await db.execute(
        select(PatientMapping).limit(limit)
    )).scalars().all()

    created = 0
    for m in mappings:
        did = m.dicom_patient_id
        if not did or did in existing:
            continue
        patient = MpiPatient(
            created_from="local",
            demographics={"name": m.dicom_patient_name or m.his_patient_name} if (m.dicom_patient_name or m.his_patient_name) else None,
        )
        db.add(patient)
        await db.flush()
        db.add(PatientIdentifier(enterprise_id=patient.id, domain_id=local.id, identifier=did))
        existing.add(did)
        created += 1

    await db.commit()
    return {"status": "ok", "scanned": len(mappings), "created": created, "already_present": len(existing) - created}
