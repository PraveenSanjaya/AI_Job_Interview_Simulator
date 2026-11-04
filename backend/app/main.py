"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.integrations.github.client import GitHubRestClient
from app.integrations.portfolio.safe_fetch import SafeFetcher
from app.storage import create_storage

API_V1_PREFIX = "/api/v1"
MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and form fields around the file
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.portfolio_fetcher.aclose()
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
    app.state.portfolio_fetcher = SafeFetcher(
        timeout_seconds=settings.integration_timeout_seconds,
        max_bytes=settings.integration_max_response_bytes,
    )
    app.state.github_client = GitHubRestClient(
        base_url=settings.github_api_base_url,
        token=settings.github_token.get_secret_value() if settings.github_token else None,
        timeout_seconds=settings.integration_timeout_seconds,
        max_response_bytes=settings.integration_max_response_bytes,
    )
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
    # Outermost, so preflights and even error responses carry the CORS headers. Only the
    # configured browser origins are allowed; credentials (cookies) are not used: the API
    # authenticates with a bearer token in the Authorization header.
    origins = list(
        dict.fromkeys(
            o.rstrip("/") for o in [settings.frontend_url, *settings.cors_allowed_origins] if o
        )
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "Retry-After"],
        allow_credentials=False,
        max_age=600,
    )
    app.include_router(health.router)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
