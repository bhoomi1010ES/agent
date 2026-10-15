"""Unit tests for @log_errors decorator."""

import pytest

from modernization_platform.core.decorators import log_errors


def test_sync_function_success() -> None:
    """Verify decorated synchronous function executes and returns result."""

    @log_errors
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


def test_sync_function_reraises_exception() -> None:
    """Verify decorated synchronous function logs and re-raises exception."""

    @log_errors
    def fail() -> None:
        raise ValueError("Simulated sync error")

    with pytest.raises(ValueError) as exc_info:
        fail()
    assert "Simulated sync error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_function_success() -> None:
    """Verify decorated asynchronous function executes and returns result."""

    @log_errors
    async def async_add(a: int, b: int) -> int:
        return a + b

    result = await async_add(10, 20)
    assert result == 30


@pytest.mark.asyncio
async def test_async_function_reraises_exception() -> None:
    """Verify decorated asynchronous function logs and re-raises exception."""

    @log_errors
    async def async_fail() -> None:
        raise KeyError("Simulated async error")

    with pytest.raises(KeyError) as exc_info:
        await async_fail()
    assert "Simulated async error" in str(exc_info.value)
