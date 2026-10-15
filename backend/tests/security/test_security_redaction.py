"""Credential redaction and request-shape security regressions."""

import pytest
from pydantic import ValidationError

from modernization_platform.core.logging import RedactingFilter
from modernization_platform.schemas.gates import GateDecisionRequest


@pytest.mark.parametrize(
    "sensitive_text, secret",
    [
        ("Authorization: Bearer abc.def.ghi0123456789", "abc.def.ghi0123456789"),
        ("Cookie: session=super-secret-cookie", "super-secret-cookie"),
        ("client_secret=top-secret-client-value", "top-secret-client-value"),
        ("refresh_token=refresh-token-value-123", "refresh-token-value-123"),
    ],
)
def test_sensitive_credentials_are_redacted(sensitive_text: str, secret: str) -> None:
    redacted = RedactingFilter().redact_text(sensitive_text)
    assert secret not in redacted
    assert "REDACTED" in redacted


def test_gate_request_cannot_forge_actor_or_tenant() -> None:
    with pytest.raises(ValidationError):
        GateDecisionRequest.model_validate(
            {
                "decision": "approved",
                "actor": "forged-admin",
                "tenant_id": "00000000-0000-0000-0000-000000000000",
            }
        )
