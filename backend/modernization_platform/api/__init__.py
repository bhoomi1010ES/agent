"""API package for transport-level routers and dependencies."""

from modernization_platform.api.root import router as root_router
from modernization_platform.api.v1.router import api_v1_router

__all__ = ["api_v1_router", "root_router"]
