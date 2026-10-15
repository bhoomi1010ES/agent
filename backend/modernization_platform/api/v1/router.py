"""API version 1 central router aggregator."""

import logging

from fastapi import APIRouter

from modernization_platform.api.v1.endpoints import health

logger = logging.getLogger(__name__)

api_v1_router = APIRouter()

# Register core v1 health endpoints
api_v1_router.include_router(health.router, prefix="/health", tags=["Health"])

# Future phase extension points:
# api_v1_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
# api_v1_router.include_router(gates.router, prefix="/gates", tags=["Gates"])
# api_v1_router.include_router(artifacts.router, prefix="/artifacts", tags=["Artifacts"])
