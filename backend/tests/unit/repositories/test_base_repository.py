"""Unit tests for BaseRepository error translation and session attachment."""

from unittest.mock import AsyncMock

from modernization_platform.core.exceptions import PersistenceError
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.base import BaseRepository


def test_base_repository_error_translation() -> None:
    """Verify _translate_error creates safe PersistenceError without swallowing."""
    mock_session = AsyncMock()
    repo = BaseRepository[Job](session=mock_session)

    original_exc = RuntimeError("Database deadlock detected")
    pers_error = repo._translate_error("update_job_status", original_exc)

    assert isinstance(pers_error, PersistenceError)
    assert "Database operation 'update_job_status' failed" in str(pers_error)
    assert "Database deadlock detected" in str(pers_error)
