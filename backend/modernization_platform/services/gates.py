"""Durable human-in-the-loop approval gates and append-only decision service."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.domain.gates.errors import (
    DuplicateDecisionError,
    GateClosedError,
    GateNotFoundError,
    GateTimeoutError,
    InvalidGateStateTransitionError,
    InvalidWaiverError,
    MissingRejectionRationaleError,
    StaleArtifactVersionError,
)
from modernization_platform.domain.gates.notifications import (
    GateNotificationEvent,
    GateNotificationType,
    default_gate_dispatcher,
)
from modernization_platform.domain.gates.rejection import get_rejection_target_stage
from modernization_platform.domain.gates.states import (
    GateDecisionType,
    GateState,
    is_terminal_gate_state,
)
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.gates import GateRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.security.authorization import (
    has_tenant_admin_scope,
    require_permission,
)
from modernization_platform.security.permissions import Permission
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


class GateService:
    """Service orchestrating durable gate state transitions, immutable audit decisions, and resume."""

    def __init__(
        self,
        session: AsyncSession,
        workflow_engine: Any | None = None,
    ) -> None:
        self.session = session
        self._gates = GateRepository(session)
        self._audit = AuditEventRepository(session)
        self._jobs = JobRepository(session)
        self._artifacts = ArtifactRepository(session)
        self._engine = workflow_engine

    @log_errors
    async def create_gate(
        self,
        *,
        principal: AuthenticatedPrincipal | None = None,
        job_id: uuid.UUID,
        gate_type: str,
        timeout_seconds: int | None = None,
        artifact_versions_shown: dict[str, Any] | None = None,
        artifact_diff_ref: str | None = None,
        needs_human_flags: list[dict[str, Any]] | None = None,
        budget_used_cents: float = 0.0,
        workflow_thread_id: str | None = None,
        gate_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
    ) -> Gate:
        """Create a new durable human approval gate interrupting workflow execution."""
        try:
            actor = str(principal.user_id) if principal else "system:workflow"
            actor_user_id = principal.user_id if principal else None

            timeout_at = (
                datetime.now(UTC) + timedelta(seconds=timeout_seconds)
                if timeout_seconds is not None
                else None
            )

            gate = await self._gates.create_gate(
                gate_id=gate_id,
                job_id=job_id,
                gate_type=gate_type,
                artifact_versions_shown=artifact_versions_shown,
                needs_human_flags=needs_human_flags,
                budget_used_cents=budget_used_cents,
                timeout_at=timeout_at,
                workflow_thread_id=workflow_thread_id or str(job_id),
                artifact_diff_ref=artifact_diff_ref,
            )

            await self._audit.append_event(
                actor=actor,
                actor_user_id=actor_user_id,
                action="GATE_CREATED",
                job_id=job_id,
                correlation_id=correlation_id,
                payload={
                    "gate_id": str(gate.id),
                    "gate_type": gate_type,
                    "timeout_at": timeout_at.isoformat() if timeout_at else None,
                    "artifact_versions_shown": artifact_versions_shown or {},
                },
            )

            await default_gate_dispatcher.dispatch(
                GateNotificationEvent(
                    event_type=GateNotificationType.GATE_CREATED,
                    gate_id=gate.id,
                    job_id=job_id,
                    gate_type=gate_type,
                    details={
                        "timeout_at": timeout_at.isoformat() if timeout_at else None,
                        "artifact_versions_shown": artifact_versions_shown or {},
                    },
                )
            )

            return gate
        except Exception as exc:
            logger.exception("create_gate failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def get_gate(
        self,
        *,
        principal: AuthenticatedPrincipal,
        gate_id: uuid.UUID,
        job_id: uuid.UUID | None = None,
    ) -> Gate:
        """Retrieve a gate verifying job and tenant authorization."""
        try:
            require_permission(principal, Permission.GATE_VIEW)
            gate = await self._gates.get_by_id_scoped(
                gate_id=gate_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if gate is None or (job_id is not None and gate.job_id != job_id):
                raise GateNotFoundError(str(gate_id))

            return gate
        except (GateNotFoundError, Exception):
            raise

    @log_errors
    async def list_job_gates(
        self,
        *,
        principal: AuthenticatedPrincipal,
        job_id: uuid.UUID,
        state: str | None = None,
    ) -> list[Gate]:
        """List gates for an authorized job with loaded decisions."""
        try:
            require_permission(principal, Permission.GATE_VIEW)
            # Verify job access
            job = await self._jobs.get_by_id_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
            )
            if job is None:
                raise GateNotFoundError(f"Job '{job_id}' not found")

            gates = await self._gates.list_gates_by_job_scoped(
                job_id=job_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                state=state,
            )
            return gates
        except Exception:
            raise

    @log_errors
    async def list_gate_decisions(
        self,
        *,
        principal: AuthenticatedPrincipal,
        gate_id: uuid.UUID,
        job_id: uuid.UUID | None = None,
    ) -> list[GateDecision]:
        """Return the immutable audit history of decisions for a gate."""
        try:
            gate = await self.get_gate(principal=principal, gate_id=gate_id, job_id=job_id)
            return await self._gates.list_decisions_for_gate(gate.id)
        except Exception:
            raise

    @log_errors
    async def decide_gate(
        self,
        *,
        principal: AuthenticatedPrincipal,
        gate_id: uuid.UUID,
        decision: str,
        reason: str | None = None,
        artifact_versions: dict[str, Any] | None = None,
        artifact_diff_ref: str | None = None,
        waivers: list[dict[str, Any]] | dict[str, Any] | None = None,
        return_to_stage: bool = True,
        rejection_target: str | None = None,
        job_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
    ) -> GateDecision:
        """Render an authorized, immutable, append-only human gate decision under database lock."""
        try:
            require_permission(principal, Permission.GATE_DECIDE)

            actor_user_id = principal.user_id
            actor_role = next((r.value for r in principal.roles), "approver")
            actor_name = principal.subject or str(principal.user_id)

            # 1. Acquire row-level lock on the gate
            gate = await self._gates.get_by_id_scoped(
                gate_id=gate_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                for_update=True,
            )
            if gate is None or (job_id is not None and gate.job_id != job_id):
                raise GateNotFoundError(str(gate_id))

            # 2. Check current state and terminal closure
            if is_terminal_gate_state(gate.state):
                raise DuplicateDecisionError(str(gate_id))

            if gate.state == GateState.PAUSED.value:
                raise GateClosedError(str(gate_id), gate.state)

            if gate.state != GateState.PENDING.value:
                raise GateClosedError(str(gate_id), gate.state)

            # 3. Check timeout: now >= gate.timeout_at transitions to paused (NEVER to approved)
            now = datetime.now(UTC)
            if gate.timeout_at and now >= gate.timeout_at:
                await self._gates.transition_gate_state(gate, GateState.PAUSED)
                await self._audit.append_event(
                    actor="system:timeout",
                    action="GATE_PAUSED",
                    job_id=gate.job_id,
                    correlation_id=correlation_id,
                    payload={"gate_id": str(gate.id), "reason": "Gate timeout threshold exceeded"},
                )
                await default_gate_dispatcher.dispatch(
                    GateNotificationEvent(
                        event_type=GateNotificationType.GATE_PAUSED,
                        gate_id=gate.id,
                        job_id=gate.job_id,
                        gate_type=gate.gate_type,
                        details={"reason": "timeout"},
                    )
                )
                raise GateTimeoutError(str(gate.id))

            # 4. Artifact Version Binding Check
            if gate.artifact_versions_shown:
                # 4a. Client submitted versions must match gate versions
                if artifact_versions is not None:
                    for art_key, reviewed_ver in artifact_versions.items():
                        if art_key in gate.artifact_versions_shown:
                            expected_ver = int(gate.artifact_versions_shown[art_key])
                            if int(reviewed_ver) != expected_ver:
                                raise StaleArtifactVersionError(
                                    artifact_id=str(art_key),
                                    expected_version=expected_ver,
                                    actual_version=int(reviewed_ver),
                                )

                # 4b. Database check: has any artifact version increased since gate was opened?
                for art_key, expected_ver in gate.artifact_versions_shown.items():
                    is_uuid = False
                    art_uuid: uuid.UUID | None = None
                    try:
                        art_uuid = uuid.UUID(str(art_key))
                        is_uuid = True
                    except ValueError:
                        is_uuid = False

                    if is_uuid and art_uuid is not None:
                        db_art = await self._artifacts._get_by_id_unscoped(art_uuid)
                        if db_art and db_art.version > int(expected_ver):
                            raise StaleArtifactVersionError(
                                artifact_id=str(art_key),
                                expected_version=int(expected_ver),
                                actual_version=db_art.version,
                            )
                    else:
                        # art_key is an artifact type string
                        max_stmt = select(func.max(Artifact.version)).where(
                            Artifact.job_id == gate.job_id,
                            Artifact.type == str(art_key),
                        )
                        max_res = await self.session.execute(max_stmt)
                        current_max = max_res.scalar()
                        if current_max is not None and current_max > int(expected_ver):
                            raise StaleArtifactVersionError(
                                artifact_id=str(art_key),
                                expected_version=int(expected_ver),
                                actual_version=current_max,
                            )

            # 5. Validation per decision type
            dec_norm = decision.lower()
            if dec_norm == GateDecisionType.REJECTED.value and (
                not reason or not str(reason).strip()
            ):
                raise MissingRejectionRationaleError(str(gate.id))

            if dec_norm == GateDecisionType.WAIVED.value and (
                not reason or not str(reason).strip()
            ):
                raise InvalidWaiverError("Waiver decisions require written justification reason.")

            # 6. Format waivers dictionary
            waivers_dict: dict[str, Any] | None = None
            if waivers:
                waivers_dict = {"items": waivers} if isinstance(waivers, list) else dict(waivers)

            # Authoritative artifact version snapshot at decision time
            effective_art_versions = artifact_versions or gate.artifact_versions_shown

            # 7. Record immutable decision in database
            decision_record = await self._gates.record_authorized_decision(
                gate=gate,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                actor_name=actor_name,
                decision=dec_norm,
                feedback=reason,
                waivers=waivers_dict,
                artifact_version_refs=effective_art_versions,
                artifact_diff_ref=artifact_diff_ref or gate.artifact_diff_ref,
            )

            # 8. Dispatch notification event
            event_type = (
                GateNotificationType.GATE_APPROVED
                if dec_norm in (GateDecisionType.APPROVED.value, GateDecisionType.WAIVED.value)
                else GateNotificationType.GATE_REJECTED
            )
            await default_gate_dispatcher.dispatch(
                GateNotificationEvent(
                    event_type=event_type,
                    gate_id=gate.id,
                    job_id=gate.job_id,
                    gate_type=gate.gate_type,
                    details={
                        "decision": dec_norm,
                        "actor": actor_name,
                        "reason": reason,
                        "waivers": waivers_dict,
                    },
                )
            )

            # 9. Append immutable audit event
            audit_action = (
                "GATE_APPROVED"
                if dec_norm == GateDecisionType.APPROVED.value
                else (
                    "GATE_WAIVED" if dec_norm == GateDecisionType.WAIVED.value else "GATE_REJECTED"
                )
            )
            await self._audit.append_event(
                actor=actor_name,
                actor_user_id=actor_user_id,
                action=audit_action,
                job_id=gate.job_id,
                correlation_id=correlation_id,
                payload={
                    "gate_id": str(gate.id),
                    "decision_id": str(decision_record.id),
                    "decision": dec_norm,
                    "reason": reason,
                    "approver_role": actor_role,
                    "artifact_versions": effective_art_versions,
                },
            )

            # 10. Resume workflow if workflow engine is present
            if self._engine:
                if dec_norm in (GateDecisionType.APPROVED.value, GateDecisionType.WAIVED.value):
                    await self._engine.resume_workflow(
                        job_id=gate.job_id,
                        resume_payload={
                            "decision": "approved",
                            "actor": actor_name,
                            "feedback": reason,
                            "waivers": waivers_dict,
                        },
                        session=self.session,
                        correlation_id=correlation_id,
                    )
                elif dec_norm == GateDecisionType.REJECTED.value:
                    target = rejection_target or get_rejection_target_stage(gate.gate_type)
                    await self._engine.resume_workflow(
                        job_id=gate.job_id,
                        resume_payload={
                            "decision": "rejected",
                            "actor": actor_name,
                            "feedback": reason,
                            "return_to_stage": return_to_stage,
                            "rejection_target": target,
                        },
                        session=self.session,
                        correlation_id=correlation_id,
                    )

            return decision_record
        except Exception:
            raise

    @log_errors
    async def resume_gate(
        self,
        *,
        principal: AuthenticatedPrincipal,
        gate_id: uuid.UUID,
        reason: str | None = None,
        job_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
    ) -> Gate:
        """Resume a paused or timed out gate back to pending state for human decision."""
        try:
            require_permission(principal, Permission.GATE_DECIDE)

            gate = await self._gates.get_by_id_scoped(
                gate_id=gate_id,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                membership_id=principal.membership_id,
                tenant_admin=has_tenant_admin_scope(principal),
                for_update=True,
            )
            if gate is None or (job_id is not None and gate.job_id != job_id):
                raise GateNotFoundError(str(gate_id))

            if gate.state not in (GateState.PAUSED.value, GateState.TIMED_OUT.value):
                raise InvalidGateStateTransitionError(
                    from_state=gate.state,
                    to_state=GateState.PENDING.value,
                    reason=f"Cannot resume gate from non-paused state '{gate.state}'.",
                )

            gate = await self._gates.transition_gate_state(gate, GateState.PENDING)

            actor_name = principal.subject or str(principal.user_id)
            await self._audit.append_event(
                actor=actor_name,
                actor_user_id=principal.user_id,
                action="GATE_RESUMED",
                job_id=gate.job_id,
                correlation_id=correlation_id,
                payload={"gate_id": str(gate.id), "reason": reason},
            )

            await default_gate_dispatcher.dispatch(
                GateNotificationEvent(
                    event_type=GateNotificationType.GATE_RESUMED,
                    gate_id=gate.id,
                    job_id=gate.job_id,
                    gate_type=gate.gate_type,
                    details={"reason": reason, "resumed_by": actor_name},
                )
            )

            return gate
        except Exception:
            raise

    @log_errors
    async def check_and_handle_timeouts(
        self,
        current_time: datetime | None = None,
    ) -> list[Gate]:
        """Scan for expired pending gates and transition them to paused state.

        Timeout MUST NOT produce approved state.
        """
        try:
            now = current_time or datetime.now(UTC)
            expired_gates = await self._gates.find_expired_pending_gates(now)
            paused_gates: list[Gate] = []

            for gate in expired_gates:
                # Lock and verify
                locked_gate = await self._gates._get_by_id_unscoped(gate.id, for_update=True)
                if locked_gate and locked_gate.state == GateState.PENDING.value:
                    await self._gates.transition_gate_state(locked_gate, GateState.PAUSED)

                    await self._audit.append_event(
                        actor="system:timeout",
                        action="GATE_PAUSED",
                        job_id=locked_gate.job_id,
                        payload={
                            "gate_id": str(locked_gate.id),
                            "reason": "Automated timeout reconciliation",
                            "timeout_at": (
                                locked_gate.timeout_at.isoformat()
                                if locked_gate.timeout_at
                                else None
                            ),
                        },
                    )

                    await default_gate_dispatcher.dispatch(
                        GateNotificationEvent(
                            event_type=GateNotificationType.GATE_PAUSED,
                            gate_id=locked_gate.id,
                            job_id=locked_gate.job_id,
                            gate_type=locked_gate.gate_type,
                            details={"reason": "timeout_reconciliation"},
                        )
                    )

                    # Update associated job state if awaiting approval
                    job = await self._jobs._get_by_id_unscoped(locked_gate.job_id)
                    if job and job.status in (
                        JobLifecycleState.AWAITING_APPROVAL.value,
                        JobLifecycleState.RUNNING.value,
                    ):
                        job.status = JobLifecycleState.PAUSED.value
                        await self.session.flush()

                    paused_gates.append(locked_gate)

            return paused_gates
        except Exception as exc:
            logger.exception("check_and_handle_timeouts failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["GateService"]
