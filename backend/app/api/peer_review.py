"""피어 리뷰 API — 판독 결과 동료 평가 및 불일치율 통계.

NOTE: peer_reviews 테이블이 아직 없으므로 마이그레이션 필요:
  CREATE TABLE peer_reviews (
      id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
      report_id UUID NOT NULL,
      study_instance_uid TEXT,
      original_reader TEXT NOT NULL,
      reviewer TEXT NOT NULL,
      assignment_type TEXT DEFAULT 'random',  -- random | targeted
      agreement TEXT,  -- agree | disagree | partial
      comment TEXT,
      suggested_category TEXT,
      status TEXT DEFAULT 'pending',  -- pending | completed
      assigned_at TIMESTAMPTZ DEFAULT now(),
      completed_at TIMESTAMPTZ
  );
"""
import logging
import random
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, RequireRole
from app.models.user import Role, User
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/peer-review", tags=["피어 리뷰"])


class AssignRequest(BaseModel):
    """피어 리뷰 배정 요청."""
    report_id: str
    reviewer_username: str | None = None  # None이면 랜덤 배정
    assignment_type: str = "random"  # random | targeted


class SubmitReviewRequest(BaseModel):
    """피어 리뷰 결과 제출."""
    agreement: str  # agree | disagree | partial
    comment: str | None = None
    suggested_category: str | None = None


# ── 1. 리뷰 배정 ──
@router.post("/assign", summary="피어 리뷰 배정")
async def assign_peer_review(
    body: AssignRequest,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """판독 리포트에 대한 피어 리뷰를 배정합니다.

    reviewer_username이 없으면 랜덤으로 다른 판독의를 선택합니다.
    """
    # 원본 판독의 확인
    report = await db.execute(text(
        "SELECT author_name, study_instance_uid FROM reports WHERE id = :rid"
    ), {"rid": body.report_id})
    row = report.mappings().first()
    if not row:
        return {"error": "Report not found"}
    original_reader = row["author_name"]

    reviewer = body.reviewer_username
    if not reviewer:
        # 랜덤 배정: 원본 판독의 제외한 활성 사용자 중 선택
        readers = await db.execute(text(
            "SELECT username FROM users WHERE is_active = true AND username != :me"
        ), {"me": original_reader})
        candidates = [r._mapping["username"] for r in readers]
        if not candidates:
            return {"error": "No available reviewers"}
        reviewer = random.choice(candidates)

    await db.execute(text("""
        INSERT INTO peer_reviews (report_id, study_instance_uid, original_reader,
            reviewer, assignment_type)
        VALUES (:rid, :suid, :reader, :reviewer, :atype)
    """), {"rid": body.report_id, "suid": row["study_instance_uid"],
           "reader": original_reader, "reviewer": reviewer,
           "atype": body.assignment_type})
    await db.commit()

    return {"report_id": body.report_id, "reviewer": reviewer,
            "assignment_type": body.assignment_type, "status": "pending"}


# ── 2. 대기 중인 리뷰 ──
@router.get("/pending", summary="내 대기 리뷰 목록")
async def pending_reviews(
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """현재 사용자에게 배정된 미완료 피어 리뷰 목록을 반환합니다."""
    result = await db.execute(text("""
        SELECT pr.id, pr.report_id, pr.study_instance_uid, pr.original_reader,
               pr.assignment_type, pr.assigned_at
        FROM peer_reviews pr
        WHERE pr.reviewer = :me AND pr.status = 'pending'
        ORDER BY pr.assigned_at ASC
    """), {"me": user.username})
    return {"pending": [dict(r._mapping) for r in result]}


# ── 3. 리뷰 제출 ──
@router.put("/{review_id}/submit", summary="피어 리뷰 제출")
async def submit_review(
    review_id: str,
    body: SubmitReviewRequest,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """피어 리뷰 결과를 제출합니다 (agree/disagree/partial)."""
    if body.agreement not in ("agree", "disagree", "partial"):
        return {"error": "agreement must be agree, disagree, or partial"}

    result = await db.execute(text("""
        UPDATE peer_reviews
        SET agreement = :agr, comment = :cmt, suggested_category = :cat,
            status = 'completed', completed_at = now()
        WHERE id = :rid AND reviewer = :me AND status = 'pending'
        RETURNING id
    """), {"agr": body.agreement, "cmt": body.comment, "cat": body.suggested_category,
           "rid": review_id, "me": user.username})
    await db.commit()
    updated = result.first()
    if not updated:
        return {"error": "Review not found or already completed"}
    return {"id": review_id, "status": "completed", "agreement": body.agreement}


# ── 4. 불일치율 통계 ──
@router.get("/statistics", summary="피어 리뷰 불일치 통계")
async def review_statistics(
    from_date: str = Query(None),
    to_date: str = Query(None),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
    db: AsyncSession = Depends(get_db),
):
    """판독의별, 기간별 피어 리뷰 불일치율을 반환합니다."""
    now = datetime.now(timezone.utc)
    if not from_date:
        from_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    if not to_date:
        to_date = now.strftime("%Y-%m-%d")
    from_d = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_d_excl = datetime.strptime(to_date, "%Y-%m-%d").date() + timedelta(days=1)

    by_reader = await db.execute(text("""
        SELECT original_reader, count(*) as total,
            count(CASE WHEN agreement = 'agree' THEN 1 END) as agree,
            count(CASE WHEN agreement = 'disagree' THEN 1 END) as disagree,
            count(CASE WHEN agreement = 'partial' THEN 1 END) as partial,
            round(count(CASE WHEN agreement = 'disagree' THEN 1 END)::numeric
                  / NULLIF(count(*), 0) * 100, 1) as discrepancy_pct
        FROM peer_reviews
        WHERE status = 'completed'
          AND completed_at >= :f AND completed_at < :t_excl
        GROUP BY original_reader ORDER BY discrepancy_pct DESC
    """), {"f": from_d, "t_excl": to_d_excl})

    summary = await db.execute(text("""
        SELECT count(*) as total,
            count(CASE WHEN agreement = 'disagree' THEN 1 END) as discrepancies
        FROM peer_reviews
        WHERE status = 'completed'
          AND completed_at >= :f AND completed_at < :t_excl
    """), {"f": from_d, "t_excl": to_d_excl})
    s = summary.mappings().first()

    return {
        "period": {"from": from_date, "to": to_date},
        "overall": dict(s) if s else {},
        "by_reader": [dict(r._mapping) for r in by_reader],
    }
