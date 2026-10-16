"""Provider-neutral Model Gateway Service.

Orchestrates policy validation, budget reservations, retries, fallbacks,
execution tracking, and OpenTelemetry instrumentation.
"""

import asyncio
import logging
import time
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.config.settings import Settings, get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.contracts import (
    ModelExecutionContext,
    ModelRequest,
    ModelResponse,
)
from modernization_platform.domain.model_gateway.errors import (
    ModelAuthenticationError,
    ModelBudgetExceededError,
    ModelBudgetReservationError,
    ModelFallbackExhaustedError,
    ModelGatewayError,
    ModelPolicyViolationError,
    ModelProviderUnavailableError,
    ModelRateLimitError,
    ModelTimeoutError,
    NoEligibleProviderError,
)
from modernization_platform.domain.model_gateway.policy import (
    PolicyRegistry,
    default_policy_registry,
    validate_policy_invocation,
)
from modernization_platform.domain.model_gateway.pricing import (
    PricingRegistry,
    default_pricing_registry,
)
from modernization_platform.domain.model_gateway.redaction import (
    redact_string,
)
from modernization_platform.integrations.models.anthropic import AnthropicProviderAdapter
from modernization_platform.integrations.models.base import BaseProviderAdapter
from modernization_platform.integrations.models.mock import MockProviderAdapter
from modernization_platform.integrations.models.openai import OpenAIProviderAdapter
from modernization_platform.integrations.models.openrouter import OpenRouterProviderAdapter
from modernization_platform.integrations.models.qwen import QwenProviderAdapter
from modernization_platform.observability.metrics import default_metrics_registry
from modernization_platform.observability.telemetry import (
    trace_model_call,
    trace_provider_request,
)
from modernization_platform.repositories.agent_runs import AgentRunRepository
from modernization_platform.repositories.model_executions import ModelExecutionRepository
from modernization_platform.services.model_gateway.budget_service import BudgetService

logger = logging.getLogger(__name__)


@log_errors
def is_retryable_error(exc: Exception) -> bool:
    """Classify whether a model invocation failure is safe and appropriate to retry."""
    if isinstance(
        exc,
        (
            ModelAuthenticationError,
            ModelPolicyViolationError,
            ModelBudgetExceededError,
            ModelBudgetReservationError,
            NoEligibleProviderError,
        ),
    ):
        return False

    msg = str(exc).lower()
    if (
        "429" in msg
        or "rate limit" in msg
        or "timeout" in msg
        or "connection reset" in msg
        or "503" in msg
        or "temporary" in msg
        or "overloaded" in msg
    ):
        return True

    return isinstance(exc, (ModelRateLimitError, ModelTimeoutError, ModelProviderUnavailableError))


class ModelGatewayService:
    """Authoritative provider-neutral entry point for all hosted LLM operations."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        pricing_registry: PricingRegistry | None = None,
        policy_registry: PolicyRegistry | None = None,
        adapters: Mapping[str, BaseProviderAdapter] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.pricing = pricing_registry or default_pricing_registry
        self.policy_registry = policy_registry or default_policy_registry
        self.budget_service = BudgetService(session)
        self.execution_repo = ModelExecutionRepository(session)
        self.agent_run_repo = AgentRunRepository(session)

        # Initialize provider adapters
        self.adapters: dict[str, BaseProviderAdapter] = (
            dict(adapters)
            if adapters is not None
            else {
                "mock": MockProviderAdapter(),
                "openai": OpenAIProviderAdapter(self.settings),
                "anthropic": AnthropicProviderAdapter(self.settings),
                "qwen": QwenProviderAdapter(self.settings),
                "openrouter": OpenRouterProviderAdapter(self.settings),
            }
        )

    @log_errors
    def register_adapter(self, provider: str, adapter: BaseProviderAdapter) -> None:
        """Register or override a provider adapter."""
        self.adapters[provider.lower()] = adapter

    @log_errors
    async def generate(
        self,
        request: ModelRequest,
        context: ModelExecutionContext,
    ) -> ModelResponse:
        """Execute a provider-neutral model generation request with strict controls.

        Lifecycle:
        1. Policy Validation (reject unapproved models, providers, agents)
        2. Budget Estimation & Atomic Concurrency-Safe Reservation
        3. Rate Limit & Timeout Enforcement
        4. Outbound Provider Execution with Retry Loop
        5. Fallback Routing if primary provider fails
        6. Spend Reconciliation (release unspent or apply actuals)
        7. Audit Record Persistence & Telemetry Recording
        """
        # 1. Resolve Policy
        policy = self.policy_registry.get_policy_for_agent(context.agent_role)
        validate_policy_invocation(policy, request, context)

        # Set default model if unspecified
        target_model = request.model or policy.primary_model
        effective_request = (
            request
            if request.model == target_model
            else request.model_copy(update={"model": target_model})
        )

        # Estimate input tokens and cost
        est_input_tokens = len(" ".join(m.content for m in effective_request.messages)) // 4
        est_max_output = effective_request.max_tokens or policy.max_tokens
        est_cost = self.pricing.estimate_cost(
            provider=policy.allowed_providers[0] if policy.allowed_providers else "mock",
            model_id=target_model,
            estimated_input_tokens=est_input_tokens,
            max_output_tokens=est_max_output,
        )

        # 2. Concurrency-Safe Budget Reservation
        reservation = await self.budget_service.reserve_budget(
            job_id=context.job_id,
            agent_role=context.agent_role,
            estimated_microcents=est_cost,
            task_id=context.task_id,
        )

        providers_to_try = list(policy.allowed_providers)
        if not providers_to_try:
            await self.budget_service.release_reservation(reservation.id, reason="no_provider")
            raise NoEligibleProviderError("No eligible providers configured in approved policy")

        last_error: Exception | None = None
        start_time = time.perf_counter()

        # 3. Execution Loop with Fallback Support
        for provider_idx, provider_name in enumerate(providers_to_try):
            adapter = self.adapters.get(provider_name.lower())
            if not adapter:
                logger.warning("Provider adapter %s not found; trying fallback", provider_name)
                continue

            current_model = target_model
            if provider_idx > 0:
                default_metrics_registry.record_model_fallback(providers_to_try[0], provider_name)
                for ft in policy.fallback_targets:
                    if ft.provider.lower() == provider_name.lower():
                        current_model = ft.model_id
                        break
                if current_model != effective_request.model:
                    effective_request = effective_request.model_copy(
                        update={"model": current_model}
                    )

            # Attempt provider execution with retry loop
            attempts = 0
            max_retries = policy.max_retries

            while attempts <= max_retries:
                attempts += 1
                try:
                    async with (
                        trace_model_call(
                            provider=provider_name,
                            model_id=current_model,
                            job_id=str(context.job_id),
                            task_id=str(context.task_id) if context.task_id else None,
                            agent_role=context.agent_role,
                            correlation_id=context.correlation_id,
                        ),
                        trace_provider_request(provider_name, current_model),
                    ):
                        # Enforce explicit per-call timeout
                        response = await asyncio.wait_for(
                            adapter.generate(
                                effective_request,
                                context,
                                timeout_seconds=policy.timeout_seconds,
                            ),
                            timeout=policy.timeout_seconds,
                        )

                    # Successful generation: reconcile budget and record telemetry
                    duration_s = time.perf_counter() - start_time
                    duration_ms = int(duration_s * 1000)

                    actual_cost = response.usage.actual_cost_microcents or est_cost
                    await self.budget_service.reconcile_reservation(
                        reservation_id=reservation.id,
                        actual_microcents=actual_cost,
                    )

                    # Update response usage duration
                    response.usage.duration_ms = duration_ms

                    # Record metrics
                    default_metrics_registry.record_model_call(
                        provider_name, current_model, status="success"
                    )
                    default_metrics_registry.record_model_tokens(
                        provider_name, current_model, "input", response.usage.input_tokens
                    )
                    default_metrics_registry.record_model_tokens(
                        provider_name, current_model, "output", response.usage.output_tokens
                    )
                    default_metrics_registry.record_model_tokens(
                        provider_name, current_model, "total", response.usage.total_tokens
                    )
                    default_metrics_registry.record_model_cost(
                        provider_name, current_model, actual_cost
                    )
                    default_metrics_registry.record_model_duration(
                        provider_name, current_model, duration_s
                    )

                    # 1. Persist AgentRun record for historical analytics and satisfy foreign key
                    recorded_run_id = context.agent_run_id
                    try:
                        agent_run = await self.agent_run_repo.record_run(
                            job_id=context.job_id,
                            agent=context.agent_role,
                            model=current_model,
                            prompt_version=request.prompt_version,
                            input_artifact_ids=request.metadata.get("input_artifact_ids"),
                            output_artifact_ids=request.metadata.get("output_artifact_ids"),
                            tokens_input=response.usage.input_tokens,
                            tokens_output=response.usage.output_tokens,
                            cost_cents=actual_cost / 10000.0,
                            duration_ms=duration_ms,
                            tool_calls=[
                                {"name": tc.name, "arguments": tc.arguments}
                                for tc in response.tool_calls
                            ],
                            run_id=context.agent_run_id,
                        )
                        recorded_run_id = agent_run.id
                    except Exception as exc:
                        logger.warning("Could not persist agent_run record: %s", exc)
                        recorded_run_id = None

                    # 2. Persist ModelExecution audit record
                    await self.execution_repo.record_execution(
                        job_id=context.job_id,
                        agent_role=context.agent_role,
                        stage=context.stage,
                        provider=provider_name,
                        model_id=current_model,
                        prompt_version=effective_request.prompt_version,
                        correlation_id=context.correlation_id,
                        task_id=context.task_id,
                        agent_run_id=recorded_run_id,
                        workflow_thread_id=context.workflow_thread_id,
                        module=context.module,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        estimated_cost_microcents=est_cost,
                        actual_cost_microcents=actual_cost,
                        duration_ms=duration_ms,
                        status="success",
                        attempt_number=attempts,
                        is_fallback=(provider_idx > 0),
                        primary_provider=providers_to_try[0] if provider_idx > 0 else None,
                        primary_model_id=target_model if provider_idx > 0 else None,
                        tool_call_count=len(response.tool_calls),
                        tool_calls=[
                            {"name": tc.name, "arguments": tc.arguments}
                            for tc in response.tool_calls
                        ],
                        artifact_id=context.artifact_id,
                        artifact_version=context.artifact_version,
                    )

                    return response

                except TimeoutError:
                    last_error = ModelTimeoutError(
                        provider=provider_name, timeout_seconds=policy.timeout_seconds
                    )
                    default_metrics_registry.record_model_failure(
                        provider_name, target_model, "timeout"
                    )
                    if attempts <= max_retries:
                        default_metrics_registry.record_model_retry(provider_name, target_model)
                        await asyncio.sleep(0.05 * attempts)
                        continue
                    break

                except Exception as exc:
                    last_error = exc
                    is_retryable = is_retryable_error(exc)
                    failure_type = "rate_limit" if "429" in str(exc) else type(exc).__name__
                    default_metrics_registry.record_model_failure(
                        provider_name, target_model, failure_type
                    )

                    if "429" in str(exc) or "rate limit" in str(exc).lower():
                        default_metrics_registry.record_model_rate_limit(provider_name)

                    if is_retryable and attempts <= max_retries:
                        default_metrics_registry.record_model_retry(provider_name, target_model)
                        logger.warning(
                            "Retrying model call on provider %s (attempt %d/%d) after error: %s",
                            provider_name,
                            attempts,
                            max_retries,
                            redact_string(str(exc)),
                        )
                        await asyncio.sleep(0.05 * attempts)
                        continue
                    else:
                        logger.warning(
                            "Non-retryable or max retries reached for provider %s: %s",
                            provider_name,
                            redact_string(str(exc)),
                        )
                        break

        # If all providers/fallbacks exhausted: release reservation and persist failure
        await self.budget_service.release_reservation(reservation.id, reason="provider_failure")

        safe_err_msg = redact_string(str(last_error)) if last_error else "Unknown failure"
        await self.execution_repo.record_execution(
            job_id=context.job_id,
            agent_role=context.agent_role,
            stage=context.stage,
            provider=providers_to_try[0],
            model_id=target_model,
            prompt_version=effective_request.prompt_version,
            correlation_id=context.correlation_id,
            task_id=context.task_id,
            agent_run_id=context.agent_run_id,
            workflow_thread_id=context.workflow_thread_id,
            module=context.module,
            status="failed",
            failure_classification=type(last_error).__name__ if last_error else "UnknownError",
            fallback_reason=safe_err_msg,
            estimated_cost_microcents=est_cost,
            actual_cost_microcents=0,
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            artifact_id=context.artifact_id,
            artifact_version=context.artifact_version,
        )

        if len(providers_to_try) > 1:
            raise ModelFallbackExhaustedError(
                f"All approved model providers failed. Last error: {safe_err_msg}"
            )
        if isinstance(last_error, ModelGatewayError):
            raise last_error
        raise ModelProviderUnavailableError(providers_to_try[0], safe_err_msg)


__all__ = ["ModelGatewayService", "is_retryable_error"]
