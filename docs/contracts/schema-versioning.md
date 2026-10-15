# Artifact Schema Versioning

## Declaration and registry

An artifact declares `schema_version` inside its payload. The workflow independently supplies the
expected artifact type and exact version. `ArtifactContractRegistry` resolves the pair to a fixed
Pydantic model; payload values never trigger imports or code execution.

Current support is deliberately narrow:

| Declared version | Status | Ordinary read behavior |
|---|---|---|
| `1.0.0` | Same version | Parse with the exact registered v1 model |
| Registered historical version | Supported older | Parse with that historical model; never the current model |
| Unregistered version lower than current | Unsupported older | Reject |
| Unregistered version higher than current | Newer unknown | Reject |
| Non-semantic version | Invalid | Reject |
| Explicitly transformed version | No transformation exists in 01.3 | A future transformer must preserve original bytes, hash, version and provenance |

No historical schema is currently registered and no transformation is implemented. Ordinary reads
never migrate stored content. Adding a version requires a new immutable model, registry entry,
compatibility tests, documentation, and reference-job regression testing.

Artifact schema version, database business version, payload hash, model identifier, prompt version,
and producer execution ID are separate values and must not be collapsed.

