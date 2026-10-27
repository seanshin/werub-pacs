"""Physician Portal API — referring physician's "My Patients" view.

Clinicians (외과, 내과, 응급) see only their own ordered studies
with reading status and report access.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/my-patients", tags=["주치의 포털"])


# ── A4 fix: ownership scoping ─────────────────────────────────────────────
# This portal promised "only studies I ordered" but had no caller scope at all,
# so any PHYSICIAN could enumerate/read every patient's PHI (IDOR). ADMIN and
# RADIOLOGIST legitimately read globally (established PACS design); PHYSICIAN is
# restricted to studies whose worklist referring/requesting physician matches
# their name. Name matching is fuzzy (DICOM ReferringPhysicianName vs login) so
# this errs toward fewer results — never toward exposing another patient.
def _user_attr(user, attr: str, default: str = "") -> str:
    if hasattr(user, attr):
        return getattr(user, attr) or default
    if isinstance(user, dict):
        return user.get(attr, default) or default
    return default


def _is_unrestricted(user) -> bool:
    role = str(_user_attr(user, "role", "")).upper()
    return "ADMIN" in role or "RADIOLOGIST" in role


def _physician_match_name(user) -> str:
    return (_user_attr(user, "full_name") or _user_attr(user, "username") or "").strip()


async def _can_access_study(db: AsyncSession, user, study_uid: str) -> bool:
    if _is_unrestricted(user):
        return True
    name = _physician_match_name(user)
    if not name:
        return False
    res = await db.execute(text("""
        SELECT 1 FROM worklist_items
        WHERE study_instance_uid = :uid
          AND (referring_physician ILIKE :pname OR requesting_physician ILIKE :pname)
        LIMIT 1
    """), {"uid": study_uid, "pname": f"%{name}%"})
    return res.first() is not None


@router.get("", summary="내 환자 영상 목록")
async def my_patient_studies(
    request: Request,
    status: Optional[str] = Query(None, description="unread|completed|all"),
    search: Optional[str] = Query(None, description="환자명 또는 환자번호"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """내가 의뢰한 검사의 영상/리포트 목록.

    HospitalRun 오더 기반으로 현재 로그인한 주치의가 의뢰한
    검사만 표시합니다. 판독 상태(대기/완료)와 리포트 바로보기 제공.
    """
    username = user.username if hasattr(user, 'username') else user.get("username", "")
    offset = (page - 1) * page_size

    # Get studies from reading queue that match this physician's orders
    # Uses worklist + reports to determine status
    result = await db.execute(text("""
        SELECT DISTINCT ON (r.study_instance_uid)
            r.study_instance_uid,
            r.patient_id,
            r.patient_name,
            r.modality,
            r.study_description,
            r.study_date,
            r.accession_number,
            CASE
                WHEN rep.signed_at IS NOT NULL THEN 'completed'
                WHEN rep.id IS NOT NULL THEN 'draft'
                ELSE 'unread'
            END as read_status,
            rep.id as report_id,
            rep.findings,
            rep.impression,
            rep.urgency,
            rep.signed_at
        FROM (
            -- worklist_items has no study_description/study_date columns; map the
            -- scheduled-procedure fields instead.
            SELECT study_instance_uid, patient_id,
                   patient_name, modality,
                   scheduled_procedure_step_description AS study_description,
                   scheduled_date::text AS study_date, accession_number
            FROM worklist_items
            UNION
            -- reports already carries the real values — use them (was '' before).
            SELECT study_instance_uid, patient_id,
                   patient_name, modality,
                   study_description, study_date::text AS study_date,
                   accession_number
            FROM reports
        ) r
        LEFT JOIN reports rep ON rep.study_instance_uid = r.study_instance_uid
        WHERE 1=1
            -- A4 fix: scope to the caller's own referred studies unless ADMIN/
            -- RADIOLOGIST (global readers). PHYSICIAN sees only worklist rows whose
            -- referring/requesting physician matches their name.
            AND (CAST(:unrestricted AS boolean) = true
                 OR r.study_instance_uid IN (
                     SELECT study_instance_uid FROM worklist_items
                     WHERE referring_physician ILIKE :pname
                        OR requesting_physician ILIKE :pname))
            -- CAST(... AS text): asyncpg can't infer a param's type from IS NULL alone
            AND (CAST(:status AS text) IS NULL
                 OR (:status = 'completed' AND rep.signed_at IS NOT NULL)
                 OR (:status = 'unread' AND rep.signed_at IS NULL))
            AND (CAST(:search AS text) IS NULL
                 OR r.patient_name ILIKE '%' || :search || '%'
                 OR r.patient_id ILIKE '%' || :search || '%')
        ORDER BY r.study_instance_uid, rep.created_at DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """), {
        "status": status, "search": search,
        "limit": page_size, "offset": offset,
        "unrestricted": _is_unrestricted(user),
        # When a physician has no resolvable name, this sentinel matches nothing
        # (never '%%', which would expose everyone).
        "pname": f"%{_physician_match_name(user)}%" if _physician_match_name(user) else "\x00",
    })
    studies = [dict(row._mapping) for row in result]

    # Enrich with viewer URL
    for s in studies:
        s["viewer_url"] = f"/werub-viewer/viewer?StudyInstanceUIDs={s['study_instance_uid']}"
        s["report_url"] = f"/pacs-admin/reading/view?study={s['study_instance_uid']}" if s.get("report_id") else None

    return {
        "studies": studies,
        "page": page,
        "page_size": page_size,
        "username": username,
    }


@router.get("/report/{study_uid}", summary="리포트 바로보기")
async def get_report_for_study(
    study_uid: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """스터디의 최신 리포트를 반환합니다 (주치의용 읽기 전용)."""
    if not await _can_access_study(db, user, study_uid):
        raise HTTPException(403, "이 검사에 접근 권한이 없습니다")
    result = await db.execute(text("""
        SELECT id, study_instance_uid, patient_id, findings, impression,
               recommendation, urgency, status, author_name,
               signed_at, signed_by_name, created_at
        FROM reports
        WHERE study_instance_uid = :uid
        ORDER BY created_at DESC LIMIT 1
    """), {"uid": study_uid})
    row = result.mappings().first()

    if not row:
        raise HTTPException(404, "리포트가 아직 없습니다")

    return dict(row)


@router.get("/notifications", summary="내 리포트 알림")
async def my_report_notifications(
    unread_only: bool = Query(True),
    user: User = Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """내가 의뢰한 검사의 판독 완료 알림 목록."""
    # A3 fix: the previous query referenced non-existent columns (n.metadata /
    # n.user_id / n.notification_type → actual columns are data / target_user_id /
    # type) so it 500'd on every call. It also targeted the wrong field: report
    # completion alerts use type='report_signed' and target the ordering physician
    # via target_username / target_role='physician' (NOT target_user_id).
    uname = _user_attr(user, "username")
    result = await db.execute(text("""
        SELECT n.id, n.title, n.message, n.is_read, n.created_at, n.data
        FROM notifications n
        WHERE n.type = 'report_signed'
          AND (n.target_username = :uname OR n.target_role = 'physician')
          AND (:unread = false OR n.is_read = false)
        ORDER BY n.created_at DESC
        LIMIT 50
    """), {
        "uname": uname,
        "unread": unread_only,
    })

    return {"notifications": [dict(r._mapping) for r in result]}


@router.get("/report/{study_uid}/pdf", summary="리포트 PDF 다운로드")
async def download_report_pdf(
    study_uid: str,
    user: User = Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """스터디의 판독 리포트를 PDF 형식으로 반환합니다."""
    from fastapi.responses import Response

    if not await _can_access_study(db, user, study_uid):
        raise HTTPException(403, "이 검사에 접근 권한이 없습니다")
    result = await db.execute(text("""
        SELECT r.patient_id, r.patient_name, r.modality, r.study_description,
               r.study_date, r.findings, r.impression, r.recommendation,
               r.urgency, r.status, r.signed_by_name, r.signed_at
        FROM reports r
        WHERE r.study_instance_uid = :uid AND r.status = 'FINAL'
        ORDER BY r.signed_at DESC LIMIT 1
    """), {"uid": study_uid})
    row = result.mappings().first()

    if not row:
        raise HTTPException(404, "판독 완료된 리포트가 없습니다")

    r = dict(row)
    # Simple HTML-to-PDF via basic HTML (real PDF requires weasyprint or similar)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>판독 리포트</title>
<style>body{{font-family:'Noto Sans KR',sans-serif;max-width:700px;margin:40px auto;font-size:14px}}
h1{{font-size:18px;border-bottom:2px solid #333;padding-bottom:8px}}
.field{{margin:12px 0}}.label{{font-weight:bold;color:#555;font-size:12px}}
.value{{margin-top:4px;white-space:pre-wrap}}.impression{{color:#16a34a;font-weight:bold}}
.meta{{color:#888;font-size:11px;margin-top:20px;border-top:1px solid #ddd;padding-top:8px}}</style></head>
<body>
<h1>판독 리포트</h1>
<div class="field"><span class="label">환자번호</span><div class="value">{r.get('patient_id','')}</div></div>
<div class="field"><span class="label">환자명</span><div class="value">{r.get('patient_name','')}</div></div>
<div class="field"><span class="label">검사</span><div class="value">{r.get('modality','')} — {r.get('study_description','')}</div></div>
<div class="field"><span class="label">검사일</span><div class="value">{r.get('study_date','')}</div></div>
<div class="field"><span class="label">소견 (Findings)</span><div class="value">{r.get('findings','')}</div></div>
<div class="field"><span class="label">결론 (Impression)</span><div class="value impression">{r.get('impression','')}</div></div>
<div class="field"><span class="label">권고</span><div class="value">{r.get('recommendation','') or '-'}</div></div>
<div class="meta">판독의: {r.get('signed_by_name','')} | 서명: {r.get('signed_at','')}</div>
</body></html>"""

    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f"inline; filename=report_{study_uid[:16]}.html"},
    )


@router.get("/study/{study_uid}/thumbnail", summary="영상 썸네일 URL")
async def get_study_thumbnail(
    study_uid: str,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """스터디의 대표 영상 썸네일 URL을 반환합니다."""
    if not await _can_access_study(db, user, study_uid):
        raise HTTPException(403, "이 검사에 접근 권한이 없습니다")
    # Use DICOMweb WADO-RS thumbnail
    thumbnail_url = f"/dicom-web/studies/{study_uid}/thumbnail"
    viewer_url = f"/werub-viewer/viewer?StudyInstanceUIDs={study_uid}"

    return {
        "study_uid": study_uid,
        "thumbnail_url": thumbnail_url,
        "viewer_url": viewer_url,
    }


@router.get("/verify-access", summary="포털 접근 토큰 검증")
async def verify_portal_access(
    user: User = Depends(RequireRole(Role.ADMIN, Role.PHYSICIAN, Role.RADIOLOGIST)),
):
    """현재 토큰이 유효한지 확인합니다. 포털 앱의 인증 상태 확인용."""
    return {
        "valid": True,
        "username": user.username if hasattr(user, 'username') else "",
        "role": user.role if hasattr(user, 'role') else "user",
    }
