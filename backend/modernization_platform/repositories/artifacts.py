"""Artifact repository for appending and querying content-addressed artifacts."""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ArtifactRepository(BaseRepository[Artifact]):
    """Repository operations for Artifact entity (append-only)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def append_artifact(
        self,
        job_id: uuid.UUID,
        artifact_type: str,
        content_hash: str,
        storage_ref: str,
        derived_from: list[str] | None = None,
        artifact_metadata: dict[str, Any] | None = None,
        produced_by_run_id: uuid.UUID | None = None,
        version: int | None = None,
        artifact_id: uuid.UUID | None = None,
    ) -> Artifact:
        """Append a new versioned, immutable artifact record."""
        try:
            target_version = version
            if target_version is None:
                # Auto-calculate next monotonic version for this (job_id, type)
                stmt = select(func.coalesce(func.max(Artifact.version), 0)).where(
                    Artifact.job_id == job_id,
                    Artifact.type == artifact_type,
                )
                res = await self.session.execute(stmt)
                current_max = res.scalar() or 0
                target_version = current_max + 1

            artifact = Artifact(
                id=artifact_id or uuid.uuid4(),
                job_id=job_id,
                type=artifact_type,
                version=target_version,
                content_hash=content_hash,
                storage_ref=storage_ref,
                produced_by_run_id=produced_by_run_id,
                derived_from=derived_from or [],
                artifact_metadata=artifact_metadata or {},
            )
            self.session.add(artifact)
            await self.session.flush()
            return artifact
        except Exception as exc:
            raise self._translate_error("append_artifact", exc) from exc

    async def get_by_id(self, artifact_id: uuid.UUID) -> Artifact | None:
        """Retrieve an artifact by its primary key ID."""
        try:
            stmt = select(Artifact).where(Artifact.id == artifact_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id", exc) from exc

    async def get_by_job_and_type_version(
        self,
        job_id: uuid.UUID,
        artifact_type: str,
        version: int,
    ) -> Artifact | None:
        """Retrieve a specific artifact version by job and schema type."""
        try:
            stmt = select(Artifact).where(
                Artifact.job_id == job_id,
                Artifact.type == artifact_type,
                Artifact.version == version,
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_job_and_type_version", exc) from exc

    async def list_artifacts_by_job(
        self,
        job_id: uuid.UUID,
        artifact_type: str | None = None,
    ) -> list[Artifact]:
        """List all artifacts for a given job ordered by version."""
        try:
            stmt = (
                select(Artifact)
                .where(Artifact.job_id == job_id)
                .order_by(Artifact.type, Artifact.version.asc())
            )
            if artifact_type:
                stmt = stmt.where(Artifact.type == artifact_type)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_artifacts_by_job", exc) from exc
