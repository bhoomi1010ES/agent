"""Module repository for managing DAG nodes of conversion units."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.module import Module
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ModuleRepository(BaseRepository[Module]):
    """Repository operations for Module entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_module(
        self,
        job_id: uuid.UUID,
        name: str,
        legacy_paths: list[str],
        depends_on: list[str] | None = None,
        risk_score: float = 0.0,
        module_id: uuid.UUID | None = None,
    ) -> Module:
        """Create a new module in the conversion DAG."""
        try:
            module = Module(
                id=module_id or uuid.uuid4(),
                job_id=job_id,
                name=name,
                legacy_paths=legacy_paths,
                depends_on=depends_on or [],
                risk_score=risk_score,
                status="pending",
            )
            self.session.add(module)
            await self.session.flush()
            return module
        except Exception as exc:
            raise self._translate_error("create_module", exc) from exc

    async def get_by_id(self, module_id: uuid.UUID) -> Module | None:
        """Retrieve a module by its identifier."""
        try:
            stmt = select(Module).where(Module.id == module_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def get_by_name(self, job_id: uuid.UUID, name: str) -> Module | None:
        """Retrieve a module by job and module name."""
        try:
            stmt = select(Module).where(Module.job_id == job_id, Module.name == name)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_name", exc) from exc

    async def list_by_job(self, job_id: uuid.UUID) -> list[Module]:
        """List all modules for a job ordered by name."""
        try:
            stmt = select(Module).where(Module.job_id == job_id).order_by(Module.name.asc())
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_by_job", exc) from exc

    async def update_status(self, module_id: uuid.UUID, status: str) -> Module | None:
        """Update module conversion status."""
        try:
            module = await self.get_by_id(module_id)
            if module is None:
                return None
            module.status = status
            await self.session.flush()
            return module
        except Exception as exc:
            raise self._translate_error("update_status", exc) from exc
