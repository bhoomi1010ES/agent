# PRD: Multi-Agent Legacy Code Modernization Platform

Version 1.0 · Derived from TDD dated Oct 13, 2026 · Owner: @Raj

---

## 1. Product Summary

The platform takes a **legacy codebase** and a **target tech stack** as per-job inputs and returns a **modernized codebase on a Git branch (plus pull request)**. Behavior is verified against the original system, and every risky decision is approved by a human at an explicit gate.

Neither the legacy stack nor the target stack is fixed. Both are supplied per job and handled by one stack-agnostic pipeline.

## 2. Problem Statement

Legacy modernization is slow, risky and expensive. Existing approaches either:

- rewrite by hand (months of effort, regressions discovered late), or
- let an LLM convert code and trust tests the LLM wrote about its own output (proves nothing).

Teams need conversion that is **provably equivalent on tested behavior**, **honest about what is not covered**, **auditable**, and **bounded in cost**.

## 3. Users and Roles

| Role | Description | Key actions |
|---|---|---|
| **Owner** (engineering lead) | Starts a conversion job, sets budget | Create job, set budget/target stack, receive budget warnings |
| **Reviewer** | Inspects artifacts at gates | Review reports, flag items, resolve flagged uncertainty |
| **Approver** | Named role that makes gate decisions | Approve/reject G1–G4, waive intended differences with reason |
| **Admin** | Platform operator | Manage users, retention, model endpoint policy |

## 4. Goals

1. Convert any legacy stack to any requested target stack through one pipeline.
2. Check **before any code is generated** whether the target stack can express everything the legacy system does; show gaps and the tools needed.
3. Prove behavioral equivalence with **characterization tests captured from the legacy system**, not tests written by the converting agents.
4. Keep humans in control through explicit approval gates where wrong decisions are expensive.
5. Make every job **resumable, auditable and cost-bounded**.

## 5. Success Metrics (to be calibrated on pilot jobs)

| Metric | Target |
|---|---|
| Characterization tests passing before final review | ≥ 95% of tests the user accepted as in scope |
| Unexplained behavior differences at final review | 0 (each fixed or waived by a named reviewer) |
| Jobs that resume correctly after worker/process crash | 100% |
| Gate decisions with stored rationale and artifact diff | 100% |

## 6. Scope

### In scope (V1)

- Ingest a legacy repository (optionally a running legacy instance or DB snapshot).
- Analysis: inventory, dependency graph, business-capability map, risk and complexity scoring.
- Target-stack feasibility check with gap report and user decision.
- Conversion plan, target code, schema migrations, data-migration scripts.
- Characterization-test capture, execution against both systems, equivalence report.
- Human approval gates, audit trail, delivery as Git branch and pull request.

### Non-goals (V1)

- Production cutover, traffic shifting, live data migration execution.
- Guaranteeing equivalence for behavior no test exercises (reported as coverage instead).
- Automatic installation of missing target-stack tooling (platform reports; user chooses).
- Pixel-perfect UI parity (UI checked by flow and DOM-level assertions only).

### Assumptions

- Legacy code is readable in full; a runnable legacy environment exists for at least core flows (otherwise fall back to static analysis and flag the gap).
- Each job has a named owner who approves gates.
- LLM access via provider API / local models, with per-job token and cost budgets.
- Conversion is module by module (strangler-style), not big-bang.

## 7. Agent Roster and Model Assignment

Eleven specialist agents plus one supervisor. Agents exchange **typed artifacts**, never free-form chat.

| Agent | Responsibility (product view) | Model | Where |
|---|---|---|---|
| **Intake** | Clone repo, detect languages/build systems/entry points, size codebase | Qwen2.5-Coder 7B | Ollama (local) |
| **Legacy Analyzer** | AST, call/dependency graphs, DB schema map, integrations, business rules | Qwen2.5-Coder 7B (initially) | Ollama (local) |
| **Architect** | Map legacy capabilities to target architecture and module boundaries | Qwen3 30B-A3B | OpenRouter |
| **Feasibility** | Check each required capability against target stack and tool catalog | Qwen3 30B-A3B | OpenRouter |
| **Planner** | Split work into modules, order by dependency, estimate risk and cost | Qwen3 30B-A3B | OpenRouter |
| **Characterizer** | Capture legacy behavior as executable tests and golden data | Qwen2.5-Coder 7B | Ollama (local) |
| **Schema & Data** | Design target schema, migrations, data-migration scripts | Qwen2.5-Coder 7B | Ollama (local) |
| **CodeWriter (pool)** | Convert one module at a time on its own branch | Qwen2.5-Coder 7B (initially) | Ollama (local) |
| **Verifier** | Run characterization tests on legacy and converted code, classify differences | Compiler / tests / type-checkers (no LLM) | Local |
| **Reviewer** | Static review for security, style, architecture; propose repairs | Qwen3 30B-A3B | OpenRouter |
| **Integrator** | Merge module branches, full build, open PR, write final report | Qwen2.5-Coder 7B | Ollama (local) |
| **Supervisor** | Route work, enforce budgets, open gates, retry vs escalate | LangGraph / Python (no LLM) | Local |

> "Initially" means the model is expected to be revisited (e.g. swapped to a stronger model) after pilot results; model routing must therefore be configuration, not code.

## 8. Functional Requirements

### FR-1 Job creation and intake
- Owner submits repo URL or archive, target stack spec, and job budget.
- Owner declares which model endpoints may see the code (local Ollama, OpenRouter, or both).
- System produces a `RepoInventory`.

### FR-2 Legacy analysis
- System produces a `LegacyModel`: AST, call and dependency graphs, DB schema map, I/O and integration list, extracted business rules, risk and complexity scores.

### FR-3 Target-stack feasibility (Gate G1)
- System normalizes the legacy system into required capabilities and rates each as **native / library / custom / unsupported**.
- If the target stack has no catalog entry, a provisional catalog is built and every rating is marked lower confidence.
- System checks its own pipeline readiness for the stack (sandbox image, test runner, linter, formatter, security scanner).
- Any custom, unsupported, low-confidence item or missing pipeline tool **opens G1**.
- For each gap, show options with **effort cost** and **verification coverage lost**. The platform never installs tooling or picks a substitute silently.
- User choices are written back as constraints and the Planner re-runs.

### FR-4 Characterization testing (Gate G2)
- Layers: Unit, API contract, Data effects, Batch/file output, UI flows (only where a UI exists).
- Sources: legacy tests, sanitized production traffic/logs, generated boundary and property-based inputs, user-written scenarios.
- Nondeterminism handled by explicit normalization rules, each approved at G2.
- Suite is **frozen with a content hash** at G2 approval. CodeWriter agents cannot modify it; later edits require new G2 approval and invalidate earlier results.

### FR-5 Blueprint and plan (Gate G3)
- Architect produces `TargetBlueprint`; Planner produces `ConversionPlan` (DAG) with cost and time estimate.
- G2 and G3 run in parallel; conversion starts only when both are approved.

### FR-6 Conversion
- Module by module, leaf modules first, independent modules in parallel.
- Each module: generate → build/typecheck/lint/format → run characterization slice → review → repair or finish.
- Attempt limit (default 3) or module budget exhaustion triggers Escalation.
- Schema & Data agent runs before schema-dependent modules; migrations tested on a data sample.

### FR-7 Verification
- Every failing comparison is classified: **Regression**, **Intended difference**, **Nondeterministic**, **Test defect**. No failure is left unclassified.
- Coverage report lists legacy code never touched by the suite, ranked by risk ("equivalent on the behavior we tested").
- Optional mutation testing on legacy code.

### FR-8 Final review and delivery (Gate G4)
- Equivalence report, waivers (named reviewer + reason), uncovered-code list.
- Approver approves the PR. Integrator delivers a Git branch/PR plus a software bill of materials.

### FR-9 Escalation
- Per-module escalation options: give guidance, raise budget, hand-fix, drop module. Only that module is blocked.

## 9. Human Gates Summary

| Gate | After | Reviewer decides | Blocks |
|---|---|---|---|
| G1 Feasibility | Feasibility report | Per gap: accept substitute, add tool, build custom, descope, cancel | Planning |
| G2 Test suite | Characterizer finishes | In-scope behaviors, legacy bugs keep/fix, normalization rules; freezes suite | Code conversion |
| G3 Blueprint & plan | Architect + Planner | Architecture, module boundaries, order, cost/time | Code conversion |
| G4 Final review | Verifier + Reviewer done | Equivalence report, waivers, uncovered code; approves PR | Merge/delivery |
| Escalation | Module exhausts attempts/budget | Guidance, budget, hand-fix, drop | That module |

Gate rules: rejection requires written feedback; gates time out into **paused**, never silent approval; waivers need reason and approver identity; reminders via email or chat webhook.

## 10. User Experience Requirements

- **Web UI** and matching **REST API** for gate review; both resume the graph via `POST /jobs/{id}/gates/{gate}`.
- Each gate view shows: the artifact, a diff against the previous version, agent-flagged uncertainties (`needs_human`), and budget used.
- Live job status streaming (stage, module pass rates, cost, repair attempts).
- Input form for job creation (repo, target stack, budget, allowed model endpoints).

## 11. Non-Functional Requirements (product level)

| Area | Requirement |
|---|---|
| Resumability | Jobs survive worker/process crash and resume from last checkpoint |
| Auditability | Append-only log of every agent action and human decision with identity and time |
| Cost control | Hard job ceiling; warning at 80%, stop and escalate at 100% |
| Security | Secrets/PII never in prompts; legacy code runs only in sandbox; default-deny egress |
| Confidentiality | Each job restricts which model endpoints may see its code |
| Retention | Snapshots, recordings, sandboxes deleted on owner-set schedule; audit kept longer |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Legacy runtime cannot be recreated | Environment builder, user Dockerfile/docs, coverage loss shown at G2/G4 |
| Suite misses important behavior | Coverage ceiling, risk-ranked uncovered code, mutation testing |
| "Any stack to any stack" too broad | Curated catalogs for a named set first; provisional catalogs flagged low confidence |
| Agents loop and burn budget | Budgets, no-progress detection, escalation |
| Large codebases exceed context | Graph-based slicing, each agent gets only its module and contracts |
| Reviewers rubber-stamp gates | Show diffs and flagged uncertainties; written reason for waivers |
| 7B local models weak on hard conversions | Config-driven model routing; stronger-model tactic on repeated failure; escalation |
| Business logic hidden in stored procs/config/UI | Treat DB and config as first-class inputs; G2 asks about unexplained rules |

## 13. Open Questions

1. Which target stacks get a curated capability catalog and stack profile in V1?
2. Largest legacy codebase V1 must handle (LOC, modules)?
3. Will most jobs have a runnable legacy instance, and who supplies its environment?
4. Which providers/self-hosted models are allowed; is any customer data barred from external APIs (relevant because Architect, Feasibility, Planner and Reviewer use OpenRouter)?
5. Which Git hosts must receive the PR (GitHub, GitLab, Bitbucket, on-prem)?
6. Single-tenant or multi-tenant from the start?
7. Which parts of the existing Postgres-based orchestrator carry over under LangGraph?

## 14. Out-of-Scope Reminder for Agents

Agents working from this PRD must not add features beyond Section 6. Anything unspecified is an open question to raise via `needs_human`, not to guess.
