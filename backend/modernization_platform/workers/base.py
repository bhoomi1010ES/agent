"""Abstract base worker providing lifecycle hooks, signal handling, and cooperative cancellation."""

import asyncio
import logging
import signal
import sys
from typing import Any

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)


class BaseWorker:
    """Cooperative background worker managing execution lifecycle and graceful shutdown."""

    def __init__(self, name: str = "worker") -> None:
        self.name = name
        self._stop_event = asyncio.Event()
        self._is_running = False
        self._active_tasks: set[asyncio.Task[Any]] = set()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    @log_errors
    def request_stop(self) -> None:
        """Signal the worker to gracefully complete active tasks and cease polling."""
        try:
            logger.info("Graceful shutdown requested for worker '%s'", self.name)
            self._stop_event.set()
        except Exception as exc:
            logger.exception("BaseWorker.request_stop failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    def setup_signal_handlers(self) -> None:
        """Register OS signal listeners for graceful termination."""
        try:
            # On Unix, register with event loop signal handlers
            if sys.platform != "win32":
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, self.request_stop)
                logger.debug("Registered SIGTERM and SIGINT handlers for worker '%s'", self.name)
            else:
                # Windows doesn't support add_signal_handler for SIGTERM, fallback to standard signal
                signal.signal(signal.SIGINT, lambda _s, _f: self.request_stop())
                logger.debug("Registered SIGINT handler for Windows worker '%s'", self.name)
        except Exception as exc:
            logger.warning("Could not register signal handlers for worker '%s': %s", self.name, exc)

    @log_errors
    async def start(self) -> None:
        """Start worker execution loop."""
        try:
            self._is_running = True
            self._stop_event.clear()
            self.setup_signal_handlers()
            logger.info("Worker '%s' started", self.name)
            await self._run_loop()
        except asyncio.CancelledError:
            logger.info("Worker '%s' received task cancellation", self.name)
        finally:
            await self.shutdown()

    @log_errors
    async def _run_loop(self) -> None:
        """Primary execution loop to be implemented by concrete workers."""
        try:
            raise NotImplementedError
        except Exception as exc:
            logger.exception("BaseWorker._run_loop failed | %s: %s", type(exc).__name__, exc)
            raise

    @log_errors
    async def shutdown(self, timeout_seconds: float = 10.0) -> None:
        """Await completion of active tasks within a bounded grace period."""
        try:
            self._is_running = False
            self._stop_event.set()
            logger.info(
                "Shutting down worker '%s' (waiting for %d active tasks)",
                self.name,
                len(self._active_tasks),
            )

            if self._active_tasks:
                _done, pending = await asyncio.wait(
                    self._active_tasks,
                    timeout=timeout_seconds,
                    return_when=asyncio.ALL_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            logger.info("Worker '%s' shutdown complete", self.name)
        except Exception as exc:
            logger.exception("BaseWorker.shutdown failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = ["BaseWorker"]
