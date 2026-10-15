"""Service-layer authorization for human and background resource operations."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.exceptions import ConflictException, NotFoundException
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.gate_decision import GateDecision
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
