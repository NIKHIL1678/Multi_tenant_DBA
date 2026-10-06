"""Health endpoints for load balancers and container orchestrators."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import check_database

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    """Process is up. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
async def readiness(response: Response) -> dict[str, str]:
    """Ready to serve traffic: the database answers a query."""
    try:
        await check_database()
    except (SQLAlchemyError, OSError):
        logger.exception("database not reachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "down"}
    return {"status": "ok", "database": "up"}
