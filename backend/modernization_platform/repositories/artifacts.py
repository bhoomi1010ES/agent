"""Artifact repository for appending and querying content-addressed artifacts."""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ArtifactRepository(BaseRepository[Artifact]):
    """Repository operations for Artifact entity (append-only)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _append_artifact_after_authorization(
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
        status: str = "available",
        size_bytes: int | None = None,
        content_type: str | None = "application/json",
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
                status=status,
                size_bytes=size_bytes,
                content_type=content_type,
            )
            self.session.add(artifact)
            await self.session.flush()
            return artifact
        except Exception as exc:
            raise self._translate_error("_append_artifact_after_authorization", exc) from exc

    async def update_status(self, artifact_id: uuid.UUID, status: str) -> Artifact | None:
        """Update lifecycle status of an artifact."""
        try:
            artifact = await self._get_by_id_unscoped(artifact_id)
            if artifact is not None:
                artifact.status = status
                await self.session.flush()
            return artifact
        except Exception as exc:
            raise self._translate_error("update_status", exc) from exc

    async def find_dependents_unscoped(self, artifact_id: uuid.UUID) -> list[Artifact]:
        """Find any artifacts whose derived_from references the given artifact_id."""
        try:
            str_id = str(artifact_id)
            try:
                stmt = select(Artifact).where(Artifact.derived_from.contains([str_id]))
                res = await self.session.execute(stmt)
                return list(res.scalars().all())
            except Exception:
                stmt = select(Artifact)
                res = await self.session.execute(stmt)
                all_arts = res.scalars().all()
                return [a for a in all_arts if str_id in (a.derived_from or [])]
        except Exception as exc:
            raise self._translate_error("find_dependents_unscoped", exc) from exc

    async def delete_artifact(self, artifact_id: uuid.UUID, hard_delete: bool = False) -> bool:
        """Delete an artifact record (soft delete to 'deleted' status or hard delete)."""
        try:
            artifact = await self._get_by_id_unscoped(artifact_id)
            if artifact is None:
                return False
            if hard_delete:
                await self.session.delete(artifact)
            else:
                artifact.status = "deleted"
            await self.session.flush()
            return True
        except Exception as exc:
            raise self._translate_error("delete_artifact", exc) from exc

    async def _get_by_id_unscoped(self, artifact_id: uuid.UUID) -> Artifact | None:
        """Internal lookup for persistence workflows after authorization."""
        try:
            stmt = select(Artifact).where(Artifact.id == artifact_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("_get_by_id_unscoped", exc) from exc

    async def get_by_id_scoped(
        self,
        *,
        artifact_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
    ) -> Artifact | None:
        """Retrieve an artifact only through its authorized parent job scope."""
        try:
            statement = (
                select(Artifact)
                .join(Job, Job.id == Artifact.job_id)
                .where(Artifact.id == artifact_id, Job.tenant_id == tenant_id)
            )
            if not tenant_admin:
                member_access = (
                    select(JobMember.id)
                    .where(
                        JobMember.job_id == Job.id,
                        JobMember.membership_id == membership_id,
                    )
                    .exists()
                )
                statement = statement.where((Job.owner_user_id == user_id) | member_access)
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_id_scoped", exc) from exc

    async def list_artifacts_scoped(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
        artifact_type: str | None = None,
    ) -> list[Artifact]:
        """List artifacts for a job within authorized tenant and membership scope."""
        try:
            statement = (
                select(Artifact)
                .join(Job, Job.id == Artifact.job_id)
                .where(Artifact.job_id == job_id, Job.tenant_id == tenant_id)
            )
            if not tenant_admin:
                member_access = (
                    select(JobMember.id)
                    .where(
                        JobMember.job_id == Job.id,
                        JobMember.membership_id == membership_id,
                    )
                    .exists()
                )
                statement = statement.where((Job.owner_user_id == user_id) | member_access)
            if artifact_type is not None:
                statement = statement.where(Artifact.type == artifact_type)
            statement = statement.order_by(Artifact.type, Artifact.version.asc(), Artifact.id.asc())
            result = await self.session.execute(statement)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("list_artifacts_scoped", exc) from exc

    async def get_by_job_and_type_scoped(
        self,
        *,
        job_id: uuid.UUID,
        artifact_type: str,
        version: int | None = None,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        tenant_admin: bool = False,
    ) -> Artifact | None:
        """Retrieve an artifact by job and type (and optional version) within authorized scope."""
        try:
            statement = (
                select(Artifact)
                .join(Job, Job.id == Artifact.job_id)
                .where(
                    Artifact.job_id == job_id,
                    Artifact.type == artifact_type,
                    Job.tenant_id == tenant_id,
                )
            )
            if not tenant_admin:
                member_access = (
                    select(JobMember.id)
                    .where(
                        JobMember.job_id == Job.id,
                        JobMember.membership_id == membership_id,
                    )
                    .exists()
                )
                statement = statement.where((Job.owner_user_id == user_id) | member_access)
            if version is not None:
                statement = statement.where(Artifact.version == version)
            else:
                statement = statement.order_by(Artifact.version.desc())
            statement = statement.limit(1)
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_by_job_and_type_scoped", exc) from exc

    async def _get_by_ids_unscoped(self, artifact_ids: list[uuid.UUID]) -> list[Artifact]:
        """Retrieve artifact rows used to validate lineage ownership."""
        try:
            if not artifact_ids:
                return []
            stmt = select(Artifact).where(Artifact.id.in_(artifact_ids))
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            raise self._translate_error("get_by_ids", exc) from exc

    async def _get_by_job_and_type_version_unscoped(
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

    async def _list_artifacts_by_job_unscoped(
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
