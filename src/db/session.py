"""Async SQLAlchemy session factory backed by aiosqlite.

Use `get_db()` as a FastAPI dependency, and `init_db()` once at startup.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import settings
from src.db.models import Base

# SQLite async URL — aiosqlite driver
DATABASE_URL = f"sqlite+aiosqlite:///{settings.DB_PATH}"

# echo=False to keep PHI-free logs; SQLite needs no pool sizing
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession with auto-close."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


__all__ = ["async_engine", "AsyncSessionLocal", "get_db", "init_db", "DATABASE_URL"]
