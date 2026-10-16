"""Unit tests for SourceIngestionService business logic, provenance persistence, and audit."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.errors import JobNotFoundError
from modernization_platform.integrations.git.base import GitProvider
from modernization_platform.integrations.git.models import (
    RepositoryMetadata,
    SourceProvenance,
)
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.source_ingestion import SourceIngestionService


def _test_principal(role: Role = Role.OWNER) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-architect",
        issuer="https://auth.modernization.internal",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_git_provider() -> AsyncMock:
    provider = AsyncMock(spec=GitProvider)
    return provider


@pytest.mark.asyncio
async def test_ingest_source_success(
    mock_session: AsyncMock,
    mock_git_provider: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    principal = _test_principal(Role.OWNER)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="queued",
        version=1,
        source_ref="https://github.com/acme/legacy.git@main",
        source_revision="main",
        target_stack_spec={},
        budget={},
    )

    commit_sha = "4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345"
    tree_hash = "1111111122222222333333334444444455555555"
    metadata = RepositoryMetadata(
        default_branch="main",
        size_bytes=5000,
        file_count=12,
        commit_author="Alice Dev",
        commit_author_email="alice@example.com",
        commit_timestamp=datetime.now(UTC),
        commit_message="Initial commit",
        tree_hash=tree_hash,
    )
    fake_provenance = SourceProvenance(
        job_id=job_id,
        repository_url="https://github.com/acme/legacy.git",
        provider="git",
        requested_ref="main",
        resolved_commit_sha=commit_sha,
        branch="main",
        tree_hash=tree_hash,
        commit_author="Alice Dev",
        commit_author_email="alice@example.com",
        commit_timestamp=metadata.commit_timestamp,
        commit_message="Initial commit",
        repository_metadata=metadata,
        ingestion_timestamp=datetime.now(UTC),
        ingestion_id=uuid.uuid4(),
        ingestion_status="completed",
        provenance_hash="abcdef0123456789" * 4,
    )
    mock_git_provider.clone_to_working_copy.return_value = fake_provenance

    service = SourceIngestionService(
        session=mock_session,
        git_provider=mock_git_provider,
        workdir_base=tmp_path,
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))
    monkeypatch.setattr(service._provenance_repo, "save_provenance", AsyncMock())
    monkeypatch.setattr(service._audit, "append_event", AsyncMock())

    result = await service.ingest_source(
        principal=principal,
        job_id=job_id,
        correlation_id="corr-1234",
    )

    assert result is fake_provenance
    assert job.source_revision == commit_sha
    mock_git_provider.clone_to_working_copy.assert_called_once()
    service._provenance_repo.save_provenance.assert_called_once()  # type: ignore[attr-defined]
    service._audit.append_event.assert_called_once()  # type: ignore[attr-defined]
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_source_job_not_found(
    mock_session: AsyncMock,
    mock_git_provider: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    principal = _test_principal(Role.OWNER)
    service = SourceIngestionService(
        session=mock_session,
        git_provider=mock_git_provider,
        workdir_base=tmp_path,
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=None))

    with pytest.raises(JobNotFoundError):
        await service.ingest_source(
            principal=principal,
            job_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_ingest_source_failure_rolls_back(
    mock_session: AsyncMock,
    mock_git_provider: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    principal = _test_principal(Role.OWNER)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="queued",
        version=1,
        source_ref="https://github.com/acme/legacy.git@main",
        source_revision="main",
        target_stack_spec={},
        budget={},
    )
    mock_git_provider.clone_to_working_copy.side_effect = RuntimeError("Network error")

    service = SourceIngestionService(
        session=mock_session,
        git_provider=mock_git_provider,
        workdir_base=tmp_path,
    )
    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))

    with pytest.raises(RuntimeError, match="Network error"):
        await service.ingest_source(
            principal=principal,
            job_id=job_id,
        )

    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_create_module_workspace(
    mock_session: AsyncMock,
    mock_git_provider: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    principal = _test_principal(Role.OWNER)
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        version=2,
        source_ref="https://github.com/acme/legacy.git",
        source_revision="4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345",
        target_stack_spec={},
        budget={},
    )
    service = SourceIngestionService(
        session=mock_session,
        git_provider=mock_git_provider,
        workdir_base=tmp_path,
    )
    # Ensure source dir exists
    source_dir = service.get_job_source_dir(job_id, principal.tenant_id)
    source_dir.mkdir(parents=True, exist_ok=True)

    expected_branch = f"job/{job_id}/auth-module"
    mock_git_provider.create_module_branch.return_value = expected_branch

    monkeypatch.setattr(service._jobs, "get_by_id_scoped", AsyncMock(return_value=job))
    monkeypatch.setattr(service._provenance_repo, "get_by_job_id", AsyncMock(return_value=None))

    branch_name = await service.create_module_workspace(
        principal=principal,
        job_id=job_id,
        module="auth-module",
    )

    assert branch_name == expected_branch
    mock_git_provider.create_module_branch.assert_called_once_with(
        working_dir=source_dir,
        job_id=job_id,
        module="auth-module",
        base_commit=job.source_revision,
    )
