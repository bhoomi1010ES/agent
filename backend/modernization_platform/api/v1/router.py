"""API version 1 central router aggregator."""

import logging

from fastapi import APIRouter

from modernization_platform.api.v1.endpoints import (
    artifacts,
    gates,
    health,
    jobs,
    model_gateway,
    security,
)

logger = logging.getLogger(__name__)

api_v1_router = APIRouter()

# Register core v1 endpoints
api_v1_router.include_router(health.router, prefix="/health", tags=["Health"])
api_v1_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_v1_router.include_router(artifacts.router, prefix="/artifacts", tags=["Artifacts"])
api_v1_router.include_router(gates.router, tags=["Gates"])
api_v1_router.include_router(security.router, tags=["Security"])
api_v1_router.include_router(model_gateway.router, tags=["Model Gateway"])
