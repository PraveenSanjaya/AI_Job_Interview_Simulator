"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import health
from app.api.v1.router import api_router
from app.core.config import get_settings

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Application factory; keeps construction testable."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(health.router)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
