"""컨퍼런스 및 세컨드 오피니언 API.

컨퍼런스 세션 관리, 케이스 추가/제거, 프레젠테이션 모드, 회의록, 세컨드 오피니언 요청.
NOTE: 아래 테이블이 아직 없으므로 마이그레이션 필요:
  CREATE TABLE conferences (
      id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
      title TEXT NOT NULL, scheduled_date TIMESTAMPTZ,
      department TEXT, participants JSONB DEFAULT '[]',
      minutes TEXT, status TEXT DEFAULT 'scheduled',
      created_by TEXT, created_at TIMESTAMPTZ DEFAULT now()
  );
  CREATE TABLE conference_cases (
      id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
      conference_id UUID REFERENCES conferences(id) ON DELETE CASCADE,
      study_instance_uid TEXT, report_id UUID,
      notes TEXT, added_by TEXT, added_at TIMESTAMPTZ DEFAULT now()
  );
  CREATE TABLE second_opinions (
      id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
      study_instance_uid TEXT NOT NULL, question TEXT,
      requester TEXT, external_email TEXT,
      response TEXT, status TEXT DEFAULT 'pending',
      created_at TIMESTAMPTZ DEFAULT now(), responded_at TIMESTAMPTZ
  );
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/conferences", tags=["컨퍼런스"])


class ConferenceCreate(BaseModel):
    title: str
    scheduled_date: str
    department: str | None = None
    participants: list[str] = []


class CaseAdd(BaseModel):
    study_instance_uid: str
    report_id: str | None = None
    notes: str | None = None


class MinutesSave(BaseModel):
    minutes: str


class SecondOpinionRequest(BaseModel):
    study_instance_uid: str
    question: str
    external_email: str | None = None


class SecondOpinionResponse(BaseModel):
    response: str


# ── 1. 컨퍼런스 생성 ──
@router.post("", summary="컨퍼런스 세션 생성")
async def create_conference(
    body: ConferenceCreate,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """새 컨퍼런스 세션을 생성합니다."""
    result = await db.execute(text("""
        INSERT INTO conferences (title, scheduled_date, department, participants, created_by)
        VALUES (:title, :dt, :dept, :parts::jsonb, :user)
        RETURNING id
    """), {"title": body.title, "dt": body.scheduled_date,
           "dept": body.department,
           "parts": str(body.participants).replace("'", '"'),
           "user": user.username})
    await db.commit()
    row = result.first()
    return {"id": str(row[0]), "title": body.title, "status": "scheduled"}


# ── 2. 컨퍼런스 목록 ──
@router.get("", summary="컨퍼런스 목록 조회")
async def list_conferences(
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """컨퍼런스 세션 목록을 페이지네이션으로 조회합니다."""
    offset = (page - 1) * size
    result = await db.execute(text("""
        SELECT id, title, scheduled_date, department, status, created_by
        FROM conferences ORDER BY scheduled_date DESC
        LIMIT :lim OFFSET :off
    """), {"lim": size, "off": offset})
    total = await db.execute(text("SELECT count(*) FROM conferences"))
    return {"items": [dict(r._mapping) for r in result],
            "total": total.scalar(), "page": page, "size": size}


# ── 3. 컨퍼런스 상세 ──
@router.get("/{conf_id}", summary="컨퍼런스 상세 조회")
async def get_conference(
    conf_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """컨퍼런스 상세 정보와 등록된 케이스를 반환합니다."""
    conf = await db.execute(text(
        "SELECT * FROM conferences WHERE id = :cid"
    ), {"cid": conf_id})
    row = conf.mappings().first()
    if not row:
        return {"error": "Conference not found"}

    cases = await db.execute(text("""
        SELECT id, study_instance_uid, report_id, notes, added_by, added_at
        FROM conference_cases WHERE conference_id = :cid ORDER BY added_at
    """), {"cid": conf_id})
    return {**dict(row), "cases": [dict(c._mapping) for c in cases]}


# ── 4. 케이스 추가 ──
@router.post("/{conf_id}/cases", summary="컨퍼런스 케이스 추가")
async def add_case(
    conf_id: str, body: CaseAdd,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """컨퍼런스에 영상 케이스를 추가합니다."""
    result = await db.execute(text("""
        INSERT INTO conference_cases (conference_id, study_instance_uid, report_id, notes, added_by)
        VALUES (:cid, :suid, :rid, :notes, :user) RETURNING id
    """), {"cid": conf_id, "suid": body.study_instance_uid,
           "rid": body.report_id, "notes": body.notes, "user": user.username})
    await db.commit()
    return {"case_id": str(result.first()[0]), "conference_id": conf_id}


# ── 5. 케이스 제거 ──
@router.delete("/{conf_id}/cases/{case_id}", summary="컨퍼런스 케이스 제거")
async def remove_case(
    conf_id: str, case_id: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """컨퍼런스에서 케이스를 제거합니다."""
    await db.execute(text(
        "DELETE FROM conference_cases WHERE id = :cid AND conference_id = :conf"
    ), {"cid": case_id, "conf": conf_id})
    await db.commit()
    return {"deleted": case_id}


# ── 6. 프레젠테이션 모드 ──
@router.get("/{conf_id}/presentation", summary="프레젠테이션 모드")
async def presentation_mode(
    conf_id: str,
    anonymize: bool = Query(False, description="환자 정보 익명화 여부"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """프레젠테이션용 케이스 목록을 반환합니다. 익명화 옵션 지원."""
    cases = await db.execute(text("""
        SELECT cc.id, cc.study_instance_uid, cc.notes, cc.report_id
        FROM conference_cases cc
        WHERE cc.conference_id = :cid ORDER BY cc.added_at
    """), {"cid": conf_id})
    items = [dict(c._mapping) for c in cases]
    if anonymize:
        for i, item in enumerate(items):
            item["display_id"] = f"CASE-{i+1:03d}"
            item.pop("study_instance_uid", None)
    return {"conference_id": conf_id, "anonymized": anonymize, "cases": items}


# ── 7. 회의록 저장 ──
@router.post("/{conf_id}/minutes", summary="회의록 저장")
async def save_minutes(
    conf_id: str, body: MinutesSave,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """컨퍼런스 회의록을 저장합니다."""
    await db.execute(text("""
        UPDATE conferences SET minutes = :min, status = 'completed'
        WHERE id = :cid
    """), {"min": body.minutes, "cid": conf_id})
    await db.commit()
    return {"conference_id": conf_id, "minutes_saved": True}


# ── 8. 세컨드 오피니언 요청 ──
@router.post("/second-opinion/request", summary="세컨드 오피니언 요청")
async def request_second_opinion(
    body: SecondOpinionRequest,
    # 외부 전문의 토큰 공유+이메일 반출 — BTG 우회 차단.
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """외부 전문의에게 세컨드 오피니언을 요청합니다."""
    import secrets
    access_token = secrets.token_urlsafe(32)

    result = await db.execute(text("""
        INSERT INTO second_opinions (study_instance_uid, question, requester, external_email, access_token)
        VALUES (:suid, :q, :user, :email, :atoken) RETURNING id
    """), {"suid": body.study_instance_uid, "q": body.question,
           "user": user.username, "email": body.external_email,
           "atoken": access_token})
    await db.commit()
    portal_url = f"/pacs-admin/consult-portal?token={access_token}"

    # Send email to external specialist
    if body.external_email:
        try:
            from app.services.email_service import send_consult_email
            send_consult_email(
                to_email=body.external_email,
                subject=f"[WeRU.B PACS] 세컨드 오피니언 요청",
                portal_url=portal_url,
                consult_type="second_opinion",
                requester_name=user.username,
                reason=body.question[:200],
            )
        except Exception:
            pass

    return {"id": str(result.first()[0]), "status": "pending",
            "study_uid": body.study_instance_uid,
            "portal_url": portal_url,
            "access_token": access_token,
            "email_sent": bool(body.external_email)}


# ── 9. 세컨드 오피니언 이력 ──
@router.get("/second-opinion/history", summary="세컨드 오피니언 이력")
async def second_opinion_history(
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자의 세컨드 오피니언 요청 이력을 조회합니다."""
    result = await db.execute(text("""
        SELECT id, study_instance_uid, question, external_email,
               response, status, created_at, responded_at, requester
        FROM second_opinions
        WHERE requester = :user ORDER BY created_at DESC
    """), {"user": user.username})
    return {"requests": [dict(r._mapping) for r in result]}


# ── 10. 세컨드 오피니언 전체 목록 (관리자/판독의) ──
@router.get("/second-opinion/all", summary="세컨드 오피니언 전체 목록")
async def second_opinion_all(
    status_filter: str | None = Query(None, alias="status"),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """모든 세컨드 오피니언 요청을 조회합니다."""
    query = """
        SELECT id, study_instance_uid, question, external_email,
               response, status, created_at, responded_at, requester
        FROM second_opinions
    """
    params: dict = {}
    if status_filter:
        query += " WHERE status = :status"
        params["status"] = status_filter
    query += " ORDER BY created_at DESC LIMIT 100"
    result = await db.execute(text(query), params)
    return {"requests": [dict(r._mapping) for r in result]}


# ── 11. 세컨드 오피니언 상세 조회 (토큰 없이 — 외부 전문의용) ──
@router.get("/second-opinion/{opinion_id}", summary="세컨드 오피니언 상세")
async def get_second_opinion(
    opinion_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """세컨드 오피니언 상세 조회 (내부 판독의/관리자용).

    A8 fix: 이 EP는 인증된 admin 페이지(second-opinion)가 PK(id)로 호출한다.
    외부 전문의의 무인증 접근은 토큰 게이트 consult_portal(/view?token=)이 별도
    담당하므로, 여기에 인증을 추가해 id만 알면 PHI 열람·허위 의견 주입이 가능하던
    인증우회를 차단한다(형제 EP history/all과 동일 RequireRole).
    """
    result = await db.execute(text("""
        SELECT id, study_instance_uid, question, external_email,
               response, status, created_at, responded_at, requester
        FROM second_opinions WHERE id = :id
    """), {"id": opinion_id})
    row = result.mappings().first()
    if not row:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("SecondOpinion", opinion_id)
    return dict(row)


# ── 12. 세컨드 오피니언 응답 제출 ──
@router.put("/second-opinion/{opinion_id}/respond", summary="세컨드 오피니언 응답")
async def respond_second_opinion(
    opinion_id: str,
    body: SecondOpinionResponse,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """세컨드 오피니언 응답 (내부 판독의/관리자용).

    A8 fix: 무인증 PK 게이트였던 것을 인증 추가로 차단. 외부 전문의 응답은
    토큰 게이트 consult_portal(/respond)이 담당한다.
    """
    result = await db.execute(text("""
        UPDATE second_opinions
        SET response = :resp, status = 'completed', responded_at = NOW()
        WHERE id = :id AND status = 'pending'
        RETURNING id, study_instance_uid, requester
    """), {"resp": body.response, "id": opinion_id})
    await db.commit()
    row = result.mappings().first()
    if not row:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("SecondOpinion", opinion_id)

    # Notify requester
    try:
        from app.api.notification import create_notification
        await create_notification(
            db, type="second_opinion_response",
            title="세컨드 오피니언 응답 도착",
            message=f"요청하신 세컨드 오피니언에 응답이 도착했습니다.",
            urgency="normal",
            target_role="radiologist",
            study_instance_uid=row["study_instance_uid"],
        )
    except Exception:
        pass

    return {"id": opinion_id, "status": "completed"}
