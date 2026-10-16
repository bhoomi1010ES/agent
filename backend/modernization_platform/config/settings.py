"""Centralized, validated environment configuration using Pydantic Settings."""

import logging
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Platform configuration settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
    )

    # Application Identity
    app_name: str = Field(
        default="ModernizationPlatform",
        description="Public human-readable application name",
    )
    app_version: str = Field(
        default="0.1.0",
        description="Semantic application version",
    )
    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        description="Execution environment",
    )
    debug: bool = Field(
        default=False,
        description="Debug mode; must be False in production",
    )

    # Server Networking
    host: str = Field(
        default="0.0.0.0",
        description="Network interface IP to bind server",
    )
    port: Annotated[int, Field(ge=1, le=65535)] = Field(
        default=8000,
        description="TCP port to listen on",
    )
    api_v1_prefix: str = Field(
        default="/api/v1",
        description="Prefix for version 1 API routes",
    )

    # Security & Traffic Filtering
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["*"],
        description="List of allowed HTTP Host header values",
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        description="List of allowed origins for cross-origin requests",
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow credentials (cookies, authorization headers) with CORS",
    )
    max_request_body_bytes: Annotated[int, Field(ge=1_024, le=100_000_000)] = Field(
        default=1_048_576,
        description="Maximum accepted HTTP request body size in bytes",
    )

    # Authentication (externally issued JWT access tokens)
    auth_jwt_issuer: str | None = Field(
        default=None,
        description="Exact trusted JWT issuer",
    )
    auth_jwt_audience: str | None = Field(
        default=None,
        description="Exact API audience required in access tokens",
    )
    auth_jwt_public_key: SecretStr | None = Field(
        default=None,
        description="PEM public key used exclusively for RS256 signature verification",
    )
    auth_jwt_algorithm: Literal["RS256"] = Field(
        default="RS256",
        description="Fixed JWT signature algorithm; algorithm fallback is prohibited",
    )
    auth_clock_skew_seconds: Annotated[int, Field(ge=0, le=60)] = Field(
        default=30,
        description="Maximum JWT clock skew allowed for exp/nbf/iat validation",
    )
    auth_max_token_lifetime_seconds: Annotated[int, Field(ge=60, le=86_400)] = Field(
        default=3_600,
        description="Maximum permitted access-token lifetime",
    )

    # API Documentation
    docs_enabled: bool = Field(
        default=True,
        description="Expose Swagger UI (/docs) and OpenAPI schema",
    )

    # Logging & Correlation
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Minimum log severity",
    )
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log output format",
    )
    correlation_header_name: str = Field(
        default="X-Correlation-ID",
        description="HTTP header name used for request correlation",
    )

    # Health Checks
    health_check_timeout_seconds: Annotated[float, Field(gt=0.0, le=60.0)] = Field(
        default=5.0,
        description="Maximum execution timeout for readiness checks",
    )

    # Database Configuration (PostgreSQL)
    database_url: str = Field(
        default="postgresql+asyncpg://modernizer_app:modernizer_local_dev_pwd@localhost:5432/modernizer_dev",
        description="Database connection URL with async driver prefix",
    )
    database_test_url: str | None = Field(
        default=None,
        description="Dedicated test database URL for running integration tests against PostgreSQL",
    )
    db_pool_size: Annotated[int, Field(ge=1, le=100)] = Field(
        default=10,
        description="SQLAlchemy connection pool base size",
    )
    db_max_overflow: Annotated[int, Field(ge=0, le=100)] = Field(
        default=20,
        description="Maximum temporary connections allowed beyond db_pool_size",
    )
    db_pool_timeout_seconds: Annotated[float, Field(gt=0.0, le=120.0)] = Field(
        default=30.0,
        description="Seconds to wait before timing out on pool connection checkout",
    )
    db_pool_recycle_seconds: Annotated[int, Field(ge=-1)] = Field(
        default=1800,
        description="Seconds after which connections are recycled to avoid stale server timeouts",
    )
    db_connect_timeout_seconds: Annotated[float, Field(gt=0.0, le=60.0)] = Field(
        default=10.0,
        description="Timeout in seconds for establishing initial socket connection to PostgreSQL",
    )
    db_statement_timeout_ms: Annotated[int, Field(ge=0)] = Field(
        default=30000,
        description="PostgreSQL statement timeout in milliseconds (0 for unlimited)",
    )
    db_application_name: str = Field(
        default="modernization_platform",
        description="Application name sent to PostgreSQL in connection parameters",
    )
    db_echo: bool = Field(
        default=False,
        description="Enable raw SQLAlchemy SQL logging. Strictly forbidden in production.",
    )
    db_ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        Field(
            default="prefer",
            description="SSL mode for PostgreSQL connections",
        )
    )

    # Object Storage Configuration (S3 / MinIO)
    storage_backend: Literal["s3", "memory"] = Field(
        default="s3",
        description="Object storage backend type ('s3' for AWS S3 / MinIO, 'memory' for testing)",
    )
    storage_s3_endpoint_url: str | None = Field(
        default=None,
        description="Custom endpoint URL for S3/MinIO (e.g. http://localhost:9000)",
    )
    storage_s3_bucket: str = Field(
        default="modernization-artifacts",
        description="Target S3/MinIO bucket for artifact storage",
    )
    storage_s3_region: str = Field(
        default="us-east-1",
        description="AWS region or MinIO region",
    )
    storage_s3_access_key_id: SecretStr | None = Field(
        default=None,
        description="S3/MinIO access key ID",
    )
    storage_s3_secret_access_key: SecretStr | None = Field(
        default=None,
        description="S3/MinIO secret access key",
    )
    storage_s3_use_ssl: bool = Field(
        default=False,
        description="Whether to use TLS/SSL when connecting to S3/MinIO",
    )
    storage_max_artifact_size_bytes: Annotated[int, Field(ge=1_024, le=500_000_000)] = Field(
        default=52_428_800,
        description="Maximum accepted artifact size in bytes (default 50 MiB)",
    )
    storage_timeout_seconds: Annotated[float, Field(gt=0.0, le=300.0)] = Field(
        default=30.0,
        description="Timeout in seconds for object storage operations",
    )
    storage_max_retries: Annotated[int, Field(ge=0, le=10)] = Field(
        default=3,
        description="Maximum number of retries for transient object storage operations",
    )

    @property
    def storage_s3_endpoint_masked(self) -> str:
        """Return S3 endpoint with credentials safely masked for diagnostic logging."""
        try:
            if not self.storage_s3_endpoint_url:
                return f"https://s3.{self.storage_s3_region}.amazonaws.com"
            from urllib.parse import urlsplit, urlunsplit

            parsed = urlsplit(self.storage_s3_endpoint_url)
            if parsed.password:
                netloc = f"{parsed.username or ''}:***@{parsed.hostname or ''}"
                if parsed.port:
                    netloc = f"{netloc}:{parsed.port}"
                return urlunsplit(
                    (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
                )
            return self.storage_s3_endpoint_url
        except Exception:
            return "http://***@masked-endpoint"

    @property
    def database_url_masked(self) -> str:
        """Return database URL with credentials safely masked for diagnostic logging."""
        try:
            from urllib.parse import urlsplit, urlunsplit

            parsed = urlsplit(self.database_url)
            if parsed.password:
                netloc = f"{parsed.username or ''}:***@{parsed.hostname or ''}"
                if parsed.port:
                    netloc = f"{netloc}:{parsed.port}"
                return urlunsplit(
                    (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
                )
            return self.database_url
        except Exception:
            return "postgresql+asyncpg://***@masked-host/masked-db"

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Ensure API prefix starts with / and does not end with /."""
        try:
            val = value.strip()
            if not val.startswith("/"):
                val = f"/{val}"
            if val.endswith("/") and len(val) > 1:
                val = val[:-1]
            return val
        except Exception as exc:
            logger.exception("validate_api_prefix failed | %s: %s", type(exc).__name__, exc)
            raise

    @model_validator(mode="after")
    def validate_production_invariants(self) -> "Settings":
        """Enforce strict security constraints for staging and production environments."""
        try:
            if self.environment in ("staging", "production"):
                # Debug must never be enabled in production
                if self.debug:
                    raise ValueError(
                        f"Debug mode must be False in '{self.environment}' environment."
                    )

                # Wildcard allowed_hosts is prohibited in production
                if "*" in self.allowed_hosts:
                    raise ValueError(
                        f"Wildcard '*' in allowed_hosts is prohibited in '{self.environment}' environment."
                    )

                # Wildcard CORS origins with credentials is prohibited
                if "*" in self.cors_allowed_origins and self.cors_allow_credentials:
                    raise ValueError(
                        "CORS wildcard origin '*' cannot be combined with cors_allow_credentials=True."
                    )

                # Database security invariants in staging/production
                if self.db_echo:
                    raise ValueError(
                        f"Database SQL echo (db_echo) must be False in '{self.environment}' environment."
                    )

                if "sqlite" in self.database_url.lower():
                    raise ValueError(
                        f"SQLite fallback is strictly prohibited in '{self.environment}' environment. PostgreSQL is required."
                    )

                if any(
                    pwd in self.database_url
                    for pwd in ("modernizer_local_dev_pwd", "modernizer_dev_pwd")
                ):
                    raise ValueError(
                        f"Default local development database credentials cannot be used in '{self.environment}' environment."
                    )

                if self.db_ssl_mode == "disable":
                    raise ValueError(
                        f"Disabling database TLS/SSL (db_ssl_mode='disable') is prohibited in '{self.environment}' environment."
                    )

                if not (
                    self.auth_jwt_issuer
                    and self.auth_jwt_issuer.strip()
                    and self.auth_jwt_audience
                    and self.auth_jwt_audience.strip()
                    and self.auth_jwt_public_key is not None
                    and self.auth_jwt_public_key.get_secret_value().strip()
                ):
                    raise ValueError(
                        "JWT issuer, audience, and verification key are required in staging and production."
                    )

                if self.storage_backend == "s3":
                    if not (self.storage_s3_bucket and self.storage_s3_bucket.strip()):
                        raise ValueError(
                            f"storage_s3_bucket is required in '{self.environment}' environment."
                        )
                    if (
                        self.storage_s3_access_key_id is not None
                        and not self.storage_s3_access_key_id.get_secret_value().strip()
                    ):
                        raise ValueError(
                            f"storage_s3_access_key_id cannot be blank in '{self.environment}' environment."
                        )
                    if (
                        self.storage_s3_secret_access_key is not None
                        and not self.storage_s3_secret_access_key.get_secret_value().strip()
                    ):
                        raise ValueError(
                            f"storage_s3_secret_access_key cannot be blank in '{self.environment}' environment."
                        )

            return self
        except Exception as exc:
            logger.exception(
                "validate_production_invariants failed | %s: %s", type(exc).__name__, exc
            )
            raise


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached application settings instance."""
    try:
        return Settings()
    except Exception as exc:
        logger.exception("Failed to load application settings | %s: %s", type(exc).__name__, exc)
        raise
