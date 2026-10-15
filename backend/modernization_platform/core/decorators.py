"""Function decorators for consistent error logging and engineering standards."""

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from modernization_platform.core.ids import get_correlation_id

logger = logging.getLogger(__name__)


def log_errors[F: Callable[..., Any]](func: F) -> F:
    """Decorator ensuring any uncaught exception is logged with full context and re-raised.

    Complies with Rule 1 of production-engineering-rules.md.
    """
    try:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    cid = get_correlation_id()
                    logger.exception(
                        "Error in async function '%s' | correlation_id=%s | %s: %s",
                        func.__qualname__,
                        cid,
                        type(exc).__name__,
                        exc,
                    )
                    raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                cid = get_correlation_id()
                logger.exception(
                    "Error in sync function '%s' | correlation_id=%s | %s: %s",
                    func.__qualname__,
                    cid,
                    type(exc).__name__,
                    exc,
                )
                raise

        return sync_wrapper  # type: ignore[return-value]
    except Exception as exc:
        logger.exception("Failed to apply log_errors decorator | %s: %s", type(exc).__name__, exc)
        raise
