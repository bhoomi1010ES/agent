"""Database package exporting metadata Base, engine lifecycle, session helpers, and models."""

from modernization_platform.db.base import Base, ImmutableTimestampMixin, TimestampMixin
from modernization_platform.db.engine import (
    create_database_engine,
    dispose_database_engine,
    get_database_engine,
)
from modernization_platform.db.models import (
    AgentRun,
    Artifact,
    AuditEvent,
    Gate,
    GateDecision,
    Job,
    Module,
    ModuleAttempt,
    TestCase,
    TestResult,
)
from modernization_platform.db.session import (
    get_db_session,
    get_session_factory,
    transactional_session,
)
from modernization_platform.db.types import GUID, UTCDateTime

__all__ = [
    "GUID",
    "AgentRun",
    "Artifact",
    "AuditEvent",
    "Base",
    "Gate",
    "GateDecision",
    "ImmutableTimestampMixin",
    "Job",
    "Module",
    "ModuleAttempt",
    "TestCase",
    "TestResult",
    "TimestampMixin",
    "UTCDateTime",
    "create_database_engine",
    "dispose_database_engine",
    "get_database_engine",
    "get_db_session",
    "get_session_factory",
    "transactional_session",
]
