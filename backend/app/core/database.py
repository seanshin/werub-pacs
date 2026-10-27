from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# Only create async engine if using asyncpg driver
if "asyncpg" in settings.database_url:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        # Per-worker pool. With gunicorn's 4 workers this caps idle connections at
        # 4*5=20 (was 4*20=80), leaving headroom on the shared postgres
        # (max_connections=100, also serving HospitalRun). max_overflow handles bursts.
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def get_db() -> AsyncSession:
        async with async_session() as session:
            yield session

    # Alias for backwards compatibility
    get_async_db = get_db
else:
    engine = None
    async_session = None

    async def get_db():
        raise RuntimeError("Async DB not available in sync worker mode")
