# Legacy Modernization Platform — UI Implementation Plan

## 1. Outcome and scope

Build a review-first web application that takes an engineering lead from job creation through repository validation, four human approval gates, module conversion monitoring, evidence review, and pull-request handoff.

This plan covers the Next.js application, browser-facing authentication, API integration, live progress, accessibility, frontend tests, and release sequencing. It does not implement agents, orchestration, sandbox execution, or Git operations; those are backend responsibilities described in `backend_implementation_plan.md`.

## 2. Verified workflow and binding decisions

The requested seven-step journey, the 71-page build specification, and the supplied Mermaid diagram describe the same main flow. The following reconciliations are binding for implementation:

1. **G1 is always a human gate.** The build spec conditionally bypasses G1 when no gap exists, but the requested journey requires the user to review and approve feasibility. The UI must always show G1. A no-gap report has a shorter approval form, not an automatic approval.
2. **A draft architecture precedes G1.** Feasibility cannot map legacy capabilities to a target stack without a draft target blueprint. Show it as supporting evidence at G1; the final blueprint remains subject to G3.
3. **G2 and G3 are independent and parallel.** Both can be open at the same time. Conversion remains blocked until both are approved.
4. **G2 freezes an exact test-suite version.** The approved hash, scope, normalization rules, and legacy-quirk decisions are immutable. Any later test change creates a new version and reopens G2.
5. **Schema planning follows the G2/G3 join.** Schema & Data runs only after both gates are approved, before dependent conversion modules can start.
6. **Verification is evidence-limited.** The UI may show “all in-scope tests passed”; it must not show “equivalent” without the associated coverage ceiling, uncovered code, and unresolved evidence gaps.
7. **Internal Git branches exist before G4; external delivery happens after G4.** Module and integration branches are implementation details needed for conversion. The customer-host branch and pull request are created only after G4 approval. Merge remains a user action, and production deployment is never triggered by this product.
8. **Failed validation is correctable.** Unsafe input remains blocked. Correctable configuration or access errors return the job to an editable validation state without requiring a new job.
9. **Repairs are bounded.** The module view must expose attempt count, tactic, budget, repeated failures, and escalation; it must not imply that retries continue indefinitely.
10. **Reject, request changes, cancel, pause, and resume are distinct actions.** Each has different consequences and requires explicit confirmation where data or compute may be lost.

### Journey-to-screen traceability

| User journey | Primary UI | Completion signal |
|---|---|---|
| 1. Login and create job | `/login`, `/jobs`, `/jobs/new` | Job accepted with immutable ID and queued validation |
| 2. Validate repository | Job overview validation panel | Validation passes, or actionable issues are corrected and rechecked |
| 3. Analyze and approve G1 | Analysis view and `/gates/g1` | Named approver submits feasibility decisions |
| 4. Prepare tests and architecture | `/gates/g2` and `/gates/g3` | Frozen suite hash and approved blueprint/plan both exist |
| 5. Convert codebase | Module DAG and module details | All required modules reach a terminal acceptable state |
| 6. Verify behavior and quality | Test results, findings, escalation views | Every difference is classified; unresolved evidence is visible |
| 7. Final review and delivery | `/gates/g4`, delivery panel | G4 approved, PR created, user follows external link to review/merge |

## 3. Frontend technical baseline

- Next.js 16 App Router, React 19, and TypeScript 5 in strict mode.
- shadcn/ui over Radix primitives with Tailwind CSS 4.
- TanStack Query for server state; Zustand only for local view state such as diff selections and DAG filters.
- React Hook Form plus Zod for forms. Generate API types from the backend OpenAPI contract and keep handwritten UI-only validation separate.
- TanStack Table with row virtualization for feasibility items, tests, findings, and audit events.
- React Flow plus ELK.js for dependency and module DAGs.
- Monaco read-only/diff editors, lazy-loaded on routes that need them.
- Recharts for budget, coverage, pass-rate, and stage-duration summaries.
- Vitest and React Testing Library for components; MSW for API behavior; Playwright for end-to-end journeys.
- WCAG 2.2 AA as the acceptance target.

As of 2026-10-14, Next.js 16.x and React 19.x are valid choices, but exact patches must be locked in the repository rather than copied from this document. Next.js 16.4 and React 19.3 are the current documented lines. Review security advisories before the first lockfile is committed.

## 4. Information architecture and routes

### Global routes

| Route | Purpose | Allowed roles |
|---|---|---|
| `/login` | OIDC sign-in and authentication error recovery | Public |
| `/jobs` | Searchable job list with state, stage, cost, owner, and pending gates | Job members |
| `/jobs/new` | Create-job wizard | Owner |
| `/admin/catalogs` | Versioned capability catalog editor | Admin |
| `/admin/profiles` | Versioned target-stack profile editor | Admin |
| `/admin/users` | User/role mapping and access diagnostics | Admin |

### Job routes

| Route | Purpose |
|---|---|
| `/jobs/[jobId]` | Overview, stage timeline, validation, pending actions, live events, budget |
| `/jobs/[jobId]/analysis` | Inventory, draft blueprint, capability map, dependency graph, risks |
| `/jobs/[jobId]/gates/g1` | Feasibility review and per-gap decisions |
| `/jobs/[jobId]/gates/g2` | Characterization scope, quirks, normalization rules, freeze action |
| `/jobs/[jobId]/gates/g3` | Final blueprint, module DAG, order, estimates, profile |
| `/jobs/[jobId]/gates/g4` | Final evidence, waivers, uncovered code, SBOM, PR preview |
| `/jobs/[jobId]/modules` | Live DAG and queue/conversion status |
| `/jobs/[jobId]/modules/[moduleId]` | Attempt timeline, failures, changes, checks, escalation |
| `/jobs/[jobId]/tests` | Suite summary and filterable case list |
| `/jobs/[jobId]/tests/[testId]` | Legacy/target results, normalized and raw-safe diffs |
| `/jobs/[jobId]/lineage` | Target line to legacy evidence, tests, decisions, and agent run |
| `/jobs/[jobId]/audit` | Append-only audit/event explorer and export |
| `/jobs/[jobId]/report` | Final report and delivery status |

Use a shared job layout with persistent stage navigation, pending-gate badges, budget status, last-event time, and lifecycle actions. A user must never have to infer whether the job is running, waiting for them, blocked, paused, cancelled, failed, or delivered.

## 5. Shared UX rules

### Status vocabulary

Render backend states without inventing frontend-only synonyms:

- Job: `draft`, `validating`, `needs_correction`, `analyzing`, `waiting_gate`, `planning`, `converting`, `verifying`, `paused`, `failed`, `cancelled`, `approved`, `delivering`, `delivered`.
- Gate: `not_ready`, `open`, `approved`, `rejected`, `timed_out`, `superseded`.
- Module: `blocked`, `queued`, `running`, `repairing`, `escalated`, `done`, `dropped`, `failed`.
- Evidence: `complete`, `partial`, `missing`, `waived`; never convert `partial` into a success color.

All status chips need text and icon differences, not color alone.

### Gate pattern shared by G1–G4

Every gate page must include:

1. What this gate decides and which downstream work it blocks.
2. Request time, due time, current reviewer, source artifact versions, and budget used.
3. `needs_human`, uncertainty, injection, and missing-evidence items pinned above normal content.
4. Artifact view with evidence links and a diff against the preceding version after rejection.
5. Required per-item decisions before global approval becomes available.
6. Required feedback on rejection and required rationale for every waiver.
7. A final confirmation summarizing irreversible effects, such as freezing the G2 suite.
8. Conflict handling for HTTP 409 when another approver has already decided the gate.

Track which required items were opened and include that evidence in the submitted decision. Do not use elapsed reading time as proof of meaningful review; it is audit context only.

### Evidence presentation

- Show source path, commit, line range, artifact version, and confidence with every code-backed claim.
- Open code references in a drawer so the reviewer keeps their place.
- Label inferred/static evidence separately from captured/runtime evidence.
- Show pass rate next to coverage ceiling and uncovered-risk count everywhere.
- Preserve raw result artifacts for authorized download, but redact secrets and personal data in browser-visible previews.
- Provide a “Why is this blocked?” affordance that names unmet prerequisites and links to the action owner.

### Destructive and external actions

- `Cancel` requires job-name confirmation and explains artifact retention.
- `Pause` stops new work but preserves resumability; `Resume` shows estimated remaining budget.
- G4 approval explicitly states that it authorizes PR creation, not merge or deployment.
- External links to the PR open with a clear host/domain indicator.

## 6. Step-by-step UI implementation

### UI-0 — Bootstrap contracts, quality gates, and design primitives

**Build**

1. Create `apps/web` with the App Router, strict TypeScript, lint/format/typecheck, Vitest, Playwright, and MSW.
2. Add CI generation of `lib/api/schema.d.ts` and the typed API client from the backend OpenAPI document. Fail CI on uncommitted schema drift.
3. Define design tokens for statuses, severity, risk, confidence, focus, and data visualization.
4. Build primitives: `StatusChip`, `SeverityBadge`, `EvidenceLink`, `CodeRefDrawer`, `BudgetMeter`, `EmptyState`, `ProblemDetails`, `ConfirmAction`, and accessible table/toolbar wrappers.
5. Add Storybook or an equivalent component workbench for data-dense states, errors, loading, and keyboard testing.
6. Establish frontend telemetry with page/route errors and Web Vitals. Never include code snippets, test payloads, repository URLs with credentials, access tokens, or form secrets.

**Exit criteria**

- CI runs lint, typecheck, unit tests, accessibility smoke tests, production build, and OpenAPI drift check.
- Shared components demonstrate loading, empty, partial, stale, error, unauthorized, and forbidden states.
- No route uses untyped `fetch` calls.

### UI-1 — Authentication, authorization, shell, and job list

**Build**

1. Configure Auth.js OIDC login, callback, logout, token refresh, and session-expired recovery.
2. Implement the authenticated application shell, skip link, breadcrumbs, notification area, and role-aware navigation.
3. Load the signed-in user and effective roles from the API; UI hiding is convenience only, never the authorization boundary.
4. Build `/jobs` with server-rendered initial data, URL-backed filters, pagination, sort, pending-action indicators, cost/budget, and accessible row navigation.
5. Add 401 re-authentication and 403 access-request guidance without leaking whether an inaccessible job exists.

**API dependencies**

`GET /api/v1/me`, `GET /api/v1/jobs`.

**Exit criteria**

- Login, logout, expired-token recovery, and role-specific navigation pass Playwright tests.
- A user can see only jobs returned by server-side membership enforcement.

### UI-2 — Create-job wizard

**Build**

1. Implement five resumable steps: source, target stack, constraints/commands, legacy runtime, model policy/budget.
2. Source supports either Git URL plus revision/credentials reference or ZIP upload. Never request a raw Git token in a normal text field; use an approved credential connection or secret reference.
3. Validate archive size/type before upload and use direct-to-object-store presigned upload with progress, cancellation, expiry recovery, and checksum display.
4. Populate target choices from versioned stack profiles. Show support level (`curated`, `provisional`, `unsupported`) before submission.
5. Capture build, test, lint, and startup commands as structured argument arrays where possible. Clearly label shell-like commands as subject to backend policy validation.
6. Capture constraints, repository subdirectory, runtime recipe uploads, network/data restrictions, allowed model endpoints, retention, budget, and maximum parallel modules.
7. Show a final review page and preserve non-secret draft values locally during authentication refresh.
8. On submit, disable duplicate requests and use an idempotency key.

**API dependencies**

`POST /api/v1/uploads`, `GET /api/v1/profiles`, `POST /api/v1/jobs`.

**Exit criteria**

- Both ZIP and Git flows create exactly one job under retries/double-clicks.
- Invalid or unsupported combinations are explained before submission where deterministic, and server validation errors map to the correct wizard fields.

### UI-3 — Repository validation and correction loop

**Build**

1. Add a validation card to the job overview with source access, archive safety, structure, languages/build systems, dependencies, runtime readiness, secret findings, command policy, target support, and sandbox readiness.
2. Group findings by `blocking`, `action_required`, and `warning`; include a stable error code, evidence location, owner, and recommended correction.
3. For correctable issues, open a form prefilled with editable job configuration and submit an optimistic-concurrency version.
4. For unsafe archive traversal, disallowed executable content, detected credentials, or forbidden target/model endpoints, prevent continuation and explain the safe remediation without displaying secret values.
5. Provide `Re-run validation`; show which checks are reused and which rerun.
6. Surface validation logs only through redacted, paginated artifacts.

**API dependencies**

`GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/validation`, `PATCH /api/v1/jobs/{id}/configuration`, `POST /api/v1/jobs/{id}/validation-runs`.

**Exit criteria**

- Every blocking backend validation code has a designed UI state and actionable next step.
- A corrected configuration creates a new validation run while preserving earlier evidence in the audit view.
- Unsafe input cannot expose an enabled continue/approve action.

### UI-4 — Analysis and G1 feasibility review

**Build**

1. Build the analysis page for inventory, entry points, dependencies, DB assets, business rules, capability map, confidence, and draft blueprint.
2. Render large graphs progressively; provide a table alternative and filters by module, capability, risk, and confidence.
3. Build G1 with every capability, including high-confidence native/library matches, and focus review on custom, unsupported, low-confidence, or missing-tool items.
4. For each gap show concrete options, effort range, verification impact, dependency/security/license notes, and evidence.
5. Require exactly one permitted choice per gap. Support “change target” and “request changes” without losing reviewer work.
6. Allow cancellation from G1 with an explicit retention summary.
7. For a no-gap report, show the full coverage summary and require one approval; never silently advance.

**API dependencies**

`GET /api/v1/jobs/{id}/artifacts`, `GET /api/v1/jobs/{id}/lineage`, `GET /api/v1/jobs/{id}/gates/{gateId}`, `POST /api/v1/jobs/{id}/gates/{gateId}/decisions`, and target-profile lookup when changing target.

**Exit criteria**

- Approval is impossible while a required gap choice is missing.
- Rejection feedback is preserved and the next G1 version shows an artifact diff.
- Low-confidence and missing-evidence items cannot be hidden by default filters.

### UI-5 — Parallel G2 characterization and G3 architecture planning

**Build G2**

1. List test cases by unit, API contract, data effects, batch/file, and UI flow.
2. Show provenance, three-run legacy stability, scope, risk, covered CodeRefs, and whether the expected output is runtime-captured or static/inferred.
3. Add in-scope toggles subject to role and policy; require rationale for excluding a case.
4. Present every suspected legacy quirk with `keep`, `fix as specified`, or `request more evidence`.
5. Provide a normalization-rule editor showing before/after examples and exactly what variation the rule hides.
6. Show module coverage, coverage ceiling, uncovered high-risk code, nondeterminism, and missing-runtime consequences.
7. Before approval, display the canonical suite version and SHA-256 hash and require confirmation that it will be frozen.

**Build G3**

1. Show the final architecture, target modules, contracts, data ownership, stack profile, and decisions inherited from G1.
2. Render dependency cycles, their resolution, conversion order, schema dependencies, parallel groups, risk, time, and per-module/total cost ranges.
3. Show budget reserve and block approval when the plan exceeds the approved budget unless the owner updates budget or scope through an audited action.
4. Diff final blueprint/plan against the draft and prior rejected version.

**Parallel-state behavior**

- Overview shows G2 and G3 as separate cards and never implies one approves the other.
- If one is approved while the other remains open, show the approved artifact as locked and name the remaining blocker.
- Rejection reruns only the rejected branch unless a changed decision invalidates both; the backend supplies invalidation metadata and the UI must show it.

**Exit criteria**

- G2 submission records exact case scope, quirk decisions, normalization rules, suite version, and hash.
- G3 submission records exact blueprint/plan/profile versions and estimate.
- Conversion UI stays locked until the backend reports both approved.

### UI-6 — Conversion, module checks, repairs, and escalation

**Build**

1. Build a live module DAG with list/table fallback, dependency blockers, critical path, parallel groups, and summarized progress.
2. Build module details with base commit, allowed paths, budget, attempt number, tactic, model tier, changed files, build/type/lint/security/test checks, and published contracts.
3. Provide attempt-to-attempt diffs and emphasize that repairs restart from the approved base rather than stacking unreviewed patches.
4. For failures, show classified test IDs, likely root cause, Reviewer findings, remaining retry budget, and the next deterministic action.
5. Build the escalation decision form: provide guidance, raise budget, attach a human-fix commit, split module, drop with impact, retry, pause, or terminate. Only render choices permitted by the backend payload and user role.
6. Keep independent modules updating while one is escalated; show the whole job as partially blocked only when no other ready work remains.
7. Handle stale updates and out-of-order SSE events using monotonic event sequence numbers.

**Exit criteria**

- A reviewer can explain why any module is blocked from the UI alone.
- Attempt histories are immutable and link to artifacts, agent runs, costs, and commits.
- The UI never offers retry after the backend reports hard budget exhaustion unless an authorized budget increase has completed.

### UI-7 — Verification and evidence review

**Build**

1. Build Verifier result tables with in-scope totals, pass/fail/error/blocked, classification, layer, module, and evidence quality; present Reviewer findings as a distinct quality/security assessment.
2. Build per-test views showing legacy and converted results, approved normalization effects, concise structured diff, rerun evidence, and linked decisions.
3. Build Reviewer findings by severity/category with source and target CodeRefs, dependency/license/security details, and repair status.
4. Distinguish `regression`, `intended_difference`, `nondeterministic`, `test_defect`, and `infrastructure_failure`. Intended differences must link to the authorizing G2 decision.
5. When required evidence is missing, use a neutral “not demonstrated” state, never success.
6. Show integration reroutes and the owning module when cross-module checks fail.

**Exit criteria**

- Every non-pass result has a classification or is visibly blocking.
- Any newly proposed normalization/test correction links to a reopened G2 workflow.
- Security and coverage summaries remain visible at all screen widths and in exported reports.

### UI-8 — G4 final review and delivery

**Build**

1. Compose G4 from equivalence results, pass rate with coverage ceiling, all classified differences, waivers, Reviewer findings, security/license results, SBOM, uncovered code by risk, descoped capabilities, costs, and documented limitations.
2. Require a named reason and impact acknowledgement for each permitted waiver. Never allow blanket “waive all.”
3. Show the proposed external branch name and PR title/body before approval, while clearly marking them as not yet created.
4. Approval confirmation states: “Create a customer-host branch and pull request. This does not merge or deploy.”
5. Rejection supports targeted modules and feedback. The resulting G4 version must display what changed.
6. After approval, show delivery progress, idempotent retry status, external PR URL, commit, and webhook-reported PR state.
7. Mark the modernization job complete only after PR creation succeeds. PR merge is displayed as an external status, not performed by this UI.

**Exit criteria**

- No delivery call or external PR exists before an approved G4 decision.
- The final report never states equivalence without scope, suite hash, pass rate, coverage ceiling, and limitations.
- A user can open the PR and independently review/merge it on the Git host.

### UI-9 — Lineage, audit, administration, and operational polish

**Build**

1. Implement target-line lineage to legacy CodeRefs, tests, G1/G2 decisions, model/prompt/tool versions, attempt, and artifact hashes.
2. Add append-only audit browsing with actor, action, timestamp, job/module, correlation ID, and filtered CSV export.
3. Build catalog/profile YAML editors with schema validation, version diff, staged publish, and rollback by creating a new version.
4. Add notification preferences and deep links for gate, escalation, budget, delivery, and failure events.
5. Add responsive and reduced-motion behavior, full keyboard access, focus restoration after drawers/dialogs, table alternatives for graphs, and screen-reader summaries for charts.
6. Add route-level error boundaries, retry behavior, stale-data banners, and maintenance/outage messages.

**Exit criteria**

- A reviewer can trace a target line to its evidence without database access.
- Admin changes are versioned and audited; existing jobs retain their pinned version.
- Automated accessibility checks have no serious/critical findings, followed by manual keyboard and screen-reader review of all four gates.

## 7. Live-update design

The PDF proposes browser `EventSource` plus an access token, but native `EventSource` cannot add an `Authorization` header. Implement one of these reviewed patterns:

1. Preferred: a same-origin Next.js route handler authenticates the secure Auth.js session, attaches the API token server-side, proxies the SSE body without buffering, and forwards `Last-Event-ID`.
2. Alternative: host the API on the same origin and authenticate SSE with a secure, HTTP-only, SameSite cookie plus CSRF protections for mutations.

Do not put bearer tokens in query strings.

`useJobEvents(jobId)` must:

- persist the highest monotonic `seq` seen;
- reconnect with `Last-Event-ID` and exponential backoff plus jitter;
- ignore duplicates and events older than the current sequence;
- invalidate only the affected TanStack Query keys;
- show connection state and last successful event time;
- fall back to bounded polling when streaming is unavailable;
- force a full job snapshot refresh after any detected sequence gap.

## 8. Frontend file plan

```text
apps/web/
  app/
    (auth)/login/
    (app)/jobs/
      new/
      [jobId]/
        analysis/
        gates/[gate]/
        modules/[moduleId]/
        tests/[testId]/
        lineage/
        audit/
        report/
    (admin)/admin/{catalogs,profiles,users}/
    api/auth/[...nextauth]/
    api/jobs/[jobId]/events/       # authenticated SSE proxy
  components/
    evidence/ gates/ jobs/ modules/ tests/ reports/ dag/ diff/ ui/
  features/
    auth/ job-create/ validation/ g1/ g2/ g3/ conversion/ verification/ g4/
  lib/
    api/{client.ts,schema.d.ts,query-keys.ts}
    auth/ sse/ telemetry/ validation/
  e2e/
```

Keep domain mutations in feature-level hooks, not page components. Gate form schemas must be generated from or mechanically checked against the backend decision schemas.

## 9. Frontend test plan

### Unit and component tests

- Status mapping and unknown-state fallback.
- Problem-details mapping to fields and page-level errors.
- Budget, confidence, risk, pass-rate, and coverage calculations are display-only and match API values.
- G1 per-gap completeness, G2 freeze confirmation, G3 budget blocking, G4 waiver validation.
- SSE deduplication, replay, reconnect, gap recovery, and polling fallback.
- Redaction rendering and safe handling of untrusted repository text.
- Keyboard/focus behavior for drawers, dialogs, virtual tables, Monaco, and DAG alternative views.

### Contract tests

- Generate fixtures from OpenAPI examples for every job, gate, module, test, artifact, validation, and report state.
- Verify every known RFC 9457 `code` has an intentional UI behavior.
- Verify all mutations send idempotency or optimistic-concurrency headers where required.

### Playwright journeys

1. Git job creation through correctable validation failure and successful recheck.
2. ZIP job rejected for unsafe archive content.
3. G1 no-gap approval and G1 gap-by-gap choices/change-target/rejection.
4. G2 and G3 open concurrently and approve in either order.
5. G2 freeze with normalization and quirk decisions.
6. Module failure, bounded repairs, budget warning, escalation, and resume.
7. Verification with regression, intended difference, nondeterminism, test defect, and missing evidence.
8. G4 waiver validation, approval, delivery failure/retry, and successful external PR link.
9. Role/access matrix and concurrent gate decision conflict.
10. SSE disconnect/replay and runner restart without duplicate visible work.

## 10. Delivery sequence and dependencies

| Increment | UI result | Backend contract needed |
|---|---|---|
| U1 | Login, shell, job list, create wizard | Auth, profiles, uploads, jobs |
| U2 | Validation/correction and live overview | Validation resources, events |
| U3 | Analysis and G1 | Artifacts, lineage, G1 schema |
| U4 | Parallel G2/G3 | Test suite, blueprint/plan, gate concurrency |
| U5 | Module DAG, attempts, escalation | Modules, attempts, escalation decisions |
| U6 | Verification and G4 | Results, findings, reports, waivers |
| U7 | Delivery, lineage, audit, admin | Git delivery state, lineage, audit, catalogs/profiles |
| U8 | Accessibility, load, security, pilot polish | Stable API and representative staging jobs |

Frontend development should use generated fixtures and a fake event stream before each backend stage is live. Integrate against the real API at the end of every increment rather than deferring integration to the end.

## 11. UI definition of done

The UI is ready for a production pilot when a named user can create either a ZIP or Git job, correct validation failures, approve G1, independently review and approve G2/G3, monitor parallel conversion and bounded repairs, resolve escalations, inspect every result and evidence limitation at G4, authorize PR creation, and follow the resulting PR without any path that merges or deploys code. All state survives refresh and reconnect, authorization is enforced by the backend, all four gates are keyboard and screen-reader usable, and the UI never overstates behavioral equivalence.
