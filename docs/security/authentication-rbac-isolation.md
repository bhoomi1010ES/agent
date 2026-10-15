# Authentication, RBAC, and Isolation

Sub-Phase 01.4 establishes backend security boundaries for the modernization platform.
The implementation uses organization multi-tenancy. Jobs are owned by one tenant and one
user; additional users can access a job only through an explicit `job_member` grant.
Artifacts and gates inherit their access boundary from the parent job. Tenant admins can
access tenant resources deliberately; an approver does not gain tenant-wide access merely
from the approver role.

## Authentication and identity

The API accepts externally issued RS256 JWT access tokens. Issuer, audience, and public
verification key come from settings. Validation requires signature, issuer, audience,
expiration, not-before, issued-at, access-token type, subject, tenant UUID, token ID, and a
bounded lifetime. No token issuing or password endpoint is provided. The identity provider
vendor remains an open deployment choice; the application depends only on issuer/JWT
configuration.

The stable external identity is `(issuer, subject)`, mapped to a local `user_account` UUID.
Authorization roles come from the active `tenant_membership` row, never from JWT role
claims. An `auth_session` allowlist stores a one-way hash of `(issuer, jti)` and supports
revocation. The principal carries local user, tenant, membership, session, role, expiry,
subject, issuer, and authentication-method facts. It contains no raw token or credential.

Tenant and user provisioning, membership changes, and session allowlisting are currently
out-of-band administrative operations. They are not exposed as APIs in this phase.

## Roles and access-control matrix

The four baseline roles are exact and enforced by a database check constraint:

| Operation | owner | reviewer | approver | admin |
|---|:---:|:---:|:---:|:---:|
| Create/manage own jobs | Yes | No | No | Yes, tenant-wide |
| View a job | Own/member | Own/member | Own/member | Tenant-wide |
| Cancel a job | Own/member | No | No | Tenant-wide |
| View/create/manage artifacts | Own/member | View | View | Tenant-wide |
| View repository metadata | Own/member | Own/member | Own/member | Tenant-wide |
| Manage repository metadata | Own/member | No | No | Tenant-wide |
| View gates | Own/member | Own/member | Own/member | Tenant-wide |
| Decide gates | No | No | Own/member | Tenant-wide |
| View audit records | Own/member | No | No | Tenant-wide |
| Manage users / tenant | No | No | No | Yes |

Job membership controls resource access independently of role. A reviewer or approver must
be the job owner or have an explicit membership grant; membership alone does not grant a
permission omitted from that role. Unknown or empty role state denies access. Admin access
is tenant-wide and explicit in the scoped repository query.

The TDD names auditability as a system requirement but does not assign audit-read access.
The conservative baseline limits `audit.view` to the job owner and tenant admin; reviewers
and approvers can inspect the gate artifacts and decisions needed for their work without
receiving the broader event history. Revisit this scope if a later workflow requires it.

The permission catalog is centralized in `security/permissions.py`: `job.create`,
`job.view`, `job.cancel`, `job.manage`, `artifact.view`, `artifact.create`,
`artifact.manage`, `repository.view`, `repository.manage`, `gate.view`, `gate.decide`,
`audit.view`, `user.manage`, and `tenant.manage`. Several permissions are defined for the
future protected operations but have no endpoint yet.

## Enforcement and resource boundaries

HTTP routes depend on a validated principal. Protected services repeat permission checks
and pass tenant, user, membership, and deliberate admin scope to repository queries.
Protected job, artifact, and gate ID reads use scoped SQL queries; generic unscoped ID
lookups are private workflow helpers. The database adds foreign keys, unique constraints,
role checks, and indexes, but these structural checks complement rather than replace
application authorization.

Gate decisions require `gate.decide`, an accessible job, and a pending gate. The service
derives actor UUID from the principal and stages both decision and audit event in the same
transaction. The request schema rejects actor and tenant fields. Repository decision
recording accepts an already scoped gate and a stable actor UUID, not a caller-supplied
actor label.

Artifact persistence requires an authenticated principal or a worker context. It checks
`artifact.create` and job scope before validating or persisting data. Worker contexts carry
initiator, tenant, membership, job, and initiation time without credentials. Every worker
operation re-reads current active membership and rechecks role and job scope; revocation or
membership changes therefore deny later work. Queue authentication and tenant-specific
object-store credentials are deployment boundaries for the worker system, which is not
implemented in this phase.

Legacy jobs keep nullable tenant and owner UUID columns so migration 0004 preserves data.
Scoped application queries deny access to unassigned legacy rows. A controlled data
backfill must assign ownership before any future feature exposes those records.

## Future integrations, operational limits, and logging

Object storage and Git providers are not implemented here. Callers must authorize through
the parent job before obtaining an object reference or repository credential. Storage
references continue to pass the Phase 01.3 syntax validation; raw provider credentials are
not returned by these APIs. Future provider credentials must be stored and scoped by tenant
through a dedicated secrets mechanism.

Request bodies are capped at 1 MiB by default (`MAX_REQUEST_BODY_BYTES`), configurable up
to 100 MB for a deployment with a documented upload need. Authentication rate limiting is
deferred because this service does not issue credentials and has no login endpoint. Gate
and artifact operations also lack a distributed rate-limit store; add an edge or shared
store policy before exposing high-volume production workloads.

Authentication failures return a generic unauthorized response. Cross-owner and
cross-tenant resource misses return the same not-found response. Authorization denials log
only stable local IDs and permission names. Redaction covers authorization/bearer values,
cookies, refresh tokens, passwords, client secrets, API keys, and signing keys. Request
bodies and raw authentication headers are not logged. Audit payloads exclude credentials.

## Database changes

Forward-only migration `0004_authentication_rbac_isolation` adds `tenant`, `user_account`,
`tenant_membership`, `auth_session`, and `job_member`; adds nullable job tenant/owner
references; and adds nullable actor UUID references to gate decisions and audit events.
The downgrade removes only these new structures and restores the prior schema.

## Open deployment decisions

- Select the production identity-provider vendor and its key rotation/discovery process.
- Define the trusted provisioning path for tenants, users, memberships, and session records.
- Select authenticated queue transport and object-storage credential strategy before those
  integrations are implemented.
- Decide the legacy-job ownership backfill before enabling secured job workflows for old
  rows.
