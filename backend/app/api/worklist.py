"""Worklist (MWL) API endpoints.

★변경(생성/수정/삭제)은 반드시 감사에 남긴다. 워크리스트는 검사 오더 그 자체라
상태 전이·삭제가 임상 워크플로와 외부 연계(LIS/HIS MWL)에 직접 영향을 준다.
2026-08-03까지 이 3개 엔드포인트에 감사가 전혀 없어, 관리자가 오더 상태를 바꾸거나
삭제해도 `audit_logs`에 아무 기록이 남지 않았다(LIS 고아 워크리스트 정리 중 발견).

감사는 범용 `@AuditLogger.log` 데코레이터 대신 **핸들러 안에서 명시 기록**한다 —
데코레이터는 작업자·동작만 남기고 *어떤 오더가 어떻게 바뀌었는지*를 못 남기는데,
워크리스트에서 필요한 건 정확히 그 부분(accession·전후 상태)이기 때문이다.
"""
from datetime import date, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import _log_audit_entry
from app.core.cache import cached, invalidate_on_write
from app.core.cache_config import CACHE_TTL_WORKLIST, CACHE_PATTERN_WORKLIST
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User
from app.models.worklist import Priority, ProcedureStatus, WorklistItem

router = APIRouter(prefix="/api/v1/worklist", tags=["worklist"])

# 워크리스트 조회는 환자명·PatientID·생년월일을 그대로 담는다 → **PHI 열거 표면**이다.
# 리포트(v13.8 ReportReadRoles)·QIDO(v13.19 StudyReadRoles)에는 이미 적용한 "저권한 역할의
# MRN/이름/DOB 열거 차단"이 워크리스트에만 누락돼 있었다(2026-08-03 실측: RESEARCHER가
# `GET /worklist`로 환자명·MRN·DOB 전량 열거 200).
#   · RESEARCHER 제외 — 비임상·연구용 역할
#   · SERVICE(svc-lis) 제외 — LIS에 **타 부서 오더의 환자 정보**까지 열리면 안 된다.
#     LIS가 필요한 것은 자기가 보낸 accession의 도달 여부이고, 그건 PHI를 반환하지 않는
#     `GET /worklist/verify`가 담당한다(v13.40). 감사상 svc-lis는 QIDO-RS만 사용해 왔다.
#   · RESIDENT는 RequireRole이 RADIOLOGIST로 승격.
WorklistReadRoles = RequireRole(
    Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, Role.TECHNOLOGIST
)


def _enum_str(v) -> str | None:
    """enum이면 NAME(대문자), 아니면 원값 문자열. DB가 NAME을 저장하므로 감사도 NAME으로
    맞춘다(소문자 value로 남기면 DB 조회와 대조가 안 된다 — enum NAME 함정)."""
    if v is None:
        return None
    return v.name if hasattr(v, "name") else str(v)


async def _audit_worklist(db, user, operation: str, item, extra: dict | None = None):
    """워크리스트 변경 감사. 실패해도 주 동작을 막지 않는다(_log_audit_entry가 흡수)."""
    details = {
        "worklist_item_id": str(item.id),
        "accession_number": item.accession_number,
        "patient_id": item.patient_id,
        "modality": item.modality,
        "status": _enum_str(item.status),
    }
    if extra:
        details.update(extra)
    await _log_audit_entry(
        db=db, operation=operation, resource_type="WorklistItem", status="SUCCESS",
        user_id=str(user.id), username=user.username, details=details,
    )


class WorklistCreate(BaseModel):
    patient_id: str
    patient_name: str
    patient_birth_date: date | None = None
    patient_sex: str | None = None
    accession_number: str
    requested_procedure_id: str
    requested_procedure_description: str | None = None
    referring_physician: str | None = None
    requesting_physician: str | None = None
    scheduled_station_ae_title: str
    modality: str
    scheduled_date: date
    scheduled_time: time | None = None
    scheduled_procedure_step_description: str | None = None
    body_part_examined: str | None = None
    priority: Priority = Priority.ROUTINE
    clinical_info: str | None = None
    notes: str | None = None


class WorklistUpdate(BaseModel):
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    scheduled_station_ae_title: str | None = None
    status: ProcedureStatus | None = None
    priority: Priority | None = None
    notes: str | None = None


class WorklistResponse(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    patient_birth_date: date | None
    patient_sex: str | None
    accession_number: str
    requested_procedure_id: str
    requested_procedure_description: str | None
    referring_physician: str | None
    scheduled_station_ae_title: str
    modality: str
    scheduled_date: date
    scheduled_time: time | None
    scheduled_procedure_step_description: str | None
    body_part_examined: str | None
    study_instance_uid: str | None
    status: str
    priority: str
    clinical_info: str | None
    notes: str | None


def _to_response(item: WorklistItem) -> dict:
    return {
        "id": str(item.id),
        "patient_id": item.patient_id,
        "patient_name": item.patient_name,
        "patient_birth_date": item.patient_birth_date,
        "patient_sex": item.patient_sex,
        "accession_number": item.accession_number,
        "requested_procedure_id": item.requested_procedure_id,
        "requested_procedure_description": item.requested_procedure_description,
        "referring_physician": item.referring_physician,
        "scheduled_station_ae_title": item.scheduled_station_ae_title,
        "modality": item.modality,
        "scheduled_date": item.scheduled_date,
        "scheduled_time": item.scheduled_time,
        "scheduled_procedure_step_description": item.scheduled_procedure_step_description,
        "body_part_examined": item.body_part_examined,
        "study_instance_uid": item.study_instance_uid,
        "status": item.status,
        "priority": item.priority,
        "clinical_info": item.clinical_info,
        "notes": item.notes,
        # MPPS (performed procedure step) — populated when a modality reports
        # IN PROGRESS / COMPLETED via MPPS N-CREATE/N-SET.
        "performed_start_time": item.performed_start_time,
        "performed_end_time": item.performed_end_time,
        "performed_station_ae_title": item.performed_station_ae_title,
        "mpps_sop_instance_uid": item.mpps_sop_instance_uid,
    }


@router.get("")
@cached(
    ttl=CACHE_TTL_WORKLIST,
    key_prefix='worklist',
    include_params=['scheduled_date', 'status_filter', 'modality', 'ae_title', 'patient_id', 'limit', 'offset']
)
async def list_worklist(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WorklistReadRoles)],
    scheduled_date: date | None = Query(None),
    status_filter: ProcedureStatus | None = Query(None, alias="status"),
    modality: str | None = Query(None),
    ae_title: str | None = Query(None),
    patient_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List worklist items with filters. Results cached for 5 minutes per user."""
    # STAT/urgent studies first, then by date
    from sqlalchemy import case
    priority_order = case(
        (WorklistItem.priority == 'stat', 0),
        (WorklistItem.priority == 'high', 1),
        (WorklistItem.priority == 'routine', 2),
        (WorklistItem.priority == 'low', 3),
        else_=4,
    )
    query = select(WorklistItem).order_by(
        priority_order, WorklistItem.scheduled_date.desc(), WorklistItem.scheduled_time.asc()
    )

    if scheduled_date:
        query = query.where(WorklistItem.scheduled_date == scheduled_date)
    if status_filter:
        query = query.where(WorklistItem.status == status_filter)
    if modality:
        query = query.where(WorklistItem.modality == modality)
    if ae_title:
        query = query.where(WorklistItem.scheduled_station_ae_title == ae_title)
    if patient_id:
        query = query.where(WorklistItem.patient_id == patient_id)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    # Paginate
    result = await db.execute(query.offset(offset).limit(limit))
    items = result.scalars().all()

    return {
        "total": total,
        "count": len(items),
        "offset": offset,
        "results": [_to_response(item) for item in items],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
@invalidate_on_write(CACHE_PATTERN_WORKLIST)
async def create_worklist(
    body: WorklistCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST))],
):
    """Create a new worklist entry. Admin or Technologist only. Invalidates cached worklist."""
    # Check duplicate accession number
    existing = await db.execute(
        select(WorklistItem).where(WorklistItem.accession_number == body.accession_number)
    )
    if existing.scalar_one_or_none():
        raise ConflictError(message="Accession number already exists")

    item = WorklistItem(**body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await _audit_worklist(db, user, "WORKLIST_CREATED", item,
                          {"scheduled_date": str(item.scheduled_date)})
    return _to_response(item)


@router.get("/stats")
async def worklist_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WorklistReadRoles)],
    target_date: date | None = Query(None),
):
    """Get worklist statistics for a date."""
    base_filter = WorklistItem.scheduled_date == target_date if target_date else True

    total = await db.execute(select(func.count()).where(base_filter).select_from(WorklistItem))
    status_result = await db.execute(
        select(WorklistItem.status, func.count()).where(base_filter).group_by(WorklistItem.status)
    )
    modality_result = await db.execute(
        select(WorklistItem.modality, func.count()).where(base_filter).group_by(WorklistItem.modality)
    )

    stats = {"total": total.scalar() or 0}
    for s, c in status_result.all():
        stats[s] = c
    stats["by_modality"] = dict(modality_result.all())

    return stats


# 송신측 자기검증 — LIS가 ORM 송신 후 "정말 워크리스트가 생겼는지"를 스스로 확인한다.
#
# 계기(2026-08-03): LIS가 `mwl_status='SENT'`로 기록한 3건이 PACS에 도달한 적이 없었고
# (리스너 로그 해당 구간 0줄), 아무도 몰랐다. 취소 ORM의 ACK가 "전이됨"과 "항목이 없어
# 무시됨"을 구분하지 못하듯, 송신 ACK도 최종 반영을 보장하지 않는다. 조용한 유실을 막으려면
# 송신측이 사후 확인할 수단이 있어야 한다.
#
# ★PHI를 반환하지 않는다 — 환자명·PatientID·검사설명 없이 **존재 여부와 상태만**. 호출자는
# 자기가 보낸 accession을 이미 알고 있으므로 이것으로 충분하고, 워크리스트 전량 열거로
# 타 부서 오더의 환자 정보가 새는 것을 막는다.
# ★캐시하지 않는다 — 송신 직후 확인이 용도라 신선도가 본질이다. (기존 목록 EP는 5분 캐시고
# 캐시 키가 include_params 기반이라, 여기에 필터만 추가하면 accession별로 오염된다.)
@router.get("/verify", summary="Accession 도달·상태 확인(송신측 자기검증, PHI 미반환)")
async def verify_worklist(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(
        Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, Role.SERVICE, allow_btg=False))],
    accession_number: str = Query(..., min_length=1, max_length=64,
                                  description="확인할 AccessionNumber (완전 일치)"),
):
    result = await db.execute(
        select(WorklistItem).where(WorklistItem.accession_number == accession_number)
    )
    item = result.scalar_one_or_none()
    if item is None:
        # 404가 아니라 200 + exists=false — "도달하지 않음"은 정상 응답이지 오류가 아니다.
        # 404로 주면 호출측이 장애와 미도달을 구분하기 어렵다.
        return {"accession_number": accession_number, "exists": False}
    return {
        "accession_number": item.accession_number,
        "exists": True,
        "status": item.status.name if hasattr(item.status, "name") else str(item.status),
        "modality": item.modality,
        "scheduled_date": item.scheduled_date,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        # 영상 도착 시 채워짐(v13.34 pathology_arrival) — 송신측이 열람 가능 시점을 안다
        "study_instance_uid": item.study_instance_uid,
    }


@router.get("/{item_id}")
async def get_worklist_item(
    item_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WorklistReadRoles)],
):
    """Get a single worklist item."""
    result = await db.execute(select(WorklistItem).where(WorklistItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Worklist item", str(item_id))
    return _to_response(item)


@router.patch("/{item_id}")
@invalidate_on_write(CACHE_PATTERN_WORKLIST)
async def update_worklist_item(
    item_id: UUID,
    body: WorklistUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST))],
):
    """Update a worklist item. Admin or Technologist only. Invalidates cached worklist."""
    result = await db.execute(select(WorklistItem).where(WorklistItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Worklist item", str(item_id))

    update_data = body.model_dump(exclude_unset=True)
    # 전후 대조는 setattr 전에 떠 둔다 — 감사의 핵심이 "무엇이 무엇으로" 바뀌었는지다
    changes = {}
    for key, value in update_data.items():
        before = getattr(item, key, None)
        if before != value:
            changes[key] = {"from": _enum_str(before), "to": _enum_str(value)}
        setattr(item, key, value)

    await db.commit()
    await db.refresh(item)
    await _audit_worklist(db, user, "WORKLIST_UPDATED", item,
                          {"changes": changes or None})
    return _to_response(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
@invalidate_on_write(CACHE_PATTERN_WORKLIST)
async def delete_worklist_item(
    item_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Delete a worklist item. Admin only. Invalidates cached worklist."""
    result = await db.execute(select(WorklistItem).where(WorklistItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("Worklist item", str(item_id))

    # 삭제 후에는 item 속성을 읽을 수 없으므로 스냅샷을 먼저 뜬다. 감사는 삭제가
    # 실제로 커밋된 뒤에 남긴다(실패한 삭제를 삭제로 기록하지 않기 위해).
    snapshot = {
        "worklist_item_id": str(item.id),
        "accession_number": item.accession_number,
        "patient_id": item.patient_id,
        "modality": item.modality,
        "status": _enum_str(item.status),
        "scheduled_date": str(item.scheduled_date),
    }

    await db.delete(item)
    await db.commit()

    await _log_audit_entry(
        db=db, operation="WORKLIST_DELETED", resource_type="WorklistItem",
        status="SUCCESS", user_id=str(user.id), username=user.username,
        details=snapshot,
    )
