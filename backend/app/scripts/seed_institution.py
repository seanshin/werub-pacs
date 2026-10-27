"""Seed institution defaults so a fresh install is immediately usable. Idempotent.

Run inside the backend container after the schema exists:
    docker compose exec -T backend python -m app.scripts.seed_institution

Seeds (only when empty):
  - DICOM issue validation rules (24), modality render configs, message templates.
    (These otherwise self-seed lazily on first admin access; doing it at install
    makes the DICOM Issue Center ready from minute one.)

Not seeded here (by design):
  - Reading-report templates — create from the admin UI (Templates → 기본 템플릿)
    or POST /api/v1/templates/seed-defaults.
  - SLA thresholds — built-in defaults apply until configured.
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.api.dicom_issues.seed import seed_dicom_issue_data


def _async_url(url: str) -> str:
    if "+asyncpg" in url:
        return url
    return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://")


async def main() -> int:
    engine = create_async_engine(_async_url(settings.database_url))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            await seed_dicom_issue_data(s)
            await s.commit()
        print("institution defaults seeded (DICOM issue rules / modalities / messages)")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
