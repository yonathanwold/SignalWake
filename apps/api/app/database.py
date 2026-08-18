from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.models import Base


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_phase7_columns)


def _ensure_phase7_columns(connection) -> None:
    """Upgrade a create_all-managed dev database without requiring a reset.

    Production deployments apply numbered SQL migrations.  The local SQLite
    path intentionally uses ``create_all`` for deterministic tests and demos,
    but ``create_all`` does not add columns to existing Phase 6 files.  These
    idempotent additions keep that path bootable after the Phase 7 model adds
    optional source-run metadata.
    """

    additions = {
        "sources": {
            "expected_update_interval_seconds": "INTEGER",
            "last_run_id": "VARCHAR(36)",
            "last_records_retrieved": "INTEGER",
            "last_records_accepted": "INTEGER",
            "last_records_rejected": "INTEGER",
        },
        "infrastructure_sources": {
            "expected_update_interval_seconds": "INTEGER",
            "last_run_id": "VARCHAR(36)",
            "last_records_retrieved": "INTEGER",
            "last_records_accepted": "INTEGER",
            "last_records_rejected": "INTEGER",
        },
    }
    inspector = inspect(connection)
    for table, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, sql_type in columns.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'))


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session
