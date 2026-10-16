"""Workflow-to-Agent Model Gateway dispatch bridge."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
    ModelResponse,
)
from modernization_platform.domain.model_gateway.errors import (
    ModelBudgetExceededError,
    ModelGatewayError,
)
from modernization_platform.services.model_gateway.gateway_service import (
    ModelGatewayService,
)

logger = logging.getLogger(__name__)


@log_errors
async def dispatch_agent_step(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    agent_role: str,
    prompt: str,
    prompt_version: str = "v1.0",
    task_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    workflow_thread_id: str | None = None,
    input_artifact_ids: list[str] | None = None,
    output_artifact_ids: list[str] | None = None,
    correlation_id: str | None = None,
    custom_model: str | None = None,
    max_tokens: int = 1000,
    temperature: float = 0.7,
) -> ModelResponse:
    """Execute an agent reasoning/transformation step through the Model Gateway.

    Adheres strictly to the architectural hierarchy:
    Job -> Workflow -> Task -> Agent -> Model Gateway -> Provider Adapter
    """
    try:
        gateway = ModelGatewayService(session)

        request = ModelRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            model=custom_model,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_version=prompt_version,
            metadata={
                "input_artifact_ids": input_artifact_ids or [],
                "output_artifact_ids": output_artifact_ids or [],
            },
        )

        context = ModelExecutionContext(
            job_id=job_id,
            task_id=task_id,
            workflow_thread_id=workflow_thread_id or str(job_id),
            agent_run_id=agent_run_id,
            agent_role=agent_role,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )

        return await gateway.generate(request, context)

    except ModelBudgetExceededError:
        logger.error("Agent %s step halted: budget exhausted for job %s", agent_role, job_id)
        raise
    except ModelGatewayError:
        logger.exception("Agent %s step failed under gateway error for job %s", agent_role, job_id)
        raise
    except Exception as exc:
        logger.exception(
            "dispatch_agent_step failed unexpectedly | %s: %s", type(exc).__name__, exc
        )
        raise


__all__ = ["dispatch_agent_step"]
