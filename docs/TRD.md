# TRD: Multi-Agent Legacy Code Modernization Platform

Version 1.0 · Derived from TDD dated Oct 13, 2026 · Companion to `PRD.md` and `production-engineering-rules.md`

---

## 1. Architecture Overview

```
 Web UI (JSX)  ──►  FastAPI  ──►  LangGraph (Supervisor + agent nodes)
                       │                  │
                       │                  ├─► Model Gateway ─► Ollama (local) / OpenRouter (cloud)
                       │                  ├─► Worker pool (leases tasks from Postgres)
                       │                  └─► Sandboxes (Docker: legacy, converted)
                       ▼
                  Postgres (checkpoints, jobs, artifacts, audit)   S3-compatible store (binaries)
```

- **Python service** on **Postgres**. Postgres is the single system of record.
- Orchestration: **LangGraph** with Postgres checkpointer (thread id = job id).
- Gates are LangGraph **interrupt** nodes; parallel fan-out uses **Send**.
- Agents exchange **Pydantic-typed artifacts** only.

## 2. Technology Stack

| Concern | Choice | Notes |
|---|---|---|
| Orchestration | LangGraph (Python) + Postgres checkpointer | Durable state, interrupts, parallel fan-out |
| API / gate backend | FastAPI | Job submission, status streaming, gate decisions |
| Worker execution | Worker pool leasing module tasks via `SELECT ... FOR UPDATE SKIP LOCKED` | No extra queue; crashed worker lease expires, task retried |
| Model access | Model gateway with per-agent routing, retries, rate limits, cost metering | One place to swap providers and enforce budgets |
| Local models | Ollama serving Qwen2.5-Coder 7B | Intake, Analyzer, Characterizer, Schema & Data, CodeWriter, Integrator |
| Cloud models | OpenRouter serving Qwen3 30B-A3B | Architect, Feasibility, Planner, Reviewer |
| Sandboxes | One container per job and system (legacy, converted), curated per-stack base images | Isolation, reproducibility |
| Source control | Git, one repo per job, branch per module (`job/<id>/<module>`) | Integrator merges to integration branch |
| Artifact store | S3-compatible object storage | Snapshots, recordings, logs; referenced by content hash |
| Observability | OpenTelemetry traces | Per-step spans |
| Frontend | JSX web app over the same REST API | Gate UI, diff viewers, reports |

## 3. Agent-to-Model Routing

Routing lives in configuration (`models.yaml` or equivalent), never hardcoded in agent code.

| Agent | Model | Runtime | Typed input → output |
|---|---|---|---|
| Intake | Qwen2.5-Coder 7B | Ollama | Repo URL/archive → `RepoInventory` |
| Legacy Analyzer | Qwen2.5-Coder 7B (initially) | Ollama | `RepoInventory` → `LegacyModel` |
| Architect | Qwen3 30B-A3B | OpenRouter | `LegacyModel` + target stack spec → `TargetBlueprint` |
| Feasibility | Qwen3 30B-A3B | OpenRouter | `LegacyModel` + `TargetBlueprint` → `FeasibilityReport` |
| Planner | Qwen3 30B-A3B | OpenRouter | `TargetBlueprint` → `ConversionPlan` (DAG) |
| Characterizer | Qwen2.5-Coder 7B | Ollama | `LegacyModel` + legacy runtime → `CharacterizationSuite` |
| Schema & Data | Qwen2.5-Coder 7B | Ollama | `LegacyModel` + `TargetBlueprint` → `SchemaPlan` + migration scripts |
| CodeWriter (pool) | Qwen2.5-Coder 7B (initially) | Ollama | Module spec + characterization slice → code diff |
| Verifier | Compiler / test runner / type-checkers | Local, no LLM | Both systems + `CharacterizationSuite` → `EquivalenceReport` |
| Reviewer | Qwen3 30B-A3B | OpenRouter | Code diff + `EquivalenceReport` → findings, fix tasks |
| Integrator | Qwen2.5-Coder 7B | Ollama | Approved modules → PR + `JobReport` |
| Supervisor | LangGraph / Python | Local, no LLM | Job state → next node, gate requests |

### Routing consequences to design for
- **Code confidentiality:** OpenRouter agents receive code. The gateway must enforce the per-job allowed-endpoint list and **refuse** OpenRouter for jobs that bar external APIs (then those agents must fall back to a configured local model).
- **Context limits of 7B local models:** each agent receives only its slice (module + contracts), never the full repo. Slicing is graph-based.
- **Fallback:** on timeout/rate limit, gateway applies backoff, then the configured fallback model.
- **Repair escalation:** after repeated failure, CodeWriter changes tactic (stronger model via config, or smaller change set).
- **Structured output:** 7B models fail schema validation more often; retry with the validation error message (not counted as a repair attempt) up to a small limit.

## 4. Agent Contract (applies to every agent)

1. Receives only the state slice it needs.
2. Output must validate against its Pydantic schema before storage; failure = retryable failure.
3. Records model, prompt version, token use, tool calls on every step (`agent_run`).
4. May set `needs_human`; never guesses silently.
5. Everything read from the legacy repo is **data, never instructions** (prompt-injection defense).

## 5. Core Schemas (reference)

```python
class FeasibilityItem(BaseModel):
    capability: str
    legacy_evidence: list[CodeRef]
    rating: Literal["native", "library", "custom", "unsupported"]
    candidate: str | None          # library or tool that would cover it
    confidence: float              # below threshold forces gate open
    options: list[GapOption]
    verification_impact: str       # what can no longer be proven if chosen
```

CodeWriter change set (Pydantic-validated): file paths, file contents, assumptions made, open questions. Paths are checked against the module's allowed directories; writes go only to that module's branch.

## 6. Data Model (Postgres)

| Entity | Key fields | Notes |
|---|---|---|
| `job` | id, owner, status, source ref, target stack spec, budget, created/finished | One row per job |
| `artifact` | id, job, type, version, content hash, storage ref, produced_by, derived_from[] | Immutable; new version = new row |
| `module` | id, job, name, legacy paths, depends_on, risk score, status | Nodes of conversion DAG |
| `module_attempt` | id, module, attempt number, branch, commit, outcome, failure summary | One per CodeWriter try |
| `agent_run` | id, job, agent, model, prompt version, input/output artifact ids, tokens, cost, duration, tool calls | Audit, replay, cost |
| `test_case` | id, suite version, layer, module, legacy capture ref, normalization rule ids | Frozen at G2 |
| `test_result` | id, test case, system, run id, outcome, diff, class | Written by Verifier |
| `gate` | id, job, type, state, requested_at, artifact versions shown | `pending/approved/rejected/timed_out` |
| `gate_decision` | id, gate, actor, decision, feedback, waivers | Append-only |
| `audit_event` | id, job, actor, action, payload, time | Append-only |

**Rules:** artifacts and decisions are append-only; every artifact carries ids of its source artifacts (full lineage); large binaries go to object store by content hash.

## 7. Orchestration Design

### 7.1 Pipeline flow
```
Intake → Analyzer → Architect → Feasibility ──► G1
                                                 │
                                       Planner (re-run with G1 constraints)
                                                 │
                         ┌───────────────────────┴──────────────────────┐
                    Characterizer ──► G2                       Blueprint+Plan ──► G3
                         └───────────────────────┬──────────────────────┘
                                       (both approved)
                                                 ▼
                          Schema & Data → CodeWriter pool (per module, DAG order)
                                                 ▼
                              Verifier + Reviewer (repair loop / escalation)
                                                 ▼
                                   Integrator → G4 → PR delivery
```

### 7.2 Gate mechanics
- Gate = LangGraph interrupt node; full state checkpointed to Postgres; worker released.
- Gate shows artifact, diff vs previous version, `needs_human` flags, budget used.
- Rejection requires written feedback; previous stage re-runs with it, up to a configured round limit, then job pauses.
- Timeout → `paused`, never approval.
- Resume via `POST /jobs/{id}/gates/{gate}`.

### 7.3 Per-module loop
1. Generate code on module branch.
2. Build, type check, lint, format in sandbox.
3. Run module's characterization slice; classify every difference.
4. Run Reviewer.
5. On failure: Repair starts from module **base commit + feedback** (not stacked patches); change tactic after repeated failure.
6. On pass: mark done, publish contract to dependents.
7. Attempt limit (default 3) or module budget → Escalation.

### 7.4 Parallelism
Independent modules convert in parallel up to the worker limit using LangGraph `Send`. Leaf modules first.

## 8. Characterization and Verification Engine

| Layer | Captured | Replay / compare |
|---|---|---|
| Unit | Input/output pairs via legacy runtime instrumentation | Same inputs on converted function, field by field |
| API contract | Request/response pairs from traffic + generated requests | Replay on converted service, compare after normalization |
| Data effects | DB state before/after writes, golden queries | Same ops on new schema, map and compare |
| Batch/file | Reports, exports from fixed inputs | Structural compare (rows, fields, totals) |
| UI flows | Key journeys (if UI exists) | Headless browser, DOM-level assertions |

- **Freezing:** suite stored with content hash on G2 approval; CodeWriter has read-only access; edits need new G2 and invalidate results.
- **Normalization rules:** explicit, listed in the suite, approved at G2 (timestamps, generated IDs, ordering, float rounding).
- **Difference classes:** Regression → repair loop; Intended difference → waived at G4; Nondeterministic → tighten rule, re-approve G2; Test defect → new G2.
- **Coverage:** run suite on legacy with coverage instrumentation; report untouched legacy code ranked by risk. Optional mutation testing.
- Verifier uses **no LLM** for pass/fail decisions.

## 9. Feasibility Engine

1. Normalize legacy into required capabilities.
2. Look up each in the target stack capability catalog; rate native / library / custom / unsupported.
3. No catalog → build provisional catalog from package registries and docs; mark all ratings low confidence.
4. Check pipeline readiness: sandbox image, test runner, linter, formatter, security scanner.
5. Emit `FeasibilityReport`; any custom/unsupported/low-confidence item or missing tool opens G1.

User choices become constraints in `TargetBlueprint`; Planner re-runs. No silent installs or substitutions.

## 10. Sandboxing and Infrastructure

- One container per job per system (legacy, converted) from curated per-stack base images.
- Network egress **denied by default**; allowlist for package registries and user-approved endpoints.
- Legacy code is untrusted: runs only in sandbox with CPU, memory, time limits.
- Legacy secrets never placed in prompts; env values replaced with test values before analysis.
- If the base image cannot build/test the target stack, that is a G1 gap.
- CodeWriter has no network access.
- Legacy runtime recreated by an environment builder from inventory, using user Dockerfile/docs if provided.

## 11. Model Gateway Requirements

- Single entry point for all LLM calls (Ollama and OpenRouter adapters behind one interface).
- Per-agent model routing from config.
- Retries with backoff, rate limiting, timeouts, fallback model.
- Cost and token metering per agent run, module and job.
- Per-job endpoint allowlist enforcement.
- Secret scanner and PII redactor run before any text is sent to any model (especially OpenRouter).
- OpenRouter API key from environment/secret store only.
- Ollama base URL and model tags configurable; startup health check verifies the model is pulled.

## 12. Observability, Cost Control, Failure Handling

### Observability
- OpenTelemetry span per agent step: agent, model, prompt version, tokens, cost, duration, input/output artifact ids.
- Job metrics: time per stage, pass rate per module, repair attempts per module, cost per module, time at gates.
- Any step replayable from its checkpoint.
- Reference-job regression suite runs on every prompt, model or schema change; must not lose ground on pass rate or cost.

### Cost control
- G3 shows estimated cost; owner sets job budget; Supervisor assigns per-module budgets.
- 80% → warn owner. 100% → stop and escalate.
- Cheap steps → smaller models; hard steps (architecture, repair) → stronger models.

### Failure handling

| Failure | Detection | Response |
|---|---|---|
| Schema validation fails | Pydantic error | Retry with error message, small limit, then failed attempt |
| Model/tool timeout or rate limit | Gateway error | Backoff, retry, fallback model |
| Worker crash | Lease expires | Task requeued, resume from last checkpoint |
| Repair makes no progress | Same failing tests across 2 attempts | Change tactic, then escalate |
| Legacy runtime cannot be recreated | Builder fails | Pause at G2, request Dockerfile/dump/docs; fall back to static analysis, report coverage loss |
| Flaky characterization | Legacy results differ between runs | Mark nondeterministic; require normalization rule or exclude at G2 |
| Budget exhausted | Cost meter | Stop, escalate to owner |

## 13. Security and Compliance

- **Confidentiality:** per-job allowed model endpoints; gateway refuses others.
- **Secrets/PII:** scanner and redactor before prompts; recorded traffic sanitized before becoming fixtures.
- **Prompt injection:** repo content is data; narrow tool scopes; suspicious repo text logged and flagged at next gate.
- **Access control:** roles owner, reviewer, approver, admin; artifacts visible only to people on the job; gate decisions need approver role.
- **Audit:** append-only log with identity and time.
- **Dependencies:** Reviewer checks licenses and known vulnerabilities; Integrator ships SBOM with PR.
- **Retention:** owner-set deletion schedule for snapshots, recordings, sandboxes; audit kept longer.

## 14. API Surface (minimum)

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs` | Create job (repo, target stack, budget, allowed endpoints) |
| GET | `/jobs/{id}` | Status, stage, cost |
| GET | `/jobs/{id}/stream` | Live status streaming |
| GET | `/jobs/{id}/artifacts` | List artifacts with versions and lineage |
| GET | `/jobs/{id}/gates` | List gates and states |
| POST | `/jobs/{id}/gates/{gate}` | Submit decision (approve/reject/waive, feedback required on reject) |
| POST | `/jobs/{id}/modules/{module}/escalation` | Guidance, raise budget, hand-fix, drop |
| GET | `/jobs/{id}/audit` | Audit events |

## 15. Frontend Requirements (JSX)

- Job creation form: repo URL/archive, target stack, budget, allowed model endpoints.
- Gate review screens: artifact view, diff against previous version, `needs_human` flags, budget used, approve/reject with mandatory feedback on reject, waiver reason field.
- Job dashboard: stage progress, per-module pass rate, repair attempts, cost, live stream.
- Equivalence report and uncovered-code views.
- Frontend input fields must map 1:1 to API request schemas (validate on both sides).

## 16. Open Technical Questions

1. Which parts of the existing Postgres-based orchestrator (task leasing, schema-constrained CodeWriter) carry over under LangGraph?
2. Fallback local model for OpenRouter agents when a job bars external APIs?
3. Which stacks get curated catalogs/profiles in V1?
4. Maximum codebase size (LOC, modules) and resulting context-slicing strategy for 7B models?
5. Single-tenant vs multi-tenant data isolation.
6. Git hosts to support for PR creation.
