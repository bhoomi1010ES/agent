"""Pytest configuration and database fixtures for PostgreSQL integration tests."""

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Ensure all models are loaded
import modernization_platform.db.models  # noqa: F401
from modernization_platform.db.base import Base

TEST_DB_URL = os.getenv(
    "DATABASE_TEST_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/modernization_test",
)


def _is_port_listening(db_url: str) -> bool:
    """Quickly check if the target database host and port are accepting connections."""
    try:
        clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )
        parsed = urlparse(clean_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (TimeoutError, OSError):
        return False


_PORT_AVAILABLE = _is_port_listening(TEST_DB_URL)


def _skip_or_fail_database(message: str) -> None:
    """Fail in CI, while keeping unavailable local PostgreSQL an explicit skip."""
    if os.getenv("CI"):
        pytest.fail(message)
    pytest.skip(message)


def _is_dedicated_test_database(database_url: str) -> bool:
    """Reject destructive fixture cleanup against a non-test database name."""
    database_name = urlparse(database_url).path.lstrip("/").lower()
    return bool(database_name) and "test" in database_name


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Provide an AsyncEngine bound to the PostgreSQL test database, or skip gracefully."""
    if not _is_dedicated_test_database(TEST_DB_URL):
        pytest.fail("DATABASE_TEST_URL must identify a dedicated database containing 'test'")
    if not _PORT_AVAILABLE:
        _skip_or_fail_database(
            f"PostgreSQL server is not reachable at {TEST_DB_URL}. "
            "Configure DATABASE_TEST_URL in .env to run integration tests against your local pgAdmin database."
        )

    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={"timeout": 2.0},
    )

    # Verify credentials and database existence
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        _skip_or_fail_database(
            f"PostgreSQL test database not accessible ({exc}). "
            "Ensure the database exists in pgAdmin and valid credentials are set in DATABASE_TEST_URL."
        )

    # Ensure tables are created
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Provide an isolated database session with automatic data cleanup after each test."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    # Truncate all tables after each test to ensure test isolation.
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                """
                TRUNCATE TABLE
                    idempotency_record,
                    audit_event,
                    auth_session,
                    gate_decision,
                    gate,
                    test_result,
                    test_case,
                    agent_run,
                    model_execution,
                    budget_reservation,
                    budget_account,
                    task,
                    module_attempt,
                    module,
                    job_member,
                    artifact,
                    job,
                    tenant_membership,
                    user_account,
                    tenant
                CASCADE;
                """
            )
        )
