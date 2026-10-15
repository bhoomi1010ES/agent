# Contract Conventions

Sub-Phase 01.3 uses Pydantic v2 contracts under `backend/modernization_platform/schemas`.
Pydantic contracts are separate from SQLAlchemy persistence models and no API endpoint is
added by this phase.

## Model policy

- Contract instances are immutable and reject unknown fields (`extra="forbid"`).
- Identifiers and schema versions use constrained strings; database and artifact identities use UUIDs.
- Event and persistence timestamps require timezone-aware datetimes.
- Agent artifacts use an exact semantic schema version (`1.0.0`), not a floating "latest" version.
- API request models exclude server-owned identity and authorization fields.
- ORM objects are not API response models.

All nine artifacts carry an explicit `ReviewAssessment`. `confidence` is a bounded producer
assessment in `[0, 1]`; it is not a calibrated probability, an authorization result, or approval.
Incomplete analysis must set `needs_human=true`, and any human-review request requires a reason.
Gate approval remains a separate append-only decision.

Validation is deterministic and side-effect-free. Pydantic validators do not query databases,
read files, fetch URLs, or dereference object-store references.

## Trust boundaries

Artifact payloads, repository paths, evidence references, and claimed hashes are untrusted.
Artifact type and schema version are selected by workflow state and passed separately to the
validator. Producer identity, job identity, agent-run identity, creation time, business version,
validation state, and approval state are system-assigned or verified at the service boundary.

