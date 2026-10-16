"""Workflow execution engine orchestrating LangGraph invocations, durable checkpoints, and interrupts."""

import logging
import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.workflows.graph import (
    compile_workflow_graph,
    get_workflow_thread_config,
)
from modernization_platform.workflows.reconciliation import WorkflowReconciliationService
from modernization_platform.workflows.state import (
    ModernizationWorkflowState,
    create_initial_workflow_state,
)

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Execution engine orchestrating compiled LangGraph execution with durable checkpoints and reconciliation."""

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self._checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self._graph = compile_workflow_graph(checkpointer=self._checkpointer)

    @property
    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        return self._checkpointer

    @staticmethod
    @log_errors
    def _resolve_snapshot_state(snapshot: Any) -> ModernizationWorkflowState:
        """Extract state values and map any active task interrupts to awaiting_approval status."""
        try:
            if not snapshot or not snapshot.values:
                return cast(ModernizationWorkflowState, {})
            latest_values: ModernizationWorkflowState = cast(
                ModernizationWorkflowState, dict(snapshot.values)
            )
            if snapshot.tasks and any(t.interrupts for t in snapshot.tasks):
                interrupts = [i for t in snapshot.tasks for i in t.interrupts]
                interrupt_val = interrupts[0].value if interrupts else {}
                gate_type = (
                    interrupt_val.get("gate_type") if isinstance(interrupt_val, dict) else None
                )

                latest_values["needs_human"] = True
                latest_values["current_gate"] = gate_type
                latest_values["status"] = JobLifecycleState.AWAITING_APPROVAL.value
                logger.info("Snapshot contains active interrupt at gate %s", gate_type)
            else:
                latest_values["needs_human"] = False
                latest_values["current_gate"] = None
            return latest_values
        except Exception as exc:
            logger.exception(
                "WorkflowEngine._resolve_snapshot_state failed | %s: %s", type(exc).__name__, exc
            )
            raise

    @log_errors
    async def start_workflow(
        self,
        *,
        job_id: uuid.UUID | str,
        tenant_id: uuid.UUID | str,
        owner: str,
        initial_state: ModernizationWorkflowState | None = None,
        session: AsyncSession | None = None,
        correlation_id: str | None = None,
    ) -> ModernizationWorkflowState:
        """Start or initiate workflow execution for a job under its stable thread ID."""
        try:
            thread_id = str(job_id)
            config: RunnableConfig = get_workflow_thread_config(thread_id)

            state_payload = initial_state or create_initial_workflow_state(
                job_id=job_id,
                tenant_id=tenant_id,
                owner=owner,
            )

            logger.info("Starting workflow thread %s for tenant %s", thread_id, tenant_id)
            await self._graph.ainvoke(cast(Any, state_payload), config=config)

            latest_snapshot = await self._graph.aget_state(config)
            latest_values = self._resolve_snapshot_state(latest_snapshot)

            # Reconcile with PostgreSQL Job table if session provided
            if session is not None:
                reconciler = WorkflowReconciliationService(session)
                await reconciler.reconcile_job_state(
                    state=latest_values,
                    correlation_id=correlation_id,
                )

            return latest_values
        except Exception as exc:
            logger.exception(
                "WorkflowEngine.start_workflow failed | %s: %s", type(exc).__name__, exc
            )
            raise

    @log_errors
    async def resume_workflow(
        self,
        *,
        job_id: uuid.UUID | str,
        resume_payload: dict[str, Any] | str,
        session: AsyncSession | None = None,
        correlation_id: str | None = None,
    ) -> ModernizationWorkflowState:
        """Resume an interrupted or paused workflow using LangGraph Command(resume=...)."""
        try:
            thread_id = str(job_id)
            config: RunnableConfig = get_workflow_thread_config(thread_id)

            logger.info("Resuming workflow thread %s with decision", thread_id)
            cmd: Command[Any] = Command(resume=resume_payload)
            await self._graph.ainvoke(cast(Any, cmd), config=config)

            latest_snapshot = await self._graph.aget_state(config)
            latest_values = self._resolve_snapshot_state(latest_snapshot)

            # Reconcile with PostgreSQL
            if session is not None:
                reconciler = WorkflowReconciliationService(session)
                await reconciler.reconcile_job_state(
                    state=latest_values,
                    correlation_id=correlation_id,
                )

            return latest_values
        except Exception as exc:
            logger.exception(
                "WorkflowEngine.resume_workflow failed | %s: %s", type(exc).__name__, exc
            )
            raise

    @log_errors
    async def get_state(
        self,
        job_id: uuid.UUID | str,
    ) -> ModernizationWorkflowState | None:
        """Fetch the latest durable checkpoint values for a job thread."""
        try:
            thread_id = str(job_id)
            config: RunnableConfig = get_workflow_thread_config(thread_id)
            snapshot = await self._graph.aget_state(config)
            if not snapshot or not snapshot.values:
                return None
            return self._resolve_snapshot_state(snapshot)
        except Exception as exc:
            logger.exception("WorkflowEngine.get_state failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["WorkflowEngine"]
