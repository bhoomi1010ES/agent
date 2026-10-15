# Validation and Security

## Validation-before-persistence

`ArtifactPersistenceService` performs the following in the caller-owned database transaction:

1. Validate bounded storage-reference syntax without dereferencing it.
2. Resolve the workflow-selected artifact type and exact schema version.
3. Limit serialized input to 1,000,000 bytes, depth to 20, and traversed JSON values to 100,000.
4. Validate with the registered Pydantic schema and reject unknown fields.
5. Produce canonical bytes and SHA-256; reject a mismatched producer claim.
6. Verify lineage rows and agent-run ownership against the same job.
7. Append an artifact through the existing repository and stage a sanitized audit event.

The service does not commit. Callers must commit the artifact and success audit event atomically or
roll back both. Persistence exceptions propagate and must not be reported as success.

Validation failures create no artifact row. They return a typed rejected result and stage an
`ARTIFACT_VALIDATION_REJECTED` audit event containing only type, version, error code, and affected
field locations. The caller commits that failure audit separately as part of retry/attempt handling.

## Reference security

- Code references require repository-relative POSIX paths and reject absolute, drive-qualified,
  backslash, control-character, `.` and `..` segments.
- Storage references permit only `s3`, `artifact`, and `evidence` schemes, with no credentials,
  query, fragment, or traversal.
- Validation never reads referenced files or accesses a network.
- Error summaries omit rejected input values and Pydantic diagnostic URLs.
- Payloads are JSON only; pickle, arbitrary Python objects, dynamic imports, and evaluation are absent.
- API transport requests cannot supply owner/actor identities or gate approval state.

## Known boundaries

Object storage upload/existence checks, authorization, orchestration retries, and model execution are
outside Sub-Phase 01.3. A valid contract is not authorization. Storage services must verify that
bytes written at a reference match the recorded content hash before making them trusted inputs.

