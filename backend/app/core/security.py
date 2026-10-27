"""JWT authentication and RBAC authorization."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache_manager
from app.core.cache_config import CACHE_NAMESPACE
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError, TokenRevokedError
from app.models.user import Role, User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7
SSO_PASSWORD_MARKER = "SSO_NO_LOCAL_LOGIN"

security_scheme = HTTPBearer(auto_error=False)


PBKDF2_ITERATIONS = 600_000  # OWASP 2023 recommendation for PBKDF2-SHA256

def hash_password(password: str) -> str:
    """Hash password with per-user random salt (stored as salt:hash)."""
    salt = os.urandom(16).hex()
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"{salt}:{pw_hash}"


def verify_password(password: str, hashed: str) -> bool:
    if hashed == SSO_PASSWORD_MARKER:
        return False  # SSO users cannot login locally
    if ":" not in hashed:
        # Legacy single-salt format — verify and mark for migration
        old_salt = settings.secret_key[:16]
        old_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), old_salt.encode(), 100_000).hex()
        return hmac.compare_digest(old_hash, hashed)
    salt, stored_hash = hashed.split(":", 1)
    # Try current iteration count first, then legacy 100k for migration
    for iterations in (PBKDF2_ITERATIONS, 100_000):
        pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
        if hmac.compare_digest(pw_hash, stored_hash):
            return True
    return False


def create_access_token(user_id: str, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "username": username, "role": role, "exp": expire, "type": "access"},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh"},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decode OpenPACS JWT token."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise AuthenticationError(message="Invalid token")


_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL = 3600  # seconds — periodic refresh (no permanent cache, per HIS spec §5)
_JWKS_MIN_REFRESH = 60  # min seconds between forced (kid-miss) refetches — DoS guard


def _get_jwks(force: bool = False) -> dict | None:
    """Fetch (and cache) the hospital common-SSO JWKS. Returns None if unconfigured.

    force=True re-fetches on a kid miss (key rotation, HIS spec §5: "kid 미스 시
    JWKS 재조회 1회"), throttled to _JWKS_MIN_REFRESH so random-kid tokens can't
    trigger a refetch storm.
    """
    if not settings.his_jwks_url:
        return None
    now = time.time()
    age = now - _jwks_cache["fetched_at"]
    if _jwks_cache["keys"] is None or age > _JWKS_TTL or (force and age > _JWKS_MIN_REFRESH):
        try:
            resp = httpx.get(settings.his_jwks_url, timeout=5.0)
            resp.raise_for_status()
            _jwks_cache["keys"] = resp.json()
            _jwks_cache["fetched_at"] = now
            age = 0.0
        except Exception as e:
            logging.getLogger(__name__).warning(f"JWKS fetch failed ({e}); cache age {age:.0f}s")
    # bounded stale — 갱신 실패로 캐시가 max-stale 초과면 fail-closed(매우 오래된/폐기 키 거부).
    # 짧은 blip은 stale 캐시로 SSO 유지, 장기 다운/키회전 시엔 None 반환(보안). 네이티브
    # HS256 로그인은 JWKS 미사용이라 무영향.
    if _jwks_cache["keys"] is not None and age > settings.his_jwks_max_stale_seconds:
        logging.getLogger(__name__).error(
            f"JWKS cache too stale ({age:.0f}s > {settings.his_jwks_max_stale_seconds}s) — fail-closed")
        return None
    return _jwks_cache["keys"]


def _find_jwk(jwks: dict | None, kid: str | None) -> dict | None:
    return next((k for k in (jwks or {}).get("keys", []) if k.get("kid") == kid), None)


def decode_hospitalrun_token(token: str) -> dict | None:
    """Decode a HospitalRun / hospital-common-SSO token. Returns None if not valid.

    Tries RS256/JWKS first (common SSO, issuer hospitalrun) when his_jwks_url is set
    — this is the token a radiologist also presents to the external e-sign service
    (/v1/sign/staff). Falls back to the legacy HS256 shared secret.
    """
    # 1) RS256 via JWKS (hospital common SSO)
    jwks = _get_jwks()
    if jwks:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = _find_jwk(jwks, kid)
            if not key:
                # kid miss → key rotation; re-fetch JWKS once (throttled) and retry
                key = _find_jwk(_get_jwks(force=True), kid)
            if key:
                aud = settings.his_jwt_audience or None
                payload = jwt.decode(
                    token, key, algorithms=["RS256", "RS384", "RS512"],
                    issuer=settings.his_jwt_issuer or None,
                    audience=aud,
                    options={"verify_aud": bool(aud)},
                )
                if "sub" in payload:
                    return payload
        except JWTError:
            pass
        except Exception as e:
            logging.getLogger(__name__).debug(f"JWKS verify miss: {e}")

    # 2) Legacy HS256 shared secret
    if settings.hospitalrun_auth_secret:
        try:
            payload = jwt.decode(token, settings.hospitalrun_auth_secret, algorithms=[ALGORITHM])
            # HospitalRun payload: { sub: userId, email, role }
            if "email" in payload and "sub" in payload:
                return payload
        except JWTError:
            pass
    return None


def verify_export_service_token(token: str, mrn: str | None = None) -> dict | None:
    """Verify a patient-export service token (patient-portal feature).

    Signed with a DEDICATED export secret (patient_export_secret) when set, else
    falls back to the HIS shared secret. A dedicated secret keeps the agreement
    2-party (PACS↔portal) and decouples it from HIS SSO rotation — preferred.
    The token must carry scope=patient-export. When `mrn` is given, the token's
    mrn must match it, sealing each request to the patient the portal verified.

    Returns the payload on success, None otherwise (fail-closed when no secret).
    """
    secret = settings.patient_export_secret or settings.hospitalrun_auth_secret
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("scope") != "patient-export":
        return None
    if not payload.get("mrn"):
        return None
    if mrn is not None and payload.get("mrn") != mrn:
        return None
    return payload


# HIS role → OpenPACS role mapping (per SSO spec v1.0)
HIS_ROLE_MAP = {
    "ADMIN": "admin",
    "DOCTOR": "physician",
    "RADIOLOGIST": "radiologist",
    "NURSE": "physician",        # Read-only enforced at endpoint level
    "LAB_TECH": "technologist",
    "TECHNICIAN": "technologist",
    "PHARMACIST": "physician",   # Read-only, image reference
    "RECEPTIONIST": "physician",
    "PATIENT": None,             # PACS access denied
}

# Backwards compatibility alias
HR_ROLE_MAP = HIS_ROLE_MAP


def _is_service_role(user: User) -> bool:
    try:
        return Role(user.role) == Role.SERVICE
    except Exception:
        return str(user.role).lower() == "service"


def _enforce_service_readonly(user: User, request: "Request | None") -> None:
    """SERVICE 역할(외부 연동 read-only, 예: svc-lis)은 GET/HEAD/OPTIONS만 허용.
    RequireRole은 deny-by-default라 SERVICE를 자동 차단하지만, get_current_user만 쓰는
    쓰기·AI 엔드포인트(리포트 적용/추론/주석 등)는 SERVICE가 통과하므로 여기서 뮤테이션을 차단(H1)."""
    if request is not None and request.method not in ("GET", "HEAD", "OPTIONS"):
        if _is_service_role(user):
            raise PermissionDeniedError(message="SERVICE 계정은 읽기 전용입니다")


async def _audit_service_access(db: AsyncSession, user: User, request: "Request | None") -> None:
    """SERVICE 계정의 API 접근을 audit_logs에 남김 — 외부 연동(LIS 등)의 PHI 조회 추적.

    QIDO 등 read EP는 자체 감사가 없어 SERVICE 접근이 무기록이었음(LIS 컷오버 §7
    '접근 패턴' 모니터링 요건). 임상 사용자 read엔 미적용(노이즈 방지), SERVICE 한정.
    감사 실패가 요청을 깨지 않음."""
    try:
        from app.models.audit import AuditLog
        db.add(AuditLog(
            action="SERVICE_ACCESS",
            resource_type="API",
            status="SUCCESS",
            user_id=str(user.id),
            username=user.username,
            ip_address=(request.client.host if request is not None and request.client else None),
            details={
                "method": request.method if request is not None else None,
                "path": request.url.path if request is not None else None,
            },
        ))
        await db.commit()
    except Exception:
        logging.getLogger(__name__).warning("SERVICE access audit write failed", exc_info=True)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request = None,
) -> User:
    if credentials is None:
        raise AuthenticationError(message="Not authenticated")

    token = credentials.credentials

    # 0. Check token blacklist (populated by /logout)
    if request is not None:
        try:
            redis = request.app.state.redis
            is_blacklisted = await redis.exists(f"blacklist:{token}")
            if is_blacklisted:
                raise TokenRevokedError()
        except (AuthenticationError, TokenRevokedError, PermissionDeniedError):
            raise
        except Exception:
            # Redis unavailable — fail-closed for PHI protection
            import logging
            logging.getLogger(__name__).warning(
                "Redis unavailable for token blacklist check — denying request (fail-closed)"
            )
            raise AuthenticationError(message="인증 서비스 일시 장애. 잠시 후 다시 시도해주세요.")

    # Check session idle timeout
    if request is not None:
        try:
            redis = request.app.state.redis
            # token[:32]는 같은 헤더/alg 토큰끼리 prefix 충돌→idle 타이머 공유. 전체 토큰 해시.
            idle_key = f"session_activity:{hashlib.sha256(token.encode()).hexdigest()[:32]}"
            last_activity = await redis.get(idle_key)
            idle_timeout = settings.session_idle_timeout_minutes * 60
            if last_activity:
                import time
                elapsed = time.time() - float(last_activity)
                if elapsed > idle_timeout:
                    await redis.delete(idle_key)
                    raise AuthenticationError(message="세션이 만료되었습니다. 다시 로그인해주세요.")
            # Update activity timestamp
            await redis.setex(idle_key, idle_timeout, str(time.time()))
        except (AuthenticationError, TokenRevokedError, PermissionDeniedError):
            raise
        except Exception:
            pass  # Redis unavailable — skip idle check (defense-in-depth only)

    # 1. Try OpenPACS native token first
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("type") == "access":
            user_id = payload.get("sub")

            # Check permissions cache first
            cache_mgr = get_cache_manager()
            cache_key = f"{CACHE_NAMESPACE}permissions:{user_id}"

            try:
                cached_perms = await cache_mgr.get(cache_key)
                if cached_perms:
                    # Cached permissions found — construct user from cache + DB fallback
                    result = await db.execute(select(User).where(User.id == user_id))
                    user = result.scalar_one_or_none()
                    if user and user.is_active:
                        _enforce_service_readonly(user, request)
                        if _is_service_role(user):
                            await _audit_service_access(db, user, request)
                        return user
            except Exception:
                # Cache check failed — continue to DB query
                pass

            # Cache miss or error — query database
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user and user.is_active:
                _enforce_service_readonly(user, request)
                if _is_service_role(user):
                    await _audit_service_access(db, user, request)
                return user
    except JWTError:
        pass

    # 2. Try HIS SSO token (HospitalRun)
    # 동기 _get_jwks(httpx.get)가 JWKS 캐시 cold/만료/kid-miss 시 이벤트루프를 최대 5초
    # 블로킹 → 스레드로 오프로딩(워커 전역 정지 방지).
    his_payload = await asyncio.to_thread(decode_hospitalrun_token, token)
    if his_payload:
        his_user_id = his_payload.get("sub", "")
        email = his_payload.get("email", "")
        his_role = his_payload.get("role", "")
        his_name = his_payload.get("name", "")
        # Fail-closed: an unmapped/new HIS role must NOT auto-elevate to a
        # PHI-capable role. Only explicitly mapped roles are admitted; anything
        # else (incl. PATIENT) is denied.
        pacs_role = HIS_ROLE_MAP.get(his_role)

        # Unmapped or explicitly-denied (e.g. PATIENT) role → deny PACS access
        if pacs_role is None:
            raise PermissionDeniedError(
                message="해당 HIS 역할은 PACS에 직접 접근할 수 없습니다"
            )

        # Find user by HIS user ID (stored in department field as "HIS:{id}") or email
        user = None
        if his_user_id:
            result = await db.execute(
                select(User).where(User.department.like(f"HIS:{his_user_id}%"))
            )
            user = result.scalar_one_or_none()

        if user is None and email:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if user is None:
            # JIT Provisioning — auto-create user from HIS SSO
            username = email.split("@")[0] if email else f"his_{his_user_id[:8]}"
            full_name = his_name or username
            user = User(
                username=username,
                email=email or f"{username}@his.local",
                hashed_password=SSO_PASSWORD_MARKER,
                full_name=full_name,
                role=pacs_role,
                department=f"HIS:{his_user_id}",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            # Update role/name if changed in HIS
            updated = False
            if user.role != pacs_role:
                user.role = pacs_role
                updated = True
            if his_name and user.full_name != his_name:
                user.full_name = his_name
                updated = True
            if updated:
                await db.commit()

        if user.is_active:
            # Store HIS context on request for audit logging
            if request is not None:
                request.state.his_user_id = his_user_id
                request.state.his_role = his_role
            _enforce_service_readonly(user, request)
            return user

    raise AuthenticationError(message="Invalid token")


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Returns user if authenticated, None otherwise. For endpoints that work with or without auth."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except (AuthenticationError, TokenRevokedError, PermissionDeniedError):
        return None


class RequireRole:
    """Dependency that checks if user has one of the required roles.

    RESIDENT is treated as RADIOLOGIST for access control purposes.
    This allows residents to access all radiologist endpoints
    while maintaining a distinct role for workflow differentiation
    (e.g., preliminary vs final signing).

    Break-the-Glass is an emergency *clinical-read* override and is enabled by
    default. Endpoints that perform bulk PHI export or write admin configuration
    must opt out with allow_btg=False — emergency clinical access is no
    justification for unlocking data exfiltration or config tampering.
    """

    def __init__(self, *roles: Role, allow_btg: bool = True):
        self.roles = roles
        self.allow_btg = allow_btg

    async def __call__(
        self,
        user: Annotated[User, Depends(get_current_user)],
        request: Request = None,
    ) -> User:
        user_role = Role(user.role)
        # RESIDENT inherits RADIOLOGIST access
        effective_role = Role.RADIOLOGIST if user_role == Role.RESIDENT else user_role
        if effective_role not in self.roles and user_role not in self.roles:
            # Check for Break-the-Glass override (clinical-read endpoints only)
            if self.allow_btg and request and request.headers.get("X-Break-The-Glass"):
                import logging
                logging.getLogger(__name__).warning(
                    "BREAK-THE-GLASS access granted",
                    extra={
                        "user": user.username,
                        "role": user.role,
                        "required_roles": [r.value for r in self.roles],
                        "reason": request.headers.get("X-Break-The-Glass-Reason", "emergency"),
                        "path": str(request.url.path) if request else "unknown",
                    },
                )
                # Record audit event
                if request:
                    request.state.break_the_glass = True
                    request.state.btg_reason = request.headers.get("X-Break-The-Glass-Reason", "emergency")
                return user
            raise PermissionDeniedError(
                message=f"Role '{user.role}' is not authorized. Required: {[r.value for r in self.roles]}"
            )
        return user


# ── PHI 조회 공용 역할 집합 ────────────────────────────────────────────────
# 환자명·PatientID(MRN)·생년월일을 응답에 담는 **목록/상세 조회**의 기본 집합.
#
# 계기(2026-08-03): 같은 결함을 세 번 고쳤다 — 리포트(v13.8 ReportReadRoles)·
# QIDO/WADO(v13.19 StudyReadRoles)·워크리스트(v13.41). 그러고도 전수 스윕에서
# RESEARCHER가 200으로 PHI를 열거하는 엔드포인트가 6개 더 나왔다(ai/jobs·
# reading-queue·hospitalrun orders·emergency board·retake·dicom-issues).
# 원인은 **역할 집합이 파일마다 흩어져** 새 엔드포인트가 조용히 `get_current_user`로
# 열린 것이다. 그래서 여기 하나로 둔다 — 새 PHI 조회는 이것을 쓴다.
#
#   · RESEARCHER 제외 — 비임상·연구용. MRN/이름/DOB 열거 금지
#   · SERVICE 제외 — 외부 연계(svc-lis)에 타 부서 환자 정보가 열려선 안 된다.
#     연계가 필요로 하는 것은 대개 자기 건의 상태이고, 그건 PHI 미반환 EP로 준다
#     (예: `GET /worklist/verify`, v13.40)
#   · RESIDENT는 RequireRole이 RADIOLOGIST로 승격 → 별도 지정 불요
#
# ※ 소유자 스코프가 더 필요한 곳(PHYSICIAN=본인 의뢰 건만 등)은 이 집합 위에
#    추가 검사를 얹는다. ReportReadRoles가 그 예다.
ClinicalPHIReadRoles = RequireRole(
    Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, Role.TECHNOLOGIST
)


# 임상 스태프 **쓰기** 기본 집합. 역할 목록은 ClinicalPHIReadRoles와 같지만 의도가 달라
# 분리해 둔다(읽기/쓰기 정책은 갈릴 수 있다 — 예: 리포트 작성은 ADMIN/RAD만).
# RESEARCHER(비임상)·SERVICE(외부 연계)는 임상 데이터를 쓰지 못한다.
ClinicalWriteRoles = RequireRole(
    Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN, Role.TECHNOLOGIST
)
