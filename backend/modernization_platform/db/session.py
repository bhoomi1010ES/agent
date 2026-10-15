"""Async SQLAlchemy session factory and transaction boundary context managers."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from modernization_platform.core.exceptions import PersistenceError
from modernization_platform.db.engine import get_database_engine

logger = logging.getLogger(__name__)

# Global session factory cache
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = None


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Retrieve or construct the async_sessionmaker factory bound to the active engine."""
    global _SESSION_FACTORY
    try:
        if engine is not None:
            return async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
        if _SESSION_FACTORY is None:
            active_engine = get_database_engine()
            _SESSION_FACTORY = async_sessionmaker(
                bind=active_engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
        return _SESSION_FACTORY
    except Exception as exc:
        logger.exception("get_session_factory failed | %s: %s", type(exc).__name__, exc)
        raise PersistenceError(f"Failed to create session factory: {exc}") from exc


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an isolated AsyncSession per request.

    Guarantees session rollback on unhandled errors and reliable closure on completion.
    """
    factory = get_session_factory()
    session: AsyncSession = factory()
    try:
        yield session
    except Exception as exc:
        logger.exception(
            "Error encountered during request DB session; rolling back | %s: %s",
            type(exc).__name__,
            exc,
        )
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def transactional_session(
    engine: AsyncEngine | None = None,
) -> AsyncIterator[AsyncSession]:
    """Context manager establishing an atomic transaction boundary.

    Commits upon successful exit; rolls back and re-raises on any exception.
    """
    factory = get_session_factory(engine=engine)
    session: AsyncSession = factory()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        logger.exception(
            "Transaction failed; rolling back all uncommitted writes | %s: %s",
            type(exc).__name__,
            exc,
        )
        await session.rollback()
        raise PersistenceError(f"Transaction aborted: {exc}") from exc
    finally:
        await session.close()
