"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.v1.router import api_router

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Application factory; keeps construction testable."""
    app = FastAPI(
        title="AI Job Interview Simulator",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
