# Artifact Contract Catalog

Every current artifact uses schema version `1.0.0`, rejects unknown fields, carries explicit
uncertainty, and may cite typed evidence. The contracts intentionally represent only behavior
supported by the TDD.

| Artifact | Purpose | Key fields and invariants |
|---|---|---|
| `RepoInventory` | Intake inventory without embedding repository contents | Repository/revision, bounded unique file paths, observed technologies, entry-point code references |
| `LegacyModel` | Known legacy components and behavior | Unique component IDs; capabilities may reference only declared components; incomplete analysis is representable |
| `TargetBlueprint` | Proposed target architecture | Target stack, target components, decisions and constraints; existence never implies approval |
| `FeasibilityReport` | G1 capability and tool-gap input | TDD ratings (`native`, `library`, `custom`, `unsupported`), evidence, confidence, options and verification impact; gaps/low confidence require human review |
| `ConversionPlan` | Dependency-ordered conversion scope | Unique units, validated repository-relative scope, declared dependencies, risk and mapping decisions; graph must be acyclic |
| `CharacterizationSuite` | Legacy-derived test inventory | Suite identity/version, stored test-definition evidence, normalization rules and suite hash; `frozen=true` requires a separate G2 decision reference and does not prove execution |
| `SchemaPlan` | Data/schema transformation plan | Source/target mappings, transformation decisions, evidence and explicit risks |
| `EquivalenceReport` | Deterministic comparison outcomes | Suite reference, per-case result, evidence, uncovered areas and waiver references; every failure is classified and unknown/not-run results cannot pass |
| `JobReport` | Final job summary | Artifact references, verification status, unresolved items, gates and delivery reference; success requires passed verification, no unresolved items, and approved decision references for all required gates |

The catalog models artifacts, not orchestration. It does not implement agents, model calls,
conversion workflows, object storage, Git operations, or gate authorization.

