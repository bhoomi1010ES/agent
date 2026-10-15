"""Unit tests for references, metadata, timestamps, and uncertainty."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from modernization_platform.schemas.common import AnalysisStatus, ReviewAssessment
from modernization_platform.schemas.metadata import (
    ArtifactMetadata,
    ModelPromptProvenance,
    ProducerIdentity,
    ProducerKind,
)
from modernization_platform.schemas.references import CodeReference, EvidenceReference, EvidenceType
from tests.contract.factories import HASH_A


def test_code_reference_uses_inclusive_valid_line_ranges() -> None:
    """End lines are inclusive and may equal the start line."""
    reference = CodeReference(
        repository_id="repo",
        relative_path="src/module.py",
        start_line=7,
        end_line=7,
    )
    assert reference.end_line == 7
    with pytest.raises(ValidationError):
        CodeReference(
            repository_id="repo",
            relative_path="src/module.py",
            start_line=8,
            end_line=7,
        )


def test_evidence_reference_validates_syntax_without_dereferencing() -> None:
    """Object references permit bounded schemes and reject local paths."""
    reference = EvidenceReference(
        evidence_id=uuid.uuid4(),
        evidence_type=EvidenceType.TEST,
        storage_ref="s3://evidence/job/case.json",
        content_hash=HASH_A,
        provenance="Captured from the legacy test run",
    )
    assert reference.storage_ref.startswith("s3://")
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id=uuid.uuid4(),
            evidence_type=EvidenceType.TEST,
            storage_ref="file:///etc/passwd",
            content_hash=HASH_A,
            provenance="Untrusted",
        )


def test_review_assessment_requires_explicit_human_reason() -> None:
    """Human review flags cannot be asserted without a reason."""
    with pytest.raises(ValidationError):
        ReviewAssessment(
            analysis_status=AnalysisStatus.INCOMPLETE,
            confidence=0.2,
            needs_human=False,
        )


def test_artifact_metadata_requires_aware_time_and_valid_lineage() -> None:
    """Metadata separates schema, business version, identity, and lineage."""
    artifact_id = uuid.uuid4()
    base = {
        "artifact_id": artifact_id,
        "artifact_type": "RepoInventory",
        "schema_version": "1.0.0",
        "business_version": 1,
        "content_hash": HASH_A,
        "storage_ref": "s3://artifacts/job/inventory.json",
        "producer": ProducerIdentity(kind=ProducerKind.MANUAL, identifier="operator"),
        "parent_artifact_ids": [],
        "created_at": datetime.now(UTC),
        "job_id": uuid.uuid4(),
    }
    metadata = ArtifactMetadata.model_validate(base)
    assert metadata.created_at.tzinfo is not None
    with pytest.raises(ValidationError):
        ArtifactMetadata.model_validate({**base, "created_at": datetime.now()})
    with pytest.raises(ValidationError):
        ArtifactMetadata.model_validate({**base, "parent_artifact_ids": [artifact_id]})


def test_model_prompt_provenance_is_separate_and_rejects_secrets() -> None:
    """Prompt/model versions are explicit metadata and cannot contain credential material."""
    provenance = ModelPromptProvenance(
        provider="provider",
        model_identifier="model-name",
        model_version="snapshot-1",
        prompt_template_id="intake",
        prompt_template_version="1.0.0",
    )
    assert provenance.prompt_template_version == "1.0.0"
    with pytest.raises(ValidationError):
        ModelPromptProvenance(
            provider="provider",
            model_identifier="sk-this-looks-like-a-secret",
            prompt_template_id="intake",
            prompt_template_version="1.0.0",
        )
