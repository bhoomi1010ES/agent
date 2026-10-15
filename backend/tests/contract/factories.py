"""Representative valid payload factories for artifact contract tests."""

import uuid
from typing import Any

from modernization_platform.schemas.common import ArtifactType

HASH_A = "a" * 64
HASH_B = "b" * 64


def assessment(*, needs_human: bool = False) -> dict[str, Any]:
    """Build a valid explicit uncertainty assessment."""
    return {
        "analysis_status": "complete",
        "confidence": 0.9,
        "needs_human": needs_human,
        "human_review_reason": "A reviewer must resolve the identified gap"
        if needs_human
        else None,
        "unresolved_questions": [],
        "assumptions": [],
        "blockers": [],
    }


def evidence() -> dict[str, Any]:
    """Build a content-addressed evidence reference."""
    return {
        "evidence_id": str(uuid.uuid4()),
        "evidence_type": "code",
        "storage_ref": "s3://evidence-bucket/jobs/evidence.json",
        "content_hash": HASH_A,
        "related_artifact_id": None,
        "related_execution_id": None,
        "provenance": "Captured by the intake scanner",
    }


def code_reference() -> dict[str, Any]:
    """Build a repository-relative inclusive line reference."""
    return {
        "repository_id": "legacy-repo",
        "relative_path": "src/main.py",
        "symbol": "main",
        "start_line": 1,
        "end_line": 10,
        "content_hash": HASH_B,
        "revision": "abc123",
    }


def _base(artifact_type: ArtifactType, *, needs_human: bool = False) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type.value,
        "schema_version": "1.0.0",
        "assessment": assessment(needs_human=needs_human),
        "evidence": [],
    }


def repo_inventory_payload() -> dict[str, Any]:
    """Build a representative RepoInventory payload."""
    return {
        **_base(ArtifactType.REPO_INVENTORY),
        "repository_id": "legacy-repo",
        "revision": "abc123",
        "files": [
            {
                "relative_path": "src/main.py",
                "language": "python",
                "size_bytes": 100,
                "content_hash": HASH_B,
            }
        ],
        "languages": [{"name": "python", "version": "3.8", "evidence": [code_reference()]}],
        "frameworks": [],
        "build_systems": ["pip"],
        "entry_points": [code_reference()],
    }


def legacy_model_payload() -> dict[str, Any]:
    """Build a representative LegacyModel payload."""
    return {
        **_base(ArtifactType.LEGACY_MODEL),
        "components": [
            {
                "component_id": "billing",
                "name": "Billing",
                "kind": "service",
                "description": "Calculates invoices",
                "code_references": [code_reference()],
            }
        ],
        "capabilities": [
            {
                "capability_id": "invoice",
                "description": "Creates an invoice",
                "component_ids": ["billing"],
                "evidence": [code_reference()],
            }
        ],
        "integrations": [],
        "data_stores": ["PostgreSQL"],
        "business_rules": ["Invoice totals include applicable tax"],
    }


def target_blueprint_payload() -> dict[str, Any]:
    """Build a representative TargetBlueprint payload."""
    return {
        **_base(ArtifactType.TARGET_BLUEPRINT),
        "target_stack": {
            "language": "python",
            "runtime": "3.13",
            "framework": "FastAPI",
            "database": "PostgreSQL",
        },
        "components": [
            {
                "component_id": "billing-api",
                "name": "Billing API",
                "responsibility": "Expose invoice operations",
                "maps_legacy_capabilities": ["invoice"],
            }
        ],
        "decisions": [
            {
                "decision_id": "api-style",
                "summary": "Use HTTP JSON APIs",
                "rationale": "Matches the requested target stack",
                "alternatives": [],
            }
        ],
        "constraints": [],
    }


def feasibility_report_payload() -> dict[str, Any]:
    """Build a representative FeasibilityReport payload."""
    return {
        **_base(ArtifactType.FEASIBILITY_REPORT),
        "status": "feasible",
        "items": [
            {
                "capability": "Invoice generation",
                "legacy_evidence": [code_reference()],
                "rating": "native",
                "candidate": None,
                "confidence": 0.95,
                "options": [],
                "verification_impact": "No known reduction in verification coverage",
            }
        ],
        "pipeline_tool_gaps": [],
    }


def conversion_plan_payload() -> dict[str, Any]:
    """Build a representative acyclic ConversionPlan payload."""
    return {
        **_base(ArtifactType.CONVERSION_PLAN),
        "units": [
            {
                "unit_id": "domain",
                "name": "Domain model",
                "scope": ["src/domain.py"],
                "depends_on": [],
                "risk": "medium",
                "mapping_decisions": [],
            },
            {
                "unit_id": "api",
                "name": "API layer",
                "scope": ["src/api.py"],
                "depends_on": ["domain"],
                "risk": "low",
                "mapping_decisions": [],
            },
        ],
        "estimated_effort": "Two engineering days",
        "planning_constraints": [],
    }


def characterization_suite_payload() -> dict[str, Any]:
    """Build a representative unfrozen CharacterizationSuite payload."""
    return {
        **_base(ArtifactType.CHARACTERIZATION_SUITE),
        "suite_id": str(uuid.uuid4()),
        "suite_version": 1,
        "cases": [
            {
                "case_id": str(uuid.uuid4()),
                "name": "Invoice total",
                "layer": "unit",
                "definition": evidence(),
                "source_references": [code_reference()],
            }
        ],
        "normalization_rules": [],
        "suite_content_hash": HASH_A,
        "frozen": False,
        "approval_reference": None,
    }


def schema_plan_payload() -> dict[str, Any]:
    """Build a representative SchemaPlan payload."""
    return {
        **_base(ArtifactType.SCHEMA_PLAN),
        "mappings": [
            {
                "mapping_id": "invoice-table",
                "source": "legacy_invoice",
                "target": "invoice",
                "transformation": "Rename columns without changing values",
                "evidence": [code_reference()],
            }
        ],
        "transformation_decisions": [],
        "risks": [],
    }


def equivalence_report_payload() -> dict[str, Any]:
    """Build a representative passing EquivalenceReport payload."""
    return {
        **_base(ArtifactType.EQUIVALENCE_REPORT),
        "suite": {
            "artifact_id": str(uuid.uuid4()),
            "artifact_type": "CharacterizationSuite",
            "schema_version": "1.0.0",
            "content_hash": HASH_A,
        },
        "verification_status": "passed",
        "outcomes": [
            {
                "case_id": str(uuid.uuid4()),
                "status": "passed",
                "classification": None,
                "evidence": [evidence()],
                "details": None,
            }
        ],
        "uncovered_areas": [],
        "waiver_references": [],
    }


def job_report_payload() -> dict[str, Any]:
    """Build a representative successful JobReport payload."""
    return {
        **_base(ArtifactType.JOB_REPORT),
        "outcome": "succeeded",
        "summary": "All in-scope behavior passed verification",
        "artifacts": [
            {
                "artifact_id": str(uuid.uuid4()),
                "artifact_type": "EquivalenceReport",
                "schema_version": "1.0.0",
                "content_hash": HASH_A,
            }
        ],
        "verification_status": "passed",
        "required_gates": [
            {
                "gate_id": str(uuid.uuid4()),
                "gate_type": "G4",
                "state": "approved",
                "decision_id": str(uuid.uuid4()),
            }
        ],
        "unresolved_items": [],
        "delivery_reference": "pull-request-42",
    }


ARTIFACT_PAYLOADS = {
    ArtifactType.REPO_INVENTORY: repo_inventory_payload,
    ArtifactType.LEGACY_MODEL: legacy_model_payload,
    ArtifactType.TARGET_BLUEPRINT: target_blueprint_payload,
    ArtifactType.FEASIBILITY_REPORT: feasibility_report_payload,
    ArtifactType.CONVERSION_PLAN: conversion_plan_payload,
    ArtifactType.CHARACTERIZATION_SUITE: characterization_suite_payload,
    ArtifactType.SCHEMA_PLAN: schema_plan_payload,
    ArtifactType.EQUIVALENCE_REPORT: equivalence_report_payload,
    ArtifactType.JOB_REPORT: job_report_payload,
}
