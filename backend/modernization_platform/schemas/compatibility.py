"""Explicit artifact schema-version compatibility policy."""

import re
from enum import StrEnum

from pydantic import Field

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import ContractModel, SchemaVersion
from modernization_platform.schemas.common import ArtifactType

_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class CompatibilityStatus(StrEnum):
    """Compatibility matrix outcomes for declared artifact versions."""

    SAME_VERSION = "same_version"
    SUPPORTED_OLDER = "supported_older"
    UNSUPPORTED_OLDER = "unsupported_older"
    NEWER_UNKNOWN = "newer_unknown"
    INVALID_VERSION = "invalid_version"
    EXPLICITLY_MIGRATED = "explicitly_migrated"


class CompatibilityResult(ContractModel):
    """Deterministic compatibility assessment with no implicit transformation."""

    artifact_type: ArtifactType
    declared_version: str = Field(min_length=1, max_length=50)
    current_version: SchemaVersion
    status: CompatibilityStatus
    readable: bool
    requires_explicit_transformation: bool


@log_errors
def assess_compatibility(
    artifact_type: ArtifactType,
    declared_version: str,
    *,
    current_version: str = "1.0.0",
    supported_historical_versions: frozenset[str] = frozenset(),
) -> CompatibilityResult:
    """Assess schema compatibility without parsing or mutating historical content."""
    if _VERSION_PATTERN.fullmatch(declared_version) is None:
        return CompatibilityResult(
            artifact_type=artifact_type,
            declared_version=declared_version,
            current_version=current_version,
            status=CompatibilityStatus.INVALID_VERSION,
            readable=False,
            requires_explicit_transformation=False,
        )
    declared_tuple = tuple(int(part) for part in declared_version.split("."))
    current_tuple = tuple(int(part) for part in current_version.split("."))
    if declared_version == current_version:
        status = CompatibilityStatus.SAME_VERSION
        readable = True
    elif declared_version in supported_historical_versions:
        status = CompatibilityStatus.SUPPORTED_OLDER
        readable = True
    elif declared_tuple < current_tuple:
        status = CompatibilityStatus.UNSUPPORTED_OLDER
        readable = False
    else:
        status = CompatibilityStatus.NEWER_UNKNOWN
        readable = False
    return CompatibilityResult(
        artifact_type=artifact_type,
        declared_version=declared_version,
        current_version=current_version,
        status=status,
        readable=readable,
        requires_explicit_transformation=readable and declared_version != current_version,
    )
