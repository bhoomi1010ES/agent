"""Safe validation, canonical serialization, hashing, and integrity utilities."""

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from modernization_platform.core.exceptions import ValidationFailure
from modernization_platform.schemas.agent_artifacts import AgentArtifact
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.errors import ValidationIssue
from modernization_platform.schemas.registry import (
    ArtifactContractRegistry,
    ArtifactRegistryError,
    artifact_registry,
)

logger = logging.getLogger(__name__)

MAX_ARTIFACT_PAYLOAD_BYTES = 1_000_000
MAX_ARTIFACT_NESTING_DEPTH = 20
MAX_ARTIFACT_NODES = 100_000
MAX_VALIDATION_ISSUES = 20


class ArtifactValidationError(ValidationFailure):
    """Safe artifact rejection containing no raw payload values."""

    def __init__(self, code: str, message: str, issues: tuple[ValidationIssue, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.issues = issues


@dataclass(frozen=True, slots=True)
class ValidatedArtifact:
    """Validated model and its exact canonical payload representation."""

    artifact: AgentArtifact
    canonical_payload: bytes
    content_hash: str


def safe_validation_issues(error: ValidationError) -> tuple[ValidationIssue, ...]:
    """Summarize Pydantic errors without copying rejected values or internal URLs."""
    try:
        issues: list[ValidationIssue] = []
        for item in error.errors(include_input=False, include_url=False)[:MAX_VALIDATION_ISSUES]:
            location = ".".join(str(part) for part in item.get("loc", ())) or "payload"
            message = str(item.get("msg", "Invalid value"))[:500]
            issues.append(
                ValidationIssue(
                    field=location,
                    issue=message,
                    type=str(item.get("type", "validation_error")),
                )
            )
        return tuple(issues)
    except Exception as exc:
        logger.exception("safe_validation_issues failed | %s: %s", type(exc).__name__, exc)
        return (
            ValidationIssue(
                field="payload",
                issue="Artifact payload validation failed",
                type="validation_error",
            ),
        )


def canonical_json_bytes(model: BaseModel) -> bytes:
    """Serialize a validated model as sorted, compact UTF-8 JSON with explicit nulls.

    Object keys are sorted, list ordering is preserved, aliases are used, Unicode is
    emitted directly, and optional null fields remain present. Non-finite numbers fail.
    """
    try:
        payload = model.model_dump(mode="json", by_alias=True, exclude_none=False)
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return serialized.encode("utf-8")
    except Exception as exc:
        logger.exception("canonical_json_bytes failed | %s: %s", type(exc).__name__, exc)
        raise ArtifactValidationError(
            "CANONICALIZATION_FAILED", "Validated artifact could not be serialized canonically"
        ) from exc


def generate_content_hash(model: BaseModel) -> str:
    """Return the lowercase SHA-256 hex digest of the canonical artifact payload."""
    try:
        return hashlib.sha256(canonical_json_bytes(model)).hexdigest()
    except Exception as exc:
        if isinstance(exc, ArtifactValidationError):
            raise
        logger.exception("generate_content_hash failed | %s: %s", type(exc).__name__, exc)
        raise ArtifactValidationError("HASH_FAILED", "Artifact content hashing failed") from exc


def verify_content_hash(model: BaseModel, expected_hash: str) -> bool:
    """Compare a stored digest without replacing or normalizing a mismatch."""
    try:
        actual_hash = generate_content_hash(model)
        return hmac.compare_digest(actual_hash, expected_hash.lower())
    except Exception as exc:
        if isinstance(exc, ArtifactValidationError):
            raise
        logger.exception("verify_content_hash failed | %s: %s", type(exc).__name__, exc)
        raise ArtifactValidationError("HASH_VERIFICATION_FAILED", "Integrity check failed") from exc


def _decode_payload(payload: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    try:
        if isinstance(payload, bytes):
            if len(payload) > MAX_ARTIFACT_PAYLOAD_BYTES:
                raise ArtifactValidationError("PAYLOAD_TOO_LARGE", "Artifact payload is too large")
            decoded: Any = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            if len(payload.encode("utf-8")) > MAX_ARTIFACT_PAYLOAD_BYTES:
                raise ArtifactValidationError("PAYLOAD_TOO_LARGE", "Artifact payload is too large")
            decoded = json.loads(payload)
        elif isinstance(payload, Mapping):
            decoded = dict(payload)
            encoded = json.dumps(
                decoded,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded) > MAX_ARTIFACT_PAYLOAD_BYTES:
                raise ArtifactValidationError("PAYLOAD_TOO_LARGE", "Artifact payload is too large")
        else:
            raise ArtifactValidationError(
                "INVALID_PAYLOAD_TYPE", "Artifact payload must be a JSON object"
            )
        if not isinstance(decoded, dict):
            raise ArtifactValidationError(
                "INVALID_PAYLOAD_TYPE", "Artifact payload must be a JSON object"
            )
        return decoded
    except ArtifactValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ArtifactValidationError(
            "MALFORMED_JSON", "Artifact payload is not valid JSON"
        ) from exc
    except Exception as exc:
        logger.exception("_decode_payload failed | %s: %s", type(exc).__name__, exc)
        raise ArtifactValidationError(
            "INVALID_PAYLOAD", "Artifact payload could not be read"
        ) from exc


def _validate_payload_shape(payload: dict[str, Any]) -> None:
    try:
        pending: list[tuple[Any, int]] = [(payload, 1)]
        node_count = 0
        while pending:
            value, depth = pending.pop()
            node_count += 1
            if node_count > MAX_ARTIFACT_NODES:
                raise ArtifactValidationError(
                    "PAYLOAD_TOO_COMPLEX", "Artifact payload contains too many values"
                )
            if depth > MAX_ARTIFACT_NESTING_DEPTH:
                raise ArtifactValidationError(
                    "PAYLOAD_TOO_DEEP", "Artifact payload nesting exceeds the allowed depth"
                )
            if isinstance(value, dict):
                if not all(isinstance(key, str) for key in value):
                    raise ArtifactValidationError(
                        "INVALID_OBJECT_KEY", "Artifact object keys must be strings"
                    )
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
            elif value is not None and not isinstance(value, str | int | float | bool):
                raise ArtifactValidationError(
                    "INVALID_VALUE_TYPE", "Artifact contains a non-JSON value"
                )
    except ArtifactValidationError:
        raise
    except Exception as exc:
        logger.exception("_validate_payload_shape failed | %s: %s", type(exc).__name__, exc)
        raise ArtifactValidationError(
            "INVALID_PAYLOAD", "Artifact shape validation failed"
        ) from exc


def parse_artifact(
    payload: Mapping[str, Any] | str | bytes,
    *,
    expected_type: ArtifactType | str,
    expected_schema_version: str,
    registry: ArtifactContractRegistry = artifact_registry,
) -> ValidatedArtifact:
    """Parse untrusted output using workflow-selected type and exact schema version."""
    selected_type: ArtifactType | None = None
    try:
        try:
            selected_type = ArtifactType(expected_type)
        except ValueError as exc:
            raise ArtifactValidationError(
                "UNKNOWN_ARTIFACT_TYPE", "Artifact type is not supported"
            ) from exc
        model_type = registry.resolve(selected_type, expected_schema_version)
        decoded = _decode_payload(payload)
        _validate_payload_shape(decoded)
        if decoded.get("artifact_type") != selected_type.value:
            raise ArtifactValidationError(
                "ARTIFACT_TYPE_MISMATCH", "Artifact type does not match workflow expectation"
            )
        if decoded.get("schema_version") != expected_schema_version:
            raise ArtifactValidationError(
                "SCHEMA_VERSION_MISMATCH", "Schema version does not match workflow expectation"
            )
        artifact = model_type.model_validate(decoded)
        canonical_payload = canonical_json_bytes(artifact)
        return ValidatedArtifact(
            artifact=artifact,
            canonical_payload=canonical_payload,
            content_hash=hashlib.sha256(canonical_payload).hexdigest(),
        )
    except ArtifactValidationError as exc:
        logger.warning(
            "Artifact validation rejected | type=%s schema_version=%s code=%s",
            selected_type.value if selected_type is not None else "unknown",
            expected_schema_version,
            exc.code,
        )
        raise
    except ArtifactRegistryError as exc:
        logger.warning(
            "Artifact contract unsupported | type=%s schema_version=%s",
            selected_type.value if selected_type is not None else "unknown",
            expected_schema_version,
        )
        raise ArtifactValidationError(
            "UNSUPPORTED_ARTIFACT_CONTRACT", "Artifact type or schema version is unsupported"
        ) from exc
    except ValidationError as exc:
        issues = safe_validation_issues(exc)
        logger.warning(
            "Artifact payload rejected by schema | type=%s schema_version=%s issue_count=%d",
            selected_type.value if selected_type is not None else "unknown",
            expected_schema_version,
            len(issues),
        )
        raise ArtifactValidationError(
            "ARTIFACT_SCHEMA_INVALID", "Artifact payload failed schema validation", issues
        ) from exc
    except Exception as exc:
        logger.exception(
            "parse_artifact failed | type=%s schema_version=%s | %s: %s",
            selected_type.value if selected_type is not None else "unknown",
            expected_schema_version,
            type(exc).__name__,
            exc,
        )
        raise ArtifactValidationError(
            "ARTIFACT_VALIDATION_FAILED", "Artifact validation failed safely"
        ) from exc


__all__ = [
    "MAX_ARTIFACT_PAYLOAD_BYTES",
    "ArtifactValidationError",
    "ValidatedArtifact",
    "canonical_json_bytes",
    "generate_content_hash",
    "parse_artifact",
    "safe_validation_issues",
    "verify_content_hash",
]
