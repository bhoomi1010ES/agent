"""Custom SQLAlchemy types ensuring cross-database type safety and timezone normalization."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, String, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

logger = logging.getLogger(__name__)


class UTCDateTime(TypeDecorator[datetime]):
    """Ensure DateTime columns always store and return timezone-aware UTC datetime objects."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Normalize outgoing datetime to UTC."""
        try:
            if value is not None:
                value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            return value
        except Exception as exc:
            logger.exception(
                "Failed to process bind param for UTCDateTime | %s: %s", type(exc).__name__, exc
            )
            raise

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Ensure incoming datetime from database carries UTC tzinfo."""
        try:
            if value is not None:
                value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            return value
        except Exception as exc:
            logger.exception(
                "Failed to process result value for UTCDateTime | %s: %s", type(exc).__name__, exc
            )
            raise


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent GUID/UUID type.

    Uses PostgreSQL native UUID type when available, otherwise falls back to String(36).
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        try:
            if dialect.name == "postgresql":
                return dialect.type_descriptor(PG_UUID(as_uuid=True))
            return dialect.type_descriptor(String(36))
        except Exception as exc:
            logger.exception("Failed in GUID.load_dialect_impl | %s: %s", type(exc).__name__, exc)
            raise

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        try:
            if value is None:
                return None
            if dialect.name == "postgresql":
                if isinstance(value, uuid.UUID):
                    return value
                return uuid.UUID(str(value))
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(str(value)))
        except Exception as exc:
            logger.exception("Failed in GUID.process_bind_param | %s: %s", type(exc).__name__, exc)
            raise

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        try:
            if value is None:
                return None
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(str(value))
        except Exception as exc:
            logger.exception(
                "Failed in GUID.process_result_value | %s: %s", type(exc).__name__, exc
            )
            raise
