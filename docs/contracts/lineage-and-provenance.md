# Lineage, Integrity, and Provenance

## Persistence mapping

The Phase 01.2 `artifact` table remains authoritative; no migration is required.

| Contract value | Persistence location |
|---|---|
| Artifact ID | `artifact.id` |
| Job context | `artifact.job_id` |
| Artifact type | `artifact.type` |
| Business/append version | `artifact.version` |
| Payload SHA-256 | `artifact.content_hash` |
| Object reference | `artifact.storage_ref` |
| Producer execution | `artifact.produced_by_run_id` |
| Parent artifact IDs | `artifact.derived_from` |
| Schema version, producer kind/identifier, model/prompt provenance, format, validation state and canonicalization ID | `artifact.artifact_metadata` JSONB |
| Creation time | `artifact.created_at` |

Parent IDs must be unique, cannot contain the new artifact ID, and are verified to exist in the same
job before persistence. Agent producers require an existing agent run belonging to that job. Model
provider/model identity and prompt template/version are stored separately. These values support
audit and replay analysis but do not guarantee deterministic hosted-model regeneration.

## Canonical payload hash

The payload hash covers only the validated artifact payload, not the metadata envelope.
Canonicalization identifier: `rfc8259-sort-keys-utf8-v1`.

1. Dump the Pydantic model in JSON mode with aliases and explicit nulls.
2. Sort every JSON object key lexicographically.
3. Preserve list order.
4. Emit compact JSON separators, direct Unicode (`ensure_ascii=false`), and reject non-finite numbers.
5. Encode as UTF-8 and compute lowercase SHA-256 hex.

A mismatched claimed or stored hash is rejected, never replaced. A hash proves byte integrity under
this procedure; it does not prove authorship, authorization, execution, approval, or target existence.

