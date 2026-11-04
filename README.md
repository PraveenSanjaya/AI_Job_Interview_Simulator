# AI Job Interview Simulator

An AI-powered interview preparation platform: personalized mock interviews built from a candidate's CV, GitHub, portfolio and target job descriptions.

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md).

## Status

Implemented: backend foundation (Phase 1) and database, authentication and candidate profiles (Phase 2). Not implemented yet: frontend, resume/GitHub/portfolio analysis, AI interviews, RAG/memory, voice, Redis integration and email delivery (password reset, email verification).

See [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) and [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md).

## Backend setup

Requires Python 3.12+. The API starts without a database (health endpoints work, database-backed endpoints return `503 database_unavailable`).

```bash
cd backend
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # optional; all values have safe defaults
```

### Database

PostgreSQL is the intended database. For local development either start the provided containers (needs Docker and `POSTGRES_PASSWORD` in `.env`):

```bash
docker compose up -d postgres redis
```

or point `DATABASE_URL` at any PostgreSQL server (`postgresql://user:password@host:5432/db` is upgraded to the asyncpg driver automatically). Then create the schema:

```bash
cd backend
alembic upgrade head
```

For a quick throwaway setup without PostgreSQL you can use SQLite (`DATABASE_URL=sqlite+aiosqlite:///./dev.db`). SQLite is meant for automated tests and is not a production target.

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

- Swagger UI: <http://localhost:8000/docs>
- Liveness: `GET /health/live`
- Readiness: `GET /health/ready`

Readiness reports `not_configured` for a dependency whose URL is unset, and `unchecked` when it is set but no connectivity probe exists yet. A dependency is only reported `ok` after a real probe succeeds (probes arrive with the database and cache phases).

### Configuration

Settings are read from environment variables or a `.env` file (see `.env.example`). Unknown variables are ignored, and no external API credential is required. An invalid value (for example `APP_ENV=foo`) stops startup with a validation error.

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `development`, `testing` or `production` |
| `LOG_LEVEL` | `INFO` | Standard Python level names |
| `DATABASE_URL` | unset | PostgreSQL URL. Unset means database features are unavailable |
| `REDIS_URL` | unset | Reported by readiness only; not used yet |
| `JWT_SECRET_KEY` | unset | **Required (32+ random characters) when `APP_ENV=production`.** Otherwise a random per-process secret is used and a warning is logged |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `RATE_LIMIT_ENABLED` | `true` | In-memory, per-process limiter |
| `AUTH_RATE_LIMIT_ATTEMPTS` / `AUTH_RATE_LIMIT_WINDOW_SECONDS` | `10` / `60` | Auth endpoint limits |

Generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Errors and logging

Every error response has the shape `{"error": {"code", "message", "request_id", "details?"}}`. Unexpected exceptions return a generic message, and the details are only logged. Logs are JSON on stdout. Each request gets an `X-Request-ID` (a safe inbound value is kept), and the request log records only method, path, status and duration, never query strings, headers or bodies.

### Test and quality checks

```bash
pytest --cov=app --cov-report=term-missing
ruff check .
ruff format --check .
mypy
```

## Project layout

```text
backend/
  app/
    api/           # HTTP routers and dependencies (health.py, deps.py, v1/)
    core/          # config, logging, middleware, exceptions, passwords, tokens, rate limiting
    db/            # engine, session dependency, column types
    models/        # SQLAlchemy models
    repositories/  # database access
    schemas/       # Pydantic request/response models
    services/      # business logic, independent of HTTP
  migrations/      # Alembic
  tests/
```
