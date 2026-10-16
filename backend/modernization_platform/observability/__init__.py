"""OpenTelemetry and metrics instrumentation extension boundary."""

from modernization_platform.observability.metrics import (
    MetricsRegistry,
    default_metrics_registry,
)
from modernization_platform.observability.telemetry import (
    get_tracer,
    trace_async_span,
    trace_gate_wait,
    trace_model_call,
    trace_provider_request,
    trace_span,
)

__all__ = [
    "MetricsRegistry",
    "default_metrics_registry",
    "get_tracer",
    "trace_async_span",
    "trace_gate_wait",
    "trace_model_call",
    "trace_provider_request",
    "trace_span",
]
