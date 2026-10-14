# Legacy Modernization Platform — Backend Implementation Plan

## 1. Outcome and scope

Build a durable, auditable control plane that accepts an authorized legacy repository, validates it safely, produces evidence-linked analysis, pauses at four human gates, converts modules through isolated bounded workers, verifies the result against a frozen characterization suite, and creates a customer-host pull request only after final approval.

This plan covers the FastAPI API, PostgreSQL persistence, object storage, LangGraph orchestration, agent runtime, task workers, sandbox controller, test harness, model gateway, Git integration, security, observability, and platform tests. The browser implementation is defined separately in `ui_implementation_plan.md`.

## 2. Verified interpretation and resolved conflicts

The requested journey, PDF, and workflow diagram agree on the core architecture: artifact-driven agents, G1–G4 approvals, parallel G2/G3 work, dependency-ordered conversion, bounded repair, and PR delivery without deployment. Implement these resolutions where the sources differ or leave gaps:

1. **G1 is mandatory for every job.** The PDF graph bypasses G1 when no feasibility gap exists, while the requested journey explicitly requires feasibility review and approval. Always open G1; a no-gap report needs only an overall approval.
2. **Run Architect in draft mode before Feasibility.** Feasibility needs a target mapping. G1 decisions become constraints for Architect final mode and Planner.
3. **Start Characterizer and Architect-final/Planner only after G1.** Capabilities descoped at G1 must not enter the frozen suite or conversion plan.
4. **G2 and G3 run and pause independently.** Join only after both current gate instances are approved. Rejection reruns the owning branch; cross-branch invalidation must be explicit and audited.
5. **Freeze G2 canonically.** Canonical JSON, version, SHA-256, decisions, and normalization rules are immutable. A correction produces a successor suite and new G2 gate.
6. **Schema & Data runs after the G2/G3 join.** Schema-dependent modules cannot queue until its verified contract exists.
7. **Per-module verification precedes internal integration; full verification precedes G4.** Every non-pass result must be classified. Missing evidence blocks or reduces the stated verification scope.
8. **Internal branches are allowed before G4; external delivery is not.** Workers need module branches and an integration branch. Only the post-G4 Integrator may push the customer branch and open a PR. The platform never merges the PR or deploys production.
9. **Correctable intake failures preserve the job.** Configuration/source corrections create a new validation run. Unsafe repositories remain quarantined and cannot advance.
10. **Budgets are hard transactional limits.** Warning at 80%; at 100%, no further model or sandbox work is scheduled. Only an authorized budget change or scoped human decision can resume.
11. **“Equivalence” is always qualified.** Reports carry suite hash, in-scope count, pass rate, coverage ceiling, uncovered risk, waivers, and missing evidence. Passing observed tests is not universal equivalence.

### External technical verification as of 2026-10-14

- Python 3.14 is stable; the current official maintenance release is 3.14.8: <https://www.python.org/downloads/release/python-3148/>.
- FastAPI's official release notes show the 0.141 line, so do not pin the PDF's generic `0.14x` without a lockfile review: <https://fastapi.tiangolo.com/release-notes/>.
- LangGraph 1.2.12 exists and adds typed interrupt response schemas. Its official docs confirm durable checkpointers, `thread_id`, `interrupt`, `Command(resume=...)`, and multiple simultaneous interrupts: <https://docs.langchain.com/oss/python/langgraph/interrupts> and <https://docs.langchain.com/oss/python/langgraph/persistence>.
- PostgreSQL 17 remains supported through November 2029, although 18 is the newest major line: <https://www.postgresql.org/support/versioning/>. Keep 17 only as an explicit compatibility choice and run the latest 17 minor.
- Exact patches for every dependency, model, prompt, tool, sandbox image, catalog, and stack profile must be locked and recorded per run.

## 3. Target architecture and boundaries

### Deployable services

| Service | Responsibility | Must not do |
|---|---|---|
| Web | Browser application and authenticated SSE proxy | Run agents, sandboxes, or Git writes |
| API | Auth, validation, jobs, gates, artifacts, modules, tests, reports, audit, webhooks | Execute model/tool work inline |
| Job runner | Claim run requests and execute the top-level durable graph | Convert modules directly |
| Module workers | Lease module tasks and execute module subgraphs | Decide human gates or deliver PRs |
| Sandbox controller | Create isolated environments and execute allowlisted argv | Accept generic shell scripts or unrestricted network |
| Model gateway | Enforce endpoint/model policy, rate limits, retries, accounting | Select an unapproved endpoint |
| Git service | Internal repositories, scoped writes/merges, post-G4 host adapter | Merge customer PRs or deploy |
| Notification worker | Gate/escalation/budget/delivery notifications | Become workflow state of record |

### Shared state

- PostgreSQL is authoritative for jobs, tasks, leases, artifact metadata, decisions, budgets, checkpoints, and audit.
- S3-compatible object storage contains snapshots, logs, recordings, reports, suite bodies, and other large content addressed by SHA-256.
- Redis is optional/ephemeral for SSE fan-out, caches, and rate-limit counters. A Redis loss must not lose workflow state; clients replay from `job_event`.
- Internal Gitea holds one repository per job. Customer Git hosts are delivery destinations only.
- LangGraph state contains artifact references, IDs, hashes, statuses, and budget snapshots, never large artifact bodies.

### Repository dependency rules

```text
apps/{api,runner,worker,sandboxctl}
packages/{schemas,db,agents,tools,analysis,harness,gateway_client,gitops,observability}
catalogs/{capabilities,stack_profiles}
images/
evals/
deploy/{helm,terraform,argocd}
```

- Applications may depend on packages; applications do not import each other.
- `packages/schemas` has no internal package dependency and exports versioned JSON Schema.
- Agents access persistence through repositories/services, not ORM sessions.
- Tools do not import agent definitions.
- API routers are transport adapters; transactional policy belongs in services.

## 4. Domain state machine and invariants

### Job progression

```text
draft
  -> validating
  -> needs_correction -> validating
  -> analyzing -> waiting_g1
  -> preparing_g2_g3
       -> waiting_g2 / waiting_g3 (independent)
  -> preparing_schema
  -> converting
  -> integrating
  -> verifying
  -> waiting_g4
  -> delivering
  -> delivered
```

At supported points the job may transition to `paused`, `cancelled`, or `failed`. Resume returns to a recorded `resume_stage`, not a guessed stage. A terminal state cannot be mutated back to running.

### Gate progression

Each gate is an instance with its own UUID, type, artifact versions, response schema, due time, and state:

```text
open -> approved | rejected | timed_out | superseded
```

- A rejection never mutates or reopens the same row. It creates new upstream artifacts and then a new gate instance.
- One current open instance per `(job, gate_type, scope)` is enforced with a partial unique index.
- Decisions are append-only, actor-bound, and accepted only for an open gate whose artifact versions still match.
- Timeout routes to pause, never approval.
- G2 approval atomically freezes the exact suite hash.
- G4 approval authorizes one idempotent delivery request.

### Non-negotiable invariants

1. No analysis starts before a successful current validation run.
2. No characterization/final planning starts before current G1 approval.
3. No conversion task becomes claimable before current G2 and G3 approvals and required schema contracts.
4. CodeWriter cannot write suite storage or paths outside the module allowlist.
5. A module is `done` only when required build, type, lint, security, characterization, and review checks pass under its pinned inputs.
6. An integration branch never includes an unaccepted module outcome.
7. G4 cannot open while any required result is unclassified or any critical/high finding is unresolved unless policy explicitly permits a named waiver.
8. External push/PR credentials are unavailable to pre-G4 agents and workers.
9. A pull request cannot be opened without a committed G4 approval referencing the exact integration commit.
10. Every external side effect uses a deterministic idempotency key and records its result.

## 5. API contract

All routes are under `/api/v1`. Errors use RFC 9457 `application/problem+json` with stable `code`, `correlation_id`, safe details, and optional field errors. Mutations accept `Idempotency-Key`; edits use an entity version/ETag and reject stale writes with 409.

### Identity and discovery

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/me` | User, org, roles, effective permissions |
| `GET` | `/profiles` | Published target profiles and support level |
| `GET` | `/profiles/{stack}/{version}` | Pinned profile details |

### Uploads and jobs

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/uploads` | Create presigned upload with purpose, limits, and expected checksum |
| `POST` | `/uploads/{id}/complete` | Verify object size/hash and seal upload |
| `POST` | `/jobs` | Create and submit a job from Git or sealed upload |
| `GET` | `/jobs` | Authorized filtering/pagination |
| `GET` | `/jobs/{job_id}` | Current snapshot, blockers, gates, budget, delivery |
| `PATCH` | `/jobs/{job_id}/configuration` | Correct allowed configuration while blocked/paused |
| `POST` | `/jobs/{job_id}/validation-runs` | Enqueue a new validation of current config/source |
| `GET` | `/jobs/{job_id}/validation` | Validation runs and findings |
| `POST` | `/jobs/{job_id}/pause` | Stop new work at safe points |
| `POST` | `/jobs/{job_id}/resume` | Resume recorded stage if prerequisites hold |
| `POST` | `/jobs/{job_id}/cancel` | Cancel tasks, tear down sandboxes, preserve retention policy |
| `PATCH` | `/jobs/{job_id}/budget` | Audited owner/admin budget change |

### Events, artifacts, and lineage

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/jobs/{job_id}/events` | SSE replay from `Last-Event-ID`, then live fan-out |
| `GET` | `/jobs/{job_id}/artifacts` | Artifact metadata by type/version |
| `GET` | `/artifacts/{artifact_id}` | Authorized typed artifact or download reference |
| `GET` | `/artifacts/{artifact_id}/diff?against={id}` | Structured version diff |
| `GET` | `/jobs/{job_id}/lineage` | Query by target/legacy file, line, artifact, or test |
| `GET` | `/jobs/{job_id}/audit` | Paginated immutable audit metadata |

### Gates

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/jobs/{job_id}/gates` | Gate history and current instances |
| `GET` | `/jobs/{job_id}/gates/{gate_id}` | Payload, response schema, artifacts, required items |
| `POST` | `/jobs/{job_id}/gates/{gate_id}/decisions` | Typed approve/reject/choices/waivers response |

Use distinct decision schemas:

- G1: overall decision plus one allowed option per gap, target/scope changes, and rationale.
- G2: case scope, exclusion rationales, quirk keep/fix decisions, normalization approvals, suite version/hash acknowledgement.
- G3: blueprint/plan/profile versions, module scope, estimate/budget acknowledgement.
- G4: exact integration commit, report version, permitted per-item waivers, and delivery authorization.
- Escalation: guidance, budget change reference, human-fix commit, split, drop, retry, pause, or terminate as policy allows.

### Modules, tests, reports, and delivery

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/jobs/{job_id}/modules` | DAG, status, dependencies, budgets |
| `GET` | `/modules/{module_id}` | Module contract and current state |
| `GET` | `/modules/{module_id}/attempts` | Immutable attempt history |
| `POST` | `/modules/{module_id}/escalations/{gate_id}/decisions` | Resolve current module escalation |
| `GET` | `/jobs/{job_id}/tests` | Suite and filtered cases |
| `GET` | `/tests/{test_id}/results` | Legacy/converted runs, diffs, classification |
| `GET` | `/jobs/{job_id}/report` | Job/equivalence/security/coverage/SBOM summary |
| `GET` | `/jobs/{job_id}/delivery` | External branch/PR attempt and host status |
| `POST` | `/webhooks/git/{provider}` | Signed/idempotent PR-state webhook |

### Administration and operations

- Versioned CRUD/publish endpoints for catalogs and stack profiles; published versions are immutable.
- Replay endpoint for an agent run creates a new tagged run and cannot overwrite production artifacts.
- `/healthz`, `/readyz`, and `/metrics` are internal and separately authenticated/network-restricted.

## 6. Persistence and migration plan

### Core tables

Implement and migrate these groups before dependent services:

1. Identity: `org`, `app_user`, `job_member`, `git_connection` (secret reference only).
2. Intake: `upload`, `job`, `job_configuration_version`, `validation_run`, `validation_finding`.
3. Durable execution: `job_run_request`, `module_task`, `worker_lease`, LangGraph checkpoint tables.
4. Evidence: `agent_run`, `artifact`, `artifact_derivation`, `code_ref`, `lineage_edge`.
5. Planning: `module`, `module_dependency`, `module_attempt`, `module_contract`.
6. Tests: `test_suite`, `normalization_rule`, `test_case`, `test_result`, `difference_classification`.
7. Human control: `gate`, `gate_decision`, `waiver`, `item_view_event`.
8. Cost/operations: `cost_ledger`, `sandbox_run`, `tool_call`, `job_event`, `audit_event`, `notification_outbox`.
9. Configuration: `capability_catalog`, `stack_profile`, `model_route_policy`, `tool_policy`.
10. Delivery: `git_branch`, `delivery_request`, `pull_request`.

### Improvements over the abridged PDF DDL

- Replace `module.depends_on uuid[]` with `module_dependency` for referential integrity and efficient ready-module queries.
- Replace artifact UUID arrays with `artifact_derivation` rows so lineage is queryable and enforceable.
- Add artifact `scope_type`/`scope_id`; version uniqueness is `(job, artifact_type, scope, version)`, because sliced analysis and per-module outputs produce many artifacts of the same type.
- Add `org_id` consistently to tenant-owned tables, even though V1 deploys single-tenant.
- Add `version` columns for optimistic concurrency and explicit state-machine constraints.
- Add unique idempotency records for job submission, node side effects, gate decisions, module attempts, Git pushes, and PR creation.
- Generate event sequence numbers atomically per job; never use `MAX(seq)+1` under concurrency.
- Store money as fixed numeric values and account for model and sandbox costs in the same transaction that advances the hard budget.
- Partition or lifecycle high-volume `job_event`, `tool_call`, and test-result data after measuring real load.

### Immutability and retention

The PDF requires append-only artifacts/decisions/audit and also retention deletion. Reconcile them as follows:

- Gate decisions, audit metadata, hashes, actor, timestamps, and lineage metadata are append-only.
- Sensitive or bulky bodies live encrypted in object storage; database rows retain hashes and tombstone metadata when retention deletes the body.
- Inline artifact bodies are allowed only for small nonsensitive data or must be moved to encrypted storage before general availability.
- Deletion jobs are policy-driven, audited, idempotent, and cover snapshots, recordings, sandbox volumes, temporary Git credentials, and customer content.
- Legal/privacy deletion requirements override ordinary retention; use cryptographic erasure where WORM policy permits metadata retention.

## 7. Step-by-step backend implementation

### BE-0 — Foundations and executable contracts

**Build**

1. Create the Python/TypeScript monorepo workspaces and enforce import boundaries.
2. Define versioned Pydantic API/artifact schemas and JSON Schema export.
3. Establish CI for Ruff, formatting, strict typing, pytest, migration upgrade/downgrade, OpenAPI generation/drift, container scanning, and changed-prompt evals.
4. Create local infrastructure for PostgreSQL, Redis, object store, internal Git, model-gateway stub, and telemetry collector.
5. Add correlation IDs, structured logs, OTel setup, secret filtering, and RFC 9457 error middleware.
6. Write architecture decisions for exact dependency versions, Postgres 17 vs 18, sandbox runtime, model providers, Git hosts, and single-tenant deployment.

**Exit criteria**

- One command starts a synthetic local environment.
- Schemas generate OpenAPI and frontend types deterministically.
- A trace spans API request, DB transaction, and fake background run without sensitive payloads.

### BE-1 — Identity, authorization, jobs, uploads, and audit

**Build**

1. Validate OIDC JWTs against pinned issuer/audience/JWKS behavior and map IdP groups to application roles.
2. Enforce organization and job membership in service/repository queries, not only routers.
3. Implement presigned uploads with purpose, content-length limits, expiry, SHA-256 verification, and sealed state.
4. Implement idempotent job creation with immutable source reference, target/profile version, constraints, command arrays, runtime references, endpoint policy, retention, budget, and concurrency cap.
5. Implement pause/resume/cancel/budget lifecycle policy and append audit events transactionally.
6. Add a transactional outbox for notifications and state events.

**Exit criteria**

- Authz matrix tests cover owner, reviewer, approver, admin, nonmember, and service identities.
- Retried job creation produces one job.
- Raw Git/model credentials never enter database JSON, logs, or audit payloads.

### BE-2 — Secure repository validation and correction

**Build**

1. For Git, validate schemes/hosts, prevent SSRF and local-network access, resolve and pin the revision, restrict submodules/LFS, use short-lived credentials, and snapshot the exact commit.
2. For ZIP, reject absolute paths, traversal, symlink/hardlink escapes, device names, nested/compression bombs, excessive files/bytes, and unsupported encryption before extraction.
3. Quarantine input and run language/build/dependency detection, manifest checks, secret scanning, command-policy validation, runtime readiness, target-profile availability, and repository-size policy.
4. Never execute repository-provided build hooks during validation outside the isolated legacy sandbox.
5. Produce structured findings with stable codes, severity, redacted evidence, correction fields, and retryability.
6. Allow configuration corrections only in safe states; each change creates `job_configuration_version` and a new validation run.
7. Promote only a hash-verified, safe snapshot to analysis.

**Exit criteria**

- Adversarial archive/Git corpus passes traversal, bomb, SSRF, submodule, secret, and command-injection tests.
- Same pinned revision yields a reproducible inventory baseline.
- A blocking finding cannot be bypassed by direct API calls.

### BE-3 — Durable job graph, artifacts, events, and restart safety

**Build**

1. Implement `job_run_request` claiming with `FOR UPDATE SKIP LOCKED`, lease expiry, fencing token, heartbeat, attempt count, and idempotent completion.
2. Use one durable LangGraph thread per job and artifact references in state.
3. Implement graph nodes for intake, analyze, architect draft, feasibility, G1, fork, G2 branch, G3 branch, join, schema, dispatch/await, integrate, verify/review, G4, and delivery.
4. Use typed interrupt response schemas. Remember that a resumed LangGraph node restarts from the beginning: every action before `interrupt()` must be read-only or idempotent.
5. Support simultaneous G2/G3 interrupts by stable interrupt/gate IDs and test resume in either order.
6. Implement artifact canonicalization, hash verification, schema validation, derivation links, and object-store atomic publish.
7. Append job events with per-job monotonic sequence in the same transaction as state changes; replay from Postgres before Redis live events.
8. Use a dedicated connection or transaction-scoped advisory lock correctly; do not return a session-level locked connection to the pool.

**Exit criteria**

- Kill/restart the runner before and after every node side effect without duplicate artifacts, gates, tasks, or events.
- G2 and G3 survive concurrent open/resume/rejection scenarios.
- SSE reconnect from any retained sequence reconstructs the current view.

### BE-4 — Agent runtime and least-privilege tools

**Build**

1. Define one `AgentSpec` runtime with prompt version/hash, output schema, tool allowlist, model tier, turn/output limits, budget share, and mode.
2. Require completion through `submit_<artifact>`; validate Pydantic shape plus semantic rules such as resolvable CodeRefs, complete capability mapping, and allowed paths.
3. Implement schema-retry limits, tool timeouts/output pagination, context compaction, progress notes, and replay records.
4. Wrap repository/tool output as untrusted data; scan injection attempts and attach flags without obeying repository instructions.
5. Redact secrets and personal data before model calls and telemetry. Store only safe summaries by default.
6. Enforce job endpoint allowlists at the gateway, fixed model routes, retry/fallback policy, token/cost metering, and denial beyond budget.
7. Provide typed tools for repository, analysis, SQL, artifacts, profiles/catalogs, sandboxes, harness, Git, SAST/dependencies/SBOM, and run notes. Never expose a generic shell.
8. Implement the Supervisor as deterministic code. Use its advisor only for ambiguous repair tactic selection, with rule-based output winning on disagreement.

**Exit criteria**

- Seeded prompt injection causes zero unauthorized tool calls.
- Seeded secrets/PII appear in neither prompt logs nor submitted artifacts.
- Tool/path/command/model endpoint violations fail closed and are audited.
- Every agent output can be replayed from recorded versions and artifact IDs.

### BE-5 — Analysis, draft architecture, feasibility, and G1

**Build**

1. Intake produces `RepoInventory`: measured languages/LOC, build systems, entry points, tests, schemas, runtime requirements, integrations, and excluded paths.
2. Deterministic parsers/LSP/graph builders create AST, symbol, call/dependency, SQL, and searchable code indexes.
3. Legacy Analyzer runs by slice and deterministic merge creates a complete `LegacyModel`; every business rule and capability requires a CodeRef.
4. Architect draft maps capabilities into a candidate target structure without treating it as approved.
5. Feasibility rates every capability, checks real packages/licenses/advisories and sandbox tooling, records provenance/confidence, and provides permitted options for every gap.
6. Always open G1 with report and draft blueprint. Validate choices server-side, persist constraints, and route change-target/request-changes/cancel correctly.
7. Recompute affected artifacts when the target changes; do not reuse incompatible indexes or estimates silently.

**Exit criteria**

- Seeded capability gaps and business rules meet agreed recall/evidence thresholds on reference repositories.
- A no-gap job still pauses at G1.
- No downstream branch starts without the committed current G1 decision.

### BE-6 — Sandbox controller and characterization branch (G2)

**Build platform isolation**

1. Resolve signed, pinned stack images and create separate legacy/converted namespaces with gVisor or approved equivalent.
2. Enforce non-root, read-only root filesystem, seccomp, no service-account token, resource/time quotas, capped output, and default-deny egress through an allowlisted package proxy.
3. Use argv execution only; commands and working directories come from the pinned stack profile. Deny shells, network utilities, and arbitrary package installation.
4. Build environment recipes as reviewable artifacts; never use production secrets or live production data.
5. Stub external HTTP/SOAP, queue, file, and database dependencies from sanitized recordings.

**Build characterization**

1. Implement language-neutral JSON cases and adapters for unit, API contract, data effect, batch/file, then UI flow.
2. Gather passing legacy tests, sanitized user fixtures/traffic, generated boundary/branch inputs, and user scenarios in that order.
3. Run candidates three times on legacy and mark nondeterminism; proposed normalization must be narrower than observed variation.
4. Capture expected outputs from runtime only. Mark static fallback explicitly with lower confidence.
5. Measure coverage by module, rank uncovered code by risk, and stop only on budget/risk policy with a visible ceiling.
6. At G2 decision, validate all scope/quirk/rule choices, canonicalize the suite, hash and freeze it, and revoke CodeWriter write access.

**Exit criteria**

- Each accepted case has provenance, sanitized fixtures, repeatable result or approved nondeterminism handling, and CodeRefs.
- Frozen suite mutation causes an abort, incident event, and paused job.
- Missing legacy runtime evidence is visible at G2 and carried through G4.

### BE-7 — Final blueprint, Planner, and G3 branch

**Build**

1. Architect final consumes G1 constraints and returns explicit modules, contracts, data ownership, integrations, unmapped code, and decision rationale.
2. Planner normalizes dependency edges, detects strongly connected components, groups/splits safely, produces leaf-first order, parallel groups, schema dependencies, risk, time, and cost ranges.
3. Guarantee each in-scope legacy path belongs to exactly one module and every target module appears exactly once.
4. Reserve integration/repair budget and flag plans beyond the approved job budget.
5. Open G3 with exact blueprint, plan, profile, estimate, and diffs. Rejections create new artifact versions.
6. Join only current approved G2 and current approved G3 whose shared G1 dependency still matches.

**Exit criteria**

- Cycles and schema dependencies have explicit resolution.
- Plan estimates are reproducible from recorded price/model/profile inputs.
- No module task exists before the G2/G3 join succeeds.

### BE-8 — Schema/Data and dependency-aware module conversion

**Build Schema & Data**

1. Map every legacy column/object to target, dropped-with-reason, or retained legacy dependency.
2. Generate native target migrations and sample-data migration scripts within allowed paths.
3. Apply to an empty database, migrate sanitized sample data, and verify row counts, constraints, keys, precision, checksums, reversibility, and schema diff.
4. Publish the schema contract and unblock only dependent modules after verification.

**Build workers and module subgraph**

1. Normalize `module_dependency` and atomically queue only ready modules within per-job/global concurrency caps.
2. Claim tasks with lease, fencing token, heartbeat, and checkpointed `thread_id = job_id:module_id`.
3. For each module run: load pinned context -> CodeWriter -> validate paths/change set -> build/type/lint/format/security -> frozen test slice -> Verifier -> Reviewer -> decide.
4. Start repairs from the module base commit, not the prior failed branch. Record tactic and compare failure IDs.
5. Use bounded policy: initial conversion, smaller-change tactic, stronger reasoning tactic, then escalate; skip ineffective repeats under the no-progress rule.
6. Keep independent modules running while one escalation interrupt is open.
7. Store immutable attempts, commits, check outputs, costs, contracts, and failure classifications.

**Exit criteria**

- A killed worker resumes without duplicate commits/cost entries and stale workers cannot complete after lease loss.
- Path traversal, unexpected binary/generated files, unapproved dependencies, test edits, or suite hash mismatch fail closed.
- No failed/escalated/dropped module disappears from reports.

### BE-9 — Integration, full verification, Reviewer, and G4

**Build**

1. Merge accepted module branches in plan order to the internal integration branch. Resolve mechanical conflicts only; reroute semantic conflicts to the owning module.
2. Run full build, type/lint/format, frozen suite, schema/data checks on safe samples, contract checks, SAST, dependency/license scans, and SBOM generation.
3. Verifier classifies every difference as regression, intended difference with G2 decision ID, nondeterministic with rerun evidence, test defect with evidence, or infrastructure failure.
4. Reviewer checks architecture, security, dependencies, business-rule coverage, and test gaming. Critical/high findings and unmatched regressions block by default.
5. Targeted failures redispatch owning modules and produce a new integration commit/result version.
6. Generate the G4 report with exact commit, suite hash, pass rate, coverage ceiling, uncovered risk, descoped capabilities, findings, waivers, model/tool provenance, cost, and limitations.
7. Validate waiver authority/category and require per-item reasons. Open G4 only when all mandatory evidence is present or explicitly presented as blocking.

**Exit criteria**

- Zero unexplained differences reach an approvable G4.
- The report cannot serialize an unqualified equivalence claim.
- G4 rejection can target modules without losing prior immutable evidence.

### BE-10 — Post-G4 Git delivery

**Build**

1. In the same transaction as G4 approval, create an idempotent delivery request containing job, approved integration commit, host connection, target repository, branch name, and report version.
2. A delivery worker validates the current approval/commit, creates or safely updates `modernize/<job-short-id>`, pushes the exact commit, and opens one PR.
3. PR body includes modules, test pass rate and coverage ceiling, waivers, known gaps, descoped capabilities, uncovered risk, SBOM link, and reproduction steps.
4. Reconcile timeouts by querying the Git host with the idempotency marker before retrying creation.
5. Verify signed webhooks and deduplicate delivery-status changes.
6. Never request merge, production deployment, or privileged branch bypass scopes.

**Exit criteria**

- No customer-host write occurs before G4 approval.
- Repeated delivery attempts create one branch/PR.
- Job reaches `delivered` after PR creation, while later PR merge/close remains external status.

### BE-11 — Hardening, operations, and pilot

**Build and prove**

1. Crash/failover tests for API, runner, worker, Redis, Postgres, object store partial writes, model timeouts, and Git timeouts.
2. Security suites for authz, malicious repos, prompt injection, seeded secrets/PII, sandbox escape, egress, dependency supply chain, webhook signatures, and artifact access.
3. Load tests for 20 concurrent jobs, 200 module tasks, and 200 SSE clients; tune DB pools, claim queries, checkpoints, and event retention from measurements.
4. Alerts for stuck non-gate stages, lease churn, schema retries, budget anomalies, suite hash mismatch, delivery failure, and sandbox policy violations.
5. Retention/deletion evidence, WORM audit export, backup/PITR, restore drill, credential rotation, and incident runbooks.
6. Reference jobs for supported stack paths and a controlled customer pilot with human approval at every gate.

**Exit criteria**

- No unresolved critical/high security issue.
- Restore and runner/worker recovery are demonstrated, not documented only.
- Reference-job quality does not regress beyond the approved pass-rate, evidence, cost, and security thresholds.

## 8. Agent and artifact implementation order

Implement deterministic infrastructure before the agent that depends on it:

1. `RepoInventory` schema, repository tools, then Intake.
2. Code/SQL/graph indexes, `LegacyModel`, sliced Analyzer, deterministic merge.
3. Profiles/catalogs, `TargetBlueprint` draft, Feasibility, G1.
4. Sandbox/harness/coverage, `CharacterizationSuite`, Characterizer, G2.
5. `TargetBlueprint` final, `ConversionPlan`, Architect/Planner, G3.
6. Schema verification tools, `SchemaPlan`, Schema & Data.
7. Git path controls, `ChangeSet`, CodeWriter convert/repair.
8. Result comparison, `EquivalenceReport`, Verifier.
9. SAST/dependency policies, `ReviewFindings`, Reviewer.
10. Ordered merge/SBOM/delivery adapters, `JobReport`, Integrator.

Every artifact includes schema version, content hash, producer run, input artifact IDs, prompt/model/tool/profile/catalog versions, `needs_human`, injection flags, and safe provenance.

## 9. Security and data-handling requirements

- Treat repository text, docs, comments, traffic, tool output, and generated code as untrusted data.
- Use per-agent tool allowlists, per-module read/write scopes, argv command allowlists, output caps, timeouts, and no generic network tools.
- Separate legacy and converted sandboxes; no service account token, host mounts, Docker socket, or platform database credentials.
- Use short-lived scoped service/Git/model credentials and secret references; rotate/revoke at job completion.
- Route package access through controlled mirrors and pin image digests and dependency locks.
- Redact before model and telemetry boundaries, not only before display.
- Encrypt transport and storage; authorize every artifact/object request and use short-lived download URLs.
- Sign images, retain SBOMs, scan platform and generated dependencies, and verify webhook signatures.
- Record model-provider data policy per job; restricted jobs must be technically unable to reach external providers.

## 10. Reliability, cost, and observability

### Reliability

- All queue consumers use leases plus fencing; all completion writes check the current fencing token.
- Checkpoint and side-effect commit ordering is explicit and tested for every node.
- Object publish uses temporary key -> hash verify -> metadata transaction -> immutable final key.
- Pause/cancel stops new claims first, then cooperatively terminates active work at safe points and forcibly expires after policy timeout.
- Checkpoints reference artifacts only and are pruned by a measured retention policy.

### Cost

- Reserve a configurable percentage for repairs/integration before module allocation.
- Reserve the maximum permitted cost atomically before each model/sandbox call, derive model `max_tokens` and runtime limits from that reservation, then settle actual cost and release the remainder. This prevents parallel workers from collectively crossing the hard limit.
- Write `cost_ledger` and settle job/module spend atomically after each billable call.
- Check remaining unreserved budget before dispatch and again at the gateway/sandbox boundary.
- Emit 80% warning once per budget scope; emit hard-stop/escalation at 100%.
- Store the price-table version used for G3 estimates and actual-cost reconciliation.

### Observability

- Trace hierarchy: job -> node -> agent run -> model/tool/sandbox/Git call.
- Correlate `job_id`, `module_id`, `attempt_id`, `artifact_id`, `gate_id`, and event sequence without code content.
- Metrics: stage/gate duration, queue depth/age, lease expiry, schema retry, tool failure, pass/coverage, escalation, budget, SSE lag/replay, delivery.
- PostgreSQL audit and cost ledgers remain authoritative; telemetry backends are diagnostic only.

## 11. Backend test strategy

### Unit

- State transitions, gate response validation, ready-module calculation, risk/budget math, tactic/no-progress rules.
- Archive/Git validation, CodeRef/path/command policy, canonical hashing, redaction, endpoint allowlist.
- Event sequencing, idempotency, lease/fencing, waiver policy, report wording constraints.

### Integration

- API + Postgres + object store with authz and migration tests.
- Runner/checkpointer interrupt and restart tests with fake deterministic model responses.
- Worker leases and subgraph checkpoints with forced crashes.
- Sandbox controller policy against a disposable cluster.
- Git adapters against test organizations/repositories with minimum scopes.

### Agent evaluations

- Schema validity 100%.
- CodeRef resolution and evidence correctness against seeded facts.
- Recall of seeded business rules/capabilities/gaps and precision of classifications.
- Prompt-injection resistance and zero seeded secret/PII leakage.
- Test-gaming detection and correct escalation for missing evidence.

### End-to-end/reference jobs

- Cover runnable and non-runnable legacy environments, data migrations, UI flows, stored procedures, nondeterminism, unsupported capabilities, budget exhaustion, module escalation, G4 rejection, and delivery timeout recovery.
- Run gates in both G2/G3 approval orders and with one/both rejected.
- Assert no customer-host branch/PR before G4 and no merge/deploy action at any time.

## 12. Delivery milestones

| Milestone | Demonstrable result |
|---|---|
| B1 Foundation | Authenticated user creates an audited job |
| B2 Safe intake | Git/ZIP validates, blocks unsafe input, supports correction |
| B3 Durable graph | Intake reaches G1 and resumes after runner restart |
| B4 Analysis | Reference jobs produce evidence-linked G1 reports |
| B5 Parallel approvals | G2/G3 open and resume independently; suite freezes |
| B6 Conversion | Dependency-aware workers pass module loop and crash recovery |
| B7 Verification | Integration produces fully classified G4 evidence |
| B8 Delivery | Approved G4 creates exactly one external PR |
| B9 Hardening | Security/load/restore suites pass and pilot is accepted |

## 13. Decisions required before production coding completes

1. Supported V1 source/target stack pairs and maximum repository/module sizes.
2. Sandbox technology and whether Windows-only legacy workloads require a node pool or customer-hosted runtime.
3. Allowed model providers/data-retention terms and self-hosted model quality baseline.
4. Git hosts, app installation model, network reachability, and minimum PR scopes.
5. Gate SLA/reminder policy, waiver categories/authorities, and maximum rejection rounds.
6. Artifact/audit retention, privacy deletion, WORM duration, and customer export requirements.
7. Cost/pricing presentation, hard budget ownership, and whether sandbox runtime is metered with model usage.
8. Exact pilot owner, sanitized data/runtime responsibility, success metrics, and manual baseline.

## 14. Backend definition of done

The backend is ready for a production pilot when an authorized user can submit a pinned ZIP or Git source; unsafe content is quarantined; correctable validation errors can be fixed; the durable graph produces evidence-linked artifacts and pauses at mandatory G1, parallel G2/G3, escalations, and G4; frozen tests are hash-enforced; modules convert in dependency order under hard budgets and isolated execution; crashes resume without duplicate side effects; every difference is classified without overstating equivalence; and an exact approved integration commit creates one customer pull request after G4 with no capability to merge or deploy it.
