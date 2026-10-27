"""Audit log API endpoints and logging decorators."""
import logging
from datetime import date, datetime, timezone
from functools import wraps
from typing import Annotated, Callable, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import RequireRole
from app.models.audit import AuditLog
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ── v1.1: Audit Logging Decorator ──────────────────────────────────────────

_SCALAR = (str, int, UUID)
# 리소스 식별에 쓰는 키 이름들. 액터(user/admin)는 kwargs 이름이 다르므로 섞이지 않는다.
_STUDY_KEYS = ("study_instance_uid", "study_uid", "studyinstanceuid")
_PATIENT_KEYS = ("patient_id", "mrn")


def _scalar_or_none(v):
    if isinstance(v, _SCALAR):
        return str(v)
    # 리스트로 오는 study UID 등은 첫 값만
    if isinstance(v, (list, tuple)) and v and isinstance(v[0], _SCALAR):
        return str(v[0])
    return None


def _collect_identifiers(kwargs: dict, result=None) -> dict:
    """핸들러 kwargs(경로/쿼리 파라미터)·요청 body·반환값에서 리소스 식별자를 뽑는다.

    스칼라 id류만 본다 — body 전체를 감사에 덤프하면 PHI가 통째로 실린다.
    탐색 순서는 kwargs(경로 파라미터가 대상 리소스를 가장 정확히 지목) → body → result.
    """
    found: dict = {}

    def _scan(source: dict):
        for k, v in source.items():
            lk = k.lower()
            s = _scalar_or_none(v)
            if s is None:
                continue
            if lk in _STUDY_KEYS and "study_instance_uid" not in found:
                found["study_instance_uid"] = s
            elif lk in _PATIENT_KEYS and "patient_id" not in found:
                found["patient_id"] = s
            elif (lk.endswith("_id") or lk.endswith("_uid") or lk in ("id", "uid")) \
                    and "resource_id" not in found:
                found["resource_id"] = s

    _scan(kwargs)

    body = kwargs.get("body")
    if body is not None and hasattr(body, "model_dump"):
        try:
            _scan(body.model_dump())
        except Exception:
            pass

    if isinstance(result, dict):
        _scan(result)

    return found


class AuditLogger:
    """Decorator for automatic audit logging of sensitive operations.

    ★식별자 자동 수집(2026-08-03): 예전에는 작업자·동작만 남고 *어떤 리소스인지*가
    빠져서 "티칭 케이스가 삭제됨"은 남는데 "어느 케이스"가 없었다. 이제 경로 파라미터·
    요청 body·반환값에서 스칼라 id류를 뽑아 전용 컬럼(resource_id/study_instance_uid/
    patient_id)에 싣는다. 리소스별 전후 값처럼 **의미를 아는 기록이 필요하면** 이
    데코레이터가 아니라 핸들러에서 `_log_audit_entry`를 직접 호출한다(워크리스트 방식).
    """

    @staticmethod
    def log(operation: str, resource_type: str = None):
        """
        Decorator for automatic audit logging.

        Usage:
            @AuditLogger.log("USER_CREATED", "User")
            async def create_user(...):
                ...
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Extract dependencies
                user = kwargs.get('user') or kwargs.get('admin') or None
                db = kwargs.get('db') or None

                # Get current user from context if not in kwargs
                if not user:
                    for arg in args:
                        if hasattr(arg, 'id') and hasattr(arg, 'username'):
                            user = arg
                            break

                if not db:
                    for arg in args:
                        if hasattr(arg, 'execute'):  # AsyncSession check
                            db = arg
                            break

                try:
                    result = await func(*args, **kwargs)

                    # Log success
                    if db and user:
                        # Include HIS SSO context if available
                        details = {}
                        request = kwargs.get('request')
                        if request and hasattr(request, 'state'):
                            his_id = getattr(request.state, 'his_user_id', None)
                            if his_id:
                                details['his_user_id'] = his_id
                                details['his_role'] = getattr(request.state, 'his_role', '')
                        ids = _collect_identifiers(kwargs, result)
                        details.update(ids)
                        await _log_audit_entry(
                            db=db,
                            operation=operation,
                            resource_type=resource_type,
                            status="SUCCESS",
                            user_id=str(user.id),
                            username=user.username,
                            details=details,
                            **ids,
                        )

                    return result

                except Exception as e:
                    # Log failure — 실패 감사에도 대상 식별자가 있어야 추적된다
                    # (result는 없으므로 kwargs/body만으로 수집)
                    if db and user:
                        ids = _collect_identifiers(kwargs)
                        await _log_audit_entry(
                            db=db,
                            operation=operation,
                            resource_type=resource_type,
                            status="FAILED",
                            user_id=str(user.id),
                            username=user.username,
                            details={"error": str(e), **ids},
                            **ids,
                        )
                    raise

            return async_wrapper
        return decorator


async def _log_audit_entry(
    db: AsyncSession,
    operation: str,
    resource_type: str,
    status: str,
    user_id: UUID,
    username: str,
    details: dict = None,
    resource_id: str | None = None,
    study_instance_uid: str | None = None,
    patient_id: str | None = None,
) -> None:
    """Helper function to create audit log entry.

    ★resource_id/study_instance_uid/patient_id는 AuditLog에 **전용 컬럼**이 있고
    감사 조회 필터(`_apply_audit_filters`)가 그 컬럼으로 검색한다. 예전에는 이 헬퍼가
    셋 다 채우지 않아 **study_instance_uid가 전 행 NULL**이었고(2026-08-03 실측:
    1009행 중 0행), 감사 UI의 study 검색은 영구히 0건을 반환했다. details에만 넣으면
    조회되지 않으므로 컬럼에 함께 싣는다."""
    # details에 이미 실려 온 값이 있으면 인자 미지정 시 그것을 쓴다(호출부 중복 방지)
    d = details or {}
    resource_id = resource_id or d.get("resource_id")
    study_instance_uid = study_instance_uid or d.get("study_instance_uid") or d.get("study_uid")
    patient_id = patient_id or d.get("patient_id") or d.get("mrn")

    def _fit(v, n: int):  # 컬럼 길이 초과로 감사가 통째로 실패하지 않도록
        return str(v)[:n] if v is not None else None

    try:
        audit_log = AuditLog(
            action=operation,
            resource_type=resource_type,
            resource_id=_fit(resource_id, 128),
            study_instance_uid=_fit(study_instance_uid, 128),
            patient_id=_fit(patient_id, 64),
            status=status,
            user_id=user_id,
            username=username,
            details=details or {},
            created_at=datetime.now(timezone.utc)
        )
        db.add(audit_log)
        await db.commit()
    except Exception as e:
        # 감사 실패가 주 동작을 깨지 않게 하되, 가시성 확보 위해 logger.error(print은 유실)
        logging.getLogger(__name__).error(f"Failed to log audit entry: {e}")

    # Also emit the standard IHE ATNA audit message (no-op unless atna_enabled).
    # Kept outside the DB try/except and fully guarded so it never affects the op.
    try:
        from app.services.atna_audit import emit_atna
        await emit_atna(
            operation=operation,
            status=status,
            username=username,
            user_id=str(user_id) if user_id else None,
            patient_id=patient_id,
            resource_type=resource_type,
        )
    except Exception:
        pass


@router.get("")
async def list_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    action: str | None = Query(None),
    username: str | None = Query(None),
    resource_type: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    patient_id: str | None = Query(None),
    study_uid: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List audit logs. Admin only."""
    query = _apply_audit_filters(
        select(AuditLog).order_by(AuditLog.created_at.desc()),
        action=action, username=username, resource_type=resource_type,
        status=status, search=search, patient_id=patient_id,
        study_uid=study_uid, date_from=date_from, date_to=date_to,
    )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()
    result = await db.execute(query.offset(offset).limit(limit))
    logs = result.scalars().all()

    return {
        "total": total,
        "count": len(logs),
        "results": [
            {
                "id": str(log.id),
                "user_id": log.user_id,
                "username": log.username,
                "ip_address": log.ip_address,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "status": log.status,
                "study_instance_uid": log.study_instance_uid,
                "patient_id": log.patient_id,
                "description": log.description,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }


def _apply_audit_filters(query, *, action=None, username=None, resource_type=None,
                         status=None, search=None, patient_id=None, study_uid=None,
                         date_from=None, date_to=None):
    """Shared WHERE builder for the audit list + export endpoints."""
    if action:
        # 대소문자 무관 — 라이브에 소문자 액션(`view` 319행·`ai_inference`)이 남아 있고
        # append-only라 소급 정정할 수 없다(v13.47). 대문자로 조회해도 과거 행이 잡혀야
        # 한다. ★`upper(action) = :v`가 아니라 **IN 목록**을 쓰는 이유는 `action`에 btree
        #   인덱스가 있어서다 — 함수 적용은 인덱스를 못 쓴다.
        query = query.where(AuditLog.action.in_({action, action.upper(), action.lower()}))
    if username:
        query = query.where(AuditLog.username == username)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if status:
        query = query.where(AuditLog.status == status)
    if patient_id:
        query = query.where(AuditLog.patient_id == patient_id)
    if study_uid:
        query = query.where(AuditLog.study_instance_uid == study_uid)
    if date_from:
        query = query.where(func.date(AuditLog.created_at) >= date_from)
    if date_to:
        query = query.where(func.date(AuditLog.created_at) <= date_to)
    if search:
        like = f"%{search}%"
        query = query.where(or_(
            AuditLog.description.ilike(like),
            AuditLog.username.ilike(like),
            AuditLog.resource_id.ilike(like),
            AuditLog.study_instance_uid.ilike(like),
            AuditLog.patient_id.ilike(like),
        ))
    return query


@router.get("/export")
async def export_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    format: str = Query("csv", pattern="^(csv|json)$"),
    action: str | None = Query(None),
    username: str | None = Query(None),
    resource_type: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    patient_id: str | None = Query(None),
    study_uid: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Export filtered audit logs as CSV (UTF-8 BOM) or JSON. Admin only.

    Honors the same filters as the list endpoint. Capped at 50,000 rows to
    bound memory; narrow the date range for larger exports.
    """
    import csv
    import io
    import json as _json
    from fastapi.responses import Response

    query = _apply_audit_filters(
        select(AuditLog).order_by(AuditLog.created_at.desc()),
        action=action, username=username, resource_type=resource_type,
        status=status, search=search, patient_id=patient_id,
        study_uid=study_uid, date_from=date_from, date_to=date_to,
    ).limit(50000)
    rows = (await db.execute(query)).scalars().all()

    cols = ["created_at", "username", "ip_address", "action", "resource_type",
            "resource_id", "status", "study_instance_uid", "patient_id", "description"]

    def _row(r):
        return {
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "username": r.username or "",
            "ip_address": r.ip_address or "",
            "action": r.action or "",
            "resource_type": r.resource_type or "",
            "resource_id": r.resource_id or "",
            "status": r.status or "",
            "study_instance_uid": r.study_instance_uid or "",
            "patient_id": r.patient_id or "",
            "description": r.description or "",
        }

    if format == "json":
        body = _json.dumps([_row(r) for r in rows], ensure_ascii=False, indent=2)
        return Response(
            content=body, media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit-log.json"},
        )

    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM for Excel
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(_row(r))
    return Response(
        content=buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
    )


@router.get("/stats")
async def audit_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Get audit log statistics. Admin only."""
    total = await db.execute(select(func.count()).select_from(AuditLog))

    # 대문자로 정규화해 집계 — 그러지 않으면 같은 액션이 `view`/`VIEW` 두 버킷으로
    # 영구히 갈라져 대시보드가 실제보다 잘게 쪼개 보인다(v13.47).
    action_result = await db.execute(
        select(func.upper(AuditLog.action), func.count())
        .group_by(func.upper(AuditLog.action))
    )
    user_result = await db.execute(
        select(AuditLog.username, func.count())
        .where(AuditLog.username.isnot(None))
        .group_by(AuditLog.username)
    )

    return {
        "total_logs": total.scalar() or 0,
        "by_action": dict(action_result.all()),
        "by_user": dict(user_result.all()),
    }


@router.get("/{log_id}")
async def get_audit_log(
    log_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """특정 감사 로그 상세 조회. Admin 전용."""
    result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
    log = result.scalar_one_or_none()

    if log is None:
        raise NotFoundError(resource="audit_log", resource_id=str(log_id))

    return {
        "id": str(log.id),
        "user_id": log.user_id,
        "username": log.username,
        "ip_address": log.ip_address,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "study_instance_uid": log.study_instance_uid,
        "patient_id": log.patient_id,
        "description": log.description,
        "details": log.details,
        "created_at": log.created_at.isoformat(),
    }
