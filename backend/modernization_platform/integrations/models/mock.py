"""Deterministic mock provider adapter for tests, CI/CD, and simulated failures."""

import asyncio
import logging
from datetime import UTC, datetime

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.contracts import (
    ModelExecutionContext,
    ModelRequest,
    ModelResponse,
    ToolCall,
    UsageMetrics,
)
from modernization_platform.domain.model_gateway.pricing import (
    PricingRegistry,
    default_pricing_registry,
)
from modernization_platform.integrations.models.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class MockProviderAdapter(BaseProviderAdapter):
    """Configurable mock adapter for deterministic test execution and failure injection."""

    def __init__(
        self,
        provider_name: str = "mock",
        default_model: str = "mock-model",
        default_response: str | None = None,
        simulate_error: Exception | None = None,
        fail_attempts: int = 1,
        simulated_delay_seconds: float = 0.0,
        pricing_registry: PricingRegistry | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._default_model = default_model
        self._call_count = 0
        self._fail_attempts = fail_attempts if simulate_error else 0
        self._injected_exception = simulate_error
        self._simulated_delay_seconds = simulated_delay_seconds
        self._canned_response_content = default_response
        self._canned_tool_calls: list[ToolCall] | None = None
        self._simulated_tokens: tuple[int, int] | None = None
        self._pricing_registry = pricing_registry or default_pricing_registry

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def call_count(self) -> int:
        return self._call_count

    @log_errors
    def configure_failure(self, exc: Exception, fail_attempts: int = 1) -> None:
        """Inject a deterministic failure for the next N invocation attempts."""
        self._injected_exception = exc
        self._fail_attempts = fail_attempts

    @log_errors
    def configure_response(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        tokens: tuple[int, int] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        """Configure return content and token usage."""
        self._canned_response_content = content
        self._canned_tool_calls = tool_calls
        self._simulated_tokens = tokens
        self._simulated_delay_seconds = delay_seconds

    @log_errors
    def reset(self) -> None:
        """Reset mock state between tests."""
        self._call_count = 0
        self._fail_attempts = 0
        self._injected_exception = None
        self._simulated_delay_seconds = 0.0
        self._canned_response_content = None
        self._canned_tool_calls = None
        self._simulated_tokens = None

    @log_errors
    async def generate(
        self,
        request: ModelRequest,
        context: ModelExecutionContext,
        timeout_seconds: float = 60.0,
    ) -> ModelResponse:
        """Execute simulated model generation."""
        try:
            self._call_count += 1

            if self._simulated_delay_seconds > 0:
                await asyncio.sleep(self._simulated_delay_seconds)

            if self._fail_attempts > 0 and self._injected_exception is not None:
                self._fail_attempts -= 1
                raise self._injected_exception

            model_id = request.model or self._default_model
            input_tokens = (
                self._simulated_tokens[0]
                if self._simulated_tokens
                else self.estimate_input_tokens(request)
            )
            output_tokens = self._simulated_tokens[1] if self._simulated_tokens else 150

            actual_microcents = self._pricing_registry.calculate_cost(
                self.provider_name, model_id, input_tokens, output_tokens
            )

            usage = UsageMetrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                estimated_cost_microcents=actual_microcents,
                actual_cost_microcents=actual_microcents,
                duration_ms=int(self._simulated_delay_seconds * 1000) or 50,
            )

            content = (
                self._canned_response_content
                if self._canned_response_content is not None
                else f"Mock response from {self.provider_name}/{model_id} for {context.agent_role}"
            )

            tool_calls = self._canned_tool_calls or []

            return ModelResponse(
                content=content,
                model_id=model_id,
                provider=self.provider_name,
                usage=usage,
                tool_calls=tool_calls,
                finish_reason="stop",
                created_at=datetime.now(UTC),
            )
        except Exception:
            raise


__all__ = ["MockProviderAdapter"]
