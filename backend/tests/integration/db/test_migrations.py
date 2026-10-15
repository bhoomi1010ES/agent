"""Integration tests verifying Alembic schema migrations against a live PostgreSQL database."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

TEST_DB_URL = os.getenv(
    "DATABASE_TEST_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/modernization_test",
)


@pytest.fixture
def alembic_config() -> Config:
    """Construct an Alembic Config pointing to the project's alembic.ini and test database."""
    ini_path = Path(__file__).resolve().parents[3] / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[3] / "migrations")
    )
    config.set_section_option("alembic", "db_url", TEST_DB_URL)
    return config


@pytest.mark.asyncio
async def test_migration_lifecycle(db_engine: AsyncEngine, alembic_config: Config) -> None:
    """Verify that migrations upgrade to head, verify all 10 tables, and downgrade cleanly."""
    # 1. Downgrade to base first
    command.downgrade(alembic_config, "base")

    # 2. Upgrade to head
    command.upgrade(alembic_config, "head")

    # 3. Inspect PostgreSQL tables
    def _inspect_tables(connection) -> list[str]:
        inspector = inspect(connection)
        return inspector.get_table_names()

    async with db_engine.connect() as conn:
        table_names = await conn.run_sync(_inspect_tables)

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
        "alembic_version",
    }
    for expected in expected_tables:
        assert expected in table_names, f"Table '{expected}' missing from PostgreSQL schema"

    # 4. Verify downgrading to base removes all application tables
    command.downgrade(alembic_config, "base")

    async with db_engine.connect() as conn:
        table_names_after_downgrade = await conn.run_sync(_inspect_tables)

    for app_table in expected_tables - {"alembic_version"}:
        assert app_table not in table_names_after_downgrade, f"Table '{app_table}' not dropped"

    # 5. Restore schema to head for subsequent tests
    command.upgrade(alembic_config, "head")
