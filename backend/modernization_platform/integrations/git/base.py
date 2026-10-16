"""Abstract interface for Git providers."""

import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from modernization_platform.integrations.git.models import (
    GitCredentials,
    RepositoryMetadata,
    SourceProvenance,
)


class GitProvider(ABC):
    """Abstract base class for Git repository operations and working copy management."""

    @abstractmethod
    async def validate_source(
        self,
        repository_url: str,
        credentials: GitCredentials | None = None,
    ) -> str:
        """Validate repository URL against security policy and return normalized URL."""

    @abstractmethod
    async def resolve_revision(
        self,
        *,
        repository_url: str,
        ref: str,
        credentials: GitCredentials | None = None,
    ) -> str:
        """Resolve a branch name, tag, or symbolic ref to an exact 40-character commit SHA."""

    @abstractmethod
    async def clone_to_working_copy(
        self,
        *,
        job_id: uuid.UUID,
        repository_url: str,
        ref: str,
        target_dir: Path,
        credentials: GitCredentials | None = None,
    ) -> SourceProvenance:
        """Clone repository into an isolated working copy, enforce limits, and return SourceProvenance."""

    @abstractmethod
    async def create_module_branch(
        self,
        *,
        working_dir: Path,
        job_id: uuid.UUID,
        module: str,
        base_commit: str,
    ) -> str:
        """Create and checkout an isolated module branch: job/{job_id}/{module}."""

    @abstractmethod
    async def inspect_working_copy(
        self,
        working_dir: Path,
    ) -> RepositoryMetadata:
        """Inspect repository working copy for file count, byte size, commit info, and tree hash."""

    @abstractmethod
    async def cleanup_working_copy(
        self,
        working_dir: Path,
    ) -> None:
        """Safely remove working directory and all checked-out files."""


__all__ = ["GitProvider"]
