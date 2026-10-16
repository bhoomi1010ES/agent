"""Authoritative state machine transition rules and completion guard for modernization jobs."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.jobs.errors import (
    InvalidStateTransitionError,
    JobCompletionBlockedError,
    TerminalJobMutationError,
)
from modernization_platform.domain.jobs.states import (
    TERMINAL_STATES,
    FailureClassification,
    JobLifecycleState,
)

logger = logging.getLogger(__name__)

# Single authoritative transition matrix for job lifecycle
LEGAL_TRANSITIONS: dict[JobLifecycleState, frozenset[JobLifecycleState]] = {
    JobLifecycleState.QUEUED: frozenset(
        {
            JobLifecycleState.RUNNING,
            JobLifecycleState.CANCELLED,
        }
    ),
    JobLifecycleState.RUNNING: frozenset(
        {
            JobLifecycleState.AWAITING_APPROVAL,
            JobLifecycleState.PAUSED,
            JobLifecycleState.FAILED,
            JobLifecycleState.CANCELLED,
            JobLifecycleState.COMPLETED,
        }
    ),
    JobLifecycleState.PAUSED: frozenset(
        {
            JobLifecycleState.RUNNING,
            JobLifecycleState.CANCELLED,
        }
    ),
    JobLifecycleState.AWAITING_APPROVAL: frozenset(
        {
            JobLifecycleState.RUNNING,
            JobLifecycleState.CANCELLED,
            JobLifecycleState.FAILED,
        }
    ),
    JobLifecycleState.FAILED: frozenset(
        {
            JobLifecycleState.RUNNING,
        }
    ),
    JobLifecycleState.COMPLETED: frozenset(),
    JobLifecycleState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class CompletionCheckResult:
    """Result of a completion guard evaluation."""

    allowed: bool
    reason: str | None = None


class CompletionGuard:
    """Domain guard verifying that all prerequisite stages and conditions are satisfied."""

    # Default canonical stages required before a job can transition to completed
    DEFAULT_REQUIRED_STAGES: tuple[str, ...] = (
        "intake",
        "analysis",
        "architecture",
        "conversion",
        "verification",
    )

    @classmethod
    @log_errors
    def can_complete(
        cls,
        job: Any,
        completed_stages: Sequence[str] | None = None,
        required_stages: Sequence[str] | None = None,
        has_pending_gates: bool = False,
        current_stage: str | None = None,
    ) -> CompletionCheckResult:
        """Evaluate whether the given job is eligible to transition to COMPLETED."""
        try:
            status = getattr(job, "status", None)
            if status is not None:
                # Normalize legacy pending status
                normalized_status = (
                    JobLifecycleState.QUEUED if status == "pending" else JobLifecycleState(status)
                )
                if normalized_status in TERMINAL_STATES:
                    return CompletionCheckResult(
                        allowed=False,
                        reason=f"Job is already in terminal state '{normalized_status.value}'.",
                    )
                if normalized_status != JobLifecycleState.RUNNING:
                    return CompletionCheckResult(
                        allowed=False,
                        reason=f"Job must be in '{JobLifecycleState.RUNNING.value}' state to complete; current state is '{normalized_status.value}'.",
                    )

            if has_pending_gates:
                return CompletionCheckResult(
                    allowed=False,
                    reason="Job cannot complete while human approval gates remain pending.",
                )

            # If stage tracking is provided, check prerequisite stages
            reqs = required_stages if required_stages is not None else cls.DEFAULT_REQUIRED_STAGES
            if reqs and completed_stages is not None:
                completed_set = set(completed_stages)
                missing = [stage for stage in reqs if stage not in completed_set]
                if missing:
                    return CompletionCheckResult(
                        allowed=False,
                        reason=f"Required stages remain incomplete: {', '.join(missing)}.",
                    )

            # Check effective current_stage if available
            eff_current_stage = (
                current_stage if current_stage is not None else getattr(job, "current_stage", None)
            )
            if eff_current_stage is not None and reqs:
                terminal_stage = reqs[-1]
                if eff_current_stage != terminal_stage:
                    return CompletionCheckResult(
                        allowed=False,
                        reason=f"Current stage is '{eff_current_stage}', but required terminal stage is '{terminal_stage}'.",
                    )

            return CompletionCheckResult(allowed=True, reason=None)
        except Exception as exc:
            logger.exception(
                "CompletionGuard.can_complete failed | %s: %s", type(exc).__name__, exc
            )
            raise


@log_errors
def normalize_state(state: JobLifecycleState | str) -> JobLifecycleState:
    """Normalize state representation, mapping legacy 'pending' to QUEUED."""
    try:
        if isinstance(state, JobLifecycleState):
            return state
        if state == "pending":
            return JobLifecycleState.QUEUED
        return JobLifecycleState(state)
    except ValueError as exc:
        raise InvalidStateTransitionError(
            from_state=str(state),
            to_state="unknown",
            reason=f"Unrecognized lifecycle state: '{state}'",
        ) from exc


@log_errors
def validate_transition(
    current_state: JobLifecycleState | str,
    target_state: JobLifecycleState | str,
    *,
    failure_classification: FailureClassification | str | None = None,
    is_retry: bool = False,
    guard_result: CompletionCheckResult | None = None,
) -> tuple[JobLifecycleState, JobLifecycleState]:
    """Validate whether transitioning from current_state to target_state is permitted.

    Returns the normalized (current, target) states if valid, otherwise raises a typed domain error.
    """
    try:
        from_state = normalize_state(current_state)
        to_state = normalize_state(target_state)

        # 1. Terminal state check: terminal states can never be mutated
        if from_state in TERMINAL_STATES:
            logger.warning(
                "Attempted illegal transition from terminal state | from_state=%s target_state=%s",
                from_state.value,
                to_state.value,
            )
            raise TerminalJobMutationError(from_state.value)

        # 2. Check transition matrix
        allowed_targets = LEGAL_TRANSITIONS.get(from_state, frozenset())
        if to_state not in allowed_targets:
            logger.warning(
                "Illegal lifecycle state transition attempted | from_state=%s target_state=%s",
                from_state.value,
                to_state.value,
            )
            raise InvalidStateTransitionError(
                from_state=from_state.value,
                to_state=to_state.value,
                reason=f"Transition from '{from_state.value}' to '{to_state.value}' is not allowed.",
            )

        # 3. Retry semantics for FAILED -> RUNNING
        if from_state == JobLifecycleState.FAILED and to_state == JobLifecycleState.RUNNING:
            is_transient = (
                failure_classification == FailureClassification.TRANSIENT
                or failure_classification == "transient"
            )
            if not is_transient and not is_retry:
                logger.warning(
                    "Transition from FAILED to RUNNING blocked for non-transient failure without explicit retry",
                )
                raise InvalidStateTransitionError(
                    from_state=from_state.value,
                    to_state=to_state.value,
                    reason="Jobs with terminal failures cannot be resumed without explicit retry authorization.",
                )

        # 4. Completion guard check for RUNNING -> COMPLETED
        if (
            to_state == JobLifecycleState.COMPLETED
            and guard_result is not None
            and not guard_result.allowed
        ):
            reason = guard_result.reason or "Prerequisite stages incomplete."
            logger.warning(
                "Transition to COMPLETED blocked by completion guard | reason=%s", reason
            )
            raise JobCompletionBlockedError(reason)

        return from_state, to_state
    except (InvalidStateTransitionError, TerminalJobMutationError, JobCompletionBlockedError):
        raise
    except Exception as exc:
        logger.exception("validate_transition failed | %s: %s", type(exc).__name__, exc)
        raise


__all__ = [
    "LEGAL_TRANSITIONS",
    "CompletionCheckResult",
    "CompletionGuard",
    "normalize_state",
    "validate_transition",
]
