"""Unit tests for model policies, per-agent routing, and validation."""

import uuid

import pytest

from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
)
from modernization_platform.domain.model_gateway.errors import (
    ModelPolicyViolationError,
)
from modernization_platform.domain.model_gateway.policy import (
    ModelPolicy,
    PolicyRegistry,
    default_policy_registry,
    validate_policy_invocation,
)


def test_default_agent_policies_exist() -> None:
    for role in ["architect", "analyzer", "converter", "reviewer"]:
        policy = default_policy_registry.get_policy_for_agent(role)
        assert policy.agent_role == role
        assert policy.primary_model is not None
        assert len(policy.allowed_models) >= 1
        assert len(policy.allowed_providers) >= 1


def test_custom_policy_registry() -> None:
    registry = PolicyRegistry()
    custom_policy = ModelPolicy(
        policy_name="custom_test_policy",
        agent_role="custom_tester",
        allowed_providers=("mock",),
        allowed_models=("test-model-1",),
        primary_provider="mock",
        primary_model_id="test-model-1",
    )
    registry.register_policy(custom_policy)

    fetched = registry.get_policy_for_agent("custom_tester")
    assert fetched.primary_model == "test-model-1"


def test_validate_approved_invocation() -> None:
    policy = default_policy_registry.get_policy_for_agent("architect")
    req = ModelRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model=policy.primary_model,
        prompt_version="v1.0",
    )
    ctx = ModelExecutionContext(
        job_id=uuid.uuid4(),
        agent_role="architect",
    )
    # Should not raise
    validate_policy_invocation(policy, req, ctx)


def test_reject_unapproved_model() -> None:
    policy = default_policy_registry.get_policy_for_agent("architect")
    req = ModelRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="unauthorized-shady-model-99",
        prompt_version="v1.0",
    )
    ctx = ModelExecutionContext(
        job_id=uuid.uuid4(),
        agent_role="architect",
    )
    with pytest.raises(ModelPolicyViolationError) as exc_info:
        validate_policy_invocation(policy, req, ctx)
    assert "not permitted by policy" in str(exc_info.value)


def test_reject_agent_role_mismatch() -> None:
    policy = default_policy_registry.get_policy_for_agent("architect")
    req = ModelRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model=policy.primary_model,
        prompt_version="v1.0",
    )
    ctx = ModelExecutionContext(
        job_id=uuid.uuid4(),
        agent_role="unauthorized_agent",
    )
    with pytest.raises(ModelPolicyViolationError) as exc_info:
        validate_policy_invocation(policy, req, ctx)
    assert "is not permitted to invoke" in str(exc_info.value)
