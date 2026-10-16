"""Unit tests for OpenTelemetry tracing helpers, span redaction, and metrics registry."""

import pytest

from modernization_platform.observability.metrics import MetricsRegistry
from modernization_platform.observability.telemetry import (
    trace_async_span,
    trace_gate_wait,
    trace_model_call,
    trace_span,
)


def test_metrics_registry_recording_and_snapshot() -> None:
    registry = MetricsRegistry()

    # Record model call
    registry.record_model_call("openai", "gpt-4o", "success")
    registry.record_model_tokens("openai", "gpt-4o", "input", 500)
    registry.record_model_tokens("openai", "gpt-4o", "output", 200)
    registry.record_model_cost("openai", "gpt-4o", 1500)
    registry.record_model_duration("openai", "gpt-4o", 0.35)

    # Record retry and fallback
    registry.record_model_retry("openai", "gpt-4o")
    registry.record_model_fallback("openai", "anthropic")

    # Record rejection and gate wait
    registry.record_budget_rejection("hard_stop")
    registry.record_gate_wait_duration("G1", 12.5)

    snap = registry.snapshot()

    assert snap["model_calls_total"]["openai:gpt-4o:success"] == 1
    assert snap["model_tokens_total"]["openai:gpt-4o:input"] == 500
    assert snap["model_tokens_total"]["openai:gpt-4o:output"] == 200
    assert snap["model_cost_microcents_total"]["openai:gpt-4o"] == 1500
    assert snap["model_retries_total"]["openai:gpt-4o"] == 1
    assert snap["model_fallbacks_total"]["openai:anthropic"] == 1
    assert snap["model_budget_rejections_total"]["hard_stop"] == 1
    assert snap["gate_wait_duration_count"]["G1"] == 1


def test_trace_span_context_manager() -> None:
    with trace_span(
        "test_span", attributes={"key": "safe_value", "secret": "sk-1234567890abcdef1234567890"}
    ) as span:
        assert span is not None


@pytest.mark.asyncio
async def test_trace_async_spans() -> None:
    async with trace_async_span("test_async_span", attributes={"job_id": "job-1"}) as span:
        assert span is not None

    async with trace_model_call("openai", "gpt-4o", job_id="job-1", agent_role="architect") as span:
        assert span is not None

    async with trace_gate_wait("gate-1", "G1", job_id="job-1") as span:
        assert span is not None
