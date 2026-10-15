"""Root application endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from modernization_platform.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


class RootResponse(BaseModel):
    """Root endpoint response schema."""

    name: str = Field(description="Application name")
    app_name: str = Field(description="Configured application name")
    version: str = Field(description="Current configured application version")
    status: str = Field(default="running", description="Application running status")
    docs_url: str | None = Field(
        default="/docs", description="Path to interactive API documentation"
    )
    docs: str | None = Field(default="/docs", description="Path to API documentation alias")


@router.get(
    "/",
    response_model=RootResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Root",
    description="Returns top-level metadata including application name, version, status, and docs path.",
    tags=["Root"],
)
async def get_root(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RootResponse:
    """Return root platform metadata."""
    try:
        docs_path = "/docs" if settings.docs_enabled else None
        return RootResponse(
            name=settings.app_name,
            app_name=settings.app_name,
            version=settings.app_version,
            status="running",
            docs_url=docs_path,
            docs=docs_path,
        )
    except Exception as exc:
        logger.exception("get_root failed | %s: %s", type(exc).__name__, exc)
        raise
