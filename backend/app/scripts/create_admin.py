"""Create (or ensure) the first PACS admin user. Idempotent.

Run inside the backend container after the schema exists:
    docker compose exec -T -e ADMIN_PASSWORD="..." backend \
        python -m app.scripts.create_admin --username admin --email admin@hospital.example.org

Re-running never resets an existing user's password — it only ensures the
account is ADMIN + active. Bypasses the HTTP layer (no existing admin needed),
so it does NOT enforce password complexity beyond the configured minimum length;
change the password from the UI after first login.
"""
import argparse
import asyncio
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
    ap = argparse.ArgumentParser(description="Create/ensure the first PACS admin user")
    ap.add_argument("--username", default=os.environ.get("ADMIN_USERNAME", "admin"))
    ap.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    ap.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", "admin@example.org"))
    ap.add_argument("--full-name", default=os.environ.get("ADMIN_FULL_NAME", "Administrator"))
    a = ap.parse_args()

    if not a.password:
        print("ERROR: --password (or ADMIN_PASSWORD env) is required", file=sys.stderr)
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
                if existing.role != Role.ADMIN or not existing.is_active:
                    existing.role = Role.ADMIN
                    existing.is_active = True
                    await s.commit()
                    print(f"admin '{a.username}' updated (role/active ensured; password unchanged)")
                else:
                    print(f"admin '{a.username}' already exists — no change")
                return 0
            s.add(User(
                username=a.username,
                email=a.email,
                hashed_password=hash_password(a.password),
                full_name=a.full_name,
                role=Role.ADMIN,
                is_active=True,
            ))
            await s.commit()
            print(f"admin '{a.username}' created")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
