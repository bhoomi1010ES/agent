"""Typed domain exceptions for LangGraph workflow orchestration and checkpointing."""

from modernization_platform.core.exceptions import ApplicationException


class WorkflowError(ApplicationException):
    """Base exception for all workflow orchestration and checkpoint failures."""

    def __init__(
        self,
        message: str = "A workflow orchestration error occurred.",
        code: str = "WORKFLOW_ERROR",
        status_code: int = 500,
        details: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details,
        )


class WorkflowExecutionError(WorkflowError):
    """Raised when graph execution fails unexpectedly during node processing."""

    def __init__(
        self,
        message: str,
        step: str | None = None,
        job_id: str | None = None,
    ) -> None:
        details: dict[str, str] = {}
        if step:
            details["step"] = step
        if job_id:
            details["job_id"] = str(job_id)
        super().__init__(
            message=message,
            code="WORKFLOW_EXECUTION_ERROR",
            status_code=500,
            details=details or None,
        )


class WorkflowStateError(WorkflowError):
    """Raised when workflow state is corrupted, missing required fields, or illegal."""

    def __init__(
        self,
        message: str,
        job_id: str | None = None,
    ) -> None:
        details = {"job_id": str(job_id)} if job_id else None
        super().__init__(
            message=message,
            code="WORKFLOW_STATE_ERROR",
            status_code=400,
            details=details,
        )


class WorkflowInterrupted(WorkflowError):
    """Informational exception or signal when a workflow pauses for approval or cooperation."""

    def __init__(
        self,
        message: str = "Workflow execution interrupted pending decision or action.",
        gate_type: str | None = None,
        job_id: str | None = None,
    ) -> None:
        details: dict[str, str] = {}
        if gate_type:
            details["gate_type"] = gate_type
        if job_id:
            details["job_id"] = str(job_id)
        super().__init__(
            message=message,
            code="WORKFLOW_INTERRUPTED",
            status_code=200,
            details=details or None,
        )


class CheckpointError(WorkflowError):
    """Raised when checkpoint serialization, write, or retrieval fails."""

    def __init__(
        self,
        message: str,
        thread_id: str | None = None,
    ) -> None:
        details = {"thread_id": str(thread_id)} if thread_id else None
        super().__init__(
            message=message,
            code="CHECKPOINT_ERROR",
            status_code=500,
            details=details,
        )


class IdempotencyViolationError(WorkflowError):
    """Raised when a non-idempotent side effect is re-attempted conflicting with a prior run."""

    def __init__(
        self,
        step: str,
        key: str,
    ) -> None:
        super().__init__(
            message=f"Idempotency conflict for step '{step}' with key '{key}'.",
            code="IDEMPOTENCY_VIOLATION",
            status_code=409,
            details={"step": step, "idempotency_key": key},
        )


__all__ = [
    "CheckpointError",
    "IdempotencyViolationError",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowInterrupted",
    "WorkflowStateError",
]
