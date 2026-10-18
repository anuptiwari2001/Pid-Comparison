"""
Health check route — equivalent of TypeScript routes/health.ts
"""

from fastapi import APIRouter
from lib.types import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    """Returns server health status."""
    return HealthStatus(status="ok")
