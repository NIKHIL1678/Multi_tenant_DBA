"""FastAPI application entry point: `uvicorn app.main:app`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    audit_log,
    auth,
    connectors,
    datasources,
    dev,
    environments,
    health,
    invitations,
    me,
    members,
    tenants,
)
from app.api.errors import install_error_handlers
from app.api.middleware import REQUEST_ID_HEADER, request_context
from app.auth.current_user import DEV_USER_HEADER
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("startup", extra={"app_env": settings.app_env, "dev_auth": settings.dev_auth})
    yield
    await get_engine().dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="ZipZy DBA Control Plane",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
    )

    install_error_handlers(app)

    # Middleware added last runs first: CORS wraps everything, so even errors carry CORS headers.
    app.middleware("http")(request_context)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", REQUEST_ID_HEADER, DEV_USER_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(tenants.router)
    app.include_router(members.router)
    app.include_router(invitations.tenant_router)
    app.include_router(invitations.public_router)
    app.include_router(environments.router)
    app.include_router(connectors.tenant_router)
    app.include_router(connectors.public_router)
    app.include_router(datasources.router)
    app.include_router(audit_log.router)
    if settings.dev_auth:
        app.include_router(dev.router)
    return app


app = create_app()
