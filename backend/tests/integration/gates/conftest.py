"""Fixtures and helper factories for human approval gate integration testing with PostgreSQL."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.identity import (
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


@log_errors
async def create_gate_test_principal(
    session: AsyncSession,
    role: Role = Role.APPROVER,
    tenant: Tenant | None = None,
) -> AuthenticatedPrincipal:
    """Create a persistent tenant, user, and membership bound to a test principal."""
    try:
        t = tenant
        if t is None:
            t = Tenant(
                id=uuid.uuid4(),
                slug=f"tenant-{uuid.uuid4().hex[:8]}",
                display_name="Gate Test Tenant",
                active=True,
            )
            session.add(t)
            await session.flush()

        user = UserAccount(
            issuer="https://auth.modernization.internal",
            subject=f"user-{uuid.uuid4().hex[:8]}",
            display_name="Approver User",
            active=True,
        )
        session.add(user)
        await session.flush()

        membership = TenantMembership(
            tenant_id=t.id,
            user_id=user.id,
            role=role.value,
            active=True,
        )
        session.add(membership)
        await session.flush()

        return AuthenticatedPrincipal(
            user_id=user.id,
            tenant_id=t.id,
            membership_id=membership.id,
            session_id=uuid.uuid4(),
            subject=user.subject,
            issuer=user.issuer,
            roles=frozenset({role}),
            expires_at=datetime.now(UTC) + timedelta(hours=2),
            authentication_method="oidc_jwt",
        )
    except Exception as exc:
        logger.exception("create_gate_test_principal failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
async def create_gate_test_job(
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    status: str = JobLifecycleState.AWAITING_APPROVAL.value,
) -> Job:
    """Create a persistent job owned by the test principal."""
    try:
        job = Job(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            owner_user_id=principal.user_id,
            owner=principal.subject,
            source_ref="git@github.com:legacy/cobol-core.git",
            source_revision="main",
            status=status,
            target_stack_spec={"framework": "FastAPI", "language": "Python"},
            budget={"max_cost_cents": 50000},
        )
        session.add(job)
        await session.flush()

        member = JobMember(
            job_id=job.id,
            membership_id=principal.membership_id,
        )
        session.add(member)
        await session.flush()
        return job
    except Exception as exc:
        logger.exception("create_gate_test_job failed | %s: %s", type(exc).__name__, exc)
        raise


@log_errors
async def create_gate_test_artifact(
    session: AsyncSession,
    job_id: uuid.UUID,
    artifact_type: str = "SPECIFICATION",
    version: int = 1,
) -> Artifact:
    """Create a persistent artifact record."""
    try:
        art = Artifact(
            id=uuid.uuid4(),
            job_id=job_id,
            type=artifact_type,
            version=version,
            content_hash=f"hash-{uuid.uuid4().hex[:16]}",
            storage_ref=f"s3://artifacts/{job_id}/{artifact_type}_{version}.json",
            status="available",
        )
        session.add(art)
        await session.flush()
        return art
    except Exception as exc:
        logger.exception("create_gate_test_artifact failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "create_gate_test_artifact",
    "create_gate_test_job",
    "create_gate_test_principal",
]
