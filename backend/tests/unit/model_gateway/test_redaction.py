"""Unit tests for centralized secret and credential redaction."""

from modernization_platform.domain.model_gateway.redaction import (
    redact_data,
    redact_exception,
    redact_string,
)


def test_redact_openai_api_key() -> None:
    raw = "Failed with token sk-abcdef1234567890abcdef1234567890 and request."
    redacted = redact_string(raw)
    assert "abcdef1234567890abcdef" not in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_redact_anthropic_api_key() -> None:
    raw = "Header x-api-key: ant-api03-abcdef1234567890abcdef1234567890 sent."
    redacted = redact_string(raw)
    assert "ant-api03-abcdef" not in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_redact_bearer_token() -> None:
    raw = "Authorization: Bearer my-super-secret-token-12345 in header"
    redacted = redact_string(raw)
    assert "my-super-secret-token-12345" not in redacted
    assert "Bearer [REDACTED_TOKEN]" in redacted


def test_redact_database_url_credentials() -> None:
    raw = "Connecting to postgresql+asyncpg://admin_user:P@ssw0rd123!@localhost:5432/mydb"
    redacted = redact_string(raw)
    assert "P@ssw0rd123!" not in redacted
    assert "admin_user:*****@localhost:5432/mydb" in redacted


def test_redact_nested_dict() -> None:
    data = {
        "job_id": "12345",
        "nested": {
            "api_key": "sk-realapikey12345678901234567890",
            "normal_field": "safe_value",
            "headers": {
                "Authorization": "Bearer secret_jwt_token_payload",
            },
        },
        "url": "postgresql://usr:secret_pass@db:5432/platform",
    }
    redacted = redact_data(data)
    assert isinstance(redacted, dict)
    assert "sk-realapikey" not in str(redacted)
    assert "secret_jwt_token_payload" not in str(redacted)
    assert "secret_pass" not in str(redacted)
    assert redacted["nested"]["normal_field"] == "safe_value"


def test_redact_exception() -> None:
    exc = ValueError("Provider returned 401 with key sk-openai12345678901234567890 rejected")
    sanitized = redact_exception(exc)
    assert "sk-openai" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
