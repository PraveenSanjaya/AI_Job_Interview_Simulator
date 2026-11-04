# AI Job Interview Simulator

An AI-powered interview preparation platform: personalized mock interviews built from a candidate's CV, GitHub, portfolio and target job descriptions.

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md).

## Status

Phase 1 (backend foundation) is implemented: FastAPI app, configuration, health endpoints, error handling, logging and tests. Authentication, database, AI and voice features are not implemented yet.

## Backend setup

Requires Python 3.12+. Docker, PostgreSQL and Redis are **not** required at this stage.

```bash
cd backend
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # optional; all values have safe defaults
```

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
| `DATABASE_URL` | unset | Not used yet |
| `REDIS_URL` | unset | Not used yet |

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
    api/         # HTTP routers (health.py, v1/)
    core/        # config, logging, middleware, exceptions
    schemas/     # Pydantic request/response models
    services/    # business logic, independent of HTTP
  tests/
```
