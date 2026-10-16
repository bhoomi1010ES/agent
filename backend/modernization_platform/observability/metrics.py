"""Metrics collectors and registry for Model Gateway and Observability."""

import logging
from collections import defaultdict
from threading import Lock
from typing import Any

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)


class MetricsRegistry:
    """Thread-safe in-memory metrics registry for model gateway and workflow telemetry.

    Adheres strictly to low-cardinality label rules (no prompt text, user IDs,
    or high-cardinality request IDs).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    @log_errors
    def reset(self) -> None:
        """Reset all in-memory counters and metric distributions."""
        with self._lock:
            self.model_calls_total: dict[tuple[str, str, str], int] = defaultdict(int)
            self.model_call_failures_total: dict[tuple[str, str, str], int] = defaultdict(int)
            self.model_call_duration_seconds: dict[tuple[str, str], list[float]] = defaultdict(list)
            self.model_tokens_total: dict[tuple[str, str, str], int] = defaultdict(int)
            self.model_cost_microcents_total: dict[tuple[str, str], int] = defaultdict(int)
            self.model_retries_total: dict[tuple[str, str], int] = defaultdict(int)
            self.model_fallbacks_total: dict[tuple[str, str], int] = defaultdict(int)
            self.model_rate_limit_total: dict[str, int] = defaultdict(int)
            self.model_budget_rejections_total: dict[str, int] = defaultdict(int)
            self.gate_wait_duration_seconds: dict[str, list[float]] = defaultdict(list)
            self.budget_pauses_total: int = 0
            self.task_failures_total: int = 0
            self.repair_attempts_total: int = 0

    @log_errors
    def record_model_call(self, provider: str, model_id: str, status: str = "success") -> None:
        """Increment model_calls_total counter."""
        with self._lock:
            self.model_calls_total[(provider, model_id, status)] += 1

    @log_errors
    def record_model_failure(self, provider: str, model_id: str, failure_type: str) -> None:
        """Increment model_call_failures_total counter."""
        with self._lock:
            self.model_call_failures_total[(provider, model_id, failure_type)] += 1

    @log_errors
    def record_model_duration(self, provider: str, model_id: str, duration_seconds: float) -> None:
        """Record model call duration in seconds."""
        with self._lock:
            self.model_call_duration_seconds[(provider, model_id)].append(duration_seconds)

    @log_errors
    def record_model_tokens(
        self, provider: str, model_id: str, token_type: str, count: int
    ) -> None:
        """Record token consumption (token_type='input'|'output'|'total')."""
        with self._lock:
            self.model_tokens_total[(provider, model_id, token_type)] += count

    @log_errors
    def record_model_cost(self, provider: str, model_id: str, cost_microcents: int) -> None:
        """Record model execution financial cost in microcents."""
        with self._lock:
            self.model_cost_microcents_total[(provider, model_id)] += cost_microcents

    @log_errors
    def record_model_retry(self, provider: str, model_id: str) -> None:
        """Increment model retry counter."""
        with self._lock:
            self.model_retries_total[(provider, model_id)] += 1

    @log_errors
    def record_model_fallback(self, primary_provider: str, fallback_provider: str) -> None:
        """Increment fallback routing counter."""
        with self._lock:
            self.model_fallbacks_total[(primary_provider, fallback_provider)] += 1

    @log_errors
    def record_model_rate_limit(self, provider: str) -> None:
        """Increment rate limit detection counter."""
        with self._lock:
            self.model_rate_limit_total[provider] += 1

    @log_errors
    def record_budget_rejection(self, reason: str = "hard_stop") -> None:
        """Increment budget rejection counter."""
        with self._lock:
            self.model_budget_rejections_total[reason] += 1

    @log_errors
    def record_gate_wait_duration(self, gate_type: str, duration_seconds: float) -> None:
        """Record gate waiting duration in seconds."""
        with self._lock:
            self.gate_wait_duration_seconds[gate_type].append(duration_seconds)

    @log_errors
    def record_budget_pause(self) -> None:
        """Increment budget pause event counter."""
        with self._lock:
            self.budget_pauses_total += 1

    @log_errors
    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time snapshot of recorded metrics."""
        with self._lock:
            return {
                "model_calls_total": {
                    f"{k[0]}:{k[1]}:{k[2]}": v for k, v in self.model_calls_total.items()
                },
                "model_call_failures_total": {
                    f"{k[0]}:{k[1]}:{k[2]}": v for k, v in self.model_call_failures_total.items()
                },
                "model_tokens_total": {
                    f"{k[0]}:{k[1]}:{k[2]}": v for k, v in self.model_tokens_total.items()
                },
                "model_cost_microcents_total": {
                    f"{k[0]}:{k[1]}": v for k, v in self.model_cost_microcents_total.items()
                },
                "model_retries_total": {
                    f"{k[0]}:{k[1]}": v for k, v in self.model_retries_total.items()
                },
                "model_fallbacks_total": {
                    f"{k[0]}:{k[1]}": v for k, v in self.model_fallbacks_total.items()
                },
                "model_rate_limit_total": dict(self.model_rate_limit_total),
                "model_budget_rejections_total": dict(self.model_budget_rejections_total),
                "gate_wait_duration_count": {
                    k: len(v) for k, v in self.gate_wait_duration_seconds.items()
                },
                "budget_pauses_total": self.budget_pauses_total,
            }


default_metrics_registry = MetricsRegistry()

__all__ = ["MetricsRegistry", "default_metrics_registry"]
