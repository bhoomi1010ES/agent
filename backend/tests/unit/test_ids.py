"""Unit tests for identifier management and correlation ID context."""

from modernization_platform.core.ids import (
    generate_correlation_id,
    get_correlation_id,
    is_valid_correlation_id,
    set_correlation_id,
)


def test_is_valid_correlation_id() -> None:
    """Verify validation logic for correlation IDs."""
    assert is_valid_correlation_id("abc-123_XYZ") is True
    assert is_valid_correlation_id("550e8400-e29b-41d4-a716-446655440000") is True
    assert is_valid_correlation_id("") is False
    assert is_valid_correlation_id(None) is False
    assert is_valid_correlation_id("invalid spaces") is False
    assert is_valid_correlation_id("bad\nnewline") is False
    assert is_valid_correlation_id("a" * 65) is False


def test_generate_correlation_id() -> None:
    """Verify generation of valid UUIDv4 correlation IDs."""
    cid = generate_correlation_id()
    assert is_valid_correlation_id(cid) is True
    assert len(cid) == 36


def test_get_and_set_correlation_id() -> None:
    """Verify context variable get and set behavior."""
    set_correlation_id("custom-corr-id-1")
    assert get_correlation_id() == "custom-corr-id-1"

    # Setting an invalid ID falls back to generating a valid one
    fallback = set_correlation_id("invalid with spaces")
    assert fallback != "invalid with spaces"
    assert is_valid_correlation_id(fallback) is True
    assert get_correlation_id() == fallback


def test_is_valid_correlation_id_invalid_type() -> None:
    """Verify non-string types return False safely without raising."""
    assert is_valid_correlation_id(123) is False  # type: ignore[arg-type]
    assert is_valid_correlation_id([]) is False  # type: ignore[arg-type]
