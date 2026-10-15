"""PostgreSQL integration tests for validation-before-persistence behavior."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.exceptions import ForbiddenException
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.identity import Tenant, TenantMembership, UserAccount
from modernization_platform.db.models.job import Job
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.metadata import ProducerIdentity, ProducerKind
from modernization_platform.schemas.validation import parse_artifact
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.artifacts import ArtifactPersistenceService
from tests.contract.factories import repo_inventory_payload, target_blueprint_payload


async def _create_owner_job(
    db_session: AsyncSession,
    *,
    slug: str,
) -> tuple[Job, AuthenticatedPrincipal]:
    tenant = Tenant(slug=slug, display_name=slug)
    user = UserAccount(issuer="https://identity.test", subject=f"{slug}-owner")
    db_session.add_all([tenant, user])
    await db_session.flush()
    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role=Role.OWNER.value,
    )
    db_session.add(membership)
    await db_session.flush()
    job = await JobRepository(db_session).create_job(
        owner="contract-test-owner",
        owner_user_id=user.id,
        tenant_id=tenant.id,
        source_ref="https://example.com/legacy.git",
        target_stack_spec={"language": "python"},
    )
    principal = AuthenticatedPrincipal(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        subject=user.subject,
        issuer=user.issuer,
        roles=frozenset({Role.OWNER}),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        authentication_method="test",
    )
    await db_session.commit()
    return job, principal


@pytest.mark.asyncio
async def test_validated_artifact_persistence_and_rejection_audit(
    db_session: AsyncSession,
) -> None:
    """Only validated artifacts become rows; rejected output becomes a safe audit event."""
    job, principal = await _create_owner_job(db_session, slug="artifact-persistence")
    producer = ProducerIdentity(kind=ProducerKind.MANUAL, identifier="test-operator")
    service = ArtifactPersistenceService(db_session)
    inventory_payload = repo_inventory_payload()

    reviewer_user = UserAccount(
        issuer="https://identity.test",
        subject="artifact-reviewer",
    )
    db_session.add(reviewer_user)
    await db_session.flush()
    reviewer_membership = TenantMembership(
        tenant_id=principal.tenant_id,
        user_id=reviewer_user.id,
        role=Role.REVIEWER.value,
    )
    db_session.add(reviewer_membership)
    await db_session.flush()
    reviewer = AuthenticatedPrincipal(
        user_id=reviewer_user.id,
        tenant_id=principal.tenant_id,
        membership_id=reviewer_membership.id,
        session_id=uuid.uuid4(),
        subject=reviewer_user.subject,
        issuer=reviewer_user.issuer,
        roles=frozenset({Role.REVIEWER}),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        authentication_method="test",
    )
    with pytest.raises(ForbiddenException):
        await service.persist(
            authorization_context=reviewer,
            job_id=job.id,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
            payload=inventory_payload,
            storage_ref=f"s3://artifacts/{job.id}/unauthorized.json",
            producer=producer,
        )

    first = await service.persist(
        authorization_context=principal,
        job_id=job.id,
        expected_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
        payload=inventory_payload,
        storage_ref=f"s3://artifacts/{job.id}/inventory.json",
        producer=producer,
    )
    assert first.persisted is True
    assert first.metadata is not None
    await db_session.commit()

    stored = await db_session.get(Artifact, first.metadata.artifact_id)
    assert stored is not None
    reparsed = parse_artifact(
        inventory_payload,
        expected_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
    )
    assert stored.content_hash == reparsed.content_hash
    assert stored.artifact_metadata["schema_version"] == "1.0.0"

    blueprint = await service.persist(
        authorization_context=principal,
        job_id=job.id,
        expected_type=ArtifactType.TARGET_BLUEPRINT,
        expected_schema_version="1.0.0",
        payload=target_blueprint_payload(),
        storage_ref=f"s3://artifacts/{job.id}/blueprint.json",
        producer=producer,
        parent_artifact_ids=[first.metadata.artifact_id],
    )
    assert blueprint.persisted is True
    assert blueprint.metadata is not None
    assert blueprint.metadata.parent_artifact_ids == [first.metadata.artifact_id]
    await db_session.commit()

    invalid_payload = repo_inventory_payload()
    invalid_payload["unexpected"] = "must not be discarded"
    rejected = await service.persist(
        authorization_context=principal,
        job_id=job.id,
        expected_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
        payload=invalid_payload,
        storage_ref=f"s3://artifacts/{job.id}/invalid.json",
        producer=producer,
    )
    assert rejected.persisted is False
    assert rejected.error_code == "ARTIFACT_SCHEMA_INVALID"
    await db_session.commit()

    artifacts = await ArtifactRepository(db_session)._list_artifacts_by_job_unscoped(job.id)
    assert len(artifacts) == 2
    events = await AuditEventRepository(db_session).list_events_by_job(job.id)
    assert [event.action for event in events].count("ARTIFACT_VALIDATION_REJECTED") == 1


@pytest.mark.asyncio
async def test_artifact_transaction_can_roll_back_when_a_later_write_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller rollback removes a staged artifact when the atomic audit write fails."""
    job, principal = await _create_owner_job(db_session, slug="artifact-rollback")
    job_id = job.id
    service = ArtifactPersistenceService(db_session)
    monkeypatch.setattr(
        service._audit,
        "append_event",
        AsyncMock(side_effect=RuntimeError("simulated audit failure")),
    )

    with pytest.raises(RuntimeError, match="simulated audit failure"):
        await service.persist(
            authorization_context=principal,
            job_id=job_id,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
            payload=repo_inventory_payload(),
            storage_ref=f"s3://artifacts/{job_id}/rollback.json",
            producer=ProducerIdentity(kind=ProducerKind.MANUAL, identifier="test-operator"),
        )
    await db_session.rollback()
    assert await ArtifactRepository(db_session)._list_artifacts_by_job_unscoped(job_id) == []
