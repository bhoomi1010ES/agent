"""Unit tests for custom SQLAlchemy types (UTCDateTime, GUID)."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect

from modernization_platform.db.types import GUID, UTCDateTime


def _postgresql_dialect() -> Dialect:
    """Return SQLAlchemy's PostgreSQL dialect through its typed interface."""
    factory = cast(Callable[[], Dialect], postgresql.dialect)
    return factory()


def _sqlite_dialect() -> Dialect:
    """Return SQLAlchemy's SQLite dialect through its typed interface."""
    factory = cast(Callable[[], Dialect], sqlite.dialect)
    return factory()


def test_utc_datetime_process_bind_param() -> None:
    """Verify UTCDateTime binds datetimes as timezone-aware UTC."""
    decorator = UTCDateTime()
    dialect = _postgresql_dialect()

    # None passthrough
    assert decorator.process_bind_param(None, dialect) is None

    # Naive datetime gets assigned UTC
    naive_dt = datetime(2026, 10, 15, 12, 0, 0)
    bound_naive = decorator.process_bind_param(naive_dt, dialect)
    assert bound_naive is not None
    assert bound_naive.tzinfo == UTC
    assert bound_naive.year == 2026

    # Aware non-UTC datetime gets converted to UTC
    tz_offset = UTC
    aware_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=tz_offset)
    bound_aware = decorator.process_bind_param(aware_dt, dialect)
    assert bound_aware is not None
    assert bound_aware.tzinfo == UTC


def test_utc_datetime_process_result_value() -> None:
    """Verify UTCDateTime returns datetimes with UTC timezone attached."""
    decorator = UTCDateTime()
    dialect = _postgresql_dialect()

    assert decorator.process_result_value(None, dialect) is None

    naive_dt = datetime(2026, 10, 15, 12, 0, 0)
    res_naive = decorator.process_result_value(naive_dt, dialect)
    assert res_naive is not None
    assert res_naive.tzinfo == UTC

    aware_dt = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
    res_aware = decorator.process_result_value(aware_dt, dialect)
    assert res_aware is not None
    assert res_aware.tzinfo == UTC


def test_guid_load_dialect_impl() -> None:
    """Verify GUID adapts type descriptor based on dialect (PostgreSQL vs SQLite)."""
    guid = GUID()

    pg_dialect = _postgresql_dialect()
    pg_impl = guid.load_dialect_impl(pg_dialect)
    assert isinstance(pg_impl, postgresql.UUID)

    sqlite_dialect = _sqlite_dialect()
    sqlite_impl = guid.load_dialect_impl(sqlite_dialect)
    assert sqlite_impl.length == 36


def test_guid_process_bind_param() -> None:
    """Verify GUID binds UUID objects and UUID strings correctly."""
    guid = GUID()
    sample_uuid = uuid.uuid4()
    uuid_str = str(sample_uuid)

    pg_dialect = _postgresql_dialect()
    assert guid.process_bind_param(None, pg_dialect) is None
    assert guid.process_bind_param(sample_uuid, pg_dialect) == sample_uuid
    assert guid.process_bind_param(uuid_str, pg_dialect) == sample_uuid

    sqlite_dialect = _sqlite_dialect()
    assert guid.process_bind_param(None, sqlite_dialect) is None
    assert guid.process_bind_param(sample_uuid, sqlite_dialect) == uuid_str
    assert guid.process_bind_param(uuid_str, sqlite_dialect) == uuid_str


def test_guid_process_result_value() -> None:
    """Verify GUID converts database values to python uuid.UUID instances."""
    guid = GUID()
    sample_uuid = uuid.uuid4()
    uuid_str = str(sample_uuid)
    dialect = _postgresql_dialect()

    assert guid.process_result_value(None, dialect) is None
    assert guid.process_result_value(sample_uuid, dialect) == sample_uuid
    assert guid.process_result_value(uuid_str, dialect) == sample_uuid
