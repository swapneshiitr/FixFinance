"""Database access (LLD §1). Async SQLAlchemy engine over asyncpg.

The schema itself is created by api/db/schema.sql (auto-run by the Postgres image
on first boot), so this module only manages connections + a health probe.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session, closes it after the request."""
    async with SessionLocal() as session:
        yield session


async def health() -> dict:
    """Verify connectivity, that pgvector is installed, and the schema is present."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        has_vector = (
            await conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
        ).first() is not None
        n_tables = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        ).scalar_one()
    return {"db": "up", "pgvector": has_vector, "public_tables": int(n_tables)}
