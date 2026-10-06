from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    return create_async_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_recycle=s.db_pool_recycle_seconds,
        pool_pre_ping=True,
        echo=s.db_echo,
        # Every connection works in UTC regardless of server settings.
        connect_args={"server_settings": {"timezone": "UTC", "application_name": "zipzy-dba"}},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_sessionmaker()() as session:
        yield session


async def check_database() -> str:
    """Run a trivial query; return 'user@database (PostgreSQL x.y)'. Raises if unreachable."""
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT current_user, current_database(), current_setting('server_version')")
            )
        ).one()
    return f"{row[0]}@{row[1]} (PostgreSQL {row[2]})"
