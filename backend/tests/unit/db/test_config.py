"""Unit tests for database configuration validation, URL masking, and production security invariants."""

import pytest
from pydantic import SecretStr, ValidationError

from modernization_platform.config.settings import Settings


def test_database_settings_defaults() -> None:
    """Verify default database settings values."""
    settings = Settings(environment="development")
    assert "postgresql+asyncpg://" in settings.database_url
    assert settings.db_pool_size == 10
    assert settings.db_max_overflow == 20
    assert settings.db_pool_timeout_seconds == 30.0
    assert settings.db_pool_recycle_seconds == 1800
    assert settings.db_connect_timeout_seconds == 10.0
    assert settings.db_statement_timeout_ms == 30000
    assert settings.db_application_name == "modernization_platform"
    assert settings.db_echo is False
    assert settings.db_ssl_mode == "prefer"


def test_database_url_masked_redacts_credentials() -> None:
    """Verify database_url_masked redacts user passwords."""
    settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://admin_user:super_secret_password_123@db.example.com:5432/platform_db",
    )
    masked = settings.database_url_masked
    assert "super_secret_password_123" not in masked
    assert "admin_user:***@db.example.com:5432/platform_db" in masked


def test_database_url_masked_without_credentials() -> None:
    """Verify masking behaves safely when no password is present."""
    settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://localhost:5432/platform_db",
    )
    assert settings.database_url_masked == "postgresql+asyncpg://localhost:5432/platform_db"


def test_production_rejects_sqlite() -> None:
    """Verify production environment strictly rejects SQLite databases."""
    with pytest.raises(ValidationError, match="SQLite fallback is strictly prohibited"):
        Settings(
            environment="production",
            database_url="sqlite+aiosqlite:///prod.db",
            allowed_hosts=["prod.example.com"],
            cors_allowed_origins=["https://prod.example.com"],
            db_ssl_mode="require",
        )


def test_production_rejects_sql_echo() -> None:
    """Verify production environment strictly rejects raw SQL logging."""
    with pytest.raises(ValidationError, match=r"Database SQL echo .* must be False"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://prod_user:strong_prod_pass_999@db.prod.internal:5432/prod_db",
            db_echo=True,
            allowed_hosts=["prod.example.com"],
            cors_allowed_origins=["https://prod.example.com"],
            db_ssl_mode="require",
        )


def test_production_rejects_default_dev_passwords() -> None:
    """Verify production environment rejects default development passwords."""
    with pytest.raises(ValidationError, match="Default local development database credentials"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://modernizer:modernizer_dev_pwd@db.prod.internal:5432/prod_db",
            allowed_hosts=["prod.example.com"],
            cors_allowed_origins=["https://prod.example.com"],
            db_ssl_mode="require",
        )


def test_production_rejects_disabled_ssl() -> None:
    """Verify production environment rejects disabled database SSL."""
    with pytest.raises(ValidationError, match=r"Disabling database TLS/SSL .* is prohibited"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://prod_user:strong_prod_pass_999@db.prod.internal:5432/prod_db",
            db_ssl_mode="disable",
            allowed_hosts=["prod.example.com"],
            cors_allowed_origins=["https://prod.example.com"],
        )


def test_production_valid_configuration() -> None:
    """Verify production environment accepts fully compliant secure database settings."""
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://prod_user:strong_prod_pass_999@db.prod.internal:5432/prod_db",
        db_ssl_mode="require",
        allowed_hosts=["prod.example.com"],
        cors_allowed_origins=["https://prod.example.com"],
        auth_jwt_issuer="https://identity.example.com",
        auth_jwt_audience="modernization-api",
        auth_jwt_public_key=SecretStr("test-public-key"),
    )
    assert settings.environment == "production"
    assert settings.db_ssl_mode == "require"
    assert settings.db_echo is False


def test_production_rejects_blank_jwt_verification_key() -> None:
    """Verify staging and production require usable JWT verification material."""
    with pytest.raises(ValidationError, match="JWT issuer, audience, and verification key"):
        Settings(
            environment="production",
            debug=False,
            database_url="postgresql+asyncpg://prod_user:strong_prod_pass_999@db.prod.internal:5432/prod_db",
            db_ssl_mode="require",
            allowed_hosts=["prod.example.com"],
            cors_allowed_origins=["https://prod.example.com"],
            auth_jwt_issuer="https://identity.example.com",
            auth_jwt_audience="modernization-api",
            auth_jwt_public_key=SecretStr("  "),
        )
