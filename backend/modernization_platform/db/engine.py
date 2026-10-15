"""Async SQLAlchemy engine lifecycle and connection pool management."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from modernization_platform.config.settings import Settings, get_settings
from modernization_platform.core.exceptions import PersistenceError

logger = logging.getLogger(__name__)

# Module-level singleton engine reference
_ENGINE: AsyncEngine | None = None


def create_database_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create and configure a production-grade AsyncEngine with connection pooling."""
    try:
        app_settings = settings or get_settings()

        connect_args: dict[str, Any] = {}
        # Configure asyncpg specific connection parameters
        if "asyncpg" in app_settings.database_url:
            connect_args["timeout"] = app_settings.db_connect_timeout_seconds
            connect_args["server_settings"] = {
                "application_name": app_settings.db_application_name,
                "statement_timeout": str(app_settings.db_statement_timeout_ms),
            }
            if app_settings.db_ssl_mode in ("require", "verify-ca", "verify-full"):
                connect_args["ssl"] = True

        logger.info(
            "Creating AsyncEngine for database: %s (pool_size=%d, max_overflow=%d, pool_recycle=%ds)",
            app_settings.database_url_masked,
            app_settings.db_pool_size,
            app_settings.db_max_overflow,
            app_settings.db_pool_recycle_seconds,
        )

        engine = create_async_engine(
            app_settings.database_url,
            echo=app_settings.db_echo,
            pool_size=app_settings.db_pool_size,
            max_overflow=app_settings.db_max_overflow,
            pool_timeout=app_settings.db_pool_timeout_seconds,
            pool_recycle=app_settings.db_pool_recycle_seconds,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        return engine
    except Exception as exc:
        logger.exception("Failed to create database engine | %s: %s", type(exc).__name__, exc)
        raise PersistenceError(f"Database engine initialization failed: {exc}") from exc


def get_database_engine(settings: Settings | None = None) -> AsyncEngine:
    """Retrieve or lazily initialize the singleton database AsyncEngine."""
    global _ENGINE
    try:
        if _ENGINE is None:
            _ENGINE = create_database_engine(settings=settings)
        return _ENGINE
    except Exception as exc:
        logger.exception("get_database_engine failed | %s: %s", type(exc).__name__, exc)
        raise


async def dispose_database_engine(engine: AsyncEngine | None = None) -> None:
    """Safely dispose of the engine and close all idle pooled connections."""
    global _ENGINE
    try:
        target = engine or _ENGINE
        if target is not None:
            logger.info("Disposing database engine connection pool.")
            await target.dispose()
            if target is _ENGINE:
                _ENGINE = None
    except Exception as exc:
        logger.exception("Failed to dispose database engine | %s: %s", type(exc).__name__, exc)
        raise PersistenceError(f"Database engine disposal failed: {exc}") from exc


async def check_database_readiness(
    engine: AsyncEngine | None = None,
    timeout_seconds: float = 2.0,
) -> tuple[bool, str]:
    """Execute a lightweight bounded connectivity probe (SELECT 1).

    Returns a tuple of (is_ready, message) without leaking credentials or internal details.
    """
    try:
        import asyncio

        from sqlalchemy import text

        target = engine or get_database_engine()

        async def _probe() -> None:
            try:
                async with target.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            except Exception as exc:
                logger.warning(
                    "Inner database probe check failed | %s: %s", type(exc).__name__, exc
                )
                raise

        await asyncio.wait_for(_probe(), timeout=timeout_seconds)
        return True, "PostgreSQL connection healthy"
    except TimeoutError:
        logger.warning("Database connectivity probe timed out after %.1fs", timeout_seconds)
        return False, "Database connectivity probe timed out"
    except Exception as exc:
        logger.warning("Database connectivity probe failed: %s", type(exc).__name__)
        return False, "Database connectivity probe failed"
