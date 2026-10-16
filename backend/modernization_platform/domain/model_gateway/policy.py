"""Server-side model endpoint policy, agent routing, and validation rules."""

import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar

from modernization_platform.core.decorators import log_errors
from modernization_platform.domain.model_gateway.errors import (
    ModelPolicyViolationError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FallbackTarget:
    """Designated fallback target provider and model."""

    provider: str
    model_id: str


@dataclass(frozen=True)
class ModelPolicy:
    """Authoritative server-side policy governing permitted models, providers, and limits."""

    policy_name: str
    agent_role: str
    allowed_providers: tuple[str, ...]
    allowed_models: tuple[str, ...]
    primary_provider: str
    primary_model_id: str
    fallback_targets: tuple[FallbackTarget, ...] = field(default_factory=tuple)
    timeout_seconds: float = 60.0
    max_retries: int = 3
    rate_limit_rpm: int = 60
    rate_limit_tpm: int = 100_000
    max_output_tokens: int = 4096
    budget_class: str = "standard"

    @property
    def primary_model(self) -> str:
        return self.primary_model_id

    @property
    def max_tokens(self) -> int:
        return self.max_output_tokens

    @property
    def fallback_models(self) -> tuple[str, ...]:
        return tuple(ft.model_id for ft in self.fallback_targets)


class PolicyRegistry:
    """Registry of pre-approved model policies keyed by agent role and workflow stage."""

    # Built-in platform policies per agent role
    _DEFAULT_POLICIES: ClassVar[dict[str, ModelPolicy]] = {
        # Architect: deep reasoning / design model
        "architect": ModelPolicy(
            policy_name="architect_reasoning_policy_v1",
            agent_role="architect",
            allowed_providers=("mock", "anthropic", "openai", "qwen"),
            allowed_models=("mock-model", "claude-3-7-sonnet", "gpt-4o", "qwen-2.5-coder-32b"),
            primary_provider="mock",
            primary_model_id="mock-model",
            fallback_targets=(FallbackTarget(provider="mock", model_id="mock-fallback"),),
            timeout_seconds=90.0,
            max_retries=3,
        ),
        # Analyzer: characterization / legacy extraction model
        "analyzer": ModelPolicy(
            policy_name="analyzer_code_analysis_policy_v1",
            agent_role="analyzer",
            allowed_providers=("mock", "qwen", "openai", "anthropic"),
            allowed_models=("mock-model", "qwen-2.5-coder-32b", "gpt-4o", "claude-3-7-sonnet"),
            primary_provider="mock",
            primary_model_id="mock-model",
            fallback_targets=(FallbackTarget(provider="mock", model_id="mock-fallback"),),
            timeout_seconds=60.0,
            max_retries=3,
        ),
        # Converter / CodeWriter: high-throughput syntax translation
        "converter": ModelPolicy(
            policy_name="converter_codegen_policy_v1",
            agent_role="converter",
            allowed_providers=("mock", "qwen", "openai", "openrouter"),
            allowed_models=(
                "mock-model",
                "qwen-2.5-coder-32b",
                "gpt-4o",
                "qwen/qwen-2.5-coder-32b-instruct",
            ),
            primary_provider="mock",
            primary_model_id="mock-model",
            fallback_targets=(FallbackTarget(provider="mock", model_id="mock-fallback"),),
            timeout_seconds=60.0,
            max_retries=3,
        ),
        # Reviewer: inspection, diff verification, characterization review
        "reviewer": ModelPolicy(
            policy_name="reviewer_verification_policy_v1",
            agent_role="reviewer",
            allowed_providers=("mock", "anthropic", "openai"),
            allowed_models=("mock-model", "claude-3-7-sonnet", "gpt-4o"),
            primary_provider="mock",
            primary_model_id="mock-model",
            fallback_targets=(FallbackTarget(provider="mock", model_id="mock-fallback"),),
            timeout_seconds=60.0,
            max_retries=3,
        ),
        # General default fallback policy
        "default": ModelPolicy(
            policy_name="default_fallback_policy_v1",
            agent_role="default",
            allowed_providers=("mock", "qwen", "openai", "anthropic", "openrouter"),
            allowed_models=(
                "mock-model",
                "mock-fallback",
                "qwen-2.5-coder-32b",
                "gpt-4o",
                "claude-3-7-sonnet",
            ),
            primary_provider="mock",
            primary_model_id="mock-model",
            fallback_targets=(FallbackTarget(provider="mock", model_id="mock-fallback"),),
            timeout_seconds=60.0,
            max_retries=3,
        ),
    }

    def __init__(self) -> None:
        self._policies = dict(self._DEFAULT_POLICIES)

    @log_errors
    def get_policy(self, agent_role: str) -> ModelPolicy:
        """Resolve policy for an agent role, falling back to default."""
        try:
            return self._policies.get(agent_role.lower(), self._policies["default"])
        except Exception as exc:
            logger.exception("get_policy failed | %s: %s", type(exc).__name__, exc)
            return self._policies["default"]

    get_policy_for_agent = get_policy

    @log_errors
    def register_policy(self, policy: ModelPolicy) -> None:
        """Register or override an agent model policy."""
        try:
            self._policies[policy.agent_role.lower()] = policy
        except Exception as exc:
            logger.exception("register_policy failed | %s: %s", type(exc).__name__, exc)
            raise

    register = register_policy


@log_errors
def validate_policy_invocation(
    policy: ModelPolicy,
    request_or_provider: Any,
    context_or_model: Any = None,
) -> None:
    """Validate that provider and model satisfy policy constraints or raise ModelPolicyViolationError."""
    try:
        # Check if caller passed (policy, provider_str, model_str)
        if isinstance(request_or_provider, str) and isinstance(context_or_model, str):
            provider = request_or_provider.lower()
            model_id = context_or_model.lower()

            if provider not in [p.lower() for p in policy.allowed_providers]:
                raise ModelPolicyViolationError(
                    f"Provider '{provider}' is not permitted by policy '{policy.policy_name}'. "
                    f"Allowed providers: {list(policy.allowed_providers)}."
                )

            if model_id not in [m.lower() for m in policy.allowed_models]:
                raise ModelPolicyViolationError(
                    f"Model '{model_id}' is not permitted by policy '{policy.policy_name}'. "
                    f"Allowed models: {list(policy.allowed_models)}."
                )
            return

        # Otherwise caller passed (policy, ModelRequest, ModelExecutionContext)
        request = request_or_provider
        context = context_or_model

        if (
            context is not None
            and hasattr(context, "agent_role")
            and policy.agent_role != "default"
            and context.agent_role.lower() != policy.agent_role.lower()
        ):
            raise ModelPolicyViolationError(
                f"Agent role '{context.agent_role}' is not permitted to invoke policy '{policy.policy_name}'."
            )

        target_model = (getattr(request, "model", None) or policy.primary_model_id).lower()
        if target_model not in [m.lower() for m in policy.allowed_models]:
            raise ModelPolicyViolationError(
                f"Model '{target_model}' is not permitted by policy '{policy.policy_name}'. "
                f"Allowed models: {list(policy.allowed_models)}."
            )

    except ModelPolicyViolationError:
        raise
    except Exception as exc:
        logger.exception("validate_policy_invocation failed | %s: %s", type(exc).__name__, exc)
        raise ModelPolicyViolationError(f"Policy validation failed: {exc}") from exc


# Global policy registry instance
default_policy_registry = PolicyRegistry()

__all__ = [
    "FallbackTarget",
    "ModelPolicy",
    "PolicyRegistry",
    "default_policy_registry",
    "validate_policy_invocation",
]
