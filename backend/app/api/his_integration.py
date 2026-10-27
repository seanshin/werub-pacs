"""HIS (Hospital Information System) → PACS Integration API.

Endpoints that receive requests FROM the HIS/EMR system.
These are the inbound APIs that HIS calls to interact with PACS.

Existing HIS integration:
  - POST /api/v1/orders          → 검사 오더 (order.py)
  - GET  /api/v1/orders/{acc}/status → 오더 상태 조회 (order.py)
  - POST /api/v1/hospitalrun/reports/sync → 판독 결과 동기화 (hospitalrun.py)

This module adds:
  - POST /api/v1/his/retake-request       → 재촬영 요청
  - POST /api/v1/his/cancel-order         → 검사 취소
  - POST /api/v1/his/additional-view      → 추가 촬영 요청
  - POST /api/v1/his/urgent-reading       → 긴급 판독 요청
  - POST /api/v1/his/patient-update       → 환자 정보 수정
  - POST /api/v1/his/clinical-info        → 임상 정보 전송
  - GET  /api/v1/his/report-status        → 판독 상태 조회
  - GET  /api/v1/his/study-status         → 검사 상태 조회
  - POST /api/v1/his/schedule-change      → 검사 일정 변경
  - GET  /api/v1/his/available-slots      → 촬영 가능 시간 조회
"""
import logging
import uuid
from datetime import datetime, date, time, timezone
from typing import Optional

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from app.core.config import settings
from app.core.database import get_async_db
from app.core.security import RequireRole
from app.models.user import User, Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/his", tags=["HIS Integration"])


async def require_his_inbound(x_api_key: str | None = Header(None)) -> str:
    """HIS→PACS 기계간 inbound 서비스 인증(fail-closed).

    기존엔 아무 PACS 사용자 JWT로 호출 가능해 검사취소·환자명변조·STAT 강제가 열려 있었음(P3).
    default-off 게이트 + 전용 X-API-Key(상수시간 비교). HIS 송신측은 연동 합의 시 키를 받아 사용.
    actor 문자열을 반환(감사용 — 본문 actor는 req.* 필드로 별도 기록).
    """
    if not settings.his_inbound_enabled:
        raise HTTPException(503, "HIS inbound 연동이 비활성화되어 있습니다(운영자 설정 필요).")
    expected = settings.his_inbound_api_key
    if not expected or not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "유효하지 않은 HIS 서비스 키")
    return "HIS"


# ─────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────

class HISRetakeRequest(BaseModel):
    """HIS → PACS 재촬영 요청."""
    accession_number: str = Field(..., description="원래 검사 접수번호")
    patient_id: str = Field(..., description="환자 MRN")
    patient_name: str = Field(..., description="환자명")
    reason: str = Field(..., description="재촬영 사유")
    category: str = Field("quality", description="quality|positioning|motion|incomplete|other")
    urgency: str = Field("routine", description="routine|urgent|stat")
    requesting_physician: str = Field(..., description="요청 의사명")
    requesting_department: Optional[str] = Field(None, description="요청 부서")
    his_order_id: Optional[str] = Field(None, description="HIS 오더 ID")
    notes: Optional[str] = None


class HISCancelOrder(BaseModel):
    """HIS → PACS 검사 취소."""
    accession_number: str = Field(..., description="취소할 검사 접수번호")
    reason: str = Field(..., description="취소 사유")
    cancelled_by: str = Field(..., description="취소 요청자")
    his_order_id: Optional[str] = None


class HISAdditionalView(BaseModel):
    """HIS → PACS 추가 촬영 요청."""
    accession_number: str = Field(..., description="원래 검사 접수번호")
    patient_id: str = Field(..., description="환자 MRN")
    patient_name: str = Field(..., description="환자명")
    modality: str = Field(..., description="모달리티 (CR, CT, MR 등)")
    body_part: Optional[str] = Field(None, description="검사 부위")
    view_description: str = Field(..., description="추가 촬영 설명 (예: Lateral view)")
    reason: str = Field(..., description="추가 촬영 사유")
    requesting_physician: str = Field(..., description="요청 의사")
    urgency: str = Field("routine", description="routine|urgent|stat")
    his_order_id: Optional[str] = None


class HISUrgentReading(BaseModel):
    """HIS → PACS 긴급 판독 요청."""
    study_instance_uid: Optional[str] = Field(None, description="Study UID (알고 있는 경우)")
    accession_number: Optional[str] = Field(None, description="접수번호")
    patient_id: str = Field(..., description="환자 MRN")
    reason: str = Field(..., description="긴급 판독 사유")
    clinical_context: Optional[str] = Field(None, description="임상 상황")
    requesting_physician: str = Field(..., description="요청 의사")
    requesting_department: Optional[str] = None
    callback_url: Optional[str] = Field(None, description="결과 콜백 URL")


class HISPatientUpdate(BaseModel):
    """HIS → PACS 환자 정보 수정."""
    patient_id: str = Field(..., description="환자 MRN")
    patient_name: Optional[str] = Field(None, description="수정된 환자명")
    patient_birth_date: Optional[str] = Field(None, description="생년월일 YYYY-MM-DD")
    patient_sex: Optional[str] = Field(None, description="M|F|O")
    phone: Optional[str] = None
    address: Optional[str] = None
    allergy_info: Optional[str] = Field(None, description="알레르기 정보 (조영제 등)")
    insurance_type: Optional[str] = Field(None, description="보험 유형")


class HISClinicalInfo(BaseModel):
    """HIS → PACS 임상 정보 전송 (판독 참고)."""
    study_instance_uid: Optional[str] = Field(None, description="Study UID")
    accession_number: Optional[str] = Field(None, description="접수번호")
    patient_id: str = Field(..., description="환자 MRN")
    clinical_history: Optional[str] = Field(None, description="병력 요약")
    current_symptoms: Optional[str] = Field(None, description="현재 증상")
    lab_results: Optional[str] = Field(None, description="검사 결과 요약")
    medications: Optional[str] = Field(None, description="현재 투약 목록")
    allergy_info: Optional[str] = Field(None, description="알레르기")
    clinical_question: Optional[str] = Field(None, description="임상 질문 (판독의에게)")
    requesting_physician: str = Field(..., description="전송 의사")


class HISScheduleChange(BaseModel):
    """HIS → PACS 검사 일정 변경."""
    accession_number: str = Field(..., description="접수번호")
    new_date: str = Field(..., description="변경 날짜 YYYY-MM-DD")
    new_time: Optional[str] = Field(None, description="변경 시간 HH:MM")
    reason: Optional[str] = Field(None, description="변경 사유")
    changed_by: str = Field(..., description="변경 요청자")



async def _insert_request(db: AsyncSession, req_type: str, **kwargs) -> str:
    import json
    req_id = str(uuid.uuid4())
    payload = kwargs.pop("payload", {})
    await db.execute(text("""
        INSERT INTO his_requests (id, request_type, accession_number, study_instance_uid,
            patient_id, patient_name, status, payload, requested_by, requesting_department,
            his_order_id, callback_url)
        VALUES (:id, :type, :acc, :study_uid, :pid, :pname, 'received', :payload,
            :req_by, :req_dept, :his_id, :callback)
    """), {
        "id": req_id, "type": req_type,
        "acc": kwargs.get("accession_number"),
        "study_uid": kwargs.get("study_instance_uid"),
        "pid": kwargs.get("patient_id", ""),
        "pname": kwargs.get("patient_name"),
        "req_by": kwargs.get("requested_by"),
        "req_dept": kwargs.get("requesting_department"),
        "his_id": kwargs.get("his_order_id"),
        "callback": kwargs.get("callback_url"),
        "payload": json.dumps(payload, ensure_ascii=False, default=str),
    })
    await db.commit()
    return req_id


# ─────────────────────────────────────────────
# 1. 재촬영 요청 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/retake-request", summary="재촬영 요청 (HIS→PACS)",
    description="HIS에서 재촬영이 필요한 경우 PACS에 요청합니다. "
                "방사선사 워크리스트에 재촬영 항목이 추가됩니다.")
async def his_retake_request(
    req: HISRetakeRequest,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="retake",
        accession_number=req.accession_number,
        patient_id=req.patient_id,
        patient_name=req.patient_name,
        requested_by=req.requesting_physician,
        requesting_department=req.requesting_department,
        his_order_id=req.his_order_id,
        payload=req.model_dump(),
    )

    # Also create retake_requests entry
    try:
        await db.execute(text("""
            INSERT INTO retake_requests (id, study_instance_uid, reason, category, urgency,
                status, notes, requested_by, patient_id, patient_name)
            VALUES (:id, :study_uid, :reason, :category, :urgency, 'requested',
                :notes, :req_by, :pid, :pname)
        """), {
            "id": str(uuid.uuid4()),
            "study_uid": req.accession_number,  # will be resolved later
            "reason": req.reason,
            "category": req.category,
            "urgency": req.urgency,
            "notes": f"[HIS] {req.requesting_department or ''} {req.notes or ''}".strip(),
            "req_by": req.requesting_physician,
            "pid": req.patient_id,
            "pname": req.patient_name,
        })
        await db.commit()
    except Exception:
        await db.rollback()

    # Send alert to technologist
    try:
        from app.services.alert_service import alert_retake_request
        await alert_retake_request(
            patient_name=req.patient_name, reason=req.reason,
            requested_by=req.requesting_physician,
            accession=req.accession_number, urgency=req.urgency,
        )
    except Exception as e:
        logger.debug("Retake alert failed: %s", e)

    logger.info("HIS retake request: acc=%s patient=%s", req.accession_number, req.patient_id)
    return {
        "request_id": req_id,
        "status": "received",
        "message": "재촬영 요청이 접수되었습니다. 방사선사에게 알림이 전송됩니다.",
    }


# ─────────────────────────────────────────────
# 2. 검사 취소 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/cancel-order", summary="검사 취소 (HIS→PACS)",
    description="HIS에서 검사 오더를 취소합니다. 워크리스트에서 제거됩니다.")
async def his_cancel_order(
    req: HISCancelOrder,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="cancel",
        accession_number=req.accession_number,
        patient_id="",
        requested_by=req.cancelled_by,
        his_order_id=req.his_order_id,
        payload=req.model_dump(),
    )

    # Update worklist status
    try:
        result = await db.execute(text(
            "UPDATE worklist_items SET status = 'CANCELLED', notes = COALESCE(notes, '') || :note "
            "WHERE accession_number = :acc AND status NOT IN ('COMPLETED', 'CANCELLED')"
        ), {"acc": req.accession_number, "note": f"\n[취소] {req.reason} ({req.cancelled_by})"})
        await db.commit()
        cancelled = result.rowcount or 0
    except Exception:
        await db.rollback()
        cancelled = 0

    logger.info("HIS cancel order: acc=%s by=%s", req.accession_number, req.cancelled_by)
    return {
        "request_id": req_id,
        "status": "cancelled" if cancelled > 0 else "not_found",
        "cancelled_count": cancelled,
        "message": f"검사가 취소되었습니다." if cancelled > 0 else "해당 접수번호의 대기 중인 검사가 없습니다.",
    }


# ─────────────────────────────────────────────
# 3. 추가 촬영 요청 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/additional-view", summary="추가 촬영 요청 (HIS→PACS)",
    description="기존 검사에 대해 추가 뷰/촬영을 요청합니다.")
async def his_additional_view(
    req: HISAdditionalView,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="additional_view",
        accession_number=req.accession_number,
        patient_id=req.patient_id,
        patient_name=req.patient_name,
        requested_by=req.requesting_physician,
        his_order_id=req.his_order_id,
        payload=req.model_dump(),
    )

    logger.info("HIS additional view: acc=%s view=%s", req.accession_number, req.view_description)
    return {
        "request_id": req_id,
        "status": "received",
        "message": f"추가 촬영 요청이 접수되었습니다: {req.view_description}",
    }


# ─────────────────────────────────────────────
# 4. 긴급 판독 요청 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/urgent-reading", summary="긴급 판독 요청 (HIS→PACS)",
    description="응급 상황 등에서 긴급 판독을 요청합니다. "
                "판독 큐에서 최상위로 올라가며 당직의에게 알림이 전송됩니다.")
async def his_urgent_reading(
    req: HISUrgentReading,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="urgent_reading",
        accession_number=req.accession_number,
        study_instance_uid=req.study_instance_uid,
        patient_id=req.patient_id,
        requested_by=req.requesting_physician,
        requesting_department=req.requesting_department,
        callback_url=req.callback_url,
        payload=req.model_dump(),
    )

    # Update worklist urgency if accession number exists
    if req.accession_number:
        try:
            await db.execute(text(
                "UPDATE worklist_items SET priority = 'STAT', "
                "notes = COALESCE(notes, '') || :note "
                "WHERE accession_number = :acc"
            ), {
                "acc": req.accession_number,
                "note": f"\n[긴급판독] {req.reason} ({req.requesting_physician})",
            })
            await db.commit()
        except Exception:
            await db.rollback()

    # Send urgent reading alert
    try:
        from app.services.alert_service import alert_urgent_reading
        await alert_urgent_reading(
            patient_id=req.patient_id, reason=req.reason,
            requesting_physician=req.requesting_physician,
            study_uid=req.study_instance_uid or "",
            department=req.requesting_department or "",
        )
    except Exception as e:
        logger.debug("Urgent reading alert failed: %s", e)

    logger.info("HIS urgent reading: patient=%s reason=%s", req.patient_id, req.reason)
    return {
        "request_id": req_id,
        "status": "received",
        "priority": "STAT",
        "message": "긴급 판독 요청이 접수되었습니다. 당직 판독의에게 알림이 전송됩니다.",
    }


# ─────────────────────────────────────────────
# 5. 환자 정보 수정 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/patient-update", summary="환자 정보 수정 (HIS→PACS)",
    description="HIS에서 환자 인적사항이 변경된 경우 PACS에 동기화합니다. "
                "워크리스트와 환자 매핑 테이블이 업데이트됩니다.")
async def his_patient_update(
    req: HISPatientUpdate,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="patient_update",
        patient_id=req.patient_id,
        patient_name=req.patient_name,
        requested_by="HIS",
        payload=req.model_dump(exclude_none=True),
    )

    # Update patient_mappings
    updates = []
    params: dict = {"pid": req.patient_id}
    if req.patient_name:
        updates.append("his_patient_name = :pname")
        updates.append("dicom_patient_name = :pname")
        params["pname"] = req.patient_name
    if updates:
        try:
            await db.execute(text(
                f"UPDATE patient_mappings SET {', '.join(updates)} WHERE his_mrn = :pid"
            ), params)
            await db.commit()
        except Exception:
            await db.rollback()

    # Update worklist entries
    if req.patient_name:
        try:
            await db.execute(text(
                "UPDATE worklist_items SET patient_name = :pname WHERE patient_id = :pid "
                "AND status NOT IN ('COMPLETED', 'CANCELLED')"
            ), {"pname": req.patient_name, "pid": req.patient_id})
            await db.commit()
        except Exception:
            await db.rollback()

    logger.info("HIS patient update: %s", req.patient_id)
    return {
        "request_id": req_id,
        "status": "updated",
        "message": f"환자 정보가 업데이트되었습니다: {req.patient_id}",
    }


# ─────────────────────────────────────────────
# 6. 임상 정보 전송 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/clinical-info", summary="임상 정보 전송 (HIS→PACS)",
    description="판독의가 참고할 임상 정보(병력, 증상, 검사결과, 투약, 알레르기)를 전송합니다. "
                "판독 화면에서 해당 정보가 표시됩니다.")
async def his_clinical_info(
    req: HISClinicalInfo,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="clinical_info",
        accession_number=req.accession_number,
        study_instance_uid=req.study_instance_uid,
        patient_id=req.patient_id,
        requested_by=req.requesting_physician,
        payload=req.model_dump(exclude_none=True),
    )

    # Update worklist clinical_info
    if req.accession_number:
        clinical_text = "\n".join(filter(None, [
            f"[병력] {req.clinical_history}" if req.clinical_history else None,
            f"[증상] {req.current_symptoms}" if req.current_symptoms else None,
            f"[검사] {req.lab_results}" if req.lab_results else None,
            f"[투약] {req.medications}" if req.medications else None,
            f"[알레르기] {req.allergy_info}" if req.allergy_info else None,
            f"[질문] {req.clinical_question}" if req.clinical_question else None,
        ]))
        try:
            await db.execute(text(
                "UPDATE worklist_items SET clinical_info = :info WHERE accession_number = :acc"
            ), {"info": clinical_text, "acc": req.accession_number})
            await db.commit()
        except Exception:
            await db.rollback()

    logger.info("HIS clinical info: patient=%s acc=%s", req.patient_id, req.accession_number)
    return {
        "request_id": req_id,
        "status": "received",
        "message": "임상 정보가 접수되었습니다. 판독의에게 표시됩니다.",
    }


# ─────────────────────────────────────────────
# 7. 판독 상태 조회 (HIS → PACS)
# ─────────────────────────────────────────────

@router.get("/report-status", summary="판독 상태 조회 (HIS→PACS)",
    description="접수번호 또는 Study UID로 판독 상태를 조회합니다.")
async def his_report_status(
    accession_number: Optional[str] = Query(None, description="접수번호"),
    study_uid: Optional[str] = Query(None, description="Study Instance UID"),
    patient_id: Optional[str] = Query(None, description="환자 MRN"),
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    if not any([accession_number, study_uid, patient_id]):
        raise HTTPException(400, "accession_number, study_uid, 또는 patient_id 중 하나는 필수입니다")

    where_clauses = []
    params: dict = {}
    if accession_number:
        where_clauses.append("w.accession_number = :acc")
        params["acc"] = accession_number
    if study_uid:
        where_clauses.append("r.study_instance_uid = :study_uid")
        params["study_uid"] = study_uid
    if patient_id:
        where_clauses.append("w.patient_id = :pid")
        params["pid"] = patient_id

    try:
        result = await db.execute(text(f"""
            SELECT w.accession_number, w.patient_id, w.patient_name, w.modality,
                   w.status as worklist_status,
                   r.id as report_id, r.status as report_status,
                   r.findings, r.impression, r.signed_at, r.author_name,
                   r.study_instance_uid
            FROM worklist_items w
            LEFT JOIN reports r ON r.study_instance_uid = w.study_instance_uid
            WHERE {' AND '.join(where_clauses)}
            ORDER BY w.scheduled_date DESC
            LIMIT 10
        """), params)
        rows = result.fetchall()
    except Exception:
        rows = []

    items = []
    for r in rows:
        items.append({
            "accession_number": r[0], "patient_id": r[1], "patient_name": r[2],
            "modality": r[3], "worklist_status": r[4],
            "report_id": str(r[5]) if r[5] else None,
            "report_status": r[6],
            "has_findings": bool(r[7]),
            "has_impression": bool(r[8]),
            "signed_at": r[9].isoformat() if r[9] else None,
            "author": r[10],
            "study_instance_uid": r[11],
        })

    return {"items": items, "total": len(items)}


# ─────────────────────────────────────────────
# 8. 검사 상태 조회 (HIS → PACS)
# ─────────────────────────────────────────────

@router.get("/study-status", summary="검사 상태 조회 (HIS→PACS)",
    description="접수번호로 검사 촬영 상태와 영상 수신 여부를 조회합니다.")
async def his_study_status(
    accession_number: str = Query(..., description="접수번호"),
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    try:
        result = await db.execute(text("""
            SELECT accession_number, patient_id, patient_name, modality,
                   status, study_instance_uid, scheduled_date, scheduled_time,
                   priority, body_part_examined, clinical_info
            FROM worklist_items WHERE accession_number = :acc
        """), {"acc": accession_number})
        row = result.fetchone()
    except Exception:
        row = None

    if not row:
        raise HTTPException(404, f"접수번호 {accession_number}에 해당하는 검사가 없습니다")

    has_images = False
    series_count = 0
    instance_count = 0
    if row[5]:  # study_instance_uid exists
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                search = await client.post(
                    "http://orthanc:8042/tools/find",
                    json={"Level": "Study", "Query": {"StudyInstanceUID": row[5]}},
                    auth=(settings.orthanc_username, settings.orthanc_password),
                )
                if search.status_code == 200 and search.json():
                    oid = search.json()[0]
                    study = await client.get(f"http://orthanc:8042/studies/{oid}", auth=(settings.orthanc_username, settings.orthanc_password))
                    sdata = study.json()
                    series_count = len(sdata.get("Series", []))
                    instance_count = sdata.get("MainDicomTags", {}).get("NumberOfStudyRelatedInstances", 0)
                    has_images = series_count > 0
        except Exception:
            pass

    return {
        "accession_number": row[0],
        "patient_id": row[1],
        "patient_name": row[2],
        "modality": row[3],
        "worklist_status": row[4],
        "study_instance_uid": row[5],
        "scheduled_date": str(row[6]) if row[6] else None,
        "scheduled_time": str(row[7]) if row[7] else None,
        "priority": row[8],
        "body_part": row[9],
        "clinical_info": row[10],
        "has_images": has_images,
        "series_count": series_count,
        "instance_count": instance_count,
    }


# ─────────────────────────────────────────────
# 9. 검사 일정 변경 (HIS → PACS)
# ─────────────────────────────────────────────

@router.post("/schedule-change", summary="검사 일정 변경 (HIS→PACS)",
    description="예약된 검사의 날짜/시간을 변경합니다.")
async def his_schedule_change(
    req: HISScheduleChange,
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    req_id = await _insert_request(db,
        req_type="schedule_change",
        accession_number=req.accession_number,
        patient_id="",
        requested_by=req.changed_by,
        payload=req.model_dump(),
    )

    try:
        new_date = datetime.strptime(req.new_date, "%Y-%m-%d").date()
        new_time = None
        if req.new_time:
            parts = req.new_time.split(":")
            new_time = time(int(parts[0]), int(parts[1]))

        update_parts = ["scheduled_date = :new_date"]
        params: dict = {"acc": req.accession_number, "new_date": new_date}
        if new_time:
            update_parts.append("scheduled_time = :new_time")
            params["new_time"] = new_time
        update_parts.append("notes = COALESCE(notes, '') || :note")
        params["note"] = f"\n[일정변경] {req.new_date} {req.new_time or ''} ({req.changed_by}) {req.reason or ''}"

        result = await db.execute(text(
            f"UPDATE worklist_items SET {', '.join(update_parts)} "
            "WHERE accession_number = :acc AND status NOT IN ('COMPLETED', 'CANCELLED')"
        ), params)
        await db.commit()
        updated = result.rowcount or 0
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, f"일정 변경 실패: {str(e)}")

    logger.info("HIS schedule change: acc=%s → %s %s", req.accession_number, req.new_date, req.new_time)
    return {
        "request_id": req_id,
        "status": "updated" if updated > 0 else "not_found",
        "message": f"검사 일정이 {req.new_date} {req.new_time or ''}(으)로 변경되었습니다." if updated > 0
                   else "해당 접수번호의 대기 중인 검사가 없습니다.",
    }


# ─────────────────────────────────────────────
# 10. 촬영 가능 시간 조회 (HIS → PACS)
# ─────────────────────────────────────────────

@router.get("/available-slots", summary="촬영 가능 시간 조회 (HIS→PACS)",
    description="특정 모달리티/날짜의 촬영 가능 시간대를 조회합니다.")
async def his_available_slots(
    modality: str = Query(..., description="모달리티 (CT, MR, CR 등)"),
    target_date: str = Query(..., description="조회 날짜 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_async_db),
    _actor: str = Depends(require_his_inbound),
):
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "날짜 형식 오류: YYYY-MM-DD")

    # Get booked slots
    try:
        result = await db.execute(text("""
            SELECT scheduled_time FROM worklist_items
            WHERE modality = :mod AND scheduled_date = :d
              AND status NOT IN ('COMPLETED', 'CANCELLED')
            ORDER BY scheduled_time
        """), {"mod": modality.upper(), "d": d})
        booked_times = [str(r[0]) if r[0] else None for r in result.fetchall()]
    except Exception:
        booked_times = []

    # Generate available slots (08:00 - 17:00, 30min intervals)
    all_slots = [f"{h:02d}:{m:02d}" for h in range(8, 17) for m in (0, 30)]
    booked_set = set()
    for bt in booked_times:
        if bt:
            booked_set.add(bt[:5])

    available = [s for s in all_slots if s not in booked_set]

    return {
        "modality": modality.upper(),
        "date": target_date,
        "total_slots": len(all_slots),
        "booked": len(booked_set),
        "available": len(available),
        "slots": available,
    }


# ─────────────────────────────────────────────
# HIS 요청 이력 조회
# ─────────────────────────────────────────────

@router.get("/requests", summary="HIS 요청 이력 조회",
    description="HIS에서 수신한 모든 요청의 이력을 조회합니다.")
async def list_his_requests(
    request_type: Optional[str] = Query(None, description="요청 유형 필터"),
    status: Optional[str] = Query(None, description="상태 필터"),
    patient_id: Optional[str] = Query(None, description="환자 MRN"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST)),  # PACS 운영 조회 — researcher 제외
):
    where = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if request_type:
        where += " AND request_type = :type"
        params["type"] = request_type
    if status:
        where += " AND status = :status"
        params["status"] = status
    if patient_id:
        where += " AND patient_id = :pid"
        params["pid"] = patient_id

    result = await db.execute(text(f"""
        SELECT id, request_type, accession_number, study_instance_uid, patient_id,
               patient_name, status, payload, requested_by, requesting_department,
               his_order_id, created_at, processed_at, processed_by
        FROM his_requests {where}
        ORDER BY created_at DESC LIMIT :limit OFFSET :offset
    """), params)

    items = [{
        "id": str(r[0]), "request_type": r[1], "accession_number": r[2],
        "study_instance_uid": r[3], "patient_id": r[4], "patient_name": r[5],
        "status": r[6], "payload": r[7], "requested_by": r[8],
        "requesting_department": r[9], "his_order_id": r[10],
        "created_at": r[11].isoformat() if r[11] else None,
        "processed_at": r[12].isoformat() if r[12] else None,
        "processed_by": r[13],
    } for r in result.fetchall()]

    count_result = await db.execute(text(f"SELECT COUNT(*) FROM his_requests {where}"), params)
    total = count_result.scalar() or 0

    return {"items": items, "total": total}


@router.post("/sync-orders", summary="HospitalRun IMAGING 오더 동기화 (관리자, 온디맨드)")
async def sync_hospitalrun_orders(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Pull HospitalRun IMAGING orders into the OpenPACS worklist on demand.

    Read-only against HospitalRun via the verified schema path
    (orders → prescriptions.encounter_id → encounters.patient_id → patients.mrn,
    department='IMAGING'). Replaces the disabled, broken legacy poll. Creates
    worklist items + patient mappings idempotently. Requires
    ``settings.hospitalrun_db_url`` to be configured (opt-in).
    """
    if not settings.hospitalrun_db_url:
        raise HTTPException(
            status_code=503,
            detail="hospitalrun_db_url is not configured — order sync is disabled.",
        )
    from app.services.his_order_sync import sync_imaging_orders
    try:
        result = await sync_imaging_orders(settings.hospitalrun_db_url, db)
    except Exception as e:  # surface connection/schema errors without 500-crash
        logger.warning("HIS order sync failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="HospitalRun 오더 동기화에 실패했습니다. 서버 로그를 확인하세요.",
        )
    return {"ok": True, **result}


@router.post("/reconcile-merges", summary="환자 병합 재조정 (관리자, 온디맨드)")
async def reconcile_patient_merges(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Consolidate imaging of merged-away HospitalRun patients under the surviving MRN.

    Reads HospitalRun ``patients.merged_into_id`` (read-only), re-tags Orthanc
    studies from the old MRN to the surviving patient, and updates patient
    mappings (source='merge'). Idempotent. Requires ``hospitalrun_db_url``.
    """
    if not settings.hospitalrun_db_url:
        raise HTTPException(
            status_code=503,
            detail="hospitalrun_db_url is not configured — merge reconcile is disabled.",
        )
    from app.services.his_patient_merge import reconcile_merged_patients
    try:
        result = await reconcile_merged_patients(
            settings.hospitalrun_db_url, db, request.app.state.http_client
        )
    except Exception as e:
        logger.warning("Patient-merge reconcile failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="환자 병합 재조정에 실패했습니다. 서버 로그를 확인하세요.",
        )
    return {"ok": True, **result}
