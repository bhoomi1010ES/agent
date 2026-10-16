"""Integration tests verifying Alembic migrations against dedicated PostgreSQL."""

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import UUID, create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

import modernization_platform.db.models  # noqa: F401
from modernization_platform.db.base import Base
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database

TEST_DB_URL = os.getenv(
    "DATABASE_TEST_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/modernization_test",
)


def _sync_database_url(database_url: str) -> str:
    """Convert the test URL to the installed synchronous psycopg driver."""
    return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def _inspect_tables(connection: Connection) -> list[str]:
    """Return table names visible to the migration connection."""
    return list(inspect(connection).get_table_names())


def _reset_test_schema(engine: Engine) -> None:
    """Clear only the dedicated test schema before exercising the full lifecycle."""
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _assert_dedicated_test_database(database_url: str) -> None:
    """Prevent lifecycle testing against a development or production database."""
    database_name = urlparse(database_url).path.lstrip("/").lower()
    if not database_name or "test" not in database_name:
        raise RuntimeError("DATABASE_TEST_URL must identify a dedicated database containing 'test'")


@pytest.fixture
def alembic_config() -> Config:
    """Construct an Alembic config targeting the dedicated test database."""
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DB_URL)
    return config


def test_migration_lifecycle(alembic_config: Config) -> None:
    """Verify clean upgrade, downgrade, and restoration of the PostgreSQL schema."""
    _assert_dedicated_test_database(TEST_DB_URL)
    if not _PORT_AVAILABLE:
        _skip_or_fail_database(
            f"PostgreSQL server is not reachable at {TEST_DB_URL}. "
            "Configure DATABASE_TEST_URL in .env to run integration tests against your local pgAdmin database."
        )
    engine = create_engine(_sync_database_url(TEST_DB_URL))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        engine.dispose()
        _skip_or_fail_database(
            f"PostgreSQL test database not accessible ({exc}). "
            "Ensure the database exists in pgAdmin and valid credentials are set in DATABASE_TEST_URL."
        )
    expected_tables = {
        "job",
        "artifact",
        "module",
        "module_attempt",
        "agent_run",
        "test_case",
        "test_result",
        "gate",
        "gate_decision",
        "audit_event",
        "auth_session",
        "job_member",
        "tenant",
        "tenant_membership",
        "user_account",
        "alembic_version",
    }

    try:
        _reset_test_schema(engine)
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            table_names = _inspect_tables(connection)
            inspector = inspect(connection)
            artifact_constraints = {
                item["name"] for item in inspector.get_check_constraints("artifact")
            }
            attempt_constraints = {
                item["name"] for item in inspector.get_check_constraints("module_attempt")
            }
            membership_constraints = {
                item["name"] for item in inspector.get_check_constraints("tenant_membership")
            }
            job_columns = {item["name"]: item["type"] for item in inspector.get_columns("job")}

        assert expected_tables.issubset(table_names)
        assert "ck_artifact_version_positive" in artifact_constraints
        assert "ck_module_attempt_number_positive" in attempt_constraints
        assert "ck_tenant_membership_role_allowed" in membership_constraints
        assert isinstance(job_columns["id"], UUID)
        assert isinstance(job_columns["tenant_id"], UUID)

        command.downgrade(alembic_config, "base")
        with engine.connect() as connection:
            table_names_after_downgrade = _inspect_tables(connection)
        assert not (expected_tables - {"alembic_version"}) & set(table_names_after_downgrade)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
