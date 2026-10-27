"""티칭파일 라이브러리 API — 판독 교육용 케이스/태그/컬렉션.

라이브 study 참조 + RBAC. 조회 ADMIN/RAD/RESIDENT, 생성·수정 ADMIN/RAD(+RESIDENT 승격 기여),
삭제 ADMIN 전용(BTG 차단). enum NAME 함정 회피 — difficulty는 문자열+앱 검증.
"""
import logging
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID as PyUUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.anonymize import _hash_id
from app.api.audit import AuditLogger, _log_audit_entry
from app.core.database import get_db
from app.core.security import RequireRole
from app.models.teaching import (
    TeachingCase,
    TeachingCaseTag,
    TeachingCollection,
    TeachingCollectionItem,
    TeachingQuizAttempt,
)
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/teaching", tags=["teaching"])

ReadRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.RESIDENT)
WriteRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)  # RESIDENT 승격 기여 허용(의도), 단 BTG 우회는 차단(교육 쓰기는 응급 read 아님)
AdminOnly = RequireRole(Role.ADMIN, allow_btg=False)     # 삭제 — BTG 우회 차단
# 익명화 export — 데이터 반출이라 BTG 차단. RESIDENT는 _assert_attending로 추가 차단(승격 통과 방지).
ExportRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)

Difficulty = Literal["beginner", "intermediate", "advanced"]
Assessment = Literal["correct", "partial", "incorrect"]
PublishStatus = Literal["draft", "pending", "published", "rejected"]
_IMAGING_SKIP = {"SR", "KO", "PR"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_attending(user: User) -> None:
    """게시 승인/반려는 전문의 전용. RequireRole이 RESIDENT를 RAD로 승격하므로 실제 역할로 차단."""
    if user.role == Role.RESIDENT:
        raise HTTPException(403, "게시 승인/반려는 전문의(ADMIN/RADIOLOGIST)만 가능합니다.")


# ─── Schemas ────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    study_instance_uid: str
    title: str
    summary: str | None = None
    diagnosis: str | None = None
    organ: str | None = None
    difficulty: Difficulty = "intermediate"
    report_id: PyUUID | None = None
    tags: list[str] = Field(default_factory=list)
    is_published: bool = False


class CaseUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    diagnosis: str | None = None
    organ: str | None = None
    difficulty: Difficulty | None = None
    report_id: PyUUID | None = None
    tags: list[str] | None = None
    is_published: bool | None = None


class CollectionCreate(BaseModel):
    title: str
    description: str | None = None
    is_published: bool = False


class CollectionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    is_published: bool | None = None


class CollectionItemAdd(BaseModel):
    case_id: PyUUID


class CollectionReorder(BaseModel):
    case_ids: list[PyUUID]


class QuizSubmit(BaseModel):
    answer: str = Field(..., min_length=1, max_length=4000)
    time_spent_ms: int | None = Field(None, ge=0)


class QuizAssess(BaseModel):
    self_assessment: Assessment


class RejectBody(BaseModel):
    comment: str | None = Field(None, max_length=2000)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _norm_tags(tags: list[str]) -> list[str]:
    """trim·lower·dedup, 빈 값 제거."""
    out: list[str] = []
    seen = set()
    for t in tags or []:
        t = (t or "").strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t[:64])
    return out


def _primary_modality(modalities: str) -> str:
    for m in (modalities or "").replace("\\", ",").split(","):
        m = m.strip().upper()
        if m and m not in _IMAGING_SKIP:
            return m
    return (modalities or "").split(",")[0].strip().upper()


async def _capture_study_meta(client, study_uid: str) -> dict | None:
    """StudyInstanceUID로 Orthanc 조회 → modality/orthanc_id/나이/성별 캡처.

    None이면 study 미존재(등록 거부). 이름/MRN은 캡처하지 않는다.
    """
    try:
        resp = await client.post("/tools/find", json={
            "Level": "Study",
            "Query": {"StudyInstanceUID": study_uid},
            "Expand": True,
            "RequestedTags": ["ModalitiesInStudy"],
        })
        if resp.status_code != 200:
            return None
        found = resp.json()
        if not found:
            return None
        sd = found[0]
        tags = sd.get("MainDicomTags", {})
        ptags = sd.get("PatientMainDicomTags", {})
        rtags = sd.get("RequestedTags", {})
        modality = _primary_modality(rtags.get("ModalitiesInStudy", "") or tags.get("ModalitiesInStudy", ""))
        if not modality:
            series = sd.get("Series", [])
            if series:
                try:
                    ser = await client.get(f"/series/{series[0]}")
                    if ser.status_code == 200:
                        modality = (ser.json().get("MainDicomTags", {}).get("Modality", "") or "").strip().upper()
                except Exception:
                    pass
        return {
            "orthanc_study_id": sd.get("ID"),
            "modality": modality or None,
            "patient_age": (tags.get("PatientAge") or "").strip()[:8] or None,
            "patient_sex": (ptags.get("PatientSex") or "").strip()[:8] or None,
        }
    except Exception as e:
        logger.warning(f"teaching study meta capture failed for {study_uid}: {e}")
        return None


async def _study_available(client, study_uid: str) -> bool:
    try:
        resp = await client.post("/tools/find", json={
            "Level": "Study", "Query": {"StudyInstanceUID": study_uid},
        })
        return resp.status_code == 200 and bool(resp.json())
    except Exception:
        return False


async def _tags_for(db: AsyncSession, case_ids: list[PyUUID]) -> dict:
    """case_id → [tag] 배치 조회(N+1 회피)."""
    if not case_ids:
        return {}
    rows = await db.execute(
        select(TeachingCaseTag.case_id, TeachingCaseTag.tag).where(TeachingCaseTag.case_id.in_(case_ids))
    )
    out: dict = {}
    for cid, tag in rows.all():
        out.setdefault(cid, []).append(tag)
    return out


def _summary(c: TeachingCase, tags: list[str]) -> dict:
    return {
        "id": str(c.id),
        "title": c.title,
        "modality": c.modality,
        "organ": c.organ,
        "difficulty": c.difficulty,
        "is_published": c.is_published,
        "publish_status": c.publish_status,
        "view_count": c.view_count,
        "tags": tags,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _detail(c: TeachingCase, tags: list[str], study_available: bool | None = None) -> dict:
    d = _summary(c, tags)
    d.update({
        "study_instance_uid": c.study_instance_uid,
        "orthanc_study_id": c.orthanc_study_id,
        "summary": c.summary,
        "diagnosis": c.diagnosis,
        "patient_age": c.patient_age,
        "patient_sex": c.patient_sex,
        "report_id": str(c.report_id) if c.report_id else None,
        "created_by_name": c.created_by_name,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
        "reviewed_by_name": c.reviewed_by_name,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "review_comment": c.review_comment,
    })
    if study_available is not None:
        d["study_available"] = study_available
    return d


def _review_state(c: TeachingCase) -> dict:
    return {
        "id": str(c.id),
        "publish_status": c.publish_status,
        "is_published": c.is_published,
        "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
        "reviewed_by_name": c.reviewed_by_name,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "review_comment": c.review_comment,
    }


# ─── Cases ──────────────────────────────────────────────────────────────────

@router.post("/cases", summary="티칭 케이스 등록", status_code=201)
@AuditLogger.log("TEACHING_CASE_CREATED", "TeachingCase")
async def create_case(
    body: CaseCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    meta = await _capture_study_meta(request.app.state.http_client, body.study_instance_uid)
    if meta is None:
        raise HTTPException(400, "등록할 study를 찾을 수 없습니다.")

    # 전문의(ADMIN/RAD)는 생성 시 즉시 게시(self-approve) 가능. RESIDENT는 is_published 무시→draft.
    attending = user.role != Role.RESIDENT
    publish_now = bool(body.is_published) and attending
    who = user.full_name or user.username
    c = TeachingCase(
        study_instance_uid=body.study_instance_uid,
        orthanc_study_id=meta["orthanc_study_id"],
        title=body.title,
        summary=body.summary,
        diagnosis=body.diagnosis,
        modality=meta["modality"],
        organ=body.organ,
        difficulty=body.difficulty,
        patient_age=meta["patient_age"],
        patient_sex=meta["patient_sex"],
        report_id=body.report_id,
        created_by_id=user.id,
        created_by_name=who,
        is_published=publish_now,
        publish_status="published" if publish_now else "draft",
        reviewed_by_id=user.id if publish_now else None,
        reviewed_by_name=who if publish_now else None,
        reviewed_at=_now() if publish_now else None,
    )
    db.add(c)
    await db.flush()
    tags = _norm_tags(body.tags)
    for t in tags:
        db.add(TeachingCaseTag(case_id=c.id, tag=t))
    await db.commit()
    await db.refresh(c)
    logger.info(f"teaching case created: {c.id} ({c.modality}) by {user.username}")
    return _detail(c, tags, study_available=True)


@router.get("/cases", summary="티칭 케이스 검색/목록")
async def list_cases(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
    q: str | None = Query(None, description="제목/요약/진단 키워드"),
    modality: str | None = Query(None),
    difficulty: str | None = Query(None),
    organ: str | None = Query(None),
    tag: str | None = Query(None),
    published: bool | None = Query(None),
    status: str | None = Query(None, description="draft|pending|published|rejected"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
):
    page_size = min(page_size, 100)   # 상한 클램프(거부 대신) — 설계 계약
    stmt = select(TeachingCase)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            TeachingCase.title.ilike(like)
            | TeachingCase.summary.ilike(like)
            | TeachingCase.diagnosis.ilike(like)
        )
    if modality:
        stmt = stmt.where(TeachingCase.modality == modality.strip().upper())
    if difficulty:
        stmt = stmt.where(TeachingCase.difficulty == difficulty.strip().lower())
    if organ:
        stmt = stmt.where(TeachingCase.organ.ilike(f"%{organ}%"))
    if published is not None:
        stmt = stmt.where(TeachingCase.is_published == published)
    if status:
        stmt = stmt.where(TeachingCase.publish_status == status.strip().lower())
    if tag:
        sub = select(TeachingCaseTag.case_id).where(TeachingCaseTag.tag == tag.strip().lower())
        stmt = stmt.where(TeachingCase.id.in_(sub))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(TeachingCase.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    tagmap = await _tags_for(db, [c.id for c in rows])
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_summary(c, tagmap.get(c.id, [])) for c in rows],
    }


@router.get("/tags", summary="태그 클라우드(빈도순)")
async def list_tags(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    rows = await db.execute(
        select(TeachingCaseTag.tag, func.count().label("n"))
        .group_by(TeachingCaseTag.tag).order_by(func.count().desc())
    )
    return [{"tag": t, "count": n} for t, n in rows.all()]


@router.get("/cases/{case_id}", summary="티칭 케이스 상세")
async def get_case(
    case_id: PyUUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    # 원자 증가(read-modify-write 경쟁 회피)
    await db.execute(
        update(TeachingCase).where(TeachingCase.id == case_id)
        .values(view_count=TeachingCase.view_count + 1)
    )
    await db.commit()
    # commit이 ORM 속성을 만료시키므로 refresh로 재적재(증가된 view_count 포함) —
    # 이후 c.* 접근 시 비동기 컨텍스트 밖 lazy-load(MissingGreenlet) 방지.
    await db.refresh(c)
    tagmap = await _tags_for(db, [c.id])
    avail = await _study_available(request.app.state.http_client, c.study_instance_uid)
    return _detail(c, tagmap.get(c.id, []), study_available=avail)


@router.put("/cases/{case_id}", summary="티칭 케이스 수정")
@AuditLogger.log("TEACHING_CASE_UPDATED", "TeachingCase")
async def update_case(
    case_id: PyUUID,
    body: CaseUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    data = body.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    data.pop("is_published", None)   # 게시 상태는 submit/approve/reject 워크플로로만 변경
    for k, v in data.items():
        setattr(c, k, v)
    if tags is not None:
        await db.execute(delete(TeachingCaseTag).where(TeachingCaseTag.case_id == case_id))
        for t in _norm_tags(tags):
            db.add(TeachingCaseTag(case_id=case_id, tag=t))
    await db.commit()
    await db.refresh(c)
    tagmap = await _tags_for(db, [c.id])
    return _detail(c, tagmap.get(c.id, []))


@router.delete("/cases/{case_id}", summary="티칭 케이스 삭제(ADMIN)")
@AuditLogger.log("TEACHING_CASE_DELETED", "TeachingCase")
async def delete_case(
    case_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(AdminOnly)],
):
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    await db.delete(c)   # tags/collection_items CASCADE
    await db.commit()
    return {"ok": True, "id": str(case_id)}


# ─── Publish approval workflow ───────────────────────────────────────────────
# draft → (submit) → pending → (approve) → published / (reject) → rejected → (submit) …
# RESIDENT는 draft 작성·submit만, 게시 승인/반려는 전문의(ADMIN/RAD). is_published는 published와 동기.

@router.post("/cases/{case_id}/submit", summary="게시 검토 요청")
@AuditLogger.log("TEACHING_CASE_SUBMITTED", "TeachingCase")
async def submit_for_review(
    case_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    if c.publish_status not in ("draft", "rejected"):
        raise HTTPException(409, f"검토 요청할 수 없는 상태입니다: {c.publish_status}")
    c.publish_status = "pending"
    c.submitted_at = _now()
    c.review_comment = None
    await db.commit()
    await db.refresh(c)
    return _review_state(c)


@router.post("/cases/{case_id}/approve", summary="게시 승인(전문의)")
@AuditLogger.log("TEACHING_CASE_APPROVED", "TeachingCase")
async def approve_case(
    case_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    _assert_attending(user)
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    if c.publish_status != "pending":
        raise HTTPException(409, f"승인할 수 없는 상태입니다: {c.publish_status} (검토 대기만 승인 가능)")
    c.publish_status = "published"
    c.is_published = True
    c.reviewed_by_id = user.id
    c.reviewed_by_name = user.full_name or user.username
    c.reviewed_at = _now()
    c.review_comment = None
    await db.commit()
    await db.refresh(c)
    return _review_state(c)


@router.post("/cases/{case_id}/reject", summary="게시 반려(전문의)")
@AuditLogger.log("TEACHING_CASE_REJECTED", "TeachingCase")
async def reject_case(
    case_id: PyUUID,
    body: RejectBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    _assert_attending(user)
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    if c.publish_status != "pending":
        raise HTTPException(409, f"반려할 수 없는 상태입니다: {c.publish_status} (검토 대기만 반려 가능)")
    c.publish_status = "rejected"
    c.is_published = False
    c.reviewed_by_id = user.id
    c.reviewed_by_name = user.full_name or user.username
    c.reviewed_at = _now()
    c.review_comment = body.comment
    await db.commit()
    await db.refresh(c)
    return _review_state(c)


@router.post("/cases/{case_id}/unpublish", summary="게시 취소→초안(ADMIN)")
@AuditLogger.log("TEACHING_CASE_UNPUBLISHED", "TeachingCase")
async def unpublish_case(
    case_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(AdminOnly)],
):
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    if c.publish_status != "published":
        raise HTTPException(409, f"게시 취소할 수 없는 상태입니다: {c.publish_status}")
    c.publish_status = "draft"
    c.is_published = False
    await db.commit()
    await db.refresh(c)
    return _review_state(c)


@router.get("/review-queue", summary="게시 검토 대기 목록(전문의)")
async def review_queue(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    _assert_attending(user)
    rows = (await db.execute(
        select(TeachingCase).where(TeachingCase.publish_status == "pending")
        .order_by(TeachingCase.submitted_at.asc())
    )).scalars().all()
    tagmap = await _tags_for(db, [c.id for c in rows])
    return [
        {**_summary(c, tagmap.get(c.id, [])),
         "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
         "created_by_name": c.created_by_name}
        for c in rows
    ]


# ─── Anonymized export ───────────────────────────────────────────────────────
# 게시(승인)된 티칭 케이스의 익명화 DICOM 사본을 ZIP으로 내려준다(컨퍼런스/외부 공유).
# anonymize.py 재사용. ★KeepSource=True — 라이브 study 참조라 원본을 절대 건드리면 안 됨(임시본만 삭제).

async def _resolve_orthanc_id(client, c: TeachingCase) -> str | None:
    """저장된 orthanc_study_id 우선, 미존재 시 StudyInstanceUID로 재해석(이동/재색인 대비)."""
    if c.orthanc_study_id:
        r = await client.get(f"/studies/{c.orthanc_study_id}")
        if r.status_code == 200:
            return c.orthanc_study_id
    r = await client.post("/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": c.study_instance_uid},
    })
    if r.status_code == 200 and r.json():
        return r.json()[0]
    return None


@router.get("/cases/{case_id}/export", summary="익명화 사본 export(전문의·게시본 한정)")
async def export_anonymized(
    case_id: PyUUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ExportRoles)],
):
    _assert_attending(user)
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    if c.publish_status != "published":
        raise HTTPException(409, "게시(승인)된 케이스만 익명화 export할 수 있습니다.")

    client = request.app.state.http_client
    oid = await _resolve_orthanc_id(client, c)
    if not oid:
        raise HTTPException(409, "원본 영상을 찾을 수 없습니다(삭제/이동됨).")

    # 임시 익명화 사본 생성(KeepSource=True → 원본 불변) → ZIP 다운로드 → 임시본 삭제.
    # Orthanc /anonymize가 DICOM Supp 142 Basic Profile을 기본 적용(PHI 제거/블랭크)하므로 커스텀
    # Remove 리스트는 불필요(미인식 태그명 'MedicalRecordLocator'가 500 유발). PatientName/ID만 치환.
    anon = await client.post(f"/studies/{oid}/anonymize", json={
        "Replace": {"PatientName": "ANON", "PatientID": _hash_id(c.study_instance_uid)},
        "KeepSource": True,
        "Force": True,
    })
    if anon.status_code != 200:
        raise HTTPException(500, f"익명화 실패: {anon.text[:150]}")
    new_id = anon.json().get("ID")
    try:
        zip_resp = await client.get(f"/studies/{new_id}/archive")
        if zip_resp.status_code != 200:
            raise HTTPException(500, "아카이브 다운로드 실패")
        content = zip_resp.content
    finally:
        try:
            await client.delete(f"/studies/{new_id}")   # 원본은 절대 건드리지 않음
        except Exception:
            pass

    suid = c.study_instance_uid
    await _log_audit_entry(
        db, "TEACHING_CASE_EXPORTED", "TeachingCase", "SUCCESS",
        str(user.id), user.full_name or user.username,   # audit_logs.user_id는 VARCHAR — str 필수
        {"case_id": str(case_id), "study_instance_uid": suid, "bytes": len(content)},
    )
    fn = f"teaching_{str(case_id)[:8]}_anon.zip"
    return StreamingResponse(
        iter([content]), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={fn}"},
    )


# ─── Collections ────────────────────────────────────────────────────────────

@router.post("/collections", summary="컬렉션 생성", status_code=201)
async def create_collection(
    body: CollectionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    col = TeachingCollection(
        title=body.title, description=body.description, is_published=body.is_published,
        created_by_id=user.id, created_by_name=user.full_name or user.username,
    )
    db.add(col)
    await db.commit()
    await db.refresh(col)
    return _collection(col, 0)


@router.get("/collections", summary="컬렉션 목록")
async def list_collections(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    rows = (await db.execute(
        select(TeachingCollection).order_by(TeachingCollection.created_at.desc())
    )).scalars().all()
    counts = dict((await db.execute(
        select(TeachingCollectionItem.collection_id, func.count())
        .group_by(TeachingCollectionItem.collection_id)
    )).all())
    return [_collection(col, counts.get(col.id, 0)) for col in rows]


@router.get("/collections/{collection_id}", summary="컬렉션 상세(+항목)")
async def get_collection(
    collection_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    col = await db.get(TeachingCollection, collection_id)
    if not col:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    rows = (await db.execute(
        select(TeachingCase, TeachingCollectionItem.position)
        .join(TeachingCollectionItem, TeachingCollectionItem.case_id == TeachingCase.id)
        .where(TeachingCollectionItem.collection_id == collection_id)
        .order_by(TeachingCollectionItem.position)
    )).all()
    cases = [c for c, _pos in rows]
    tagmap = await _tags_for(db, [c.id for c in cases])
    out = _collection(col, len(cases))
    out["items"] = [_summary(c, tagmap.get(c.id, [])) for c in cases]
    return out


@router.put("/collections/{collection_id}", summary="컬렉션 수정")
async def update_collection(
    collection_id: PyUUID,
    body: CollectionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    col = await db.get(TeachingCollection, collection_id)
    if not col:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(col, k, v)
    await db.commit()
    await db.refresh(col)
    return _collection(col, None)


@router.delete("/collections/{collection_id}", summary="컬렉션 삭제(ADMIN)")
async def delete_collection(
    collection_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(AdminOnly)],
):
    col = await db.get(TeachingCollection, collection_id)
    if not col:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    await db.delete(col)   # items CASCADE
    await db.commit()
    return {"ok": True, "id": str(collection_id)}


@router.post("/collections/{collection_id}/items", summary="컬렉션에 케이스 추가")
async def add_item(
    collection_id: PyUUID,
    body: CollectionItemAdd,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    col = await db.get(TeachingCollection, collection_id)
    if not col:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    case = await db.get(TeachingCase, body.case_id)
    if not case:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    exists = (await db.execute(
        select(TeachingCollectionItem.id).where(
            TeachingCollectionItem.collection_id == collection_id,
            TeachingCollectionItem.case_id == body.case_id,
        )
    )).first()
    if exists:
        return {"ok": True, "duplicate": True}
    nextpos = (await db.execute(
        select(func.coalesce(func.max(TeachingCollectionItem.position), -1) + 1)
        .where(TeachingCollectionItem.collection_id == collection_id)
    )).scalar_one()
    db.add(TeachingCollectionItem(collection_id=collection_id, case_id=body.case_id, position=nextpos))
    await db.commit()
    return {"ok": True, "position": nextpos}


@router.delete("/collections/{collection_id}/items/{case_id}", summary="컬렉션에서 케이스 제거")
async def remove_item(
    collection_id: PyUUID,
    case_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    await db.execute(delete(TeachingCollectionItem).where(
        TeachingCollectionItem.collection_id == collection_id,
        TeachingCollectionItem.case_id == case_id,
    ))
    await db.commit()
    return {"ok": True}


@router.put("/collections/{collection_id}/reorder", summary="컬렉션 항목 순서 변경")
async def reorder_items(
    collection_id: PyUUID,
    body: CollectionReorder,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    col = await db.get(TeachingCollection, collection_id)
    if not col:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    # 해당 컬렉션에 실재하는 항목만 갱신(외부/누락 id 무시 — 부분 실패로 깨지 않음)
    for pos, cid in enumerate(body.case_ids):
        await db.execute(
            update(TeachingCollectionItem)
            .where(TeachingCollectionItem.collection_id == collection_id,
                   TeachingCollectionItem.case_id == cid)
            .values(position=pos)
        )
    await db.commit()
    return {"ok": True}


def _collection(col: TeachingCollection, item_count: int | None) -> dict:
    d = {
        "id": str(col.id),
        "title": col.title,
        "description": col.description,
        "is_published": col.is_published,
        "created_by_name": col.created_by_name,
        "created_at": col.created_at.isoformat() if col.created_at else None,
        "updated_at": col.updated_at.isoformat() if col.updated_at else None,
    }
    if item_count is not None:
        d["item_count"] = item_count
    return d


# ─── Quiz / Unknown mode & Learning progress ─────────────────────────────────
# 정답(diagnosis/summary/title/tags/organ)을 가린 케이스를 학습자에게 보여주고, 답안 제출 시
# 정답을 공개한다. 응답은 teaching_quiz_attempts에 누적되어 진도(모달리티/난이도별 정답률)로 집계된다.

def _acc(correct: int, assessed: int) -> float | None:
    """정답률(%) — 분모는 자가평가 완료 시도수. 미평가면 None."""
    return round(correct / assessed * 100, 1) if assessed else None


def _breakdown(rows) -> list[dict]:
    """(key, attempts, assessed, correct) 행 → 정답률 포함 분해 리스트."""
    out = []
    for key, attempts, assessed, correct in rows:
        out.append({
            "key": key,
            "attempts": attempts,
            "assessed": assessed,
            "correct": correct,
            "accuracy": _acc(correct, assessed),
        })
    return out


async def _progress_for(db: AsyncSession, user_id: PyUUID) -> dict:
    where_user = TeachingQuizAttempt.user_id == user_id
    sa = TeachingQuizAttempt.self_assessment

    dist = dict((await db.execute(
        select(sa, func.count()).where(where_user).group_by(sa)
    )).all())
    total = sum(dist.values())
    correct = dist.get("correct", 0)
    partial = dist.get("partial", 0)
    incorrect = dist.get("incorrect", 0)
    assessed = correct + partial + incorrect

    def _grouped(col):
        # FROM teaching_quiz_attempts JOIN teaching_cases — 집계는 attempt 행 기준.
        return (
            select(col, func.count(),
                   func.count().filter(sa.isnot(None)),
                   func.count().filter(sa == "correct"))
            .select_from(TeachingQuizAttempt)
            .join(TeachingCase, TeachingCase.id == TeachingQuizAttempt.case_id)
            .where(where_user).group_by(col).order_by(func.count().desc())
        )

    by_modality = _breakdown((await db.execute(_grouped(TeachingCase.modality))).all())
    by_difficulty = _breakdown((await db.execute(_grouped(TeachingCase.difficulty))).all())

    recent_rows = (await db.execute(
        select(TeachingQuizAttempt, TeachingCase.title, TeachingCase.modality, TeachingCase.difficulty)
        .join(TeachingCase, TeachingCase.id == TeachingQuizAttempt.case_id)
        .where(where_user).order_by(TeachingQuizAttempt.created_at.desc()).limit(20)
    )).all()
    recent = [{
        "attempt_id": str(a.id),
        "case_id": str(a.case_id),
        "case_title": title,
        "modality": modality,
        "difficulty": difficulty,
        "self_assessment": a.self_assessment,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a, title, modality, difficulty in recent_rows]

    return {
        "user_id": str(user_id),
        "total_attempts": total,
        "assessed": assessed,
        "correct": correct,
        "partial": partial,
        "incorrect": incorrect,
        "accuracy": _acc(correct, assessed),
        "by_modality": by_modality,
        "by_difficulty": by_difficulty,
        "recent": recent,
    }


@router.get("/cases/{case_id}/quiz", summary="퀴즈 뷰(정답 가림)")
async def quiz_view(
    case_id: PyUUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    """언노운 모드 — 정답을 노출하지 않는 케이스 표현(영상·모달리티·나이/성별만)."""
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    avail = await _study_available(request.app.state.http_client, c.study_instance_uid)
    return {
        "id": str(c.id),
        "modality": c.modality,
        "difficulty": c.difficulty,
        "patient_age": c.patient_age,
        "patient_sex": c.patient_sex,
        "study_instance_uid": c.study_instance_uid,
        "orthanc_study_id": c.orthanc_study_id,
        "study_available": avail,
        # title/summary/diagnosis/organ/tags는 의도적으로 제외(정답 유출 방지)
    }


@router.post("/cases/{case_id}/quiz/submit", summary="퀴즈 답안 제출 → 정답 공개")
async def quiz_submit(
    case_id: PyUUID,
    body: QuizSubmit,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    """답안 제출 시 시도를 기록하고 정답을 공개한다(제출 후 되돌리기 불가 = 정직한 자가테스트)."""
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    a = TeachingQuizAttempt(
        case_id=case_id,
        user_id=user.id,
        user_name=user.full_name or user.username,
        submitted_answer=body.answer.strip(),
        time_spent_ms=body.time_spent_ms,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    tagmap = await _tags_for(db, [c.id])
    return {
        "attempt_id": str(a.id),
        "submitted_answer": a.submitted_answer,
        # 정답 공개
        "title": c.title,
        "diagnosis": c.diagnosis,
        "summary": c.summary,
        "organ": c.organ,
        "tags": tagmap.get(c.id, []),
        "report_id": str(c.report_id) if c.report_id else None,
    }


@router.put("/quiz/attempts/{attempt_id}", summary="자가평가 기록")
async def quiz_assess(
    attempt_id: PyUUID,
    body: QuizAssess,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    """제출자 본인만 자기 시도를 평가한다(correct/partial/incorrect)."""
    a = await db.get(TeachingQuizAttempt, attempt_id)
    if not a:
        raise HTTPException(404, "퀴즈 시도를 찾을 수 없습니다.")
    if a.user_id != user.id:
        raise HTTPException(403, "본인의 시도만 평가할 수 있습니다.")
    a.self_assessment = body.self_assessment
    await db.commit()
    await db.refresh(a)
    return {"attempt_id": str(a.id), "self_assessment": a.self_assessment}


@router.get("/quiz/progress", summary="내 학습 진도")
async def quiz_progress(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReadRoles)],
):
    return await _progress_for(db, user.id)


@router.get("/quiz/progress/{user_id}", summary="학습자 진도(멘토링 — ADMIN/RAD)")
async def quiz_progress_of(
    user_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    return await _progress_for(db, user_id)


@router.get("/cases/{case_id}/quiz/stats", summary="케이스별 퀴즈 통계(난이도 보정 — ADMIN/RAD)")
async def quiz_case_stats(
    case_id: PyUUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(WriteRoles)],
):
    c = await db.get(TeachingCase, case_id)
    if not c:
        raise HTTPException(404, "티칭 케이스를 찾을 수 없습니다.")
    sa = TeachingQuizAttempt.self_assessment
    dist = dict((await db.execute(
        select(sa, func.count()).where(TeachingQuizAttempt.case_id == case_id).group_by(sa)
    )).all())
    learners = (await db.execute(
        select(func.count(func.distinct(TeachingQuizAttempt.user_id)))
        .where(TeachingQuizAttempt.case_id == case_id)
    )).scalar_one()
    correct = dist.get("correct", 0)
    partial = dist.get("partial", 0)
    incorrect = dist.get("incorrect", 0)
    assessed = correct + partial + incorrect
    return {
        "case_id": str(case_id),
        "total_attempts": sum(dist.values()),
        "distinct_learners": learners,
        "assessed": assessed,
        "correct": correct,
        "partial": partial,
        "incorrect": incorrect,
        "accuracy": _acc(correct, assessed),
    }
