"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai import create_llm_provider
from app.api import health
from app.api.v1.router import api_router
from app.core.body_limit import MaxBodySizeMiddleware
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import InMemoryRateLimiter, NoopRateLimiter, RateLimiter
from app.db.session import create_db_engine, create_session_factory
from app.storage import create_storage

API_V1_PREFIX = "/api/v1"
MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and form fields around the file
logger = logging.getLogger(__name__)


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
    app.state.storage = create_storage(settings)
    app.state.llm_provider = create_llm_provider(settings)
    limiter: RateLimiter = (
        InMemoryRateLimiter(
            settings.auth_rate_limit_attempts, settings.auth_rate_limit_window_seconds
        )
        if settings.rate_limit_enabled
        else NoopRateLimiter()
    )
    app.state.rate_limiter = limiter
    if settings.jwt_secret_is_ephemeral:
        logger.warning(
            "JWT_SECRET_KEY is not set; using a random per-process secret. Tokens become "
            "invalid on restart and are not shared between workers."
        )
    register_exception_handlers(app)
    # Added before RequestContextMiddleware so that one runs outermost and sets the request id.
    app.add_middleware(
        MaxBodySizeMiddleware,
        max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
        path_prefix=f"{API_V1_PREFIX}/resumes",
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
