"""Unit tests for centralized environment configuration and security invariants."""

import pytest
from pydantic import ValidationError

from modernization_platform.config.settings import Settings


def test_valid_development_settings() -> None:
    """Verify standard development configuration loads with safe defaults."""
    settings = Settings()
    assert settings.app_name == "ModernizationPlatform"
    assert settings.environment == "development"
    assert settings.debug is False
    assert settings.port == 8000
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.docs_enabled is True


def test_production_rejects_debug_true() -> None:
    """Verify debug=True is strictly rejected in staging and production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(environment="production", debug=True, allowed_hosts=["api.example.com"])
    assert "Debug mode must be False in 'production' environment" in str(exc_info.value)


def test_production_rejects_wildcard_allowed_hosts() -> None:
    """Verify wildcard '*' in allowed_hosts is prohibited in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(environment="production", debug=False, allowed_hosts=["*"])
    assert "Wildcard '*' in allowed_hosts is prohibited" in str(exc_info.value)


def test_production_rejects_wildcard_cors_with_credentials() -> None:
    """Verify wildcard CORS origin cannot be paired with cors_allow_credentials=True in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            debug=False,
            allowed_hosts=["api.example.com"],
            cors_allowed_origins=["*"],
            cors_allow_credentials=True,
        )
    assert "CORS wildcard origin '*' cannot be combined with cors_allow_credentials=True" in str(
        exc_info.value
    )


def test_invalid_port_rejected() -> None:
    """Verify port must be between 1 and 65535."""
    with pytest.raises(ValidationError):
        Settings(port=0)

    with pytest.raises(ValidationError):
        Settings(port=70000)


def test_invalid_environment_rejected() -> None:
    """Verify unrecognized environments are rejected."""
    with pytest.raises(ValidationError):
        Settings(environment="invalid_env")  # type: ignore[arg-type]


def test_api_prefix_normalization() -> None:
    """Verify api_v1_prefix is normalized with leading slash and without trailing slash."""
    s1 = Settings(api_v1_prefix="api/v1")
    assert s1.api_v1_prefix == "/api/v1"

    s2 = Settings(api_v1_prefix="/api/v1/")
    assert s2.api_v1_prefix == "/api/v1"


def test_extra_forbidden_fields() -> None:
    """Verify unknown configuration attributes are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(unknown_secret_key="secret123")  # type: ignore[call-arg]
    assert "extra_forbidden" in str(exc_info.value)


def test_database_settings_defaults() -> None:
    """Verify database configuration default values."""
    settings = Settings()
    assert "postgresql+asyncpg://" in settings.database_url
    assert settings.db_pool_size == 10
    assert settings.db_max_overflow == 20
    assert settings.db_pool_timeout_seconds == 30.0
    assert settings.db_pool_recycle_seconds == 1800
    assert settings.db_connect_timeout_seconds == 10.0
    assert settings.db_statement_timeout_ms == 30000
    assert settings.db_echo is False
    assert settings.db_ssl_mode == "prefer"


def test_database_url_masked() -> None:
    """Verify database password is redacted in database_url_masked."""
    settings = Settings(
        database_url="postgresql+asyncpg://app_user:SuperSecretPassword123@db.prod.internal:5432/platform_db"
    )
    masked = settings.database_url_masked
    assert "SuperSecretPassword123" not in masked
    assert "app_user:***@db.prod.internal:5432/platform_db" in masked


def test_production_rejects_db_echo_true() -> None:
    """Verify db_echo=True is prohibited in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            debug=False,
            allowed_hosts=["api.example.com"],
            cors_allowed_origins=["https://dashboard.example.com"],
            database_url="postgresql+asyncpg://app_user:secure_pwd@db.internal:5432/platform_prod",
            db_echo=True,
            db_ssl_mode="require",
        )
    assert "Database SQL echo (db_echo) must be False" in str(exc_info.value)


def test_production_rejects_sqlite() -> None:
    """Verify SQLite fallback is strictly prohibited in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            debug=False,
            allowed_hosts=["api.example.com"],
            cors_allowed_origins=["https://dashboard.example.com"],
            database_url="sqlite+aiosqlite:///local.db",
            db_ssl_mode="require",
        )
    assert "SQLite fallback is strictly prohibited" in str(exc_info.value)


def test_production_rejects_default_dev_db_credentials() -> None:
    """Verify default local dev credentials are prohibited in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            debug=False,
            allowed_hosts=["api.example.com"],
            cors_allowed_origins=["https://dashboard.example.com"],
            database_url="postgresql+asyncpg://modernizer_app:modernizer_local_dev_pwd@db.internal:5432/platform_prod",
            db_ssl_mode="require",
        )
    assert "Default local development database credentials cannot be used" in str(exc_info.value)


def test_production_rejects_disabled_ssl() -> None:
    """Verify db_ssl_mode='disable' is prohibited in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            debug=False,
            allowed_hosts=["api.example.com"],
            cors_allowed_origins=["https://dashboard.example.com"],
            database_url="postgresql+asyncpg://app_user:secure_pwd@db.internal:5432/platform_prod",
            db_ssl_mode="disable",
        )
    assert "Disabling database TLS/SSL (db_ssl_mode='disable') is prohibited" in str(exc_info.value)
