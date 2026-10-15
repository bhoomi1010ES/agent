"""Negative-first tests for cryptographic access-token validation."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from modernization_platform.config.settings import Settings
from modernization_platform.core.exceptions import UnauthorizedException
from modernization_platform.security.authentication import JWTAuthenticator
from tests.security.jwt_helpers import generate_key_pair, issue_token


def _settings(public_key: str) -> Settings:
    return Settings(
        environment="test",
        debug=False,
        auth_jwt_issuer="https://identity.test",
        auth_jwt_audience="modernization-api",
        auth_jwt_public_key=SecretStr(public_key),
        auth_clock_skew_seconds=0,
    )


@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt", "header.payload.signature"],
)
def test_missing_and_malformed_credentials_are_rejected(token: str) -> None:
    keys = generate_key_pair()
    with pytest.raises(UnauthorizedException, match="Authentication required"):
        JWTAuthenticator(_settings(keys.public_key)).validate(token)


def test_expired_invalid_signature_issuer_and_audience_are_rejected() -> None:
    keys = generate_key_pair()
    other_keys = generate_key_pair()
    tenant_id = uuid.uuid4()
    authenticator = JWTAuthenticator(_settings(keys.public_key))

    invalid_tokens = [
        issue_token(
            keys,
            tenant_id=tenant_id,
            now=datetime.now(UTC) - timedelta(hours=2),
            lifetime=timedelta(minutes=5),
        ),
        issue_token(other_keys, tenant_id=tenant_id),
        issue_token(keys, tenant_id=tenant_id, issuer="https://untrusted.test"),
        issue_token(keys, tenant_id=tenant_id, audience="another-api"),
    ]
    for token in invalid_tokens:
        with pytest.raises(UnauthorizedException):
            authenticator.validate(token)


def test_unsupported_algorithm_and_missing_identity_are_rejected() -> None:
    keys = generate_key_pair()
    tenant_id = uuid.uuid4()
    now = datetime.now(UTC)
    hs_token = jwt.encode(
        {
            "iss": "https://identity.test",
            "aud": "modernization-api",
            "sub": "user-1",
            "tenant_id": str(tenant_id),
            "jti": "session-1",
            "token_type": "access",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        "not-a-platform-secret-for-hmac-test-32",
        algorithm="HS256",
    )
    missing_subject = issue_token(keys, tenant_id=tenant_id, overrides={"sub": ""})

    authenticator = JWTAuthenticator(_settings(keys.public_key))
    with pytest.raises(UnauthorizedException):
        authenticator.validate(hs_token)
    with pytest.raises(UnauthorizedException):
        authenticator.validate(missing_subject)


def test_valid_token_returns_only_verified_identity_facts() -> None:
    keys = generate_key_pair()
    tenant_id = uuid.uuid4()
    token = issue_token(
        keys,
        tenant_id=tenant_id,
        overrides={"roles": ["admin"], "unrelated_provider_claim": "ignored"},
    )

    verified = JWTAuthenticator(_settings(keys.public_key)).validate(token)

    assert verified.tenant_id == tenant_id
    assert verified.subject == "user-1"
    assert not hasattr(verified, "roles")
