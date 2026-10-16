"""Production HTTPS Git adapter executing controlled subprocess operations."""

import asyncio
import logging
import os
import re
import shutil
import stat
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modernization_platform.core.decorators import log_errors
from modernization_platform.integrations.git.base import GitProvider
from modernization_platform.integrations.git.errors import (
    GitAuthenticationError,
    GitExecutionError,
    GitRevisionNotFoundError,
    GitTimeoutError,
    RepositoryFileCountExceededError,
    RepositorySizeExceededError,
)
from modernization_platform.integrations.git.models import (
    BranchConvention,
    GitCredentials,
    RepositoryMetadata,
    SourceProvenance,
    compute_provenance_hash,
)
from modernization_platform.integrations.git.policy import GitSecurityPolicy

logger = logging.getLogger(__name__)

_HEX_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")
_ASKPASS_PATH = Path(__file__).parent.parent / "askpass.py"


def _handle_remove_readonly(func: Any, path: str, exc_info: Any) -> None:
    """Error handler for shutil.rmtree to clear read-only file bits on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as exc:
        logger.debug("Failed to force chmod on %s during cleanup: %s", path, exc)


class HttpsGitProvider(GitProvider):
    """Concrete Git provider supporting HTTPS repository ingestion with strict isolation and limits."""

    def __init__(
        self,
        *,
        policy: GitSecurityPolicy | None = None,
        timeout_seconds: float = 120.0,
        max_repo_size_bytes: int = 524_288_000,  # 500 MiB
        max_file_count: int = 50_000,
    ) -> None:
        self._policy = policy or GitSecurityPolicy()
        self._timeout_seconds = timeout_seconds
        self._max_repo_size_bytes = max_repo_size_bytes
        self._max_file_count = max_file_count

    @log_errors
    async def validate_source(
        self,
        repository_url: str,
        credentials: GitCredentials | None = None,
    ) -> str:
        """Validate URL according to security policy."""
        return self._policy.validate_url(repository_url)

    @log_errors
    async def resolve_revision(
        self,
        *,
        repository_url: str,
        ref: str,
        credentials: GitCredentials | None = None,
    ) -> str:
        """Resolve a remote branch, tag, or HEAD to an exact 40-character commit SHA."""
        valid_url = self._policy.validate_url(repository_url)
        clean_ref = ref.strip()

        # If ref is already a 40-character hex commit SHA, verify syntax and return
        if _HEX_SHA_REGEX.match(clean_ref):
            return clean_ref.lower()

        # Query remote refs via git ls-remote
        stdout = await self._run_git(
            ["ls-remote", valid_url, clean_ref],
            credentials=credentials,
        )

        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and _HEX_SHA_REGEX.match(parts[0]):
                ref_name = parts[1]
                # Match exact ref or ref suffix
                if ref_name in {clean_ref, f"refs/heads/{clean_ref}", f"refs/tags/{clean_ref}"}:
                    return parts[0].lower()

        # Fallback: if user specified HEAD or default branch without exact match
        if clean_ref.upper() == "HEAD" and lines:
            first_sha = lines[0].split()[0]
            if _HEX_SHA_REGEX.match(first_sha):
                return first_sha.lower()

        # If still not found, check if HEAD ref exists
        if clean_ref in {"main", "master"}:
            head_out = await self._run_git(
                ["ls-remote", valid_url, "HEAD"],
                credentials=credentials,
            )
            head_lines = [line.strip() for line in head_out.splitlines() if line.strip()]
            if head_lines:
                first_sha = head_lines[0].split()[0]
                if _HEX_SHA_REGEX.match(first_sha):
                    return first_sha.lower()

        raise GitRevisionNotFoundError(
            f"Reference '{clean_ref}' not found in remote repository '{valid_url}'."
        )

    @log_errors
    async def clone_to_working_copy(
        self,
        *,
        job_id: uuid.UUID,
        repository_url: str,
        ref: str,
        target_dir: Path,
        credentials: GitCredentials | None = None,
    ) -> SourceProvenance:
        """Clone remote repository into an isolated working copy with resource ceiling checks."""
        valid_url = self._policy.validate_url(repository_url)
        clean_ref = ref.strip()

        # Clean existing target directory if present
        if target_dir.exists():
            await self.cleanup_working_copy(target_dir)

        target_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Attempt shallow clone by branch/tag name
            if not _HEX_SHA_REGEX.match(clean_ref):
                try:
                    await self._run_git(
                        [
                            "clone",
                            "--depth",
                            "1",
                            "--branch",
                            clean_ref,
                            "--single-branch",
                            valid_url,
                            str(target_dir),
                        ],
                        credentials=credentials,
                    )
                except GitExecutionError as exc:
                    # Fallback to fetch commit directly if ref was not a standard branch
                    logger.info(
                        "Direct branch clone for '%s' failed, falling back to init+fetch: %s",
                        clean_ref,
                        exc,
                    )
                    await self._init_and_fetch_commit(valid_url, clean_ref, target_dir, credentials)
            else:
                # 2. Ref is a direct commit SHA
                await self._init_and_fetch_commit(valid_url, clean_ref, target_dir, credentials)

            # 3. Enforce file count and size ceilings
            metadata = await self.inspect_working_copy(target_dir)
            if metadata.size_bytes > self._max_repo_size_bytes:
                await self.cleanup_working_copy(target_dir)
                raise RepositorySizeExceededError(
                    f"Repository size ({metadata.size_bytes} bytes) exceeds limit of "
                    f"{self._max_repo_size_bytes} bytes."
                )

            if metadata.file_count > self._max_file_count:
                await self.cleanup_working_copy(target_dir)
                raise RepositoryFileCountExceededError(
                    f"Repository contains {metadata.file_count} files, exceeding limit of "
                    f"{self._max_file_count} files."
                )

            # 4. Resolve exact commit SHA and tree hash
            commit_sha = await self._run_git(["rev-parse", "HEAD"], cwd=target_dir)
            commit_sha = commit_sha.strip().lower()

            tree_hash = await self._run_git(["rev-parse", "HEAD^{tree}"], cwd=target_dir)
            tree_hash = tree_hash.strip().lower()

            # 5. Extract author and commit details
            log_out = await self._run_git(
                ["log", "-1", "--format=%an%x1f%ae%x1f%aI%x1f%s"],
                cwd=target_dir,
            )
            log_parts = log_out.strip().split("\x1f")
            author_name = log_parts[0] if len(log_parts) > 0 else None
            author_email = log_parts[1] if len(log_parts) > 1 else None
            commit_dt: datetime | None = None
            if len(log_parts) > 2 and log_parts[2]:
                try:
                    commit_dt = datetime.fromisoformat(log_parts[2])
                except Exception:
                    commit_dt = None
            commit_subject = log_parts[3] if len(log_parts) > 3 else None

            # Detect branch name if checked out
            branch_name: str | None = None
            try:
                b_out = await self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target_dir)
                b_trimmed = b_out.strip()
                if b_trimmed and b_trimmed != "HEAD":
                    branch_name = b_trimmed
            except Exception:
                branch_name = None

            # Update metadata
            enriched_metadata = RepositoryMetadata(
                default_branch=branch_name or clean_ref,
                size_bytes=metadata.size_bytes,
                file_count=metadata.file_count,
                commit_author=author_name,
                commit_author_email=author_email,
                commit_timestamp=commit_dt,
                commit_message=commit_subject,
                tree_hash=tree_hash,
            )

            ingestion_id = uuid.uuid4()
            prov_hash = compute_provenance_hash(
                job_id=job_id,
                repository_url=valid_url,
                resolved_commit_sha=commit_sha,
                tree_hash=tree_hash,
                requested_ref=clean_ref,
            )

            return SourceProvenance(
                job_id=job_id,
                repository_url=valid_url,
                provider="git",
                requested_ref=clean_ref,
                resolved_commit_sha=commit_sha,
                branch=branch_name or (clean_ref if not _HEX_SHA_REGEX.match(clean_ref) else None),
                tree_hash=tree_hash,
                commit_author=author_name,
                commit_author_email=author_email,
                commit_timestamp=commit_dt,
                commit_message=commit_subject,
                repository_metadata=enriched_metadata,
                ingestion_timestamp=datetime.now(UTC),
                ingestion_id=ingestion_id,
                ingestion_status="completed",
                provenance_hash=prov_hash,
            )
        except Exception:
            # Ensure partial checkouts are cleaned up on failure
            if target_dir.exists():
                await self.cleanup_working_copy(target_dir)
            raise

    @log_errors
    async def _init_and_fetch_commit(
        self,
        repository_url: str,
        ref: str,
        target_dir: Path,
        credentials: GitCredentials | None,
    ) -> None:
        """Initialize empty directory, add remote, fetch ref, and checkout FETCH_HEAD."""
        target_dir.mkdir(parents=True, exist_ok=True)
        await self._run_git(["init"], cwd=target_dir)
        await self._run_git(["remote", "add", "origin", repository_url], cwd=target_dir)
        await self._run_git(
            ["fetch", "--depth", "1", "origin", ref],
            cwd=target_dir,
            credentials=credentials,
        )
        await self._run_git(["checkout", "FETCH_HEAD"], cwd=target_dir)

    @log_errors
    async def create_module_branch(
        self,
        *,
        working_dir: Path,
        job_id: uuid.UUID,
        module: str,
        base_commit: str,
    ) -> str:
        """Create and checkout the isolated module branch: job/{job_id}/{module}."""
        branch_name = BranchConvention.format_module_branch(job_id, module)
        await self._run_git(
            ["checkout", "-B", branch_name, base_commit],
            cwd=working_dir,
        )
        return branch_name

    @log_errors
    async def inspect_working_copy(self, working_dir: Path) -> RepositoryMetadata:
        """Inspect repository working copy for byte size and file count."""
        total_size = 0
        total_files = 0

        for root, dirs, files in os.walk(working_dir):
            # Skip .git directory from payload size calculation
            if ".git" in dirs:
                dirs.remove(".git")
            for f in files:
                total_files += 1
                try:
                    fp = os.path.join(root, f)
                    total_size += os.path.getsize(fp)
                except OSError:
                    continue

        return RepositoryMetadata(
            size_bytes=total_size,
            file_count=total_files,
        )

    @log_errors
    async def cleanup_working_copy(self, working_dir: Path) -> None:
        """Safely remove working directory and all checked-out files."""
        if not working_dir.exists():
            return
        # Run in thread pool to prevent blocking asyncio loop on disk I/O
        await asyncio.to_thread(shutil.rmtree, str(working_dir), onerror=_handle_remove_readonly)

    @log_errors
    async def _run_git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        credentials: GitCredentials | None = None,
    ) -> str:
        """Execute a git subprocess with strict timeouts, environment isolation, and credential injection."""
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_OPTIONAL_LOCKS"] = "0"

        # Securely pass credentials via GIT_ASKPASS without exposing on command line
        if credentials:
            env["GIT_ASKPASS"] = sys.executable
            # Set askpass script as wrapper
            env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent.parent)
            env["GIT_ASKPASS"] = str(_ASKPASS_PATH)
            if credentials.token:
                env["GIT_TOKEN"] = credentials.token.get_secret_value()
            if credentials.password:
                env["GIT_PASSWORD"] = credentials.password.get_secret_value()
            if credentials.username:
                env["GIT_USERNAME"] = credentials.username

        cmd = ["git", *args]
        logger.debug("Executing Git command: git %s (cwd=%s)", " ".join(args[:2]), cwd)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise GitTimeoutError(
                    f"Git command 'git {args[0]}' timed out after {self._timeout_seconds} seconds.",
                    timeout_seconds=self._timeout_seconds,
                ) from exc

            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                self._handle_git_error(args, proc.returncode, stderr_text)

            return stdout_text
        except FileNotFoundError as exc:
            raise GitExecutionError("Git CLI executable not found on system PATH.") from exc

    def _handle_git_error(self, args: list[str], returncode: int | None, stderr: str) -> None:
        """Classify stderr output into typed domain exceptions."""
        try:
            err_lower = stderr.lower()

            if any(
                term in err_lower
                for term in (
                    "authentication failed",
                    "could not read username",
                    "terminal prompts disabled",
                    "401",
                    "403",
                )
            ):
                raise GitAuthenticationError(
                    f"Authentication failed for remote repository: {stderr.strip()}"
                )

            if any(
                term in err_lower
                for term in (
                    "remote branch",
                    "not found",
                    "did not match any file",
                    "fatal: reference is not a tree",
                )
            ):
                raise GitRevisionNotFoundError(
                    f"Requested Git reference or branch not found: {stderr.strip()}"
                )

            raise GitExecutionError(
                f"Git command 'git {args[0]}' exited with code {returncode}: {stderr.strip()}",
                exit_code=returncode,
                stderr=stderr.strip(),
            )
        except Exception:
            raise


__all__ = ["HttpsGitProvider"]
