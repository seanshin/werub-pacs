"""Create (or ensure) a read-only SERVICE account for an external integration
(e.g. LIS QIDO/WADO). Idempotent.

The SERVICE role is deny-by-default under RequireRole — it is blocked from every
gated endpoint (STOW, reports, admin, delete, export) and can only reach
get_current_user reads (QIDO study/series/instance search). Use it for
server-to-server image lookup from a co-located system.

Run inside the backend container after the schema exists (the startup migration
adds the 'service' enum value; run this AFTER a restart that applied it):

    docker compose exec -T -e SVC_PASSWORD="..." backend \
        python -m app.scripts.create_service_account --username svc-lis --email lis@example.org

Re-running never resets an existing account's password unless --rotate is given —
it only ensures the account is SERVICE + active.

Password input: prefer SVC_PASSWORD env or the interactive prompt (TTY). Passing
--password on the command line lands in shell history / `ps` — avoid for rotation.
Note: rotating does NOT revoke already-issued JWTs (per-token blacklist only) —
they stay valid until expiry.
"""
import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import Role, User


def _async_url(url: str) -> str:
    if "+asyncpg" in url:
        return url
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Create/ensure a read-only SERVICE account")
    ap.add_argument("--username", default=os.environ.get("SVC_USERNAME", "svc-lis"))
    ap.add_argument("--password", default=os.environ.get("SVC_PASSWORD", ""))
    ap.add_argument("--email", default=os.environ.get("SVC_EMAIL", "svc-lis@example.org"))
    ap.add_argument("--full-name", default=os.environ.get("SVC_FULL_NAME", "LIS Integration (read-only)"))
    ap.add_argument("--rotate", action="store_true",
                    help="기존 계정의 비밀번호를 --password/SVC_PASSWORD로 교체(컷오버 회전)")
    a = ap.parse_args()

    if not a.password and sys.stdin.isatty():
        # argv/ps 노출 없는 입력 경로 — TTY면 프롬프트
        a.password = getpass.getpass("service account password: ")
    if not a.password:
        print("ERROR: --password / SVC_PASSWORD env / TTY 프롬프트 중 하나 필요", file=sys.stderr)
        return 2
    if len(a.password) < settings.password_min_length:
        print(f"ERROR: password must be at least {settings.password_min_length} characters",
              file=sys.stderr)
        return 2

    engine = create_async_engine(_async_url(settings.database_url))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            existing = (
                await s.execute(select(User).where(User.username == a.username))
            ).scalar_one_or_none()
            if existing:
                changed = []
                if existing.role != Role.SERVICE:
                    existing.role = Role.SERVICE; changed.append("role")
                if not existing.is_active:
                    existing.is_active = True; changed.append("active")
                if a.rotate:
                    # 컷오버 비번 회전 — 명시적 --rotate일 때만 기존 비번 교체
                    existing.hashed_password = hash_password(a.password); changed.append("password(rotated)")
                    print("주의: 이미 발급된 JWT는 만료까지 유효(블랙리스트는 토큰 단위) — "
                          "유출 대응 회전이면 토큰 만료시간만큼 모니터링 필요")
                if changed:
                    await s.commit()
                    print(f"service account '{a.username}' updated ({', '.join(changed)})")
                else:
                    print(f"service account '{a.username}' already exists — no change (비번 회전은 --rotate)")
                return 0
            s.add(User(
                username=a.username,
                email=a.email,
                hashed_password=hash_password(a.password),
                full_name=a.full_name,
                role=Role.SERVICE,
                is_active=True,
            ))
            await s.commit()
            print(f"service account '{a.username}' created (role=SERVICE, read-only)")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
