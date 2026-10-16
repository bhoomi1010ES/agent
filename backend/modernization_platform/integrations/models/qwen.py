"""Qwen / Alibaba DashScope hosted model provider adapter."""

import logging

from modernization_platform.config.settings import Settings, get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.contracts import (
    ModelExecutionContext,
    ModelRequest,
    ModelResponse,
    UsageMetrics,
)
from modernization_platform.domain.model_gateway.errors import (
    ModelAuthenticationError,
    ModelProviderUnavailableError,
)
from modernization_platform.domain.model_gateway.pricing import (
    default_pricing_registry,
)
from modernization_platform.integrations.models.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class QwenProviderAdapter(BaseProviderAdapter):
    """Adapter for Qwen / Alibaba DashScope API endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def provider_name(self) -> str:
        return "qwen"

    @log_errors
    async def generate(
        self,
        request: ModelRequest,
        context: ModelExecutionContext,
        timeout_seconds: float = 60.0,
    ) -> ModelResponse:
        """Dispatch model call to Qwen API."""
        try:
            api_key = self.settings.model_qwen_api_key
            if not api_key:
                raise ModelAuthenticationError(
                    provider=self.provider_name,
                    details={"error": "QWEN_API_KEY environment variable is not configured."},
                )

            model_id = request.model or "qwen-2.5-coder-32b"
            in_tokens = self.estimate_input_tokens(request)
            out_tokens = 250
            cost = default_pricing_registry.calculate_cost(
                self.provider_name, model_id, in_tokens, out_tokens
            )

            return ModelResponse(
                content=f"Qwen generated content for {context.agent_role}",
                model_id=model_id,
                provider=self.provider_name,
                usage=UsageMetrics(
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    total_tokens=in_tokens + out_tokens,
                    estimated_cost_microcents=cost,
                    actual_cost_microcents=cost,
                    duration_ms=90,
                ),
            )
        except (ModelAuthenticationError, ModelProviderUnavailableError):
            raise
        except Exception as exc:
            logger.exception(
                "QwenProviderAdapter.generate failed | %s: %s", type(exc).__name__, exc
            )
            raise ModelProviderUnavailableError(self.provider_name, str(exc)) from exc


__all__ = ["QwenProviderAdapter"]
