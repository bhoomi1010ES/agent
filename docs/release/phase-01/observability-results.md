# Phase 1 Release Evidence: Observability & Telemetry Validation

## 1. Unified Correlation Chain

Every action across the modernization platform carries a consistent correlation identifier propagated across network, background task, and database boundaries:

```text
HTTP Request (X-Correlation-ID)
      ↓
Job Lifecycle State
      ↓
LangGraph Workflow Thread
      ↓
Durable Task (correlation_id)
      ↓
Worker Execution Lease
      ↓
Agent Run Telemetry
      ↓
Model Gateway Invocation
      ↓
Provider API Request (Outbound Span)
      ↓
Artifact Generation (SHA-256)
      ↓
Human Gate Review (artifact_version_refs)
      ↓
Append-Only Decision
      ↓
Immutable Audit Event
```

---

## 2. Distributed Tracing (OpenTelemetry)

- **Tracer**: OpenTelemetry Tracer (`modernization_platform.telemetry.tracing`).
- **Standard Span Hierarchy**:
  - `gateway.generate`: Root model gateway span capturing `provider`, `model_id`, `agent_role`, `stage`.
  - `provider.request`: Outbound HTTP/SDK provider call capturing network latency and status.
  - `workflow.node`: LangGraph node execution span capturing state diffs.
  - `task.execute`: Worker background task execution span.
- **Span Redaction Verification**:
  - Provider authorization tokens (`Bearer sk-...`) and passwords are automatically stripped or masked in span attributes.
  - Test `test_secrets_never_leak_in_telemetry_spans` verified that raw secrets never appear in OpenTelemetry span events.

---

## 3. Structured Logging

- **Format**: JSON-formatted structured logging via `python-json-logger`.
- **Standard Attributes**:
  ```json
  {
    "timestamp": "2026-10-16T12:20:00Z",
    "level": "INFO",
    "logger": "modernization_platform.services.model_gateway",
    "message": "Model execution succeeded | provider=mock model=mock-model cost=250000 microcents",
    "correlation_id": "corr-job-12345",
    "job_id": "dceaef02-8b59-45f5-bc78-ae9ec3989ae5",
    "agent_role": "architect",
    "duration_ms": 42
  }
  ```

---

## 4. Platform Metrics

- **Metrics Registry**: `default_metrics_registry` (`modernization_platform.observability.metrics`).
- **Key Metrics Tracked**:
  - `model_calls_total{provider, model, status}`: Counter for model generations.
  - `model_tokens_total{provider, model, type}`: Counter for input, output, and total tokens consumed.
  - `model_cost_microcents_total{provider, model}`: Counter for reconciled financial spend.
  - `model_duration_seconds{provider, model}`: Histogram for call latency.
  - `model_retries_total{provider, model}`: Counter for transient retries.
  - `model_fallbacks_total{from_provider, to_provider}`: Counter for fallback routing events.
  - `budget_warnings_total{job_id, threshold}`: Counter for budget threshold breaches.
  - `gate_wait_duration_seconds{gate_type}`: Histogram for human approval wait times.
