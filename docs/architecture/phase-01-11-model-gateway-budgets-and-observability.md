# Sub-Phase 01.11: Model Gateway, Budgets and Observability

## 1. Overview and Core Philosophy

Sub-Phase 01.11 establishes a provider-neutral, observable, budget-controlled, and audited foundation for hosted Large Language Model (LLM) operations within the Legacy Code Modernization Platform.

**Core Architectural Rule:** Agents never interact directly with external provider SDKs (OpenAI, Anthropic, Qwen, OpenRouter, Azure). All model invocations flow through a centralized, server-side `ModelGateway` interface that strictly validates model policy, checks and atomically reserves budget in PostgreSQL, enforces timeouts and retries, captures spans and metrics, records immutable execution audit trails, and redacts sensitive credentials across all output streams.

```text
Agent
  ↓
Model Gateway
  ↓
Policy Validation (Allowed Provider, Model, Agent)
  ↓
Budget Validation & Atomic Row Reservation (Integer Microcents)
  ↓
Outbound Provider Execution (with Retries & Approved Fallbacks)
  ↓
Usage & Cost Reconciliation (Release Difference / Record Actuals)
  ↓
Observability (OpenTelemetry Spans, Metrics, Audit Events)
  ↓
Agent
```

---

## 2. Architecture & Design Principles

### 2.1 Provider-Neutral Interface

Workflow agents interact with the model gateway using provider-agnostic domain contracts:

```python
class ModelGateway(Protocol):
    async def generate(
        self,
        request: ModelRequest,
        context: ModelExecutionContext,
    ) -> ModelResponse:
        ...
```

- **`ModelRequest`**: Contains prompt messages, requested model ID, temperature, maximum tokens, tool definitions, response format, and metadata.
- **`ModelExecutionContext`**: Contains authoritative execution parameters passed from server-side infrastructure (`job_id`, `task_id`, `workflow_thread_id`, `agent_run_id`, `agent_role`, `stage`, `correlation_id`, `artifact_id`, `artifact_version`).
- **`ModelResponse`**: Returns content, parsed tool calls, finish reason, and exact `UsageMetrics` (input tokens, output tokens, total tokens, actual cost in microcents, duration).

---

## 3. Provider Adapter Pattern

Provider SDK details are isolated behind `BaseProviderAdapter`:

```mermaid
classDiagram
    class BaseProviderAdapter {
        <<interface>>
        +provider_name: str
        +generate(request, context, timeout_seconds) ModelResponse
    }
    class MockProviderAdapter {
        +configure_failure()
        +generate()
    }
    class OpenAIProviderAdapter {
        -client: AsyncOpenAI
        +generate()
    }
    class AnthropicProviderAdapter {
        -client: AsyncAnthropic
        +generate()
    }
    class QwenProviderAdapter {
        -client: AsyncOpenAI
        +generate()
    }
    class OpenRouterProviderAdapter {
        -client: AsyncOpenAI
        +generate()
    }
    BaseProviderAdapter <|-- MockProviderAdapter
    BaseProviderAdapter <|-- OpenAIProviderAdapter
    BaseProviderAdapter <|-- AnthropicProviderAdapter
    BaseProviderAdapter <|-- QwenProviderAdapter
    BaseProviderAdapter <|-- OpenRouterProviderAdapter
```

### Invariants:
1. Business logic never imports or calls `openai`, `anthropic`, or other vendor libraries directly.
2. Provider adapters translate neutral `ModelRequest` into provider-specific payloads and normalize raw responses into standard `ModelResponse` structures.
3. Test suites execute deterministically against `MockProviderAdapter` without requiring live external network access or paid API credentials.

---

## 4. Model Policy & Per-Agent Routing

Model invocations are governed by server-side `ModelPolicy` records registered in `PolicyRegistry`:

| Agent Role | Stage | Allowed Providers | Primary Model | Fallback Target | Max Output Tokens | Timeout |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Architect** | Architecture Planning | `mock`, `anthropic`, `openai`, `qwen` | `mock-model` (prod: `claude-3-7-sonnet`) | `mock-fallback` / `gpt-4o` | 4,096 | 90s |
| **Analyzer** | Extraction & Analysis | `mock`, `qwen`, `openai`, `anthropic` | `mock-model` (prod: `qwen-2.5-coder-32b`) | `mock-fallback` / `gpt-4o` | 4,096 | 60s |
| **Converter** | Code Generation | `mock`, `qwen`, `openai`, `openrouter` | `mock-model` (prod: `qwen-2.5-coder-32b`) | `mock-fallback` / `gpt-4o` | 4,096 | 60s |
| **Reviewer** | Diff & Quality Review | `mock`, `anthropic`, `openai` | `mock-model` (prod: `claude-3-7-sonnet`) | `mock-fallback` / `gpt-4o` | 4,096 | 60s |

### Policy Validation Sequence
Before outbound provider communication:
1. **Is Provider Permitted?** Reject with `ModelPolicyViolationError` if provider is unlisted.
2. **Is Model Permitted?** Reject with `ModelPolicyViolationError` if model is not approved for this policy.
3. **Is Agent Role Permitted?** Reject with `ModelPolicyViolationError` if caller role does not match policy boundary.

---

## 5. Budget Lifecycle & Concurrency-Safe Reservations

Financial limits are tracked in integer microcents ($1.00 USD = 1,000,000 microcents; 1 cent = 10,000 microcents) to eliminate floating-point rounding inaccuracies.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Workflow Agent
    participant Gateway as ModelGatewayService
    participant BudgetRepo as BudgetRepository
    participant DB as PostgreSQL (budget_account)
    participant Provider as Provider Adapter
    
    Agent->>Gateway: generate(request, context)
    Gateway->>Gateway: estimate_cost(input_tokens, max_output_tokens)
    Gateway->>BudgetRepo: reserve_budget(job_id, estimated_microcents)
    BudgetRepo->>DB: SELECT FOR UPDATE (row lock on budget_account)
    Note over BudgetRepo,DB: Check projected_total <= limit_microcents
    Note over BudgetRepo,DB: Check warning threshold (80%)
    BudgetRepo->>DB: UPDATE reserved_microcents += estimated_microcents
    BudgetRepo->>DB: INSERT INTO budget_reservation
    BudgetRepo-->>Gateway: (reservation, should_warn)
    
    alt If should_warn is True
        Gateway->>Gateway: Emit BUDGET_WARNING_80_PERCENT audit event
    end
    
    Gateway->>Provider: adapter.generate(request)
    Provider-->>Gateway: ModelResponse (actual token counts)
    
    Gateway->>BudgetRepo: reconcile_reservation(reservation_id, actual_microcents)
    BudgetRepo->>DB: SELECT FOR UPDATE (lock reservation & account)
    BudgetRepo->>DB: UPDATE account: reserved -= estimate, spent += actual
    BudgetRepo->>DB: UPDATE reservation: status="reconciled", actual=actual
    BudgetRepo-->>Gateway: Reconciled reservation
    Gateway-->>Agent: ModelResponse
```

### 5.1 80% Warning Threshold
- Triggered when `spent + reserved + estimate >= 80%` of configured budget limit.
- Emits an append-only `BUDGET_WARNING_80_PERCENT` audit event.
- **Idempotency Guarantee:** `budget_account.warning_emitted` is set to `True` under row-lock, preventing repeated duplicate warnings on subsequent tokens.

### 5.2 100% Hard Stop
- Triggered when `spent + reserved + estimate > 100%` of configured budget limit.
- Immediately halts execution before invoking provider APIs.
- Emits `BUDGET_EXHAUSTED` audit event and raises `ModelBudgetExceededError`.
- Classifies as `TaskFailureClassification.PERMANENT_FAILURE`, halting the task and workflow safely without infinite retry spin.

### 5.3 Concurrency Race Protection
Simultaneous reservations from concurrent workers acquire transactional row locks (`SELECT ... FOR UPDATE`) on the `budget_account` record. If Worker A and Worker B both attempt to reserve funds when only enough budget remains for one, the second worker is deterministically blocked and rejected with `ModelBudgetExceededError`.

---

## 6. Retries, Timeouts, and Fallback Routing

### 6.1 Retry Policy
Only transient, retryable errors are retried:
- HTTP 429 Rate Limit (with backoff)
- HTTP 503 Service Unavailable
- Connection resets and network timeouts

Non-retryable errors are never retried:
- `ModelPolicyViolationError`
- `ModelBudgetExceededError`
- `ModelAuthenticationError`
- Invalid requests or malformed payloads

### 6.2 Fallback Routing
When primary model attempts are exhausted by retryable failures, the gateway consults the policy's `fallback_targets`:
1. Transitions to designated fallback provider and model.
2. Records `model_fallbacks_total` metric.
3. Records `is_fallback=True`, `primary_provider`, `primary_model_id`, and `fallback_reason` in the audit record.

---

## 7. Security, Secrets Management & Redaction

### 7.1 Secret Storage
- API keys are retrieved strictly from server-side environment variables (`MODEL_OPENAI_API_KEY`, `MODEL_ANTHROPIC_API_KEY`, etc.).
- Raw API keys are never stored in PostgreSQL, workflow state, prompts, job payloads, or client responses.

### 7.2 Centralized Redaction Engine
`modernization_platform/domain/model_gateway/redaction.py` and `RedactingFilter` in logging sanitize:
- OpenAI keys (`sk-[a-zA-Z0-9_\-]{8,}`)
- Anthropic keys (`anthropic-[a-zA-Z0-9_\-]{8,}`, `ant-[a-zA-Z0-9_\-]{8,}`)
- Bearer tokens (`Bearer [token]`)
- Database connection strings with passwords (`postgresql://user:pass@host/db` -> `postgresql://user:*****@host/db`)
- Private keys (`-----BEGIN ... PRIVATE KEY-----`)

Redaction operates uniformly across:
1. Application and structured JSON logs.
2. OpenTelemetry span attributes and trace logs.
3. Exception messages and stack traces.
4. Database audit records and API error responses.

---

## 8. Observability & Correlation Hierarchy

### 8.1 OpenTelemetry Span Hierarchy
```text
Job Span (job_id, repository_url)
 └── Workflow Span (workflow_thread_id, stage)
      └── Task Span (task_id, task_type)
           └── Agent Run Span (agent_role, prompt_version)
                └── Model Call Span (provider, model_id, correlation_id)
                     └── Provider Request (outbound HTTP call)
```

### 8.2 Standard Platform Metrics
| Metric | Type | Dimensions | Description |
| :--- | :--- | :--- | :--- |
| `model_calls_total` | Counter | `provider`, `model`, `status` | Total model invocation attempts. |
| `model_call_failures_total` | Counter | `provider`, `model`, `failure_type` | Total model failures categorized by type. |
| `model_call_duration_seconds` | Histogram | `provider`, `model` | Call duration distribution. |
| `model_tokens_total` | Counter | `provider`, `model`, `token_type` | Input, output, and total token counters. |
| `model_cost_microcents_total` | Counter | `provider`, `model` | Total financial spend in microcents. |
| `model_retries_total` | Counter | `provider`, `model` | Number of retry attempts. |
| `model_fallbacks_total` | Counter | `primary_provider`, `fallback_provider` | Failover fallback occurrences. |
| `model_rate_limit_total` | Counter | `provider` | Provider rate limit incidents. |
| `model_budget_rejections_total` | Counter | `scope` | Invocations blocked by budget ceiling. |

---

## 9. Database Design

Alembic migration `0010_model_gateway_budgets.py` provisions durable persistence:

### 9.1 `budget_account`
- `id` (UUID, PK)
- `job_id` (UUID, FK -> `job.id` ON DELETE CASCADE)
- `scope_type`, `scope_id` (VARCHAR, Unique constraint across `(job_id, scope_type, scope_id)`)
- `limit_microcents`, `reserved_microcents`, `spent_microcents` (BigInteger, check non-negative)
- `warning_threshold_percent`, `warning_emitted` (Boolean)
- `status` (`active`, `warning`, `exhausted`, `closed`)

### 9.2 `budget_reservation`
- `id` (UUID, PK)
- `budget_account_id` (UUID, FK -> `budget_account.id` ON DELETE CASCADE)
- `job_id` (UUID, FK -> `job.id` ON DELETE CASCADE)
- `task_id` (UUID, FK -> `task.id` ON DELETE SET NULL)
- `agent_role` (VARCHAR)
- `reserved_microcents`, `actual_microcents` (BigInteger)
- `status` (`reserved`, `reconciled`, `released`, `expired`)
- `expires_at`, `created_at`, `reconciled_at` (TIMESTAMPTZ)

### 9.3 `model_execution`
- `id` (UUID, PK)
- `job_id` (UUID, FK -> `job.id` ON DELETE CASCADE)
- `task_id` (UUID, FK -> `task.id` ON DELETE SET NULL)
- `agent_run_id` (UUID, FK -> `agent_run.id` ON DELETE SET NULL)
- `agent_role`, `stage`, `module`
- `provider`, `model_id`, `prompt_version`
- `input_tokens`, `output_tokens`, `total_tokens`
- `estimated_cost_microcents`, `actual_cost_microcents`
- `duration_ms`, `status`, `failure_classification`
- `attempt_number`, `is_fallback`, `primary_provider`, `primary_model_id`, `fallback_reason`
- `tool_call_count`, `tool_calls` (JSONB)
- `artifact_id`, `artifact_version`
- `correlation_id`, `created_at`

---

## 10. Testing Strategy

The test suite validates the entire model gateway ecosystem across multiple testing tiers:

1. **Unit Tests (`tests/unit/model_gateway/`)**:
   - `test_pricing_and_contracts.py`: Integer microcent math, rounding, and contract schemas.
   - `test_policy_and_routing.py`: Policy validation, agent role enforcement, and model whitelisting.
   - `test_retries_and_fallbacks.py`: Error classifications, retryable vs permanent errors.
   - `test_redaction.py`: Scrubbing of API keys, bearer tokens, DB passwords, and private keys.
   - `test_observability.py`: Tracing context managers and metrics registry.

2. **Concurrency Tests (`tests/integration/model_gateway/test_budget_concurrency.py`)**:
   - Multi-worker race test verifying that concurrent reservations under identical budgets never exceed the configured spending ceiling.

3. **Lifecycle Integration Tests (`tests/integration/model_gateway/test_model_gateway_lifecycle.py`)**:
   - End-to-end token and cost persistence.
   - 80% warning emission and idempotency.
   - 100% hard stop enforcement.
   - Transient failure retry loop.
   - Provider fallback execution and audit recording.

4. **Workflow Integration Tests (`tests/integration/model_gateway/test_workflow_model_integration.py`)**:
   - `Job -> Workflow -> Task -> Agent -> Gateway -> Response -> DB Audit Trail`.
   - Budget exhaustion causing permanent failure classification and safe workflow pause.
   - Primary model failure failover to approved fallback.
   - Worker and session restart budget state preservation.

5. **Security Redaction Tests (`tests/integration/model_gateway/test_secrets_never_leak.py`)**:
   - Real test secrets (`sk-live-...`, `Bearer test-...`) verified absent from application logs, exception traces, OpenTelemetry attributes, and database records.
