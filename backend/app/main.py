"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import create_db_engine, create_session_factory

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    if app.state.engine is not None:
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    """Application factory; keeps construction testable."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    # The engine connects lazily, so creating it never requires a running database.
    if settings.database_url is not None:
        app.state.engine = create_db_engine(settings.database_url, echo=settings.database_echo)
        app.state.session_factory = create_session_factory(app.state.engine)
    else:
        app.state.engine = None
        app.state.session_factory = None
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
