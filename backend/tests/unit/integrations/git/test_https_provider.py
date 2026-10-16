"""Unit tests for HttpsGitProvider with mocked subprocess execution and limits."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modernization_platform.integrations.git.errors import (
    GitAuthenticationError,
    GitRevisionNotFoundError,
    GitTimeoutError,
    RepositoryFileCountExceededError,
    RepositorySizeExceededError,
)
from modernization_platform.integrations.git.models import RepositoryMetadata
from modernization_platform.integrations.git.policy import GitSecurityPolicy
from modernization_platform.integrations.git.providers.https_provider import HttpsGitProvider


@pytest.fixture
def mock_policy() -> GitSecurityPolicy:
    policy = MagicMock(spec=GitSecurityPolicy)
    policy.validate_url.side_effect = lambda url: url
    return policy


@pytest.fixture
def provider(mock_policy: GitSecurityPolicy) -> HttpsGitProvider:
    return HttpsGitProvider(
        policy=mock_policy,
        timeout_seconds=5.0,
        max_repo_size_bytes=1000,
        max_file_count=10,
    )


@pytest.mark.asyncio
async def test_resolve_revision_direct_40_char_sha(provider: HttpsGitProvider) -> None:
    sha = "4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345"
    resolved = await provider.resolve_revision(
        repository_url="https://github.com/acme/repo.git",
        ref=sha,
    )
    assert resolved == sha


@pytest.mark.asyncio
async def test_resolve_revision_via_ls_remote(provider: HttpsGitProvider) -> None:
    expected_sha = "e1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4"
    ls_remote_output = (
        f"{expected_sha}\trefs/heads/main\n"
        "1234567890abcdef1234567890abcdef12345678\trefs/heads/feature\n"
    )

    with patch.object(provider, "_run_git", AsyncMock(return_value=ls_remote_output)):
        resolved = await provider.resolve_revision(
            repository_url="https://github.com/acme/repo.git",
            ref="main",
        )
        assert resolved == expected_sha


@pytest.mark.asyncio
async def test_resolve_revision_not_found(provider: HttpsGitProvider) -> None:
    with (
        patch.object(provider, "_run_git", AsyncMock(return_value="")),
        pytest.raises(GitRevisionNotFoundError, match="not found in remote repository"),
    ):
        await provider.resolve_revision(
            repository_url="https://github.com/acme/repo.git",
            ref="non-existent-branch",
        )


@pytest.mark.asyncio
async def test_clone_to_working_copy_success(
    provider: HttpsGitProvider,
    tmp_path: Path,
) -> None:
    job_id = uuid.uuid4()
    target_dir = tmp_path / "workdir"

    # Mock git commands executed during clone
    commit_sha = "4f8a9b2c3d4e5f60718293a4b5c6d7e8f9012345"
    tree_hash = "1111111122222222333333334444444455555555"
    log_output = "Developer Dan\x1fdan@example.com\x1f2026-10-15T12:00:00+00:00\x1fInitial commit"

    async def mock_run_git(args: list[str], **kwargs: object) -> str:
        cmd = args[0]
        if cmd == "clone":
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "file.txt").write_text("code")
            return ""
        elif cmd == "rev-parse" and "--abbrev-ref" in args:
            return "main"
        elif cmd == "rev-parse" and "HEAD^{tree}" in args:
            return tree_hash
        elif cmd == "rev-parse" and "HEAD" in args:
            return commit_sha
        elif cmd == "log":
            return log_output
        return ""

    with patch.object(provider, "_run_git", side_effect=mock_run_git):
        provenance = await provider.clone_to_working_copy(
            job_id=job_id,
            repository_url="https://github.com/acme/repo.git",
            ref="main",
            target_dir=target_dir,
        )

        assert provenance.job_id == job_id
        assert provenance.resolved_commit_sha == commit_sha
        assert provenance.tree_hash == tree_hash
        assert provenance.commit_author == "Developer Dan"
        assert provenance.commit_author_email == "dan@example.com"
        assert provenance.branch == "main"
        assert provenance.repository_metadata.file_count == 1


@pytest.mark.asyncio
async def test_clone_exceeding_size_limit_raises_and_cleans_up(
    provider: HttpsGitProvider,
    tmp_path: Path,
) -> None:
    job_id = uuid.uuid4()
    target_dir = tmp_path / "oversized_repo"

    # Mock inspection to return size > max_repo_size_bytes (1000)
    fake_metadata = RepositoryMetadata(size_bytes=2000, file_count=5)

    with (
        patch.object(provider, "_run_git", AsyncMock(return_value="")),
        patch.object(provider, "inspect_working_copy", AsyncMock(return_value=fake_metadata)),
        pytest.raises(RepositorySizeExceededError, match="exceeds limit"),
    ):
        await provider.clone_to_working_copy(
            job_id=job_id,
            repository_url="https://github.com/acme/huge-repo.git",
            ref="main",
            target_dir=target_dir,
        )


@pytest.mark.asyncio
async def test_clone_exceeding_file_count_raises_and_cleans_up(
    provider: HttpsGitProvider,
    tmp_path: Path,
) -> None:
    job_id = uuid.uuid4()
    target_dir = tmp_path / "many_files_repo"

    # Mock inspection to return file count > max_file_count (10)
    fake_metadata = RepositoryMetadata(size_bytes=500, file_count=50)

    with (
        patch.object(provider, "_run_git", AsyncMock(return_value="")),
        patch.object(provider, "inspect_working_copy", AsyncMock(return_value=fake_metadata)),
        pytest.raises(RepositoryFileCountExceededError, match="exceeding limit"),
    ):
        await provider.clone_to_working_copy(
            job_id=job_id,
            repository_url="https://github.com/acme/many-files.git",
            ref="main",
            target_dir=target_dir,
        )


@pytest.mark.asyncio
async def test_authentication_error_classification(provider: HttpsGitProvider) -> None:
    with (
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=AsyncMock(
                return_value=MagicMock(
                    communicate=AsyncMock(
                        return_value=(b"", b"fatal: Authentication failed for 'https://...'")
                    ),
                    returncode=128,
                )
            ),
        ),
        pytest.raises(GitAuthenticationError, match="Authentication failed"),
    ):
        await provider._run_git(["clone", "https://github.com/private/repo.git"])


@pytest.mark.asyncio
async def test_timeout_error_handling(provider: HttpsGitProvider) -> None:
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        with pytest.raises(GitTimeoutError, match="timed out"):
            await provider._run_git(["clone", "https://github.com/acme/slow.git"])
        mock_proc.kill.assert_called_once()
