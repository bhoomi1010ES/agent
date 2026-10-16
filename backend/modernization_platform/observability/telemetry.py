"""OpenTelemetry tracing helpers and spans for Model Gateway and Workflows."""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.redaction import redact_data, redact_string

logger = logging.getLogger(__name__)

TRACER_NAME = "modernization_platform.model_gateway"


@log_errors
def get_tracer() -> trace.Tracer:
    """Return the platform OpenTelemetry tracer."""
    return trace.get_tracer(TRACER_NAME)


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """Synchronous context manager for an OpenTelemetry span with automatic secret redaction."""
    try:
        tracer = get_tracer()
        safe_attrs: dict[str, Any] = {}
        if attributes:
            try:
                redacted = redact_data(attributes)
                if isinstance(redacted, dict):
                    for k, v in redacted.items():
                        if isinstance(v, (str, int, float, bool)):
                            safe_attrs[k] = v
                        else:
                            safe_attrs[k] = redact_string(str(v))
            except Exception as exc:
                logger.warning("Failed to redact span attributes for %s: %s", name, exc)

        with tracer.start_as_current_span(name, attributes=safe_attrs) as span:
            try:
                yield span
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, description=redact_string(str(exc))))
                span.record_exception(exc)
                raise
    except Exception:
        raise


@asynccontextmanager
async def trace_async_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[trace.Span]:
    """Asynchronous context manager for an OpenTelemetry span with automatic secret redaction."""
    try:
        tracer = get_tracer()
        safe_attrs: dict[str, Any] = {}
        if attributes:
            try:
                redacted = redact_data(attributes)
                if isinstance(redacted, dict):
                    for k, v in redacted.items():
                        if isinstance(v, (str, int, float, bool)):
                            safe_attrs[k] = v
                        else:
                            safe_attrs[k] = redact_string(str(v))
            except Exception as exc:
                logger.warning("Failed to redact span attributes for %s: %s", name, exc)

        with tracer.start_as_current_span(name, attributes=safe_attrs) as span:
            try:
                yield span
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, description=redact_string(str(exc))))
                span.record_exception(exc)
                raise
    except Exception:
        raise


@asynccontextmanager
async def trace_model_call(
    provider: str,
    model_id: str,
    job_id: str | None = None,
    task_id: str | None = None,
    agent_role: str | None = None,
    correlation_id: str | None = None,
) -> AsyncIterator[trace.Span]:
    """Specialized trace span for a model gateway invocation."""
    try:
        attrs: dict[str, Any] = {
            "model.provider": provider,
            "model.id": model_id,
        }
        if job_id:
            attrs["job.id"] = job_id
        if task_id:
            attrs["task.id"] = task_id
        if agent_role:
            attrs["agent.role"] = agent_role
        if correlation_id:
            attrs["correlation.id"] = correlation_id

        async with trace_async_span(f"model_call:{provider}:{model_id}", attributes=attrs) as span:
            yield span
    except Exception:
        raise


@asynccontextmanager
async def trace_provider_request(
    provider: str,
    model_id: str,
) -> AsyncIterator[trace.Span]:
    """Specialized trace span for an outbound provider request."""
    try:
        attrs = {
            "model.provider": provider,
            "model.id": model_id,
            "span.kind": "client",
        }
        async with trace_async_span(f"provider_request:{provider}", attributes=attrs) as span:
            yield span
    except Exception:
        raise


@asynccontextmanager
async def trace_gate_wait(
    gate_id: str,
    gate_type: str,
    job_id: str | None = None,
) -> AsyncIterator[trace.Span]:
    """Trace span for waiting on a human gate decision."""
    try:
        attrs: dict[str, Any] = {
            "gate.id": gate_id,
            "gate.type": gate_type,
        }
        if job_id:
            attrs["job.id"] = job_id

        async with trace_async_span(f"gate_wait:{gate_type}", attributes=attrs) as span:
            yield span
    except Exception:
        raise


__all__ = [
    "get_tracer",
    "trace_async_span",
    "trace_gate_wait",
    "trace_model_call",
    "trace_provider_request",
    "trace_span",
]
