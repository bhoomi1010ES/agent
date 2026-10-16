"""Source ingestion service orchestrating Git cloning, provenance capture, and isolation."""

import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.config import get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.source_provenance import SourceProvenanceRecord
from modernization_platform.domain.jobs.errors import JobNotFoundError
from modernization_platform.integrations.git.base import GitProvider
from modernization_platform.integrations.git.models import (
    GitCredentials,
    SourceProvenance,
)
from modernization_platform.integrations.git.policy import GitSecurityPolicy
from modernization_platform.integrations.git.providers.https_provider import HttpsGitProvider
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.repositories.source_provenance import SourceProvenanceRepository
from modernization_platform.security.authorization import (
    has_tenant_admin_scope,
    require_permission,
)
from modernization_platform.security.permissions import Permission
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


class SourceIngestionService:
    """Manages secure source ingestion, isolation, provenance recording, and module branching."""

    def __init__(
        self,
        session: AsyncSession,
        git_provider: GitProvider | None = None,
        workdir_base: Path | None = None,
    ) -> None:
        self._session = session
        settings = get_settings()

        if git_provider is not None:
            self._git = git_provider
        else:
            policy = GitSecurityPolicy(
                allowed_hosts=settings.git_allowed_hosts,
                allow_private_ips_for_testing=settings.git_allow_private_ips_for_testing,
            )
            self._git = HttpsGitProvider(
                policy=policy,
                timeout_seconds=settings.git_default_timeout_seconds,
                max_repo_size_bytes=settings.git_max_repo_size_bytes,
                max_file_count=settings.git_max_file_count,
            )

        self._workdir_base = workdir_base or Path(settings.git_workdir_base)
        self._jobs = JobRepository(session)
        self._provenance_repo = SourceProvenanceRepository(session)
        self._audit = AuditEventRepository(session)

    @log_errors
    def get_job_source_dir(self, job_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> Path:
        """Resolve isolated local filesystem path for job source repository."""
        tenant_segment = str(tenant_id) if tenant_id else "global"
        return self._workdir_base / tenant_segment / str(job_id) / "source"

    @log_errors
    async def _get_scoped_job(
        self,
        job_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
    ) -> Job:
        """Fetch job strictly scoped to tenant and membership access."""
        job = await self._jobs.get_by_id_scoped(
            job_id=job_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            membership_id=principal.membership_id,
            tenant_admin=has_tenant_admin_scope(principal),
        )
        if job is None:
            raise JobNotFoundError(f"Job '{job_id}' not found or inaccessible.")
        return job

    @log_errors
    async def ingest_source(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        credentials: GitCredentials | None = None,
        ref_override: str | None = None,
        correlation_id: str | None = None,
    ) -> SourceProvenance:
        """Ingest remote repository for a job, enforce limits, persist provenance, and audit."""
        require_permission(principal, Permission.JOB_MANAGE)

        job = await self._get_scoped_job(job_id, principal)

        target_ref = ref_override or job.source_revision or "HEAD"
        target_dir = self.get_job_source_dir(job_id, principal.tenant_id)

        logger.info(
            "Starting source ingestion | job_id=%s repo=%s ref=%s target_dir=%s",
            job_id,
            job.source_ref,
            target_ref,
            target_dir,
        )

        try:
            provenance = await self._git.clone_to_working_copy(
                job_id=job_id,
                repository_url=job.source_ref,
                ref=target_ref,
                target_dir=target_dir,
                credentials=credentials,
            )

            # Update job's source_revision to the exact immutable commit SHA
            job.source_revision = provenance.resolved_commit_sha

            # Persist source provenance record
            await self._provenance_repo.save_provenance(
                provenance=provenance,
                tenant_id=principal.tenant_id,
            )

            # Append transactional audit event
            await self._audit.append_event(
                actor=str(principal.user_id),
                action="job.source_ingested",
                actor_user_id=principal.user_id,
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "repository_url": provenance.repository_url,
                    "requested_ref": provenance.requested_ref,
                    "resolved_commit_sha": provenance.resolved_commit_sha,
                    "branch": provenance.branch,
                    "tree_hash": provenance.tree_hash,
                    "file_count": provenance.repository_metadata.file_count,
                    "size_bytes": provenance.repository_metadata.size_bytes,
                    "commit_author": provenance.commit_author,
                    "commit_timestamp": (
                        provenance.commit_timestamp.isoformat()
                        if provenance.commit_timestamp
                        else None
                    ),
                    "provenance_hash": provenance.provenance_hash,
                    "ingestion_status": provenance.ingestion_status,
                },
            )

            await self._session.commit()
            logger.info(
                "Source ingestion completed successfully | job_id=%s commit_sha=%s files=%d size=%d",
                job_id,
                provenance.resolved_commit_sha,
                provenance.repository_metadata.file_count,
                provenance.repository_metadata.size_bytes,
            )
            return provenance

        except Exception as exc:
            await self._session.rollback()
            logger.exception("Source ingestion failed for job %s: %s", job_id, exc)
            raise

    @log_errors
    async def get_provenance(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
    ) -> SourceProvenanceRecord | None:
        """Retrieve verified source provenance record for a job."""
        require_permission(principal, Permission.JOB_VIEW)
        await self._get_scoped_job(job_id, principal)

        return await self._provenance_repo.get_by_job_id(job_id, tenant_id=principal.tenant_id)

    @log_errors
    async def create_module_workspace(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        module: str,
    ) -> str:
        """Create and checkout the isolated module branch: job/{job_id}/{module}."""
        require_permission(principal, Permission.JOB_MANAGE)

        job = await self._get_scoped_job(job_id, principal)

        prov = await self._provenance_repo.get_by_job_id(job_id, tenant_id=principal.tenant_id)
        base_commit = prov.resolved_commit_sha if prov else (job.source_revision or "HEAD")

        source_dir = self.get_job_source_dir(job_id, principal.tenant_id)
        if not source_dir.exists():
            raise JobNotFoundError(
                f"Source repository for job '{job_id}' has not been ingested yet."
            )

        branch_name = await self._git.create_module_branch(
            working_dir=source_dir,
            job_id=job_id,
            module=module,
            base_commit=base_commit,
        )

        logger.info(
            "Created module branch '%s' for job %s from commit %s",
            branch_name,
            job_id,
            base_commit,
        )
        return branch_name

    @log_errors
    async def cleanup_job_workspace(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
    ) -> None:
        """Remove isolated working directory for a job."""
        require_permission(principal, Permission.JOB_MANAGE)
        await self._get_scoped_job(job_id, principal)

        source_dir = self.get_job_source_dir(job_id, principal.tenant_id)
        await self._git.cleanup_working_copy(source_dir)


__all__ = ["SourceIngestionService"]
