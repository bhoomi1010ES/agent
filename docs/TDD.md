# TDD: Multi-Agent Legacy Code
# Modernization Platform
Oct 13, 2026 · @Raj
## 1. Overview and goals
The platform takes a legacy codebase and a target tech stack as job inputs and returns a
modernized codebase on a Git branch, with its behavior checked against the original and
every risky decision approved by a human. Neither stack is fixed: both are supplied per
job.
Primary users: engineering leads who start a conversion job, and reviewers who approve
gates and resolve flagged items.
Goals
Convert any legacy stack to any requested target stack through one stack-agnostic
pipeline.
Check, before any code is generated, whether the target stack can express everything
the legacy system does, and show the user any gaps and the tools needed to fill them.
Prove behavioral equivalence with characterization tests captured from the legacy
system, not with tests the converting agents wrote about their own output.
Keep humans in control through explicit approval gates at the points where a wrong
decision is expensive to undo.
Make every job resumable, auditable and cost-bounded.
Proposed success criteria (to be calibrated on pilot jobs)
Metric Target
Characterization tests passing on the
converted code before final review
95% or more of the tests the user accepted
as in scope
Behavior differences left unexplained at final
review
0 (each is fixed, or waived by a named
reviewer)
Jobs that resume correctly after a worker or
process crash
100%
Human gate decisions with a stored rationale
and artifact diff
100%
TDD: Multi-Agent Legacy Code Modernization Platform
Page 1 of 16

---

## 2. Scope, non-goals and assumptions
V1 converts application source code, its tests and its schema/config into a target stack
chosen per job, and verifies the result. It does not operate the converted system in
production.
In scope
Ingesting a legacy repository (and, optionally, a running legacy instance or database
snapshot) as job input.
Analysis: inventory, dependency graph, business-capability map, risk and complexity
scoring.
Target-stack feasibility check with a gap report and a user decision.
Generation of a conversion plan, target code, schema migrations and data-migration
scripts.
Characterization-test capture, execution against both systems and an equivalence
report.
Human approval gates, an audit trail, and delivery as a Git branch and pull request.
Non-goals for V1
Production cutover, traffic shifting or data migration execution on live systems.
Guaranteeing equivalence for behavior no characterization test exercises; this is
reported as coverage, not hidden.
Automatic installation of missing target-stack tooling. The platform reports the gap
and the user chooses.
Visual pixel-perfect UI parity. UI conversion is checked by flow and DOM-level
assertions only.
Assumptions
The legacy code can be read in full, and a runnable legacy environment can be provided
for at least the core flows. Where it cannot, characterization falls back to static
analysis and the gap is flagged.
Each job has a named owner who approves gates.
LLM access is through a provider API, with per-job token and cost budgets.
Conversion proceeds module by module (strangler-style), not as one big-bang rewrite.
TDD: Multi-Agent Legacy Code Modernization Platform
Page 2 of 16

---

## 4. Agent catalog
Eleven specialist agents plus one supervisor do the work. Agents never pass free-form
chat to each other: each reads and writes typed artifacts (Pydantic models, stored per
section 9), so every handoff is validated, versioned and replayable.
Agent Responsibility Consumes → produces Main tools
Supervisor Routes work,
enforces budgets,
opens gates,
decides retry vs
escalate
Job state → next node, gate
requests
LangGraph router,
budget meter
Intake Clones the repo,
detects languages,
build systems and
entry points, sizes
the codebase
Repo URL or archive →
RepoInventory
git, linguist-style
detectors, cloc
Legacy
Analyzer
Builds the AST, call
and dependency
graphs, DB schema
map, I/O and
integration list, and
extracts business
rules
RepoInventory →
LegacyModel
tree-sitter, language
servers, SQL
parsers, optional
LLM summaries
Architect Maps legacy
capabilities to a
target architecture
and module
boundaries
LegacyModel , target stack
spec → TargetBlueprint
Pattern library, LLM
Feasibility Checks every
required capability
against the target
stack and tool
catalog
LegacyModel ,
TargetBlueprint →
FeasibilityReport
Capability catalog,
package registries,
docs search
Planner Splits the work into
modules, orders
them by
dependency,
estimates risk and
cost
TargetBlueprint →
ConversionPlan (DAG)
Graph algorithms,
LLM
TDD: Multi-Agent Legacy Code Modernization Platform
Page 3 of 16

---

Rules every agent follows
It receives only the slice of state it needs, not the full job history.
Its output must validate against its Pydantic schema before it is stored; a failed
validation counts as a retryable failure, not a result.
It records its model, prompt version, token use and tool calls on every step (section 12).
It may flag uncertainty with an explicit needs_human field; it never guesses silently.
Agent Responsibility Consumes → produces Main tools
Characterizer Captures legacy
behavior as
executable tests
and golden data
LegacyModel , legacy
runtime →
CharacterizationSuite
Test harness,
HTTP/DB recorders,
sandbox
Schema &
Data
Designs the target
schema, migrations
and data-migration
scripts
LegacyModel ,
TargetBlueprint →
SchemaPlan , migration
scripts
Alembic/Flyway-
style tooling, SQL
diff
CodeWriter
(pool)
Converts one
module at a time on
its own branch,
under schema
constraints
Module spec,
characterization slice →
code diff
Git, sandbox, linters,
LLM
Verifier Runs
characterization
tests against legacy
and converted code
and classifies every
difference
Both systems,
CharacterizationSuite →
EquivalenceReport
Test runner, diff
classifier
Reviewer Static review for
security, style and
architecture rules;
proposes repairs
Code diff,
EquivalenceReport →
findings, fix tasks
SAST, linters, LLM
Integrator Merges module
branches, runs the
full build, opens the
PR and writes the
final report
All approved modules → PR,
JobReport
git, CI, report
generator
TDD: Multi-Agent Legacy Code Modernization Platform
Page 4 of 16

---

## 6. Target-stack feasibility gate
No code is generated until the Feasibility agent has shown the user which legacy
capabilities the chosen target stack cannot cover, and the user has decided what to do
about each. This is gate G1 (section 8).
How the check runs
1. Normalize the legacy system into a list of required capabilities (for example: PDF
generation, scheduled jobs, SOAP client, session auth, a specific stored procedure, a
vendor SDK).
2. Look up each capability in the target stack's capability catalog and rate it: native,
library, custom code needed, or unsupported.
3. If the target stack has no catalog entry, the agent builds a provisional one from
package registries and official docs and marks every rating as lower confidence.
4. Check the pipeline's own readiness for that stack: a sandbox image that can build and
run it, plus a test runner, linter, formatter and security scanner.
5. Emit a FeasibilityReport . Any item rated custom, unsupported or low-confidence,
or any missing pipeline tool, opens G1.
Gap types and the options shown to the user
Gap type Example Options offered
Language or runtime
construct with no equivalent
COM interop, mainframe
copybooks
Wrap behind a service,
rewrite in custom code with
an effort estimate, descope
Framework or library with no
equivalent
Reporting engine, vendor
UI toolkit
Approve named substitute
library, build custom, descope
Integration or infrastructure Message queue, SOAP
endpoint, file drop
Add a named adapter or tool,
keep legacy component
behind an API, descope
Data-layer feature Stored procedures,
proprietary SQL
Port to application code, port
to target DB equivalent, keep
and call it
Missing pipeline tooling No test runner or SAST
for the target stack
Install the named tool in the
sandbox image, accept
reduced verification, cancel
TDD: Multi-Agent Legacy Code Modernization Platform
Page 5 of 16

---

For every option the report states what it would cost in effort and what verification
coverage it would lose. The user's choice for each gap is written back into the
TargetBlueprint as a constraint, and the Planner re-runs. The platform never installs
tooling or picks a substitute silently.
class FeasibilityItem(BaseModel):
capability: str
legacy_evidence: list[CodeRef]
rating: Literal["native", "library", "custom", "unsupported"]
candidate: str | None # library or tool that would cover it
confidence: float # below the threshold forces the gate open
options: list[GapOption] # what the user may choose
verification_impact: str # what we can no longer prove if chosen
## 7. Characterization testing and verification
Equivalence is judged by tests captured from the legacy system, frozen before conversion
starts, and never edited by the agents that write the new code. A test that only the new
code was written to pass proves nothing.
Test layers
Where test cases come from
Layer What is captured How it is replayed
Unit Input and output pairs for pure
functions and business rules,
recorded by instrumenting the
legacy runtime
Same inputs through the
converted function, compared
field by field
API contract Request and response pairs for
every endpoint or RPC, from
recorded traffic and generated
requests
Replayed against the converted
service, compared after
normalization
Data effects Database state before and after
each write operation, plus golden
query results
Same operations run on the new
schema, then mapped and
compared
Batch and file
output
Reports, exports and generated
files from fixed inputs
Compared structurally (rows,
fields, totals), not byte for byte
UI flows Key user journeys, only where the
legacy system has a UI
Headless browser run with DOM-
level assertions, not pixels
TDD: Multi-Agent Legacy Code Modernization Platform
Page 6 of 16

---

The legacy system's own tests, if any.
Sanitized production traffic or logs, when the user supplies them.
Inputs generated by the Characterizer from the analysis: boundary values, branch-
driving inputs and property-based cases.
Scenarios the user writes or approves at gate G2.
Nondeterminism. Timestamps, generated IDs, ordering and floating-point rounding are
handled by explicit normalization rules. Each rule is listed in the suite and approved at G2,
because a loose rule can hide a real regression.
Freezing. Once the user approves the suite at G2, it is stored with a content hash.
CodeWriter agents can read it but cannot change it; any later edit needs a new G2
approval and invalidates earlier results.
Classifying every difference. The Verifier labels each failing comparison, and no failure is
left unclassified:
Coverage as an honest ceiling. The suite is run against the legacy system with coverage
instrumentation. The final report lists legacy code the suite never touches, ranked by risk,
so "equivalent" always reads as "equivalent on the behavior we tested". Optionally,
mutation testing on the legacy code checks that the suite actually detects changes.
## 8. Human-in-the-loop gates
Four gates sit at the points where a wrong decision is costly to undo, plus an escalation
path for work the agents cannot finish. Everything between gates runs unattended.
Class Meaning Resolution
Regression New code behaves differently
from legacy without a reason
Repair loop (section 10)
Intended
difference
Legacy behavior is a known bug
or is being changed on purpose
Named reviewer waives it at G4,
with a reason
Nondeterministic Output varies between runs of
the legacy system itself
Add or tighten a normalization
rule, re-approve at G2
Test defect The captured test is wrong or
incomplete
Fix the test through a new G2
approval
TDD: Multi-Agent Legacy Code Modernization Platform
Page 7 of 16

---

G2 and G3 run in parallel, and conversion starts only when both are approved.
Mechanics
A gate is a LangGraph interrupt node. The full job state is checkpointed to Postgres
and the worker is released, so a pending gate costs nothing and survives restarts.
Each gate shows the artifact, a diff against the previous version, the agents' own
flagged uncertainties, and the budget used so far.
A rejection requires written feedback. The feedback is added to state and the previous
stage re-runs with it, up to a configurable number of rounds before the job is paused
for a person to take over.
Each gate has a named approver role. Waivers at G4 need a reason and are stored with
the approver's identity.
Gates time out into a paused state, never into a silent approval. Reminders go out
through the notification channel (email or chat webhook).
Gate Happens after Reviewer decides Blocks
G1 Feasibility Feasibility report Per gap: accept substitute,
add tool, build custom,
descope, or cancel
(section 6)
Planning
G2 Test suite Characterizer finishes Which behaviors are in
scope, which legacy bugs
to keep or fix, and the
normalization rules; then
freezes the suite
Code
conversion
G3 Blueprint
and plan
Architect and Planner
finish
Target architecture,
module boundaries,
conversion order, cost and
time estimate
Code
conversion
G4 Final
review
Verifier and Reviewer
finish all modules
Equivalence report,
waivers for intended
differences, uncovered-
code list; approves the pull
request
Merge and
delivery
Escalation A module exhausts its
repair attempts or its
budget
Give guidance, raise the
budget, hand-fix, or drop
the module
That module
only
TDD: Multi-Agent Legacy Code Modernization Platform
Page 8 of 16

---

Reviewers work through a web UI and a matching REST API; both resume the graph by
posting a decision to /jobs/{id}/gates/{gate} .
## 9. Data model and persistence
Postgres is the single system of record: LangGraph checkpoints, job metadata and
artifact metadata all live there. Large binaries (repository snapshots, recorded traffic,
build logs) go to an S3-compatible object store and are referenced by content hash.
TDD: Multi-Agent Legacy Code Modernization Platform
Page 9 of 16

---

Rules
Artifacts and decisions are append-only. Nothing is overwritten, so any step can be
replayed or compared to an earlier one.
Every artifact carries the ids of the artifacts it was derived from, giving full lineage
from a line of converted code back to the legacy code and tests that justified it.
Entity Key fields Notes
job id, owner, status, source ref, target
stack spec, budget, created and
finished times
One row per conversion job
artifact id, job, type, version, content
hash, storage ref, produced by
(agent run)
Typed outputs such as
LegacyModel ; immutable, new
versions are new rows
module id, job, name, legacy paths,
depends on, risk score, status
Nodes of the conversion DAG
module_attempt id, module, attempt number,
branch, commit, outcome, failure
summary
One row per CodeWriter try,
including repair rounds
agent_run id, job, agent, model, prompt
version, input and output artifact
ids, tokens, cost, duration, tool
calls
Basis for audit, replay and cost
control
test_case id, suite version, layer, module,
legacy capture ref, normalization
rule ids
Frozen once G2 is approved
test_result id, test case, system (legacy or
converted), run id, outcome, diff,
class
Written by the Verifier
gate id, job, type, state, requested at,
artifact versions shown
pending , approved , rejected ,
timed_out
gate_decision id, gate, actor, decision, feedback,
waivers
Append-only
audit_event id, job, actor (agent or person),
action, payload, time
Append-only log of everything
TDD: Multi-Agent Legacy Code Modernization Platform
Page 10 of 16

---

Each job gets its own Git repository. Each module converts on its own branch
( job/<id>/<module> ), and the Integrator merges approved branches into an
integration branch.
LangGraph checkpoints use the Postgres checkpointer, keyed by job id as the thread
id, so a job can be resumed or forked from any checkpoint.
## 10. Conversion strategy and repair loops
Code is converted one module at a time, in dependency order with leaf modules first, so
each module is verified against a stable base before anything depends on it. Modules with
no dependency between them convert in parallel, up to the worker limit.
Inputs to one module conversion
The module spec from the ConversionPlan : legacy files, responsibilities, public
contracts.
The slice of the frozen characterization suite that covers the module.
The target stack profile: project layout, naming, error handling, logging and testing
conventions, written once per stack and approved at G3.
Contracts (not source) of already-converted dependencies.
Decisions made at G1 for any capability gap that touches the module.
Constrained output. The CodeWriter returns a Pydantic-validated change set: file paths,
file contents, assumptions made, and open questions. Paths are checked against the
module's allowed directories, and writes go only to that module's branch. Output that fails
validation is retried without counting as a repair attempt.
Per-module loop
1. Generate code on the module branch.
2. Run build, type check, lint and formatter in the sandbox.
3. Run the module's characterization slice against the converted code and classify each
difference (section 7).
4. Run the Reviewer for security, architecture and style findings.
5. If anything fails, the Repair step receives the classified failures and starts from the
module's base commit plus the feedback, not from a stack of earlier patches. After a
repeated failure it changes tactic, for example a stronger model or a smaller change
set.
6. If everything passes, the module is marked done and its contract is published to
dependents.
TDD: Multi-Agent Legacy Code Modernization Platform
Page 11 of 16

---

7. If the attempt limit (proposed default: 3) or the module budget is reached, the module
goes to Escalation.
Schema and data. The Schema & Data agent runs before the modules that depend on the
schema. Migrations are tested on a data sample, checking row counts, key integrity and
column-level checksums.
Integration. After modules are approved, the Integrator merges branches in plan order,
builds the whole system, and re-runs the full suite. A cross-module failure is routed back
to the module that owns the broken contract.
## 11. Tooling, sandboxing and infrastructure
The platform itself is a Python service on Postgres. These are proposed choices, open to
change in review.
Concern Proposed choice Why
Orchestration LangGraph (Python) with the
Postgres checkpointer
Chosen for this project: durable
state, interrupt for gates, Send
for parallel fan-out
API and gate
backend
FastAPI Job submission, status streaming,
gate decisions
Worker execution Worker pool that leases module
tasks from Postgres with SELECT
... FOR UPDATE SKIP LOCKED
No extra queue service; a crashed
worker's lease expires and the
task is retried
Model access A model gateway with per-agent
model routing, retries, rate limits
and cost metering
One place to swap providers and
enforce budgets
Sandboxes One container per job and system
(legacy, converted), built from
curated per-stack base images
Isolation, reproducible builds, no
cross-job leakage
Legacy runtime Environment builder that
recreates the legacy runtime from
the inventory, using the user's
Dockerfile or docs when provided
Needed to capture behavior from
the real system
Source control Git, one repo per job, branch per
module
Reviewable diffs and a clean pull
request
Artifact store S3-compatible object storage Repository snapshots,
recordings, logs
TDD: Multi-Agent Legacy Code Modernization Platform
Page 12 of 16

---

Sandbox policy
Network egress is denied by default, with an allowlist for package registries and any
endpoint the user approves.
Legacy code is untrusted: it runs only inside the sandbox, with CPU, memory and time
limits.
Secrets from the legacy system are never placed in prompts. Environment values are
replaced by test values before analysis.
The target-stack base image must be able to build and test the stack. If it cannot, that
is a G1 gap (section 6), not a silent failure.
## 12. Observability, cost control and failure handling
Every agent step is traceable and every job has a hard cost ceiling. Without both, an
unattended multi-agent loop can spend money while making no progress.
Observability
Each step emits a trace span (OpenTelemetry) with agent, model, prompt version,
tokens, cost, duration and the ids of input and output artifacts.
Job-level metrics: time per stage, pass rate per module, repair attempts per module,
cost per module, and time spent waiting at gates.
Any step can be replayed from its checkpoint with the same inputs, to debug a bad
output.
A regression suite of small reference jobs (a legacy repo with a known-good
conversion) runs on every prompt, model or schema change and must not lose ground
on pass rate or cost.
Cost control
The G3 plan shows an estimated cost. The user sets a job budget; the Supervisor also
assigns a per-module budget.
At 80% of a budget the Supervisor warns the owner. At 100% the job or module stops
and escalates; it never overspends silently.
Model routing sends cheap steps (inventory, formatting, summaries) to smaller models
and reserves stronger models for architecture and repairs.
Failure handling
Concern Proposed choice Why
Gate UI Web app over the same REST API Diff viewers, reports, approve
and reject
TDD: Multi-Agent Legacy Code Modernization Platform
Page 13 of 16

---

## 13. Security and compliance
The platform handles customers' source code, test data and sometimes credentials, and it
runs code it did not write. Security is a design input, not a later hardening step.
Code confidentiality. Each job declares which model endpoints may see its code.
Options range from a provider with zero data retention to a self-hosted model inside
the customer's network. The gateway refuses any other endpoint for that job.
Secrets and personal data. A secret scanner and PII redactor run before any text goes
into a prompt. Recorded traffic is sanitized before it becomes a test fixture.
Prompt injection. Everything read from the legacy repository (comments, strings,
docs, config) is data, never instructions. Agents have narrowly scoped tools, and the
CodeWriter has no network access. Text in the repo that tries to direct an agent is
logged and flagged at the next gate.
Execution isolation. Legacy and generated code run only in sandboxes with resource
limits and default-deny egress (section 11).
Failure Detection Response
Agent output fails schema
validation
Pydantic error Retry with the error message, up
to a small limit, then count as a
failed attempt
Model or tool call times out
or is rate limited
Gateway error Backoff and retry; switch to a
fallback model if configured
Worker crashes mid-task Lease expires Task returns to the queue and
resumes from the last
checkpoint
Repair loop makes no
progress
Same failing tests
across two attempts
Change tactic, then escalate
Legacy runtime cannot be
recreated
Environment builder
fails
Pause at G2 and ask for a
Dockerfile, credentials-free
dump or docs; fall back to static
analysis with the coverage loss
reported
Characterization is flaky Legacy results differ
between runs
Mark nondeterministic, require a
normalization rule or exclude the
test at G2
Budget exhausted Cost meter Stop and escalate to the owner
TDD: Multi-Agent Legacy Code Modernization Platform
Page 14 of 16

---

Access control. Roles are owner, reviewer, approver and admin. A job's artifacts are
visible only to the people on that job, and gate decisions need the approver role.
Auditability. The append-only audit log records every agent action and every human
decision with identity and time.
Dependency hygiene. The Reviewer checks licenses and known vulnerabilities for
every library the converted code adds, and the Integrator ships a software bill of
materials with the pull request.
Retention. Source snapshots, recordings and sandboxes are deleted on a schedule the
owner sets after job completion; audit records are kept longer.
## 15. Risks and open questions
Risks
Risk Impact Mitigation
Legacy runtime cannot be
recreated, so behavior cannot
be captured
Verification falls back to
static analysis and covers
less
Environment builder with
user-supplied Dockerfiles or
docs; coverage loss shown
at G2 and G4
Characterization suite misses
behavior that matters
A converted system that
passes but is wrong
Coverage ceiling in the
report, risk-ranked
uncovered code, optional
mutation testing
"Any stack to any stack" is too
broad to do well
Weak output for stacks
without a catalog
Curated catalogs and
profiles for a named set
first; provisional catalogs
flagged low confidence
Agents loop without progress
and burn budget
Cost with no result Budgets, no-progress
detection, escalation
(section 12)
Large codebases exceed
model context
Poor analysis and
conversion quality
Graph-based slicing: each
agent gets only its module
and contracts
Reviewers rubber-stamp
gates
Hidden errors reach
delivery
Gates show agent-flagged
uncertainties and diffs;
waivers need a written
reason
TDD: Multi-Agent Legacy Code Modernization Platform
Page 15 of 16

---

Open questions
Risk Impact Mitigation
Business logic buried in stored
procedures, config or the UI
Rules missed during
analysis
Analyzer treats the
database and config as
first-class inputs; G2 asks
the user about unexplained
rules
Which target stacks get a curated capability catalog and stack profile in V1?
What is the largest legacy codebase V1 must handle, in lines of code and number of
modules?
Will most jobs have a runnable legacy instance, and who supplies its environment?
Which model providers or self-hosted models are allowed, and is any customer data
barred from external APIs?
Which Git hosts must receive the pull request (GitHub, GitLab, Bitbucket, on-
premises)?
Is the platform single-tenant for one team, or multi-tenant from the start?
Which parts of the existing Postgres-based orchestrator (task leasing, the schema-
constrained CodeWriter) carry over under LangGraph, and which are replaced?
TDD: Multi-Agent Legacy Code Modernization Platform
Page 16 of 16