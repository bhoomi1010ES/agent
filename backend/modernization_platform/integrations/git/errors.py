"""Git integration and source ingestion exceptions."""

from typing import Any

from modernization_platform.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    ModernizerError,
    NotFoundException,
    UnauthorizedException,
)


class GitIntegrationError(ModernizerError):
    """Base exception for all Git integration and source provenance operations."""

    def __init__(self, message: str = "A Git integration error occurred.") -> None:
        super().__init__(message)
        self.message = message


class InvalidRepositoryURLError(GitIntegrationError, BadRequestException):
    """Raised when a repository URL is malformed, uses an unsupported scheme, or embeds credentials."""

    def __init__(
        self,
        message: str = "Invalid repository URL.",
        details: Any | None = None,
        code: str = "INVALID_REPOSITORY_URL",
    ) -> None:
        BadRequestException.__init__(self, message=message, details=details, code=code)
        self.message = message


class RepositoryHostNotAllowedError(GitIntegrationError, ForbiddenException):
    """Raised when a repository hostname is not in the configured GIT_ALLOWED_HOSTS allowlist."""

    def __init__(
        self,
        message: str = "Repository host is not permitted by policy.",
        details: Any | None = None,
        code: str = "REPOSITORY_HOST_NOT_ALLOWED",
    ) -> None:
        ForbiddenException.__init__(self, message=message, details=details, code=code)
        self.message = message


class PrivateNetworkAccessError(GitIntegrationError, ForbiddenException):
    """Raised when a repository URL resolves to a private, loopback, link-local, or cloud metadata IP."""

    def __init__(
        self,
        message: str = "Access to private or internal network addresses is prohibited.",
        details: Any | None = None,
        code: str = "PRIVATE_NETWORK_ACCESS_FORBIDDEN",
    ) -> None:
        ForbiddenException.__init__(self, message=message, details=details, code=code)
        self.message = message


class RepositorySizeExceededError(GitIntegrationError, BadRequestException):
    """Raised when a repository checkout exceeds the configured size ceiling."""

    def __init__(
        self,
        message: str = "Repository exceeds the maximum allowed size limit.",
        details: Any | None = None,
        code: str = "REPOSITORY_SIZE_EXCEEDED",
    ) -> None:
        BadRequestException.__init__(self, message=message, details=details, code=code)
        self.message = message


class RepositoryFileCountExceededError(GitIntegrationError, BadRequestException):
    """Raised when a repository checkout exceeds the maximum allowed file count."""

    def __init__(
        self,
        message: str = "Repository exceeds the maximum allowed file count limit.",
        details: Any | None = None,
        code: str = "REPOSITORY_FILE_COUNT_EXCEEDED",
    ) -> None:
        BadRequestException.__init__(self, message=message, details=details, code=code)
        self.message = message


class GitAuthenticationError(GitIntegrationError, UnauthorizedException):
    """Raised when repository authentication or authorization fails."""

    def __init__(
        self,
        message: str = "Authentication failed for remote repository.",
        details: Any | None = None,
        code: str = "GIT_AUTHENTICATION_FAILED",
    ) -> None:
        UnauthorizedException.__init__(self, message=message, details=details, code=code)
        self.message = message


class GitRevisionNotFoundError(GitIntegrationError, NotFoundException):
    """Raised when the requested branch, tag, or commit reference does not exist."""

    def __init__(
        self,
        message: str = "Requested revision or ref not found in repository.",
        details: Any | None = None,
        code: str = "REVISION_NOT_FOUND",
    ) -> None:
        NotFoundException.__init__(self, message=message, details=details, code=code)
        self.message = message


class GitTimeoutError(GitIntegrationError):
    """Raised when a Git command or network operation times out."""

    def __init__(
        self,
        message: str = "Git operation timed out.",
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class GitExecutionError(GitIntegrationError):
    """Raised when a Git command fails with a non-zero exit code."""

    def __init__(
        self,
        message: str = "Git command execution failed.",
        exit_code: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


__all__ = [
    "GitAuthenticationError",
    "GitExecutionError",
    "GitIntegrationError",
    "GitRevisionNotFoundError",
    "GitTimeoutError",
    "InvalidRepositoryURLError",
    "PrivateNetworkAccessError",
    "RepositoryFileCountExceededError",
    "RepositoryHostNotAllowedError",
    "RepositorySizeExceededError",
]
