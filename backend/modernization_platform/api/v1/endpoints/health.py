"""Health and readiness endpoints with extensible probe registry."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modernization_platform.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


class LivenessResponse(BaseModel):
    """Liveness probe response schema."""

    status: str = Field(default="alive", description="Process execution status")
    timestamp: str = Field(description="Current UTC timestamp")
    version: str = Field(description="Application version")


class ReadinessProbeResult(BaseModel):
    """Result of an individual dependency readiness probe."""

    ready: bool = Field(description="Probe success state")
    message: str | None = Field(default=None, description="Diagnostic detail (safe, non-sensitive)")


class ReadinessResponse(BaseModel):
    """Readiness probe response schema."""

    status: str = Field(description="'ready' or 'not_ready'")
    timestamp: str = Field(description="Current UTC timestamp")
    probes: dict[str, ReadinessProbeResult] = Field(
        default_factory=dict,
        description="Individual dependency probe results",
    )


class ReadinessProbeRegistry:
    """Registry allowing future phases to register health probes (PostgreSQL, MinIO, etc.)."""

    def __init__(self) -> None:
        self._probes: dict[str, Callable[[], Awaitable[ReadinessProbeResult]]] = {}

    def register_probe(
        self,
        name: str,
        probe_fn: Callable[[], Awaitable[ReadinessProbeResult]],
    ) -> None:
        """Register a new asynchronous dependency check."""
        try:
            self._probes[name] = probe_fn
            logger.info("Registered readiness probe: '%s'", name)
        except Exception as exc:
            logger.exception(
                "Failed to register readiness probe '%s' | %s: %s", name, type(exc).__name__, exc
            )
            raise

    async def run_all(
        self, timeout_seconds: float = 5.0
    ) -> tuple[bool, dict[str, ReadinessProbeResult]]:
        """Run all registered probes concurrently with timeout."""
        try:
            if not self._probes:
                # Phase 01.1 has no external databases or object storage yet
                return True, {}

            results: dict[str, ReadinessProbeResult] = {}
            all_ready = True

            async def _run_single(
                probe_name: str,
                fn: Callable[[], Awaitable[ReadinessProbeResult]],
            ) -> tuple[str, ReadinessProbeResult]:
                try:
                    res = await asyncio.wait_for(fn(), timeout=timeout_seconds)
                    return probe_name, res
                except TimeoutError:
                    logger.warning(
                        "Readiness probe '%s' timed out after %fs", probe_name, timeout_seconds
                    )
                    return probe_name, ReadinessProbeResult(
                        ready=False, message="Probe check timed out"
                    )
                except Exception as probe_err:
                    logger.exception(
                        "Readiness probe '%s' failed | %s: %s",
                        probe_name,
                        type(probe_err).__name__,
                        probe_err,
                    )
                    return probe_name, ReadinessProbeResult(
                        ready=False, message="Probe check encountered an error"
                    )

            tasks = [_run_single(name, fn) for name, fn in self._probes.items()]
            probe_outputs = await asyncio.gather(*tasks)

            for name, result in probe_outputs:
                results[name] = result
                if not result.ready:
                    all_ready = False

            return all_ready, results
        except Exception as exc:
            logger.exception(
                "ReadinessProbeRegistry.run_all failed | %s: %s", type(exc).__name__, exc
            )
            return False, {
                "system": ReadinessProbeResult(
                    ready=False, message="Internal probe evaluation error"
                )
            }


# Global singleton probe registry
readiness_registry = ReadinessProbeRegistry()


@router.get(
    "/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Process Liveness",
    description="Returns HTTP 200 if the Python process is alive and able to accept traffic.",
)
async def check_liveness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LivenessResponse:
    """Check process liveness."""
    try:
        return LivenessResponse(
            status="alive",
            timestamp=datetime.now(UTC).isoformat(),
            version=settings.app_version,
        )
    except Exception as exc:
        logger.exception("check_liveness failed | %s: %s", type(exc).__name__, exc)
        raise


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    summary="Application Service Readiness",
    description="Returns HTTP 200 if the platform is ready to serve workloads, or 503 if any required probe fails.",
)
async def check_readiness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Check application readiness across all registered probes."""
    try:
        is_ready, probe_results = await readiness_registry.run_all(
            timeout_seconds=settings.health_check_timeout_seconds
        )

        response_data = ReadinessResponse(
            status="ready" if is_ready else "not_ready",
            timestamp=datetime.now(UTC).isoformat(),
            probes=probe_results,
        )

        http_status = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(status_code=http_status, content=response_data.model_dump())
    except Exception as exc:
        logger.exception("check_readiness failed | %s: %s", type(exc).__name__, exc)
        fallback = ReadinessResponse(
            status="not_ready",
            timestamp=datetime.now(UTC).isoformat(),
            probes={"system": ReadinessProbeResult(ready=False, message="Evaluation error")},
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=fallback.model_dump(),
        )
