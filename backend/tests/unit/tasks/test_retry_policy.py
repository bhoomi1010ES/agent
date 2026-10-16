"""Unit tests for task retry policies and failure classification."""

import asyncio

from sqlalchemy.exc import OperationalError

from modernization_platform.core.exceptions import (
    PersistenceError,
    PolicyViolation,
    ValidationFailure,
)
from modernization_platform.domain.tasks.retry import (
    TaskRetryPolicy,
    calculate_backoff,
    classify_exception,
    should_retry,
)
from modernization_platform.domain.tasks.states import TaskFailureClassification
from modernization_platform.workflows.errors import CheckpointError


def test_classify_transient_infrastructure_exceptions() -> None:
    """Transient network, database, and checkpoint errors are classified as retryable."""
    assert (
        classify_exception(TimeoutError("Connection timed out"))
        == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    )
    assert (
        classify_exception(ConnectionResetError("Peer reset"))
        == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    )
    assert (
        classify_exception(OperationalError("stmt", {}, Exception("DB down")))
        == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    )
    assert (
        classify_exception(CheckpointError("Write failed"))
        == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    )
    assert (
        classify_exception(PersistenceError("Deadlock detected"))
        == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    )


def test_classify_permanent_domain_exceptions() -> None:
    """Validation, type, key, and policy errors are classified as permanent failures."""
    assert (
        classify_exception(ValueError("Invalid argument"))
        == TaskFailureClassification.PERMANENT_FAILURE
    )
    assert (
        classify_exception(KeyError("missing_field")) == TaskFailureClassification.PERMANENT_FAILURE
    )
    assert (
        classify_exception(ValidationFailure("Payload schema mismatch"))
        == TaskFailureClassification.PERMANENT_FAILURE
    )
    assert (
        classify_exception(PolicyViolation("Unauthorized action"))
        == TaskFailureClassification.PERMANENT_FAILURE
    )


def test_classify_cancellation() -> None:
    """CancelledError is classified as cancellation."""
    assert classify_exception(asyncio.CancelledError()) == TaskFailureClassification.CANCELLATION


def test_classify_chained_exceptions() -> None:
    """Chained cause is inspected when primary exception is generic."""
    cause = ConnectionRefusedError("Port unreachable")
    wrapper = RuntimeError("Task execution wrapper failed")
    wrapper.__cause__ = cause

    assert classify_exception(wrapper) == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR

    val_cause = ValueError("Schema invalid")
    val_wrapper = RuntimeError("Execution error")
    val_wrapper.__cause__ = val_cause

    assert classify_exception(val_wrapper) == TaskFailureClassification.PERMANENT_FAILURE


def test_classify_unknown_exception_defaults_to_permanent() -> None:
    """Unknown exception defaults to permanent failure to prevent unbounded retry loops."""

    class CustomUnknownException(Exception):
        pass

    assert (
        classify_exception(CustomUnknownException("unexpected"))
        == TaskFailureClassification.PERMANENT_FAILURE
    )


def test_calculate_backoff_exponential() -> None:
    """Exponential backoff doubles per attempt and is bounded by max_backoff_seconds."""
    assert (
        calculate_backoff(attempt_count=1, base_backoff_seconds=5.0, max_backoff_seconds=60.0)
        == 5.0
    )
    assert (
        calculate_backoff(attempt_count=2, base_backoff_seconds=5.0, max_backoff_seconds=60.0)
        == 10.0
    )
    assert (
        calculate_backoff(attempt_count=3, base_backoff_seconds=5.0, max_backoff_seconds=60.0)
        == 20.0
    )
    assert (
        calculate_backoff(attempt_count=4, base_backoff_seconds=5.0, max_backoff_seconds=60.0)
        == 40.0
    )
    # Capped at max 60.0
    assert (
        calculate_backoff(attempt_count=5, base_backoff_seconds=5.0, max_backoff_seconds=60.0)
        == 60.0
    )
    assert (
        calculate_backoff(attempt_count=10, base_backoff_seconds=5.0, max_backoff_seconds=60.0)
        == 60.0
    )


def test_should_retry_bounds() -> None:
    """Only retryable errors below max_attempts are eligible for retry."""
    assert (
        should_retry(
            attempt_count=1,
            max_attempts=3,
            classification=TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR,
        )
        is True
    )
    assert (
        should_retry(
            attempt_count=2,
            max_attempts=3,
            classification=TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR,
        )
        is True
    )
    # At max attempts, cannot retry
    assert (
        should_retry(
            attempt_count=3,
            max_attempts=3,
            classification=TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR,
        )
        is False
    )
    # Permanent failure cannot retry even on first attempt
    assert (
        should_retry(
            attempt_count=1,
            max_attempts=3,
            classification=TaskFailureClassification.PERMANENT_FAILURE,
        )
        is False
    )


def test_task_retry_policy_evaluate() -> None:
    """TaskRetryPolicy.evaluate integrates classification, eligibility, and backoff."""
    policy = TaskRetryPolicy(max_attempts=3, base_backoff_seconds=4.0, max_backoff_seconds=100.0)

    # Transient error attempt 1
    can_retry, classification, delay = policy.evaluate(1, ConnectionError("drop"))
    assert can_retry is True
    assert classification == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    assert delay == 4.0

    # Transient error attempt 3 (exhausted)
    can_retry, classification, delay = policy.evaluate(3, ConnectionError("drop"))
    assert can_retry is False
    assert classification == TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR
    assert delay == 0.0

    # Permanent error attempt 1
    can_retry, classification, delay = policy.evaluate(1, ValueError("bad"))
    assert can_retry is False
    assert classification == TaskFailureClassification.PERMANENT_FAILURE
    assert delay == 0.0

    # Helper method
    assert policy.get_backoff_seconds(1) == 4.0
    assert policy.get_backoff_seconds(2) == 8.0
