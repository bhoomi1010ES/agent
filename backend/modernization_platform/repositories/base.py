"""Base repository providing standardized async session binding and Rule 1 error handling."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.exceptions import PersistenceError
from modernization_platform.db.base import Base

logger = logging.getLogger(__name__)


class BaseRepository[ModelT: Base]:
    """Abstract generic repository implementing Rule 1 error handling and session encapsulation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _translate_error(self, operation: str, exc: Exception) -> PersistenceError:
        """Log diagnostic details and translate database exceptions into safe domain PersistenceErrors."""
        try:
            logger.exception(
                "Database repository failure during '%s' on %s | %s: %s",
                operation,
                self.__class__.__name__,
                type(exc).__name__,
                exc,
            )
            return PersistenceError(f"Database operation '{operation}' failed: {exc}")
        except Exception as handling_err:
            return PersistenceError(f"Database error translation failed: {handling_err}")
