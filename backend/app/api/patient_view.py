"""Patient result-view portal API.

환자 본인 열람 포털 — 스태프가 환자별 열람 토큰을 발급하면, 환자는
`/pacs-admin/patient-view?token=…` 에서 자기 검사 목록·확정 판독문(final/addendum)·
대표 이미지 미리보기를 열람한다.

보안 설계:
- default-off: `settings.patient_view_enabled` (PHI 읽기 표면 — patient_export와 동형)
- 토큰: urlsafe 48바이트, DB에는 SHA-256 해시만. 만료+폐기(revoke)+사용량 추적.
- IDOR 가드: 모든 portal 응답은 토큰에 봉인된 patient_id 스코프로만 조회.
  study_uid 파라미터는 Orthanc/DB에서 소유 환자 재검증 후에만 응답.
- 감사: 포털 접근 전건 `PATIENT_VIEW` (audit_logs — append-only).
- 공개 EP에 IP 기반 경량 rate limit(토큰 추측·스크래핑 방어).
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import RequireRole
from app.models.audit import AuditLog
from app.models.patient_view import PatientViewToken
from app.models.report import Report, ReportStatus
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/patient-view", tags=["patient-view"])

PORTAL_PATH = "/pacs-admin/patient-view"


def _require_enabled() -> None:
    if not settings.patient_view_enabled:
        raise HTTPException(503, "PATIENT_VIEW_DISABLED")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _rate_limit(request: Request, bucket: str, limit: int = 60) -> None:
    """공개 포털 EP의 IP 기반 경량 제한 (분당 limit회). Redis 불가 시 통과."""
    try:
        redis = request.app.state.redis
        ip = request.client.host if request.client else "unknown"
        key = f"pview_rl:{bucket}:{ip}"
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, 60)
        if n > limit:
            raise AuthenticationError(message="요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    except AuthenticationError:
        raise
    except Exception:
        pass


async def _resolve_token(db: AsyncSession, token: str) -> PatientViewToken:
    """토큰 검증 — 유효하지 않으면 401. 사용량은 best-effort 갱신."""
    if not token:
        raise AuthenticationError(message="열람 링크가 유효하지 않습니다")
    result = await db.execute(
        select(PatientViewToken).where(PatientViewToken.token_hash == _hash(token))
    )
    tok = result.scalar_one_or_none()
    if tok is None or tok.revoked:
        raise AuthenticationError(message="유효하지 않은 링크입니다")
    if tok.expires_at < datetime.now(timezone.utc):
        raise AuthenticationError(message="링크가 만료되었습니다")
    try:
        await db.execute(
            update(PatientViewToken)
            .where(PatientViewToken.id == tok.id)
            .values(use_count=PatientViewToken.use_count + 1,
                    last_used_at=datetime.now(timezone.utc)))
        await db.commit()
    except Exception:
        await db.rollback()
    return tok


async def _audit_view(db: AsyncSession, tok: PatientViewToken, request: Request,
                      resource_type: str, resource_id: str | None) -> None:
    """환자 본인 PHI 열람 감사 — 의료법 열람기록. best-effort(주동작 불침해)."""
    try:
        db.add(AuditLog(
            username=f"patient-portal:{tok.patient_id}",
            ip_address=(request.client.host if request.client else None),
            action="PATIENT_VIEW",
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=tok.patient_id,
            details={"path": request.url.path, "token_id": str(tok.id)},
        ))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("PATIENT_VIEW audit write failed: %s", e)


# ─── Staff: 토큰 발급/관리 ───────────────────────────────────────────────────

class ViewTokenCreate(BaseModel):
    patient_id: str
    patient_name: str | None = None
    memo: str | None = None
    expires_hours: int = 72  # 기본 3일


@router.post("/token")
@AuditLogger.log("PATIENT_VIEW_TOKEN_CREATED", "PatientViewToken")
async def create_view_token(
    body: ViewTokenCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """환자 결과 열람 토큰 발급 — 토큰 원문은 이 응답에서 1회만 노출."""
    _require_enabled()
    token_str = secrets.token_urlsafe(48)
    tok = PatientViewToken(
        token_hash=_hash(token_str),
        patient_id=body.patient_id.strip(),
        patient_name=body.patient_name,
        memo=body.memo,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=min(body.expires_hours, 24 * 30)),
        created_by=user.id,
    )
    db.add(tok)
    await db.commit()
    return {
        "ok": True,
        "token": token_str,
        "url": f"{PORTAL_PATH}?token={token_str}",
        "expires_at": tok.expires_at.isoformat(),
    }


@router.get("/tokens")
async def list_view_tokens(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    result = await db.execute(
        select(PatientViewToken).order_by(PatientViewToken.created_at.desc()).limit(100)
    )
    now = datetime.now(timezone.utc)
    return {
        "tokens": [
            {
                "id": str(t.id),
                "patient_id": t.patient_id,
                "patient_name": t.patient_name,
                "memo": t.memo,
                "expires_at": t.expires_at.isoformat(),
                "revoked": t.revoked,
                "expired": t.expires_at < now,
                "use_count": t.use_count,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "created_at": t.created_at.isoformat(),
            }
            for t in result.scalars().all()
        ]
    }


@router.post("/tokens/{token_id}/revoke")
@AuditLogger.log("PATIENT_VIEW_TOKEN_REVOKED", "PatientViewToken")
async def revoke_view_token(
    token_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    result = await db.execute(
        update(PatientViewToken).where(PatientViewToken.id == token_id)
        .values(revoked=True).returning(PatientViewToken.id))
    if not result.first():
        raise NotFoundError(resource="PatientViewToken", resource_id=token_id)
    await db.commit()
    return {"ok": True}


# ─── Patient portal (public, token-based) ───────────────────────────────────

@router.get("/portal/studies")
async def portal_studies(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str = Query(...),
):
    """토큰 환자의 검사 목록 + 확정 판독문 유무."""
    _require_enabled()
    await _rate_limit(request, "studies")
    tok = await _resolve_token(db, token)

    orthanc = request.app.state.http_client
    find = await orthanc.post("/tools/find", json={
        "Level": "Study",
        "Query": {"PatientID": tok.patient_id},
        "Expand": True,
        # ModalitiesInStudy는 RequestedTags로만 채워짐 (v13.7)
        "RequestedTags": ["ModalitiesInStudy"],
    })
    studies_raw = find.json() if find.status_code == 200 else []

    uids = [s.get("MainDicomTags", {}).get("StudyInstanceUID", "") for s in studies_raw]
    finals: set[str] = set()
    if uids:
        rows = await db.execute(
            select(Report.study_instance_uid).where(
                Report.patient_id == tok.patient_id,
                Report.study_instance_uid.in_(uids),
                Report.status.in_([ReportStatus.FINAL, ReportStatus.ADDENDUM]),
            ))
        finals = {r[0] for r in rows.all()}

    patient_name = tok.patient_name
    studies = []
    for s in studies_raw:
        main = s.get("MainDicomTags", {})
        ptags = s.get("PatientMainDicomTags", {})
        patient_name = patient_name or ptags.get("PatientName")
        uid = main.get("StudyInstanceUID", "")
        studies.append({
            "study_instance_uid": uid,
            "study_date": main.get("StudyDate", ""),
            "study_description": main.get("StudyDescription", ""),
            "modalities": (s.get("RequestedTags", {}) or {}).get("ModalitiesInStudy", ""),
            "series_count": len(s.get("Series", [])),
            "has_final_report": uid in finals,
        })
    studies.sort(key=lambda x: x["study_date"] or "", reverse=True)

    await _audit_view(db, tok, request, "StudyList", None)
    return {
        "patient_id": tok.patient_id,
        "patient_name": patient_name,
        "expires_at": tok.expires_at.isoformat(),
        "studies": studies,
    }


async def _assert_study_owned(request: Request, tok: PatientViewToken, study_uid: str) -> dict:
    """study_uid가 토큰 환자 소유인지 Orthanc에서 재검증 (IDOR 가드). Orthanc study 반환."""
    orthanc = request.app.state.http_client
    find = await orthanc.post("/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid}, "Expand": True,
    })
    matches = find.json() if find.status_code == 200 else []
    for s in matches:
        if s.get("PatientMainDicomTags", {}).get("PatientID", "") == tok.patient_id:
            return s
    raise NotFoundError(resource="Study", resource_id=study_uid)


@router.get("/portal/report")
async def portal_report(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str = Query(...),
    study_uid: str = Query(...),
):
    """확정(final/addendum) 판독문 — 환자에게는 확정본만 노출."""
    _require_enabled()
    await _rate_limit(request, "report")
    tok = await _resolve_token(db, token)

    result = await db.execute(
        select(Report).where(
            Report.patient_id == tok.patient_id,      # 소유 스코프가 곧 IDOR 가드
            Report.study_instance_uid == study_uid,
            Report.status.in_([ReportStatus.FINAL, ReportStatus.ADDENDUM]),
        ).order_by(Report.updated_at.desc()).limit(1))
    report = result.scalar_one_or_none()
    if report is None:
        raise NotFoundError(resource="Report", resource_id=study_uid)

    await _audit_view(db, tok, request, "Report", str(report.id))
    return {
        "study_instance_uid": study_uid,
        "study_description": report.study_description,
        "modality": report.modality,
        "study_date": report.study_date,
        "status": report.status if isinstance(report.status, str) else report.status.value,
        "findings": report.findings,
        "impression": report.impression,
        "recommendation": report.recommendation,
        "signed_by": report.signed_by_name,
        "signed_at": report.signed_at.isoformat() if report.signed_at else None,
    }


@router.get("/portal/preview")
async def portal_preview(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str = Query(...),
    study_uid: str = Query(...),
):
    """대표 이미지 미리보기(첫 시리즈 첫 인스턴스 PNG) — 진단용 아님, 참고용."""
    _require_enabled()
    await _rate_limit(request, "preview", limit=120)
    tok = await _resolve_token(db, token)
    study = await _assert_study_owned(request, tok, study_uid)

    orthanc = request.app.state.http_client
    for series_id in study.get("Series", []):
        sr = await orthanc.get(f"/series/{series_id}")
        if sr.status_code != 200:
            continue
        for inst in sr.json().get("Instances", [])[:1]:
            preview = await orthanc.get(f"/instances/{inst}/preview")
            if preview.status_code == 200:
                await _audit_view(db, tok, request, "Preview", study_uid)
                return Response(content=preview.content, media_type="image/png",
                                headers={"Cache-Control": "private, max-age=300"})
    raise NotFoundError(resource="Preview", resource_id=study_uid)
