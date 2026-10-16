"""PostgreSQL and in-memory checkpointer management for durable LangGraph execution."""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from modernization_platform.config.settings import get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.workflows.errors import CheckpointError

logger = logging.getLogger(__name__)


@log_errors
def normalize_postgres_connection_string(url: str) -> str:
    """Normalize SQLAlchemy async driver URLs to standard PostgreSQL connection strings for psycopg3."""
    try:
        clean = url.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )
        return clean
    except Exception as exc:
        logger.exception(
            "normalize_postgres_connection_string failed | %s: %s", type(exc).__name__, exc
        )
        raise


@log_errors
def ensure_windows_event_loop_policy() -> None:
    """Ensure WindowsSelectorEventLoopPolicy is active on Windows for psycopg async compatibility."""
    try:
        if sys.platform == "win32":
            policy = asyncio.get_event_loop_policy()
            if not isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy):
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                logger.debug("Configured WindowsSelectorEventLoopPolicy for async psycopg driver")
    except Exception as exc:
        logger.warning("Could not set Windows event loop policy: %s", exc)


@log_errors
async def setup_postgres_checkpointer(conn_string: str) -> None:
    """Run checkpointer schema migrations against PostgreSQL."""
    try:
        ensure_windows_event_loop_policy()
        normalized_url = normalize_postgres_connection_string(conn_string)
        async with AsyncPostgresSaver.from_conn_string(normalized_url) as checkpointer:
            await checkpointer.setup()
            logger.info(
                "Successfully established and migrated LangGraph PostgreSQL checkpoint tables."
            )
    except Exception as exc:
        logger.exception("setup_postgres_checkpointer failed | %s: %s", type(exc).__name__, exc)
        raise CheckpointError(f"Failed to setup PostgreSQL checkpointer: {exc}") from exc


@asynccontextmanager
async def get_checkpointer(
    provider: str | None = None,
    conn_string: str | None = None,
) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    """Yield a configured LangGraph checkpointer (PostgreSQL in production/integration, Memory in tests)."""
    try:
        settings = get_settings()
        eff_provider = provider or settings.workflow_checkpointer_provider

        if eff_provider == "memory":
            yield InMemorySaver()
        elif eff_provider == "postgres":
            ensure_windows_event_loop_policy()
            db_url = conn_string or settings.database_url
            if not db_url:
                logger.warning(
                    "No database URL configured for Postgres checkpointer, falling back to MemorySaver"
                )
                yield InMemorySaver()
                return

            normalized_url = normalize_postgres_connection_string(db_url)
            async with AsyncPostgresSaver.from_conn_string(normalized_url) as saver:
                yield saver
        else:
            logger.warning(
                "Unknown checkpointer provider '%s', defaulting to InMemorySaver", eff_provider
            )
            yield InMemorySaver()
    except Exception as exc:
        logger.exception("get_checkpointer failed | %s: %s", type(exc).__name__, exc)
        raise CheckpointError(f"Checkpointer error: {exc}") from exc


__all__ = [
    "ensure_windows_event_loop_policy",
    "get_checkpointer",
    "normalize_postgres_connection_string",
    "setup_postgres_checkpointer",
]
