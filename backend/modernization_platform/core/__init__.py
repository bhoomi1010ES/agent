"""Core utilities, exceptions, logging, and middleware."""

from modernization_platform.core.decorators import log_errors
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
from modernization_platform.core.ids import (
    generate_correlation_id,
    get_correlation_id,
    is_valid_correlation_id,
    set_correlation_id,
)
from modernization_platform.core.logging import setup_logging

__all__ = [
    "ApplicationException",
    "BadRequestException",
    "BudgetExceeded",
    "ConfigError",
    "ConflictException",
    "EndpointNotAllowed",
    "ForbiddenException",
    "GateRequired",
    "GatewayError",
    "InternalServerException",
    "ModernizerError",
    "NotFoundException",
    "PersistenceError",
    "PolicyViolation",
    "SandboxError",
    "ServiceUnavailableException",
    "UnauthorizedException",
    "UnprocessableEntityException",
    "ValidationFailure",
    "generate_correlation_id",
    "get_correlation_id",
    "is_valid_correlation_id",
    "log_errors",
    "set_correlation_id",
    "setup_logging",
]
