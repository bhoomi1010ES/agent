"""Canonical serialization and content-hash contract tests."""

import json

from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.validation import parse_artifact, verify_content_hash
from tests.contract.factories import repo_inventory_payload


def test_hash_is_deterministic_across_json_object_key_order() -> None:
    """Logically identical JSON objects produce the same canonical SHA-256 digest."""
    payload = repo_inventory_payload()
    reversed_payload = dict(reversed(list(payload.items())))
    first = parse_artifact(
        payload, expected_type=ArtifactType.REPO_INVENTORY, expected_schema_version="1.0.0"
    )
    second = parse_artifact(
        json.dumps(reversed_payload, ensure_ascii=False),
        expected_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
    )
    assert first.canonical_payload == second.canonical_payload
    assert first.content_hash == second.content_hash
    assert verify_content_hash(first.artifact, first.content_hash)
    assert not verify_content_hash(first.artifact, "0" * 64)


def test_round_trip_preserves_declared_interpretation() -> None:
    """Canonical bytes parse only under their original type and version."""
    first = parse_artifact(
        repo_inventory_payload(),
        expected_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
    )
    second = parse_artifact(
        first.canonical_payload,
        expected_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
    )
    assert first.artifact == second.artifact
    assert first.content_hash == second.content_hash
