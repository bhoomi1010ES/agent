"""Pricing registry and integer microcent cost calculations."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)

# Currency scale: 1 USD = 1,000,000 microcents; 1 US cent = 10,000 microcents
MICROCENTS_PER_CENT = 10_000
MICROCENTS_PER_DOLLAR = 1_000_000


@dataclass(frozen=True)
class ModelPricing:
    """Pricing rate for a specific provider and model ID."""

    provider: str
    model_id: str
    input_microcents_per_1k: int
    output_microcents_per_1k: int
    effective_from: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    effective_to: datetime | None = None


class PricingRegistry:
    """Central registry of approved model pricing rates using integer microcent precision."""

    # Default rates in microcents per 1,000 tokens
    _DEFAULT_RATES: ClassVar[dict[tuple[str, str], ModelPricing]] = {
        # Mock / Test Provider (zero cost)
        ("mock", "mock-model"): ModelPricing(
            provider="mock",
            model_id="mock-model",
            input_microcents_per_1k=0,
            output_microcents_per_1k=0,
        ),
        ("mock", "mock-fallback"): ModelPricing(
            provider="mock",
            model_id="mock-fallback",
            input_microcents_per_1k=0,
            output_microcents_per_1k=0,
        ),
        # Qwen 2.5 Coder 32B ($0.15/1M in, $0.60/1M out -> 150/1k in, 600/1k out microcents)
        ("qwen", "qwen-2.5-coder-32b"): ModelPricing(
            provider="qwen",
            model_id="qwen-2.5-coder-32b",
            input_microcents_per_1k=150,
            output_microcents_per_1k=600,
        ),
        # Anthropic Claude 3.7 Sonnet ($3.00/1M in, $15.00/1M out -> 3000/1k in, 15000/1k out microcents)
        ("anthropic", "claude-3-7-sonnet"): ModelPricing(
            provider="anthropic",
            model_id="claude-3-7-sonnet",
            input_microcents_per_1k=3000,
            output_microcents_per_1k=15000,
        ),
        # OpenAI GPT-4o ($2.50/1M in, $10.00/1M out -> 2500/1k in, 10000/1k out microcents)
        ("openai", "gpt-4o"): ModelPricing(
            provider="openai",
            model_id="gpt-4o",
            input_microcents_per_1k=2500,
            output_microcents_per_1k=10000,
        ),
        # OpenRouter default fallback
        ("openrouter", "qwen/qwen-2.5-coder-32b-instruct"): ModelPricing(
            provider="openrouter",
            model_id="qwen/qwen-2.5-coder-32b-instruct",
            input_microcents_per_1k=180,
            output_microcents_per_1k=700,
        ),
    }

    def __init__(self) -> None:
        self._rates = dict(self._DEFAULT_RATES)

    @log_errors
    def register_pricing(self, pricing: ModelPricing) -> None:
        """Register or override a pricing rate."""
        try:
            self._rates[(pricing.provider.lower(), pricing.model_id.lower())] = pricing
        except Exception as exc:
            logger.exception("register_pricing failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def reset(self) -> None:
        """Reset pricing registry to pristine default catalog."""
        try:
            self._rates = dict(self._DEFAULT_RATES)
        except Exception as exc:
            logger.exception("reset failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def get_pricing(self, provider: str, model_id: str) -> ModelPricing:
        """Lookup pricing for a provider and model; returns fallback estimate if unlisted."""
        try:
            key = (provider.lower(), model_id.lower())
            if key in self._rates:
                return self._rates[key]
            # Conservative default fallback pricing: $1.00 / 1M in ($1000/1k), $3.00 / 1M out ($3000/1k)
            logger.warning(
                "Unlisted model pricing for %s/%s; applying conservative estimate",
                provider,
                model_id,
            )
            return ModelPricing(
                provider=provider.lower(),
                model_id=model_id.lower(),
                input_microcents_per_1k=1000,
                output_microcents_per_1k=3000,
            )
        except Exception as exc:
            logger.exception("get_pricing failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def calculate_cost(
        self,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """Calculate total execution cost in integer microcents."""
        try:
            pricing = self.get_pricing(provider, model_id)
            in_cost = (max(0, input_tokens) * pricing.input_microcents_per_1k) // 1000
            out_cost = (max(0, output_tokens) * pricing.output_microcents_per_1k) // 1000
            return in_cost + out_cost
        except Exception as exc:
            logger.exception("calculate_cost failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def estimate_cost(
        self,
        provider: str,
        model_id: str,
        estimated_input_tokens: int,
        max_output_tokens: int | None = None,
    ) -> int:
        """Estimate pre-call cost in microcents using expected prompt tokens and expected output."""
        try:
            expected_out = max_output_tokens or 1000
            return self.calculate_cost(provider, model_id, estimated_input_tokens, expected_out)
        except Exception as exc:
            logger.exception("estimate_cost failed | %s: %s", type(exc).__name__, exc)
            raise


@log_errors
def microcents_to_cents(microcents: int) -> float:
    """Convert integer microcents to human-readable float cents."""
    try:
        return microcents / MICROCENTS_PER_CENT
    except Exception as exc:
        logger.exception("microcents_to_cents failed | %s: %s", type(exc).__name__, exc)
        return 0.0


@log_errors
def cents_to_microcents(cents: float | int) -> int:
    """Convert cents to integer microcents."""
    try:
        return round(cents * MICROCENTS_PER_CENT)
    except Exception as exc:
        logger.exception("cents_to_microcents failed | %s: %s", type(exc).__name__, exc)
        return 0


# Global singleton pricing registry
default_pricing_registry = PricingRegistry()

__all__ = [
    "MICROCENTS_PER_CENT",
    "MICROCENTS_PER_DOLLAR",
    "ModelPricing",
    "PricingRegistry",
    "cents_to_microcents",
    "default_pricing_registry",
    "microcents_to_cents",
]
