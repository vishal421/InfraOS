from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def init_models() -> None:
    """
    Applies the database schema on startup. Alembic migrations
    (alembic/versions/) are now the source of truth — this runs
    `alembic upgrade head` programmatically against the same DATABASE_URL
    the app uses, so `docker compose up` stays a one-command experience
    without a separate migration step to remember.

    create_all() remains as a fallback only for the case where the alembic
    directory isn't present (e.g. someone copied just the `app/` folder
    without `alembic/`) — if that happens it logs loudly, because silently
    falling back to create_all() in a real deployment would mean schema
    changes never get tracked or reviewed.
    """
    import logging
    import os

    logger = logging.getLogger("infraos.db")
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini_path = os.path.join(backend_dir, "alembic.ini")

    if os.path.exists(alembic_ini_path):
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
        # alembic's command API is synchronous; running it in a thread avoids
        # blocking the event loop during startup.
        import asyncio

        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        logger.info("Applied database schema via Alembic (upgrade head).")
    else:
        logger.warning(
            "alembic.ini not found — falling back to Base.metadata.create_all(). "
            "This means schema changes are NOT being tracked as migrations. "
            "Restore the alembic/ directory for any real deployment."
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
