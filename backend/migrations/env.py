"""Alembic async environment runner integrated with platform Settings and SQLAlchemy metadata."""

import asyncio
import logging
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure application src directory is in sys.path
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Import all models to ensure metadata registration
import modernization_platform.db.models  # noqa: E402, F401
from modernization_platform.config.settings import get_settings  # noqa: E402
from modernization_platform.db.base import Base  # noqa: E402

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# Model metadata
target_metadata = Base.metadata


def get_url() -> str:
    """Retrieve database URL dynamically from CLI argument or platform Settings."""
    try:
        x_args = context.get_x_argument(as_dictionary=True)
        if x_args.get("db_url"):
            return str(x_args["db_url"])

        ini_url = config.get_main_option("sqlalchemy.url")
        if ini_url and not ini_url.startswith("postgresql://user:password"):
            return ini_url

        settings = get_settings()
        return settings.database_url
    except Exception as exc:
        logger.exception(
            "Failed to retrieve database URL for Alembic | %s: %s", type(exc).__name__, exc
        )
        raise


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates raw SQL statements without requiring a live database connection.
    """
    try:
        url = get_url()
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()
    except Exception as exc:
        logger.exception("run_migrations_offline failed | %s: %s", type(exc).__name__, exc)
        raise


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations within an active database connection."""
    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()
    except Exception as exc:
        logger.exception("do_run_migrations failed | %s: %s", type(exc).__name__, exc)
        raise


async def run_async_migrations() -> None:
    """Execute migrations in 'online' mode using an async database connection."""
    try:
        configuration = config.get_section(config.config_ini_section) or {}
        configuration["sqlalchemy.url"] = get_url()

        connectable = async_engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)

        await connectable.dispose()
    except Exception as exc:
        logger.exception("run_async_migrations failed | %s: %s", type(exc).__name__, exc)
        raise


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using async event loop."""
    try:
        asyncio.run(run_async_migrations())
    except Exception as exc:
        logger.exception("run_migrations_online failed | %s: %s", type(exc).__name__, exc)
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
