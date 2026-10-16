"""Unit tests for retry classifications, error classification, and fallback routing."""

from modernization_platform.domain.model_gateway.errors import (
    ModelAuthenticationError,
    ModelBudgetExceededError,
    ModelPolicyViolationError,
    ModelProviderUnavailableError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from modernization_platform.domain.tasks.retry import (
    classify_exception,
)
from modernization_platform.domain.tasks.states import (
    TaskFailureClassification,
)
from modernization_platform.services.model_gateway.gateway_service import (
    is_retryable_error,
)


def test_retryable_errors_classification() -> None:
    # Rate limits, timeouts, connection resets, 503s are retryable
    assert is_retryable_error(ModelRateLimitError("openai", retry_after=5.0)) is True
    assert is_retryable_error(ModelTimeoutError("anthropic", 30.0)) is True
    assert (
        is_retryable_error(ModelProviderUnavailableError("qwen", "503 Service Unavailable")) is True
    )
    assert is_retryable_error(RuntimeError("HTTP 429 Too Many Requests")) is True
    assert is_retryable_error(ConnectionResetError("Connection reset by peer")) is True


def test_non_retryable_errors_classification() -> None:
    # Auth, budget, policy violations are strictly non-retryable
    assert is_retryable_error(ModelAuthenticationError("openai")) is False
    assert is_retryable_error(ModelPolicyViolationError("Model not allowed")) is False
    assert (
        is_retryable_error(
            ModelBudgetExceededError(
                scope="job:1",
                limit_cents=100.0,
                current_cents=100.0,
                estimated_cents=1.0,
            )
        )
        is False
    )


def test_task_exception_classification_for_model_gateway() -> None:
    # Permanent domain failures for tasks
    budget_err = ModelBudgetExceededError(
        scope="job:1",
        limit_cents=50.0,
        current_cents=50.0,
        estimated_cents=10.0,
    )
    assert classify_exception(budget_err) == TaskFailureClassification.PERMANENT_FAILURE

    policy_err = ModelPolicyViolationError("Policy check failed")
    assert classify_exception(policy_err) == TaskFailureClassification.PERMANENT_FAILURE

    auth_err = ModelAuthenticationError("openai")
    assert classify_exception(auth_err) == TaskFailureClassification.PERMANENT_FAILURE

    # Retryable infrastructure failures for tasks
    timeout_err = ModelTimeoutError("openai", 10.0)
    assert (
        classify_exception(timeout_err) == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    )

    rate_err = ModelRateLimitError("anthropic")
    assert classify_exception(rate_err) == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
