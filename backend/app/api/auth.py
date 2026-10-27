"""Authentication API endpoints."""
import json
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger, _log_audit_entry
from app.core.cache import get_cache_manager
from app.core.cache_config import CACHE_NAMESPACE
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError, TokenRevokedError
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    RequireRole,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.audit import AuditLog
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _cache_user_permissions(user: User, access_token: str) -> None:
    """
    Cache user permissions in Redis with TTL = JWT expiry time.

    Called after successful login/refresh to enable fast permission checks
    on subsequent requests.
    """
    try:
        cache_mgr = get_cache_manager()
        if not cache_mgr.available:
            return  # Redis not available, skip caching

        # Decode JWT to get expiry time
        try:
            payload = jwt.decode(access_token, settings.secret_key, algorithms=[ALGORITHM])
            exp_timestamp = payload.get("exp")
        except Exception:
            return  # Invalid token, skip caching

        if not exp_timestamp:
            return

        # Build permissions dict from user role and attributes
        permissions_data = {
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role,
            "department": user.department,
            "is_active": user.is_active,
            "cached_at": time.time(),
        }

        cache_key = f"{CACHE_NAMESPACE}permissions:{user.id}"
        ttl = int(exp_timestamp - time.time())

        if ttl > 0:
            await cache_mgr.set(cache_key, json.dumps(permissions_data, default=str), ttl=ttl)
    except Exception as e:
        # Log error but don't fail login on cache error
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error caching permissions for user {user.id}: {e}")


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    role: Role = Role.PHYSICIAN
    department: str | None = None

    @classmethod
    def validate_password_complexity(cls, password: str) -> str:
        import re
        min_len = settings.password_min_length
        if len(password) < min_len:
            raise ValueError(f"비밀번호는 최소 {min_len}자 이상이어야 합니다")
        if not re.search(r'[A-Z]', password):
            raise ValueError("비밀번호에 대문자가 포함되어야 합니다")
        if not re.search(r'[a-z]', password):
            raise ValueError("비밀번호에 소문자가 포함되어야 합니다")
        if not re.search(r'\d', password):
            raise ValueError("비밀번호에 숫자가 포함되어야 합니다")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("비밀번호에 특수문자가 포함되어야 합니다")
        return password


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    username: str
    user_id: str
    expires_in: int  # seconds until access token expiry


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    role: str
    department: str | None
    is_active: bool


async def _check_login_rate_limit(request: Request, username: str) -> None:
    """Rate limit login attempts: max 5 per minute per IP+username."""
    try:
        redis = request.app.state.redis
        ip = request.client.host if request.client else "unknown"
        key = f"login_attempts:{ip}:{username}"
        attempts = await redis.incr(key)
        if attempts == 1:
            await redis.expire(key, 60)  # 1 minute window
        if attempts > 5:
            raise AuthenticationError(message="로그인 시도 횟수 초과. 1분 후 다시 시도해주세요.")
    except (AuthenticationError, PermissionDeniedError):
        raise
    except Exception:
        pass  # Redis unavailable — allow login (rate limiting is defense-in-depth)


async def _audit_login(db: AsyncSession, request: Request, username: str,
                       status: str, reason: str, user: User | None = None) -> None:
    """로그인 시도 감사 — 성공/실패 모두.

    v13.46 계기: `audit_logs`에 **인증 이벤트가 단 한 건도 없었다**(실측). logout에만
    기록 코드가 있었고(실사용 0건) login은 성공도 실패도 남지 않아, "누가 언제
    시스템에 들어왔는가"와 "언제부터 자격증명 공격이 있었나"를 사후에 답할 수 없었다.
    BTG·PHI 스윕·append-only 트리거까지 갖춘 감사 태세에서 가장 앞단이 비어 있었다.

    비밀번호는 절대 싣지 않는다. 실패 사유는 분류값만 남긴다(계정 존재 여부를
    로그로 확증해 주는 것도 정보라, reason은 invalid_credentials로 합쳐 둔다).
    """
    await _log_audit_entry(
        db=db, operation="LOGIN", resource_type="auth", status=status,
        user_id=str(user.id) if user else None,
        username=username,
        details={"reason": reason,
                 "ip": request.client.host if request.client else None},
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    # Rate limit check — 초과도 감사 대상이다(공격의 가장 뚜렷한 신호)
    try:
        await _check_login_rate_limit(request, body.username)
    except Exception:
        await _audit_login(db, request, body.username, "FAILED", "rate_limited")
        raise

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        # 사용자 부재와 비밀번호 불일치를 구분해 남기지 않는다 — 감사 로그가
        # 계정 열거 도구가 되면 안 된다.
        await _audit_login(db, request, body.username, "FAILED",
                           "invalid_credentials", user=None)
        raise AuthenticationError(message="Invalid credentials")

    if not user.is_active:
        await _audit_login(db, request, body.username, "FAILED",
                           "account_disabled", user=user)
        raise PermissionDeniedError(message="Account is disabled")

    # Upgrade-on-login: legacy hashes (no ":") derive their salt from SECRET_KEY,
    # which couples them to the key and blocks rotation. Re-hash with the per-user
    # random-salt scheme now that we have the verified plaintext — over time this
    # migrates active users off the SECRET_KEY salt so the key can be rotated.
    if ":" not in user.hashed_password:
        user.hashed_password = hash_password(body.password)
        await db.commit()

    access_token = create_access_token(str(user.id), user.username, user.role)

    # Cache user permissions for fast permission checks
    await _cache_user_permissions(user, access_token)

    await _audit_login(db, request, user.username, "SUCCESS", "password", user=user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=create_refresh_token(str(user.id)),
        role=user.role,
        username=user.username,
        user_id=str(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
@AuditLogger.log("TOKEN_REFRESH", "Token")
async def refresh_token(body: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise TokenRevokedError()

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise AuthenticationError(message="User not found or account disabled")

    access_token = create_access_token(str(user.id), user.username, user.role)

    # Cache user permissions for fast permission checks
    await _cache_user_permissions(user, access_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=create_refresh_token(str(user.id)),
        role=user.role,
        username=user.username,
        user_id=str(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: Annotated[User, Depends(get_current_user)]):
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        is_active=user.is_active,
    )


@router.post("/logout")
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """사용자 로그아웃 — JWT 토큰을 Redis 블랙리스트에 등록.

    의료법 컴플라이언스: 세션 종료를 감사 로그에 명시적으로 기록.
    토큰의 남은 유효 시간 동안만 블랙리스트 항목을 보존(TTL 자동 만료).
    """
    redis = request.app.state.redis

    # Extract raw bearer token
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()

    if token:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
            exp = payload.get("exp")
            if exp:
                ttl = int(exp) - int(time.time())
                if ttl > 0:
                    await redis.setex(f"blacklist:{token}", ttl, "1")
        except JWTError:
            # Token already expired or malformed — no need to blacklist
            pass

    # Delete cached permissions on logout
    cache_mgr = get_cache_manager()
    if cache_mgr.available:
        cache_key = f"{CACHE_NAMESPACE}permissions:{current_user.id}"
        try:
            await cache_mgr.delete(cache_key)
        except Exception:
            pass  # Cache deletion failure shouldn't block logout

    # Record audit log (의료법 준수)
    audit = AuditLog(
        user_id=str(current_user.id),
        username=current_user.username,
        ip_address=request.client.host if request.client else None,
        action="LOGOUT",   # v13.46의 LOGIN과 짝을 맞춘다(대문자 NAME 통일, v13.47)
        resource_type="auth",
        description=f"User '{current_user.username}' logged out",
    )
    db.add(audit)
    await db.commit()

    return {"message": "Successfully logged out"}


@router.post("/register", response_model=UserResponse)
@AuditLogger.log("USER_CREATED", "User")
async def register_user(
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Register a new user. Admin only."""
    # Validate password complexity
    try:
        RegisterRequest.validate_password_complexity(body.password)
    except ValueError as e:
        from app.core.exceptions import ValidationError
        raise ValidationError(message=str(e))

    # Check duplicates
    existing = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if existing.scalar_one_or_none():
        raise ConflictError(message="Username or email already exists")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        department=body.department,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        is_active=user.is_active,
    )


@router.post("/setup", response_model=UserResponse)
async def initial_setup(body: RegisterRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Create initial admin user. Only works when no users exist AND setup is enabled.

    S13: 설치는 create_admin 스크립트가 담당 — 이 무인증 EP는 default-off. 전 사용자 삭제 시
    무인증 ADMIN 재시드를 막는다(INITIAL_SETUP_ENABLED로만 명시 활성).
    """
    if not settings.initial_setup_enabled:
        raise PermissionDeniedError(
            message="Initial setup endpoint is disabled. Use the create_admin script."
        )
    result = await db.execute(select(User).limit(1))
    if result.scalar_one_or_none():
        raise ConflictError(message="System already initialized")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=Role.ADMIN,
        department=body.department,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        is_active=user.is_active,
    )


@router.post("/seed-test-accounts", summary="테스트 계정 일괄 생성")
async def seed_test_accounts(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """역할별 테스트 계정을 생성합니다. Admin 전용. Debug 모드에서만 사용 가능."""
    if not settings.debug:
        from app.core.exceptions import PermissionDeniedError
        raise PermissionDeniedError(message="테스트 계정 생성은 debug 모드에서만 가능합니다.")
    test_accounts = [
        {"username": "tech.park", "email": "tech@example.org", "full_name": "박기사",
         "role": Role.TECHNOLOGIST, "department": "영상의학과", "password": secrets.token_urlsafe(12)},
        {"username": "dr.lee", "email": "dr.lee@example.org", "full_name": "이주치의",
         "role": Role.PHYSICIAN, "department": "내과", "password": secrets.token_urlsafe(12)},
        {"username": "res.choi", "email": "res@example.org", "full_name": "최연구원",
         "role": Role.RESEARCHER, "department": "의학연구소", "password": secrets.token_urlsafe(12)},
    ]

    created = []
    skipped = []
    for acc in test_accounts:
        existing = await db.execute(select(User).where(User.username == acc["username"]))
        if existing.scalar_one_or_none():
            skipped.append(acc["username"])
            continue
        new_user = User(
            username=acc["username"],
            email=acc["email"],
            hashed_password=hash_password(acc["password"]),
            full_name=acc["full_name"],
            role=acc["role"],
            department=acc["department"],
        )
        db.add(new_user)
        created.append(acc["username"])

    await db.commit()
    # 공개판: 무작위로 만든 비밀번호는 이 응답에서 한 번만 알려 준다
    return {"created": created, "skipped": skipped, "total": len(created),
            "passwords": {a["username"]: a["password"] for a in test_accounts if a["username"] in created}}
