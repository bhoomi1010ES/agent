"""Unit tests for pricing calculations, integer microcents, and contract schemas."""

from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    UsageMetrics,
)
from modernization_platform.domain.model_gateway.pricing import (
    cents_to_microcents,
    default_pricing_registry,
    microcents_to_cents,
)


def test_microcents_conversion() -> None:
    # $1.00 = 100 cents = 1,000,000 microcents
    assert cents_to_microcents(100.0) == 1_000_000
    assert cents_to_microcents(1.0) == 10_000
    assert microcents_to_cents(1_000_000) == 100.0
    assert microcents_to_cents(10_000) == 1.0
    assert microcents_to_cents(5_000) == 0.5


def test_pricing_calculation() -> None:
    # OpenAI gpt-4o: 2500 microcents/1k in, 10000 microcents/1k out
    # 1000 in = 2500, 1000 out = 10000 -> Total = 12500 microcents ($0.0125)
    cost = default_pricing_registry.calculate_cost(
        provider="openai",
        model_id="gpt-4o",
        input_tokens=1000,
        output_tokens=1000,
    )
    assert cost == 12500


def test_estimate_cost() -> None:
    # Anthropic claude-3-7-sonnet: 3000/1k in, 15000/1k out
    # 2000 in = 6000, 500 out = 7500 -> Total = 13500 microcents
    est = default_pricing_registry.estimate_cost(
        provider="anthropic",
        model_id="claude-3-7-sonnet",
        estimated_input_tokens=2000,
        max_output_tokens=500,
    )
    assert est == 13500


def test_contract_models_serialization() -> None:
    msg = ChatMessage(role="user", content="Analyze this legacy COBOL code")
    tool = ToolDefinition(name="read_ast", description="Read code AST", parameters={})
    req = ModelRequest(
        messages=[msg],
        model="gpt-4o",
        temperature=0.2,
        max_tokens=4000,
        prompt_version="v2.1",
        tools=[tool],
        metadata={"artifact_id": "art-123"},
    )

    assert req.messages[0].content == "Analyze this legacy COBOL code"
    assert req.tools is not None and len(req.tools) == 1
    assert req.prompt_version == "v2.1"
    assert req.max_output_tokens == 4000

    res = ModelResponse(
        content="Converted successfully",
        model_id="gpt-4o",
        provider="openai",
        usage=UsageMetrics(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_microcents=200,
            actual_cost_microcents=180,
            duration_ms=45,
        ),
        tool_calls=[ToolCall(name="read_ast", arguments={"id": "art-123"})],
    )

    assert res.content == "Converted successfully"
    assert res.usage.total_tokens == 150
    assert res.tool_calls[0].name == "read_ast"
