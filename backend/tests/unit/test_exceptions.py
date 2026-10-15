"""Unit tests for exception hierarchy and error representation."""

from modernization_platform.core.exceptions import (
    ApplicationException,
    BadRequestException,
    BudgetExceeded,
    ConfigError,
    ConflictException,
    EndpointNotAllowed,
    ForbiddenException,
    GateRequired,
    GatewayError,
    InternalServerException,
    ModernizerError,
    NotFoundException,
    PersistenceError,
    PolicyViolation,
    SandboxError,
    ServiceUnavailableException,
    UnauthorizedException,
    UnprocessableEntityException,
    ValidationFailure,
)


def test_exception_inheritance_tree() -> None:
    """Verify all domain errors inherit from ModernizerError."""
    assert issubclass(ConfigError, ModernizerError)
    assert issubclass(ValidationFailure, ModernizerError)
    assert issubclass(GatewayError, ModernizerError)
    assert issubclass(EndpointNotAllowed, GatewayError)
    assert issubclass(SandboxError, ModernizerError)
    assert issubclass(BudgetExceeded, ModernizerError)
    assert issubclass(GateRequired, ModernizerError)
    assert issubclass(PolicyViolation, ModernizerError)
    assert issubclass(PersistenceError, ModernizerError)
    assert issubclass(ApplicationException, ModernizerError)


def test_http_exceptions_status_codes() -> None:
    """Verify HTTP application exceptions carry expected status codes and default codes."""
    assert BadRequestException().status_code == 400
    assert BadRequestException().code == "BAD_REQUEST"

    assert UnauthorizedException().status_code == 401
    assert UnauthorizedException().code == "UNAUTHORIZED"

    assert ForbiddenException().status_code == 403
    assert ForbiddenException().code == "FORBIDDEN"

    assert NotFoundException().status_code == 404
    assert NotFoundException().code == "NOT_FOUND"

    assert ConflictException().status_code == 409
    assert ConflictException().code == "CONFLICT"

    assert UnprocessableEntityException().status_code == 422
    assert UnprocessableEntityException().code == "UNPROCESSABLE_ENTITY"

    assert InternalServerException().status_code == 500
    assert InternalServerException().code == "INTERNAL_SERVER_ERROR"

    assert ServiceUnavailableException().status_code == 503
    assert ServiceUnavailableException().code == "SERVICE_UNAVAILABLE"
