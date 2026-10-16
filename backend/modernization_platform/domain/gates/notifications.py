"""Internal event and notification hook abstractions for human approval gates."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)


class GateNotificationType(StrEnum):
    """Event types emitted during gate lifecycle transitions."""

    GATE_CREATED = "gate_created"
    GATE_REMINDER_DUE = "gate_reminder_due"
    GATE_APPROVED = "gate_approved"
    GATE_REJECTED = "gate_rejected"
    GATE_PAUSED = "gate_paused"
    GATE_RESUMED = "gate_resumed"


@dataclass(frozen=True)
class GateNotificationEvent:
    """Structured immutable event payload for gate lifecycle notifications."""

    event_type: GateNotificationType
    gate_id: uuid.UUID
    job_id: uuid.UUID
    gate_type: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)


GateNotificationHook = Callable[[GateNotificationEvent], Awaitable[None]]


class GateNotificationDispatcher:
    """Thread-safe in-process notification dispatcher for gate events."""

    def __init__(self) -> None:
        self._hooks: list[GateNotificationHook] = []

    @log_errors
    def register_hook(self, hook: GateNotificationHook) -> None:
        """Register an async notification hook."""
        try:
            self._hooks.append(hook)
        except Exception as exc:
            logger.exception("register_hook failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def dispatch(self, event: GateNotificationEvent) -> None:
        """Dispatch a gate event to all registered notification hooks."""
        logger.info(
            "Dispatching gate notification event: %s for gate=%s job=%s",
            event.event_type.value,
            event.gate_id,
            event.job_id,
        )
        for hook in self._hooks:
            try:
                await hook(event)
            except Exception as exc:
                logger.error(
                    "Error executing gate notification hook: %s | %s",
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )


# Global singleton dispatcher instance
default_gate_dispatcher = GateNotificationDispatcher()


__all__ = [
    "GateNotificationDispatcher",
    "GateNotificationEvent",
    "GateNotificationHook",
    "GateNotificationType",
    "default_gate_dispatcher",
]
