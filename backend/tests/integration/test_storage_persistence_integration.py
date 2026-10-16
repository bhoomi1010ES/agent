"""Integration tests for ArtifactPersistenceService storage integration and consistency recovery."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.job import Job
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.metadata import ProducerIdentity, ProducerKind
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.artifacts import ArtifactPersistenceService
from modernization_platform.storage.exceptions import ObjectNotFoundException
from modernization_platform.storage.memory import MemoryStorageAdapter
from modernization_platform.storage.service import ArtifactStorageService


def _principal(tenant_id: uuid.UUID | None = None) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-architect",
        issuer="https://auth.modernization.internal",
        roles=frozenset({Role.OWNER}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.mark.asyncio
async def test_store_and_persist_success(mock_session: AsyncMock) -> None:
    """Artifact is uploaded to storage, staged in DB, and audited in one consistent workflow."""
    principal = _principal()
    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="architect", status="active")

    memory_adapter = MemoryStorageAdapter(bucket="modernization-artifacts")
    storage_svc = ArtifactStorageService(adapter=memory_adapter)
    persistence_svc = ArtifactPersistenceService(session=mock_session, storage=storage_svc)

    from tests.contract.factories import repo_inventory_payload

    payload = repo_inventory_payload()
    producer = ProducerIdentity(kind=ProducerKind.MANUAL, identifier=str(principal.user_id))

    with (
        patch(
            "modernization_platform.services.authorization.AuthorizationService.get_job",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.audit_events.AuditEventRepository.append_event",
            new_callable=AsyncMock,
        ) as mock_audit,
    ):
        result = await persistence_svc.store_and_persist(
            authorization_context=principal,
            tenant_id=principal.tenant_id,
            job_id=job_id,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
            payload=payload,
            producer=producer,
        )

    assert result.persisted is True
    assert result.metadata is not None
    assert result.metadata.storage_ref.startswith("s3://modernization-artifacts/artifacts/")
    assert mock_audit.called is True
    assert mock_audit.call_args.kwargs["action"] == "ARTIFACT_STORED_AND_STAGED"

    # Verify object actually exists in memory storage
    exists = await storage_svc.artifact_exists(storage_ref=result.metadata.storage_ref)
    assert exists is True


@pytest.mark.asyncio
async def test_store_and_persist_compensating_cleanup_on_db_failure(
    mock_session: AsyncMock,
) -> None:
    """When DB staging fails after storage upload, compensating deletion removes the uploaded object."""
    principal = _principal()
    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="architect", status="active")

    memory_adapter = MemoryStorageAdapter(bucket="modernization-artifacts")
    storage_svc = ArtifactStorageService(adapter=memory_adapter)
    persistence_svc = ArtifactPersistenceService(session=mock_session, storage=storage_svc)

    from tests.contract.factories import repo_inventory_payload

    payload = repo_inventory_payload()
    producer = ProducerIdentity(kind=ProducerKind.MANUAL, identifier=str(principal.user_id))

    with (
        patch(
            "modernization_platform.services.authorization.AuthorizationService.get_job",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.artifacts.ArtifactRepository._append_artifact_after_authorization",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Simulated DB integrity failure"),
        ),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            await persistence_svc.store_and_persist(
                authorization_context=principal,
                tenant_id=principal.tenant_id,
                job_id=job_id,
                expected_type=ArtifactType.REPO_INVENTORY,
                expected_schema_version="1.0.0",
                payload=payload,
                producer=producer,
            )
        assert "Simulated DB integrity failure" in str(exc_info.value)

    # Verify compensating cleanup was executed: memory adapter has recorded deletion
    assert len(memory_adapter.cleaned_up_keys) == 1
    # Verify no leaked objects in store
    assert len(memory_adapter._store) == 0


@pytest.mark.asyncio
async def test_missing_underlying_storage_object_raises_not_found(
    mock_session: AsyncMock,
) -> None:
    """When DB row points to a missing storage object, retrieval raises ObjectNotFoundException."""
    principal = _principal()
    job_id = uuid.uuid4()
    job = Job(id=job_id, tenant_id=principal.tenant_id, owner="architect", status="active")

    artifact_id = uuid.uuid4()
    missing_storage_ref = "s3://modernization-artifacts/artifacts/missing/item.json"
    artifact = Artifact(
        id=artifact_id,
        job_id=job_id,
        type="RepoInventory",
        version=1,
        content_hash="0" * 64,
        storage_ref=missing_storage_ref,
    )

    memory_adapter = MemoryStorageAdapter(bucket="modernization-artifacts")
    storage_svc = ArtifactStorageService(adapter=memory_adapter)

    with (
        patch(
            "modernization_platform.repositories.jobs.JobRepository.get_by_id_scoped",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "modernization_platform.repositories.artifacts.ArtifactRepository.get_by_job_and_type_scoped",
            new_callable=AsyncMock,
            return_value=artifact,
        ),
    ):
        from modernization_platform.services.authorization import AuthorizationService

        auth_svc = AuthorizationService(mock_session)
        with pytest.raises(ObjectNotFoundException) as exc_info:
            await auth_svc.get_job_artifact_content(
                principal=principal,
                job_id=job_id,
                artifact_type="RepoInventory",
                storage_service=storage_svc,
            )
        assert "not found" in str(exc_info.value)
