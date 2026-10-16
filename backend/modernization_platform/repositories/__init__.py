"""Repositories package providing data access abstraction for all domain entities."""

from modernization_platform.repositories.agent_runs import AgentRunRepository
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.base import BaseRepository
from modernization_platform.repositories.gates import GateRepository
from modernization_platform.repositories.idempotency import IdempotencyRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.repositories.module_attempts import ModuleAttemptRepository
from modernization_platform.repositories.modules import ModuleRepository
from modernization_platform.repositories.source_provenance import SourceProvenanceRepository
from modernization_platform.repositories.tasks import TaskRepository
from modernization_platform.repositories.tests import TestRepository

__all__ = [
    "AgentRunRepository",
    "ArtifactRepository",
    "AuditEventRepository",
    "BaseRepository",
    "GateRepository",
    "IdempotencyRepository",
    "JobRepository",
    "ModuleAttemptRepository",
    "ModuleRepository",
    "SourceProvenanceRepository",
    "TaskRepository",
    "TestRepository",
]
