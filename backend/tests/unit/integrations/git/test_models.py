"""Unit tests for Git models, credentials masking, and branch conventions."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from modernization_platform.integrations.git.models import (
    BranchConvention,
    GitCredentials,
    RepositoryMetadata,
    SourceProvenance,
    compute_provenance_hash,
)


def test_git_credentials_masking() -> None:
    creds = GitCredentials(
        username="git-user",
        password=SecretStr("super-secret-password"),
        token=SecretStr("ghp_1234567890abcdef"),
    )
    repr_str = repr(creds)
    str_val = str(creds)

    assert "super-secret-password" not in repr_str
    assert "ghp_1234567890abcdef" not in repr_str
    assert "super-secret-password" not in str_val
    assert "ghp_1234567890abcdef" not in str_val
    assert "has_password=True" in repr_str
    assert "has_token=True" in repr_str


def test_branch_convention_formatting_and_parsing() -> None:
    job_id = uuid.uuid4()
    module = "auth-service"

    branch = BranchConvention.format_module_branch(job_id, module)
    assert branch == f"job/{job_id}/auth-service"

    parsed = BranchConvention.parse_module_branch(branch)
    assert parsed is not None
    parsed_job_id, parsed_module = parsed
    assert parsed_job_id == job_id
    assert parsed_module == module


def test_branch_convention_validation_rejects_invalid_names() -> None:
    invalid_modules = [
        "",
        "   ",
        "module/with/slashes",
        "module..traversal",
        "module with spaces",
        "module\x00control",
        ".",
        "..",
        "a" * 101,  # exceeds 100 chars
    ]
    for invalid in invalid_modules:
        with pytest.raises(ValueError):
            BranchConvention.validate_module_name(invalid)


def test_branch_convention_parse_invalid_returns_none() -> None:
    assert BranchConvention.parse_module_branch("invalid-branch-name") is None
    assert BranchConvention.parse_module_branch("job/not-a-uuid/mod") is None
    assert BranchConvention.parse_module_branch("feat/job/123/mod") is None


def test_compute_provenance_hash_is_deterministic() -> None:
    job_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    hash1 = compute_provenance_hash(
        job_id=job_id,
        repository_url="https://github.com/acme/legacy.git",
        resolved_commit_sha="4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345",
        tree_hash="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        requested_ref="main",
    )
    hash2 = compute_provenance_hash(
        job_id=job_id,
        repository_url="https://github.com/acme/legacy.git",
        resolved_commit_sha="4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345",
        tree_hash="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        requested_ref="main",
    )
    assert hash1 == hash2
    assert len(hash1) == 64


def test_source_provenance_model_instantiation() -> None:
    job_id = uuid.uuid4()
    meta = RepositoryMetadata(
        default_branch="main",
        size_bytes=10240,
        file_count=25,
        commit_author="Alice Developer",
        commit_author_email="alice@example.com",
        commit_timestamp=datetime.now(UTC),
        commit_message="Initial commit",
        tree_hash="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    )
    prov = SourceProvenance(
        job_id=job_id,
        repository_url="https://github.com/acme/legacy.git",
        provider="git",
        requested_ref="main",
        resolved_commit_sha="4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345",
        branch="main",
        tree_hash=meta.tree_hash,
        commit_author=meta.commit_author,
        commit_author_email=meta.commit_author_email,
        commit_timestamp=meta.commit_timestamp,
        commit_message=meta.commit_message,
        repository_metadata=meta,
        ingestion_timestamp=datetime.now(UTC),
        ingestion_id=uuid.uuid4(),
        ingestion_status="completed",
        provenance_hash="abcdef0123456789" * 4,
    )
    assert prov.job_id == job_id
    assert prov.resolved_commit_sha == "4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345"
    assert prov.repository_metadata.file_count == 25
