"""Provider-neutral Model Gateway domain package."""

from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    UsageMetrics,
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
    FallbackTarget,
    ModelPolicy,
    PolicyRegistry,
    default_policy_registry,
    validate_policy_invocation,
)
from modernization_platform.domain.model_gateway.pricing import (
    MICROCENTS_PER_CENT,
    MICROCENTS_PER_DOLLAR,
    ModelPricing,
    PricingRegistry,
    cents_to_microcents,
    default_pricing_registry,
    microcents_to_cents,
)
from modernization_platform.domain.model_gateway.redaction import (
    redact_data,
    redact_exception,
    redact_string,
)

__all__ = [
    "MICROCENTS_PER_CENT",
    "MICROCENTS_PER_DOLLAR",
    "ChatMessage",
    "FallbackTarget",
    "ModelAuthenticationError",
    "ModelBudgetExceededError",
    "ModelBudgetReservationError",
    "ModelExecutionContext",
    "ModelFallbackExhaustedError",
    "ModelGatewayError",
    "ModelPolicy",
    "ModelPolicyViolationError",
    "ModelPricing",
    "ModelProviderUnavailableError",
    "ModelRateLimitError",
    "ModelRequest",
    "ModelResponse",
    "ModelTimeoutError",
    "NoEligibleProviderError",
    "PolicyRegistry",
    "PricingRegistry",
    "ToolCall",
    "ToolDefinition",
    "UsageMetrics",
    "cents_to_microcents",
    "default_policy_registry",
    "default_pricing_registry",
    "microcents_to_cents",
    "redact_data",
    "redact_exception",
    "redact_string",
    "validate_policy_invocation",
]
