"""Provider-neutral validation for externally issued RS256 JWT access tokens."""

import logging
import uuid
from typing import Any

import jwt
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from modernization_platform.config.settings import Settings
from modernization_platform.core.exceptions import UnauthorizedException

logger = logging.getLogger(__name__)


class _TokenClaims(BaseModel):
    """Required claims; unrelated provider claims are intentionally ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    iss: str
    aud: str | list[str]
    sub: str
    tenant_id: uuid.UUID
    jti: str
    token_type: str
    exp: AwareDatetime
    nbf: AwareDatetime
    iat: AwareDatetime


class VerifiedToken(BaseModel):
    """Credential facts that passed cryptographic and semantic validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str
    subject: str
    tenant_id: uuid.UUID
    token_id: str
    expires_at: AwareDatetime


class JWTAuthenticator:
    """Validate JWT access tokens without trusting unverified payload data."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.auth_jwt_issuer
        self._audience = settings.auth_jwt_audience
        self._public_key = (
            settings.auth_jwt_public_key.get_secret_value()
            if settings.auth_jwt_public_key is not None
            else None
        )
        self._algorithm = settings.auth_jwt_algorithm
        self._leeway = settings.auth_clock_skew_seconds
        self._max_lifetime = settings.auth_max_token_lifetime_seconds

    def validate(self, token: str) -> VerifiedToken:
        """Verify signature, fixed algorithm, registered claims, type, and lifetime."""
        try:
            if not token or not self._issuer or not self._audience or not self._public_key:
                raise UnauthorizedException()
            header = jwt.get_unverified_header(token)
            if header.get("alg") != self._algorithm:
                raise UnauthorizedException()
            payload: dict[str, Any] = jwt.decode(
                token,
                key=self._public_key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "tenant_id",
                        "jti",
                        "token_type",
                        "exp",
                        "nbf",
                        "iat",
                    ],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            claims = _TokenClaims.model_validate(payload)
            if claims.token_type != "access" or not claims.sub or not claims.jti:
                raise UnauthorizedException()
            lifetime = (claims.exp - claims.iat).total_seconds()
            if lifetime <= 0 or lifetime > self._max_lifetime:
                raise UnauthorizedException()
            return VerifiedToken(
                issuer=claims.iss,
                subject=claims.sub,
                tenant_id=claims.tenant_id,
                token_id=claims.jti,
                expires_at=claims.exp,
            )
        except UnauthorizedException:
            raise
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as exc:
            logger.info("Credential validation rejected | reason=%s", type(exc).__name__)
            raise UnauthorizedException() from exc


__all__ = ["JWTAuthenticator", "VerifiedToken"]
