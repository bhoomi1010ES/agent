"""Typed RSA/JWT helpers used only by security tests."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class JWTKeyPair(NamedTuple):
    """PEM-encoded test key pair."""

    private_key: str
    public_key: str


def generate_key_pair() -> JWTKeyPair:
    """Generate an ephemeral RSA key pair for test-token signing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return JWTKeyPair(private_key=private_pem, public_key=public_pem)


def issue_token(
    keys: JWTKeyPair,
    *,
    tenant_id: uuid.UUID,
    subject: str = "user-1",
    token_id: str = "session-1",
    issuer: str = "https://identity.test",
    audience: str = "modernization-api",
    now: datetime | None = None,
    lifetime: timedelta = timedelta(minutes=15),
    overrides: dict[str, object] | None = None,
) -> str:
    """Issue a standards-shaped test access token with optional claim overrides."""
    issued_at = now or datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "tenant_id": str(tenant_id),
        "jti": token_id,
        "token_type": "access",
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + lifetime,
    }
    payload.update(overrides or {})
    return jwt.encode(payload, keys.private_key, algorithm="RS256")


__all__ = ["JWTKeyPair", "generate_key_pair", "issue_token"]
