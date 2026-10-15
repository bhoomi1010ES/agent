"""Unit tests for database engine, session factory, transaction manager, and health probe."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from modernization_platform.config.settings import Settings
from modernization_platform.core.exceptions import PersistenceError
from modernization_platform.db.engine import (
    check_database_readiness,
    create_database_engine,
    dispose_database_engine,
    get_database_engine,
)
from modernization_platform.db.session import (
    get_db_session,
    get_session_factory,
    transactional_session,
)


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://test_user:test_pwd@localhost:5432/test_db",
        db_pool_size=5,
        db_max_overflow=10,
        db_pool_timeout_seconds=5.0,
        db_pool_recycle_seconds=600,
        db_ssl_mode="prefer",
    )


@pytest.mark.asyncio
async def test_create_and_dispose_database_engine(mock_settings: Settings) -> None:
    """Verify engine creation and disposal lifecycle."""
    engine = create_database_engine(mock_settings)
    assert isinstance(engine, AsyncEngine)

    await dispose_database_engine(engine)


@pytest.mark.asyncio
async def test_get_database_engine_singleton(mock_settings: Settings) -> None:
    """Verify get_database_engine returns consistent singleton instance."""
    engine1 = get_database_engine(mock_settings)
    engine2 = get_database_engine(mock_settings)
    assert engine1 is engine2

    await dispose_database_engine()


@pytest.mark.asyncio
async def test_get_session_factory() -> None:
    """Verify session factory creation with explicit and default engine."""
    mock_engine = MagicMock(spec=AsyncEngine)
    factory = get_session_factory(mock_engine)
    assert factory is not None

    with (
        patch("modernization_platform.db.session.get_database_engine", return_value=mock_engine),
        patch("modernization_platform.db.session._SESSION_FACTORY", None),
    ):
        default_factory = get_session_factory(engine=None)
        assert default_factory is not None


@pytest.mark.asyncio
async def test_get_db_session_dependency() -> None:
    """Verify get_db_session yields an AsyncSession and closes it."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_factory = MagicMock(return_value=mock_session)

    with patch("modernization_platform.db.session.get_session_factory", return_value=mock_factory):
        session_gen: AsyncIterator[AsyncSession] = get_db_session()
        session = await anext(session_gen)
        assert session is mock_session
        with pytest.raises(StopAsyncIteration):
            await anext(session_gen)


@pytest.mark.asyncio
async def test_transactional_session_commits_on_success() -> None:
    """Verify transactional_session commits when the block completes without error."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("modernization_platform.db.session.get_session_factory", return_value=mock_factory):
        async with transactional_session() as session:
            assert session is mock_session

    mock_session.commit.assert_awaited_once()
    mock_session.rollback.assert_not_awaited()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_transactional_session_rolls_back_on_exception() -> None:
    """Verify transactional_session rolls back when an exception occurs."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with (
        patch("modernization_platform.db.session.get_session_factory", return_value=mock_factory),
        pytest.raises(PersistenceError, match="Transaction aborted: Intentional error"),
    ):
        async with transactional_session():
            raise ValueError("Intentional error")

    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_not_awaited()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_transactional_session_commit_failure_translates_to_persistence_error() -> None:
    """Verify commit failure is logged and re-raised as PersistenceError."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.side_effect = RuntimeError("Disk full")
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with (
        patch("modernization_platform.db.session.get_session_factory", return_value=mock_factory),
        pytest.raises(PersistenceError, match="Transaction aborted: Disk full"),
    ):
        async with transactional_session():
            pass


@pytest.mark.asyncio
async def test_check_database_readiness_probe_healthy() -> None:
    """Verify check_database_readiness returns (True, message) on successful probe."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = None

    mock_engine = MagicMock(spec=AsyncEngine)
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    mock_engine.connect.return_value.__aexit__.return_value = None

    is_ready, message = await check_database_readiness(engine=mock_engine)
    assert is_ready is True
    assert "healthy" in message


@pytest.mark.asyncio
async def test_check_database_readiness_probe_failure() -> None:
    """Verify check_database_readiness returns (False, message) when connection fails."""
    mock_engine = MagicMock(spec=AsyncEngine)
    mock_engine.connect.side_effect = ConnectionRefusedError("Connection refused")

    is_ready, message = await check_database_readiness(engine=mock_engine)
    assert is_ready is False
    assert "failed" in message
