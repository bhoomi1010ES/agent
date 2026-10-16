"""Strongly typed domain models for Git source references, metadata, and provenance."""

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from modernization_platform.core.decorators import log_errors

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_VALID_MODULE_NAME = re.compile(r"^[a-zA-Z0-9_\-]+$")


class GitCredentials(BaseModel):
    """Secure wrapper for private repository credentials."""

    model_config = ConfigDict(frozen=True)

    username: str | None = Field(default=None, description="Optional username for HTTP Basic Auth")
    password: SecretStr | None = Field(
        default=None, description="Optional password for HTTP Basic Auth"
    )
    token: SecretStr | None = Field(
        default=None, description="Personal access token or bearer token"
    )

    def __repr__(self) -> str:
        has_token = self.token is not None
        has_pwd = self.password is not None
        return f"GitCredentials(username={self.username!r}, has_password={has_pwd}, has_token={has_token})"

    def __str__(self) -> str:
        return self.__repr__()


class GitSourceReference(BaseModel):
    """Validated source repository and reference representation."""

    model_config = ConfigDict(frozen=True)

    repository_url: str = Field(description="Normalized remote HTTPS repository URL")
    provider: str = Field(default="git", description="Git provider classification")
    requested_ref: str = Field(description="Requested branch, tag, or commit ref")
    resolved_commit_sha: str | None = Field(
        default=None, description="Exact 40-char commit SHA once resolved"
    )
    branch: str | None = Field(default=None, description="Branch name if ref was a branch")


class RepositoryMetadata(BaseModel):
    """Structural metadata captured during repository inspection."""

    model_config = ConfigDict(frozen=True)

    default_branch: str | None = Field(default=None, description="Default remote branch")
    size_bytes: int = Field(
        default=0, ge=0, description="Total size in bytes of checked-out repository"
    )
    file_count: int = Field(
        default=0, ge=0, description="Total count of files in checked-out repository"
    )
    commit_author: str | None = Field(default=None, description="Author name from resolved commit")
    commit_author_email: str | None = Field(
        default=None, description="Author email from resolved commit"
    )
    commit_timestamp: datetime | None = Field(
        default=None, description="Commit authoring timestamp"
    )
    commit_message: str | None = Field(default=None, description="Short commit message title")
    tree_hash: str | None = Field(default=None, description="Exact 40-char Git tree object hash")
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Additional diagnostic properties"
    )


class SourceProvenance(BaseModel):
    """Reproducible, immutable source provenance record for a modernized job."""

    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    repository_url: str
    provider: str = "git"
    requested_ref: str
    resolved_commit_sha: str
    branch: str | None = None
    tree_hash: str | None = None
    commit_author: str | None = None
    commit_author_email: str | None = None
    commit_timestamp: datetime | None = None
    commit_message: str | None = None
    repository_metadata: RepositoryMetadata
    ingestion_timestamp: datetime
    ingestion_id: uuid.UUID
    ingestion_status: str = "completed"
    provenance_hash: str


@log_errors
def compute_provenance_hash(
    *,
    job_id: uuid.UUID,
    repository_url: str,
    resolved_commit_sha: str,
    tree_hash: str | None = None,
    requested_ref: str,
) -> str:
    """Compute deterministic SHA-256 digest identifying this exact source baseline."""
    canonical = {
        "job_id": str(job_id),
        "repository_url": repository_url.strip().lower(),
        "requested_ref": requested_ref.strip(),
        "resolved_commit_sha": resolved_commit_sha.strip().lower(),
        "tree_hash": (tree_hash or "").strip().lower(),
    }
    payload_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


class BranchConvention:
    """Standard naming and validation for isolated job module branches."""

    TEMPLATE = "job/{job_id}/{module}"

    @classmethod
    @log_errors
    def validate_module_name(cls, module: str) -> str:
        """Validate module identifier syntax for safe use in Git ref names."""
        trimmed = module.strip()
        if not trimmed:
            raise ValueError("Module name cannot be empty.")
        if len(trimmed) > 100:
            raise ValueError("Module name exceeds 100 character maximum.")
        if _CONTROL_CHARS.search(trimmed):
            raise ValueError("Module name cannot contain control characters.")
        if not _VALID_MODULE_NAME.match(trimmed):
            raise ValueError(
                f"Module name '{trimmed}' contains invalid characters. Must match [a-zA-Z0-9_-]+."
            )
        if trimmed in {".", "..", "@", "~", "^", ":"}:
            raise ValueError(f"Module name '{trimmed}' is a reserved Git reference token.")
        return trimmed

    @classmethod
    @log_errors
    def format_module_branch(cls, job_id: uuid.UUID, module: str) -> str:
        """Format canonical branch name: job/{job_id}/{module}."""
        valid_mod = cls.validate_module_name(module)
        return cls.TEMPLATE.format(job_id=str(job_id), module=valid_mod)

    @classmethod
    @log_errors
    def parse_module_branch(cls, branch_name: str) -> tuple[uuid.UUID, str] | None:
        """Parse a canonical module branch into job ID and module name, or return None."""
        parts = branch_name.split("/")
        if len(parts) != 3 or parts[0] != "job":
            return None
        try:
            job_id = uuid.UUID(parts[1])
            module = cls.validate_module_name(parts[2])
            return job_id, module
        except Exception:
            return None


__all__ = [
    "BranchConvention",
    "GitCredentials",
    "GitSourceReference",
    "RepositoryMetadata",
    "SourceProvenance",
    "compute_provenance_hash",
]
