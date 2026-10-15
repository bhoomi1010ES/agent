"""Exception hierarchy for the modernization platform.

Provides domain exceptions, system errors, and standardized HTTP-facing application exceptions.
"""

from typing import Any


class ModernizerError(Exception):
    """Base exception for all domain and platform errors."""

    def __init__(self, message: str = "A platform error occurred.") -> None:
        super().__init__(message)
        self.message = message


class ConfigError(ModernizerError):
    """Raised when configuration is invalid, incomplete, or violates security policy."""


class ValidationFailure(ModernizerError):
    """Raised when schema validation or artifact integrity check fails."""


class GatewayError(ModernizerError):
    """Base error for LLM provider gateway failures."""


class EndpointNotAllowed(GatewayError):
    """Raised when a requested model endpoint violates policy for the given job."""


class SandboxError(ModernizerError):
    """Raised when sandbox execution, container setup, or isolation fails."""


class BudgetExceeded(ModernizerError):
    """Raised when hard token or financial budget limit is reached."""


class GateRequired(ModernizerError):
    """Control-flow signal indicating an execution paused waiting for human approval."""


class PolicyViolation(ModernizerError):
    """Raised when an operation violates security or operational policy."""


class PersistenceError(ModernizerError):
    """Raised when database or storage operations encounter an unrecoverable failure."""


class ApplicationException(ModernizerError):
    """Base exception for HTTP-facing errors adhering to the platform error contract."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class BadRequestException(ApplicationException):
    """HTTP 400 Bad Request."""

    def __init__(
        self,
        message: str = "Bad request",
        details: Any | None = None,
        code: str = "BAD_REQUEST",
    ) -> None:
        super().__init__(code=code, message=message, status_code=400, details=details)


class UnauthorizedException(ApplicationException):
    """HTTP 401 Unauthorized."""

    def __init__(
        self,
        message: str = "Authentication required",
        details: Any | None = None,
        code: str = "UNAUTHORIZED",
    ) -> None:
        super().__init__(code=code, message=message, status_code=401, details=details)


class ForbiddenException(ApplicationException):
    """HTTP 403 Forbidden."""

    def __init__(
        self,
        message: str = "Permission denied",
        details: Any | None = None,
        code: str = "FORBIDDEN",
    ) -> None:
        super().__init__(code=code, message=message, status_code=403, details=details)


class NotFoundException(ApplicationException):
    """HTTP 404 Not Found."""

    def __init__(
        self,
        message: str = "Resource not found",
        details: Any | None = None,
        code: str = "NOT_FOUND",
    ) -> None:
        super().__init__(code=code, message=message, status_code=404, details=details)


class ConflictException(ApplicationException):
    """HTTP 409 Conflict."""

    def __init__(
        self,
        message: str = "Conflict detected",
        details: Any | None = None,
        code: str = "CONFLICT",
    ) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)


class UnprocessableEntityException(ApplicationException):
    """HTTP 422 Unprocessable Entity."""

    def __init__(
        self,
        message: str = "Unprocessable entity",
        details: Any | None = None,
        code: str = "UNPROCESSABLE_ENTITY",
    ) -> None:
        super().__init__(code=code, message=message, status_code=422, details=details)


class InternalServerException(ApplicationException):
    """HTTP 500 Internal Server Error."""

    def __init__(
        self,
        message: str = "An internal error occurred",
        details: Any | None = None,
        code: str = "INTERNAL_SERVER_ERROR",
    ) -> None:
        super().__init__(code=code, message=message, status_code=500, details=details)


class ServiceUnavailableException(ApplicationException):
    """HTTP 503 Service Unavailable."""

    def __init__(
        self,
        message: str = "Service unavailable",
        details: Any | None = None,
        code: str = "SERVICE_UNAVAILABLE",
    ) -> None:
        super().__init__(code=code, message=message, status_code=503, details=details)
