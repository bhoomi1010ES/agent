"""Live integration tests running real Git CLI commands and verifying reproducibility and isolation."""

import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modernization_platform.integrations.git.models import BranchConvention
from modernization_platform.integrations.git.policy import GitSecurityPolicy
from modernization_platform.integrations.git.providers.https_provider import HttpsGitProvider


@pytest.fixture
def local_git_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a real local Git repository with initial commits and return path, commit SHA, and tree hash."""
    repo_dir = tmp_path / "upstream_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Initialize repository
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Integration Tester"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tester@modernizer.internal"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    # Add sample source files
    (repo_dir / "app.py").write_text("print('Legacy System v1.0')\n")
    (repo_dir / "README.md").write_text("# Legacy Monolith Documentation\n")

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial legacy monolith baseline"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
    )

    # Capture real commit SHA and tree hash
    commit_sha = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_dir))
        .decode("utf-8")
        .strip()
        .lower()
    )
    tree_hash = (
        subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=str(repo_dir))
        .decode("utf-8")
        .strip()
        .lower()
    )

    return repo_dir, commit_sha, tree_hash


@pytest.mark.asyncio
async def test_live_git_clone_and_provenance_extraction(
    local_git_repo: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    repo_dir, expected_commit_sha, expected_tree_hash = local_git_repo
    job_id = uuid.uuid4()
    target_dir = tmp_path / "isolated_job_copy"

    # Allow local repo path for testing integration
    mock_policy = MagicMock(spec=GitSecurityPolicy)
    mock_policy.validate_url.return_value = str(repo_dir)

    provider = HttpsGitProvider(
        policy=mock_policy,
        timeout_seconds=30.0,
        max_repo_size_bytes=10_000_000,
        max_file_count=1_000,
    )

    # Record upstream repo state before clone
    initial_upstream_head = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_dir)).decode().strip()
    )

    # Execute clone
    provenance = await provider.clone_to_working_copy(
        job_id=job_id,
        repository_url=str(repo_dir),
        ref="main",
        target_dir=target_dir,
    )

    # 1. Verify provenance matches real Git state
    assert provenance.job_id == job_id
    assert provenance.resolved_commit_sha == expected_commit_sha
    assert provenance.tree_hash == expected_tree_hash
    assert provenance.commit_author == "Integration Tester"
    assert provenance.commit_message == "Initial legacy monolith baseline"
    assert provenance.repository_metadata.file_count == 2
    assert provenance.repository_metadata.size_bytes > 0
    assert len(provenance.provenance_hash) == 64

    # 2. Verify original repository was NOT modified
    current_upstream_head = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_dir)).decode().strip()
    )
    assert current_upstream_head == initial_upstream_head

    # 3. Verify isolated module branch creation: job/{job_id}/{module}
    module = "customer-billing"
    expected_branch_name = BranchConvention.format_module_branch(job_id, module)
    created_branch = await provider.create_module_branch(
        working_dir=target_dir,
        job_id=job_id,
        module=module,
        base_commit=expected_commit_sha,
    )
    assert created_branch == expected_branch_name

    # Check current branch in isolated copy
    active_branch = (
        subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(target_dir))
        .decode()
        .strip()
    )
    assert active_branch == expected_branch_name

    # Check upstream branches to confirm upstream was untouched
    upstream_branches = (
        subprocess.check_output(["git", "branch"], cwd=str(repo_dir)).decode().strip()
    )
    assert expected_branch_name not in upstream_branches

    # 4. Safely cleanup working copy
    await provider.cleanup_working_copy(target_dir)
    assert not target_dir.exists()
