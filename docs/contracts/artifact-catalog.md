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
| `ChangeSet` | CodeWriter module conversion output | Module ID, `job/<id>/<module>` branch constraint, repository-relative file mutations, allowed directory bounds, assumptions, open questions |
| `EquivalenceReport` | Deterministic comparison outcomes | Suite reference, per-case result, evidence, uncovered areas and waiver references; every failure is classified and unknown/not-run results cannot pass |
| `ReviewReport` | Static review findings and proposed repair tasks | Finding categories, severity-ranked findings with code evidence, actionable fix tasks; high/critical findings prevent passing review status |
| `JobReport` | Final job summary | Artifact references, verification status, unresolved items, gates and delivery reference; success requires passed verification, no unresolved items, and approved decision references for all required gates |

### Naming Resolution: `ReviewReport` vs `ReviewFindings`
While TDD Section 4 summarizes the Reviewer agent's output as "findings, fix tasks", the platform standardizes artifact handoffs under the `...Report` convention (`FeasibilityReport`, `EquivalenceReport`, `JobReport`, `ReviewReport`). `ReviewReport` encapsulates both typed `ReviewFinding` items and `ProposedFixTask` repair directives.

The catalog models artifacts, not orchestration. It does not implement agents, model calls,
conversion workflows, object storage, Git operations, or gate authorization.

