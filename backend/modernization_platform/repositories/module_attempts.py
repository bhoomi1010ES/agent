"""ModuleAttempt repository for managing CodeWriter execution rounds."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.module_attempt import ModuleAttempt
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ModuleAttemptRepository(BaseRepository[ModuleAttempt]):
    """Repository operations for ModuleAttempt entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_attempt(
        self,
        module_id: uuid.UUID,
        attempt_number: int,
        branch: str,
        commit_hash: str | None = None,
        tactic: str | None = None,
        attempt_id: uuid.UUID | None = None,
    ) -> ModuleAttempt:
        """Create a new module conversion attempt record."""
        try:
            attempt = ModuleAttempt(
                id=attempt_id or uuid.uuid4(),
                module_id=module_id,
                attempt_number=attempt_number,
                branch=branch,
                commit_hash=commit_hash,
                tactic=tactic,
                outcome="in_progress",
            )
            self.session.add(attempt)
            await self.session.flush()
            return attempt
        except Exception as exc:
            raise self._translate_error("create_attempt", exc) from exc

    async def get_by_id(self, attempt_id: uuid.UUID) -> ModuleAttempt | None:
        """Retrieve an attempt by its unique identifier."""
        try:
            stmt = select(ModuleAttempt).where(ModuleAttempt.id == attempt_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def list_by_module(self, module_id: uuid.UUID) -> list[ModuleAttempt]:
        """List all attempts for a given module ordered by attempt number."""
        try:
            stmt = (
                select(ModuleAttempt)
                .where(ModuleAttempt.module_id == module_id)
                .order_by(ModuleAttempt.attempt_number.asc())
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_by_module", exc) from exc

    async def record_outcome(
        self,
        attempt_id: uuid.UUID,
        outcome: str,
        failure_summary: str | None = None,
        commit_hash: str | None = None,
    ) -> ModuleAttempt | None:
        """Record the final outcome of an attempt."""
        try:
            attempt = await self.get_by_id(attempt_id)
            if attempt is None:
                return None
            attempt.outcome = outcome
            attempt.failure_summary = failure_summary
            if commit_hash:
                attempt.commit_hash = commit_hash
            attempt.finished_at = datetime.now(UTC)
            await self.session.flush()
            return attempt
        except Exception as exc:
            raise self._translate_error("record_outcome", exc) from exc
