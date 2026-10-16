"""Structured domain error hierarchy for the provider-neutral Model Gateway."""

from typing import Any

from modernization_platform.core.exceptions import (
    ApplicationException,
)


class ModelGatewayError(ApplicationException):
    """Base exception for all model gateway and LLM dispatch operations."""

    def __init__(
        self,
        message: str,
        code: str = "MODEL_GATEWAY_ERROR",
        status_code: int = 500,
        details: Any | None = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=status_code, details=details)


class ModelPolicyViolationError(ModelGatewayError):
    """Raised when a model invocation request violates approved provider/model/agent policy."""

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(
            message=message,
            code="MODEL_POLICY_VIOLATION",
            status_code=403,
            details=details,
        )


class ModelProviderUnavailableError(ModelGatewayError):
    """Raised when the target model provider endpoint is down, unreachable, or returns 5xx."""

    def __init__(self, provider: str, reason: str, details: Any | None = None) -> None:
        super().__init__(
            message=f"Model provider '{provider}' is currently unavailable: {reason}",
            code="MODEL_PROVIDER_UNAVAILABLE",
            status_code=503,
            details=details,
        )


class ModelBudgetExceededError(ModelGatewayError):
    """Raised when a model call cannot proceed because budget limits have been reached (100% hard stop)."""

    def __init__(
        self,
        scope: str,
        limit_cents: float,
        current_cents: float,
        estimated_cents: float,
        details: Any | None = None,
    ) -> None:
        self.scope = scope
        self.limit_cents = limit_cents
        self.current_cents = current_cents
        self.estimated_cents = estimated_cents
        super().__init__(
            message=(
                f"Budget limit exceeded for scope '{scope}'. Configured limit: "
                f"${limit_cents:.2f}, current spend: ${current_cents:.2f}, "
                f"estimated call cost: ${estimated_cents:.2f}."
            ),
            code="MODEL_BUDGET_EXCEEDED",
            status_code=409,
            details=details,
        )


class ModelBudgetReservationError(ModelGatewayError):
    """Raised when an atomic budget reservation lock or insert fails."""

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(
            message=message,
            code="MODEL_BUDGET_RESERVATION_ERROR",
            status_code=409,
            details=details,
        )


class ModelRateLimitError(ModelGatewayError):
    """Raised when provider or gateway rate limit has been exceeded."""

    def __init__(
        self,
        provider: str,
        retry_after: float | None = None,
        details: Any | None = None,
    ) -> None:
        self.provider = provider
        self.retry_after = retry_after
        msg = f"Rate limit exceeded on provider '{provider}'."
        if retry_after is not None:
            msg += f" Retry after {retry_after} seconds."
        super().__init__(
            message=msg,
            code="MODEL_RATE_LIMIT_ERROR",
            status_code=429,
            details=details,
        )


class ModelTimeoutError(ModelGatewayError):
    """Raised when a model API invocation exceeds configured timeout."""

    def __init__(
        self,
        provider: str,
        timeout_seconds: float,
        details: Any | None = None,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        super().__init__(
            message=f"Model request to provider '{provider}' timed out after {timeout_seconds} seconds.",
            code="MODEL_TIMEOUT_ERROR",
            status_code=504,
            details=details,
        )


class ModelAuthenticationError(ModelGatewayError):
    """Raised when model provider rejects authentication or API key is missing."""

    def __init__(self, provider: str, details: Any | None = None) -> None:
        super().__init__(
            message=f"Authentication failed for model provider '{provider}'. Check credentials.",
            code="MODEL_AUTHENTICATION_ERROR",
            status_code=401,
            details=details,
        )


class ModelFallbackExhaustedError(ModelGatewayError):
    """Raised when all primary and fallback model providers have failed."""

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(
            message=message,
            code="MODEL_FALLBACK_EXHAUSTED",
            status_code=502,
            details=details,
        )


class NoEligibleProviderError(ModelGatewayError):
    """Raised when no provider meets policy, quota, or budget constraints."""

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(
            message=message,
            code="NO_ELIGIBLE_PROVIDER",
            status_code=503,
            details=details,
        )


__all__ = [
    "ModelAuthenticationError",
    "ModelBudgetExceededError",
    "ModelBudgetReservationError",
    "ModelFallbackExhaustedError",
    "ModelGatewayError",
    "ModelPolicyViolationError",
    "ModelProviderUnavailableError",
    "ModelRateLimitError",
    "ModelTimeoutError",
    "NoEligibleProviderError",
]
