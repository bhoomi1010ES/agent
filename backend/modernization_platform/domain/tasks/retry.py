"""Retry policy and failure classification for durable background tasks."""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, OperationalError

from modernization_platform.core.decorators import log_errors
from modernization_platform.core.exceptions import (
    ConfigError,
    PersistenceError,
    PolicyViolation,
    ValidationFailure,
)
from modernization_platform.domain.tasks.states import TaskFailureClassification
from modernization_platform.workflows.errors import CheckpointError

logger = logging.getLogger(__name__)

# Error types considered transient infrastructure faults
TRANSIENT_INFRASTRUCTURE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    asyncio.TimeoutError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    OperationalError,
    DBAPIError,
    CheckpointError,
    PersistenceError,
)

# Error types considered deterministic / non-retryable domain faults
PERMANENT_DOMAIN_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    ValidationFailure,
    ConfigError,
    PolicyViolation,
)


@log_errors
def classify_exception(exc: BaseException) -> TaskFailureClassification:
    """Classify an exception into retryable infrastructure error or permanent failure."""
    try:
        if isinstance(exc, asyncio.CancelledError):
            return TaskFailureClassification.CANCELLATION

        from modernization_platform.domain.model_gateway.errors import (
            ModelAuthenticationError,
            ModelBudgetExceededError,
            ModelPolicyViolationError,
            ModelProviderUnavailableError,
            ModelRateLimitError,
            ModelTimeoutError,
        )

        if isinstance(
            exc,
            (ModelBudgetExceededError, ModelPolicyViolationError, ModelAuthenticationError),
        ):
            return TaskFailureClassification.PERMANENT_FAILURE

        if isinstance(
            exc,
            (ModelProviderUnavailableError, ModelRateLimitError, ModelTimeoutError),
        ):
            return TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR

        if isinstance(exc, TRANSIENT_INFRASTRUCTURE_EXCEPTIONS):
            return TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR

        if isinstance(exc, PERMANENT_DOMAIN_EXCEPTIONS):
            return TaskFailureClassification.PERMANENT_FAILURE

        # Inspect cause if exception is chained
        if exc.__cause__ is not None:
            if isinstance(exc.__cause__, TRANSIENT_INFRASTRUCTURE_EXCEPTIONS):
                return TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
            if isinstance(exc.__cause__, PERMANENT_DOMAIN_EXCEPTIONS):
                return TaskFailureClassification.PERMANENT_FAILURE

        # Default to permanent failure to prevent unbounded retries of unknown logic bugs
        return TaskFailureClassification.PERMANENT_FAILURE
    except Exception as err:
        logger.exception("classify_exception failed | %s: %s", type(err).__name__, err)
        return TaskFailureClassification.PERMANENT_FAILURE


@log_errors
def calculate_backoff(
    attempt_count: int,
    base_backoff_seconds: float = 5.0,
    max_backoff_seconds: float = 300.0,
) -> float:
    """Calculate exponential retry backoff interval in seconds."""
    try:
        exponent = max(0, attempt_count - 1)
        delay = base_backoff_seconds * (2**exponent)
        return float(min(delay, max_backoff_seconds))
    except Exception as exc:
        logger.exception("calculate_backoff failed | %s: %s", type(exc).__name__, exc)
        return base_backoff_seconds


@log_errors
def should_retry(
    attempt_count: int,
    max_attempts: int,
    classification: TaskFailureClassification,
) -> bool:
    """Determine whether a failed task is eligible for another execution attempt."""
    try:
        if classification != TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR:
            return False
        return attempt_count < max_attempts
    except Exception as exc:
        logger.exception("should_retry evaluation failed | %s: %s", type(exc).__name__, exc)
        return False


@dataclass(frozen=True)
class TaskRetryPolicy:
    """Configurable retry policy governing durable background tasks."""

    max_attempts: int = 3
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0

    @log_errors
    def evaluate(
        self, attempt_count: int, exc: BaseException
    ) -> tuple[bool, TaskFailureClassification, float]:
        """Evaluate an exception and return (can_retry, classification, backoff_seconds)."""
        try:
            classification = classify_exception(exc)
            retry_eligible = should_retry(
                attempt_count=attempt_count,
                max_attempts=self.max_attempts,
                classification=classification,
            )
            backoff = (
                calculate_backoff(
                    attempt_count=attempt_count,
                    base_backoff_seconds=self.base_backoff_seconds,
                    max_backoff_seconds=self.max_backoff_seconds,
                )
                if retry_eligible
                else 0.0
            )
            return retry_eligible, classification, backoff
        except Exception as eval_exc:
            logger.exception(
                "TaskRetryPolicy.evaluate failed | %s: %s", type(eval_exc).__name__, eval_exc
            )
            raise

    @log_errors
    def get_backoff_seconds(self, attempt_count: int) -> float:
        """Calculate retry backoff for a given attempt count."""
        try:
            return calculate_backoff(
                attempt_count=attempt_count,
                base_backoff_seconds=self.base_backoff_seconds,
                max_backoff_seconds=self.max_backoff_seconds,
            )
        except Exception as exc:
            logger.exception(
                "TaskRetryPolicy.get_backoff_seconds failed | %s: %s", type(exc).__name__, exc
            )
            return self.base_backoff_seconds


__all__ = [
    "TaskRetryPolicy",
    "calculate_backoff",
    "classify_exception",
    "should_retry",
]
