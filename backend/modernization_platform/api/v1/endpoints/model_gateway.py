"""REST API endpoints for hosted Model Gateway, Budgets, and Model Telemetry."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.session import get_db_session
from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
    ToolDefinition,
)
from modernization_platform.domain.model_gateway.pricing import microcents_to_cents
from modernization_platform.observability.metrics import default_metrics_registry
from modernization_platform.schemas.model_gateway import (
    BudgetAccountResponse,
    ModelExecutionResponse,
    ModelGenerateApiRequest,
    ModelGenerateApiResponse,
)
from modernization_platform.security.dependencies import CurrentPrincipal
from modernization_platform.services.model_gateway.budget_service import BudgetService
from modernization_platform.services.model_gateway.gateway_service import ModelGatewayService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/jobs/{job_id}/models/generate",
    response_model=ModelGenerateApiResponse,
    status_code=status.HTTP_200_OK,
)
@log_errors
async def generate_model_completion(
    job_id: uuid.UUID,
    body: ModelGenerateApiRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelGenerateApiResponse:
    """Invoke the provider-neutral Model Gateway under strict policy and budget controls."""
    try:
        gateway = ModelGatewayService(session)

        messages = [
            ChatMessage(
                role=m.get("role", "user"),
                content=m.get("content", ""),
                name=m.get("name"),
            )
            for m in body.messages
        ]

        tools = [
            ToolDefinition(
                name=t.get("name", "tool"),
                description=t.get("description", ""),
                parameters=t.get("parameters", {}),
            )
            for t in (body.tools or [])
        ]

        model_request = ModelRequest(
            messages=messages,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            prompt_version=body.prompt_version,
            tools=tools,
            metadata=body.metadata or {},
        )

        context = ModelExecutionContext(
            job_id=job_id,
            task_id=body.task_id,
            agent_run_id=body.agent_run_id,
            agent_role=body.agent_role,
            tenant_id=principal.tenant_id if hasattr(principal, "tenant_id") else None,
            correlation_id=request.headers.get("X-Correlation-ID") or str(uuid.uuid4()),
        )

        response = await gateway.generate(model_request, context)

        return ModelGenerateApiResponse(
            content=response.content,
            provider=response.provider,
            model_id=response.model_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            cost_cents=microcents_to_cents(response.usage.actual_cost_microcents),
            cost_microcents=response.usage.actual_cost_microcents,
            duration_ms=response.usage.duration_ms,
            tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls],
        )
    except Exception:
        raise


@router.get(
    "/jobs/{job_id}/budgets",
    response_model=list[BudgetAccountResponse],
    status_code=status.HTTP_200_OK,
)
@log_errors
async def list_job_budgets(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[BudgetAccountResponse]:
    """Retrieve durable budget accounts and live spend/reservation tracking for a job."""
    try:
        budget_service = BudgetService(session)
        accounts = await budget_service.list_job_accounts(job_id)
        return [BudgetAccountResponse.from_orm_model(acc) for acc in accounts]
    except Exception:
        raise


@router.get(
    "/jobs/{job_id}/models/executions",
    response_model=list[ModelExecutionResponse],
    status_code=status.HTTP_200_OK,
)
@log_errors
async def list_job_model_executions(
    job_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    provider_filter: Annotated[str | None, Query(alias="provider")] = None,
) -> list[ModelExecutionResponse]:
    """Retrieve audited model executions and token expenditures for a modernization job."""
    try:
        from modernization_platform.repositories.model_executions import ModelExecutionRepository

        repo = ModelExecutionRepository(session)
        executions = await repo.list_executions_by_job(
            job_id=job_id,
            status=status_filter,
            provider=provider_filter,
        )
        return [ModelExecutionResponse.from_orm_model(e) for e in executions]
    except Exception:
        raise


@router.get(
    "/models/metrics",
    status_code=status.HTTP_200_OK,
)
@log_errors
async def get_model_gateway_metrics(
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Retrieve in-memory OpenTelemetry-compatible platform metric counters and gauges."""
    return default_metrics_registry.snapshot()


__all__ = ["router"]
