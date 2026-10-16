"""Abstract base class for provider-specific model adapters."""

import logging
from abc import ABC, abstractmethod

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.contracts import (
    ModelExecutionContext,
    ModelRequest,
    ModelResponse,
)

logger = logging.getLogger(__name__)


class BaseProviderAdapter(ABC):
    """Abstract interface isolating provider-specific HTTP APIs and SDK dispatch logic."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Normalized lowercase provider name."""
        ...

    @abstractmethod
    async def generate(
        self,
        request: ModelRequest,
        context: ModelExecutionContext,
        timeout_seconds: float = 60.0,
    ) -> ModelResponse:
        """Invoke the provider endpoint and return a provider-neutral ModelResponse."""
        ...

    @log_errors
    def estimate_input_tokens(self, request: ModelRequest) -> int:
        """Heuristic character/word-based token estimator for pre-flight budget reservation."""
        try:
            total_chars = sum(len(m.content) for m in request.messages)
            # Standard heuristic: ~4 characters per token + tool definitions overhead
            token_estimate = max(10, total_chars // 4)
            if request.tools:
                token_estimate += len(request.tools) * 50
            return token_estimate
        except Exception as exc:
            logger.exception("estimate_input_tokens failed | %s: %s", type(exc).__name__, exc)
            return 500


__all__ = ["BaseProviderAdapter"]
