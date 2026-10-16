"""Service-layer authorization for human and background resource operations."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.exceptions import ConflictException, NotFoundException
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.audit_event import AuditEvent
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.identity import JobMember
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.gates import GateRepository
from modernization_platform.repositories.identities import IdentityRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.security.authorization import (
    has_tenant_admin_scope,
    require_permission,
)
from modernization_platform.security.permissions import Permission, Role, permissions_for_roles
from modernization_platform.security.principals import (
    AuthenticatedPrincipal,
    WorkerAuthorizationContext,
)

logger = logging.getLogger(__name__)


class AuthorizationService:
    """Enforce permission and resource scope before persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._jobs = JobRepository(session)
        self._artifacts = ArtifactRepository(session)
        self._gates = GateRepository(session)
        self._audit = AuditEventRepository(session)
        self._identities = IdentityRepository(session)

    async def get_job(
        self,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
    ) -> Job:
        """Return a job only after permission and scoped repository checks."""
        try:
            require_permission(principal, Permission.JOB_VIEW)
            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if job is None:
                raise NotFoundException()
            return job
        except NotFoundException:
            raise
        except Exception:
            raise

    async def get_artifact(
        self,
        principal: AuthenticatedPrincipal,
        artifact_id: uuid.UUID,
    ) -> Artifact:
        """Return an artifact only through its authorized parent job."""
        try:
            require_permission(principal, Permission.ARTIFACT_VIEW)
            artifact = await self._artifacts.get_by_id_scoped(
                artifact_id=artifact_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if artifact is None:
                raise NotFoundException()
            return artifact
        except NotFoundException:
            raise
        except Exception:
            raise

    async def decide_gate(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        gate_id: uuid.UUID,
        decision: str,
        feedback: str | None,
        waivers: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> GateDecision:
        """Record an authorized gate decision and audit identity from the principal."""
        try:
            require_permission(principal, Permission.GATE_DECIDE)
            gate = await self._gates.get_by_id_scoped(
                gate_id=gate_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                for_update=True,
            )
            if gate is None or gate.job_id != job_id:
                raise NotFoundException()
            if gate.state != "pending":
                raise ConflictException("Gate is not pending")

            gate_decision = await self._gates.record_authorized_decision(
                gate=gate,
                actor_user_id=principal.user_id,
                decision=decision,
                feedback=feedback,
                waivers={"items": waivers} if waivers else None,
            )
            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="GATE_DECIDED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "gate_id": str(gate_id),
                    "decision_id": str(gate_decision.id),
                    "decision": decision,
                },
            )
            return gate_decision
        except (ConflictException, NotFoundException):
            raise
        except Exception:
            raise

    async def list_job_gates(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        state: str | None = None,
    ) -> list[Gate]:
        """List gates for an authorized job."""
        try:
            require_permission(principal, Permission.GATE_VIEW)
            await self.get_job(principal, job_id)
            return await self._gates.list_gates_by_job_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                state=state,
            )
        except Exception:
            raise

    async def get_job_gate(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        gate_id: uuid.UUID,
    ) -> Gate:
        """Retrieve a specific gate verifying job and tenant authorization."""
        try:
            require_permission(principal, Permission.GATE_VIEW)
            gate = await self._gates.get_by_id_scoped(
                gate_id=gate_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if gate is None or gate.job_id != job_id:
                raise NotFoundException()
            return gate
        except NotFoundException:
            raise
        except Exception:
            raise

    async def create_job(
        self,
        *,
        principal: AuthenticatedPrincipal,
        source_repository: str,
        source_revision: str,
        target_stack_spec: dict[str, Any],
        budget: dict[str, Any],
        correlation_id: str | None = None,
    ) -> Job:
        """Create a modernization job, add membership, and log an audit event."""
        try:
            require_permission(principal, Permission.JOB_CREATE)
            source_ref = f"{source_repository}@{source_revision}"
            job = await self._jobs.create_job(
                owner=str(principal.user_id),
                source_ref=source_ref,
                target_stack_spec=target_stack_spec,
                budget=budget,
                tenant_id=principal.tenant_id,
                owner_user_id=principal.user_id,
            )
            job_member = JobMember(job_id=job.id, membership_id=principal.membership_id)
            self._jobs.session.add(job_member)
            await self._jobs.session.flush()

            await self._audit.append_event(
                actor=str(principal.user_id),
                actor_user_id=principal.user_id,
                action="JOB_CREATED",
                job_id=job.id,
                correlation_id=correlation_id,
                payload={
                    "source_repository": source_repository,
                    "source_revision": source_revision,
                    "target_stack": target_stack_spec,
                    "budget": budget,
                },
            )
            return job
        except Exception:
            raise

    async def list_jobs(
        self,
        *,
        principal: AuthenticatedPrincipal,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Job], int]:
        """List jobs visible to the principal within their authorized tenant scope."""
        try:
            require_permission(principal, Permission.JOB_VIEW)
            jobs = await self._jobs.list_jobs_scoped(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                limit=limit,
                offset=offset,
                status=status,
            )
            total = await self._jobs.count_jobs_scoped(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                status=status,
            )
            return jobs, total
        except Exception:
            raise

    async def list_job_artifacts(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        artifact_type: str | None = None,
    ) -> list[Artifact]:
        """List artifacts belonging to an authorized job."""
        try:
            require_permission(principal, Permission.ARTIFACT_VIEW)
            await self.get_job(principal, job_id)
            artifacts = await self._artifacts.list_artifacts_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                artifact_type=artifact_type,
            )
            return artifacts
        except Exception:
            raise

    async def get_job_artifact_by_type(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        artifact_type: str,
        version: int | None = None,
    ) -> Artifact:
        """Retrieve an artifact by job, schema type, and optional version."""
        try:
            require_permission(principal, Permission.ARTIFACT_VIEW)
            await self.get_job(principal, job_id)
            artifact = await self._artifacts.get_by_job_and_type_scoped(
                job_id=job_id,
                artifact_type=artifact_type,
                version=version,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if artifact is None:
                raise NotFoundException()
            return artifact
        except NotFoundException:
            raise
        except Exception:
            raise

    async def get_job_artifact_content(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        artifact_type: str,
        version: int | None = None,
        storage_service: Any = None,
    ) -> Any:
        """Retrieve verified artifact content bytes after verifying job authorization."""
        from modernization_platform.storage.service import ArtifactStorageService

        try:
            artifact = await self.get_job_artifact_by_type(
                principal=principal,
                job_id=job_id,
                artifact_type=artifact_type,
                version=version,
            )
            storage = storage_service or ArtifactStorageService()
            return await storage.retrieve_artifact(
                storage_ref=artifact.storage_ref,
                expected_hash=artifact.content_hash,
            )
        except Exception:
            raise

    async def list_job_audit_events(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[AuditEvent], int]:
        """List audit events belonging to an authorized job."""
        try:
            require_permission(principal, Permission.AUDIT_VIEW)
            await self.get_job(principal, job_id)
            events = await self._audit.list_events_by_job_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                limit=limit,
                offset=offset,
            )
            total = await self._audit.count_events_by_job_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            return events, total
        except Exception:
            raise

    async def create_worker_context(
        self,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
    ) -> WorkerAuthorizationContext:
        """Create a non-secret context only after current job authorization."""
        try:
            await self.get_job(principal, job_id)
            return WorkerAuthorizationContext(
                initiator_user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                membership_id=principal.membership_id,
                job_id=job_id,
                initiated_at=datetime.now(UTC),
            )
        except Exception:
            raise

    async def authorize_worker(
        self,
        context: WorkerAuthorizationContext,
        permission: Permission,
    ) -> Job:
        """Revalidate identity, current role, tenant, and job scope outside HTTP."""
        try:
            identity = await self._identities.resolve_active_membership(
                user_id=context.initiator_user_id,
                tenant_id=context.tenant_id,
                membership_id=context.membership_id,
            )
            if identity is None:
                raise NotFoundException()
            _user, membership = identity
            try:
                role = Role(membership.role)
            except ValueError as exc:
                raise NotFoundException() from exc
            if permission not in permissions_for_roles(frozenset({role})):
                raise NotFoundException()
            job = await self._jobs.get_by_id_scoped(
                job_id=context.job_id,
                tenant_id=context.tenant_id,
                user_id=context.initiator_user_id,
                membership_id=context.membership_id,
                tenant_admin=role is Role.ADMIN,
            )
            if job is None:
                raise NotFoundException()
            return job
        except NotFoundException:
            raise
        except Exception:
            raise


__all__ = ["AuthorizationService"]
