# AI Job Interview Simulator

An AI-powered interview preparation platform: personalized mock interviews built from a candidate's CV, GitHub, portfolio and target job descriptions.

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md).

## Status

Implemented: backend foundation (Phase 1), database, authentication and candidate profiles (Phase 2), resume upload, text extraction and AI CV analysis with user-approved profile updates (Phase 3), GitHub profile and portfolio-website analysis with SSRF-hardened fetching (Phase 4), job description analysis with explainable candidate-to-job matching (Phase 5), text-based AI mock interviews with follow-ups, evaluation and reports (Phase 6), and a React frontend covering all of the above (Phase 7). Not implemented yet: voice, RAG/memory, OCR, S3 storage, Redis integration and email delivery (password reset, email verification).

See [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md), [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md), [docs/RESUME_PROCESSING.md](docs/RESUME_PROCESSING.md) and [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) and [docs/JOB_MATCHING.md](docs/JOB_MATCHING.md) and [docs/INTERVIEWS.md](docs/INTERVIEWS.md) (security, privacy, retention, scoring) and [docs/FRONTEND.md](docs/FRONTEND.md) and [docs/TESTING.md](docs/TESTING.md).

## Frontend

React + TypeScript + Vite app in `frontend/` (needs Node 20+). With the backend running on port 8000:

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173, proxies /api to the backend
npm test
```

Details, production configuration and testing notes: [docs/FRONTEND.md](docs/FRONTEND.md).

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
| `AUTH_RATE_LIMIT_ATTEMPTS` / `AUTH_RATE_LIMIT_WINDOW_SECONDS` | `10` / `60` | Limits for auth, upload and analysis endpoints |
| `STORAGE_BACKEND` / `LOCAL_STORAGE_PATH` | `local` / `./storage` | Uploaded resumes. Keep the path outside any web root. `s3` is not implemented yet |
| `MAX_UPLOAD_BYTES` | `5242880` | Maximum resume size |
| `MAX_JSON_BODY_BYTES` | `1048576` | Maximum size of every other request body |
| `AI_PROVIDER` | `none` | `none` or `openai`. AI is optional; everything except analysis works without it |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | unset | Both required when `AI_PROVIDER=openai`. No default model is assumed |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint. `localhost` endpoints are treated as local (no consent prompt) |
| `AI_TIMEOUT_SECONDS`, `AI_MAX_INPUT_CHARS` | `60`, `30000` | Provider timeout and maximum characters sent |
| `GITHUB_TOKEN` | unset | Optional. Only raises GitHub's API rate limit for public reads; never needed |
| `GITHUB_MAX_REPOS`, `GITHUB_README_REPOS` | `100`, `5` | Repositories read and READMEs fetched per connection |
| `INTEGRATION_TIMEOUT_SECONDS`, `INTEGRATION_MAX_RESPONSE_BYTES` | `10`, `1000000` | Per-request timeout and decompressed size cap for GitHub and portfolio fetches |
| `PORTFOLIO_MAX_PAGES` | `5` | Pages fetched per portfolio (the supplied page plus same-host pages) |
| `INTERVIEW_DEFAULT_FOLLOWUPS`, `INTERVIEW_MAX_FOLLOWUPS`, `INTERVIEW_MAX_QUESTIONS` | `2`, `3`, `30` | Follow-ups per main question (default and ceiling) and maximum interview length |
| `INTERVIEW_IDLE_MINUTES`, `INTERVIEW_CREATED_EXPIRY_HOURS` | `120`, `72` | A running interview idle this long becomes `interrupted`; an unstarted one expires |
| `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS` | `http://localhost:5173`, `[]` | Browser origins allowed to call the API (the frontend URL is always allowed; extra origins as a JSON list). No cookies or credentials are involved |
| `INTERVIEW_SCORING` | unset | Optional JSON overrides of the interview scoring rules; validated at startup |
| `MATCH_WEIGHTS` | unset | Optional JSON overrides of the job-match scoring weights, e.g. `{"required_skills": 0.5}`; validated at startup |

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
    ai/            # LLM provider abstraction, CV analysis, grounding, suggestions
    db/            # engine, session dependency, column types
    documents/     # upload validation and PDF/DOCX/TXT text extraction
    integrations/  # GitHub client/snapshot, SSRF-safe portfolio fetcher and crawler
    jobs/          # job description parser and vocabulary
    matching/      # deterministic, explainable candidate-to-job matching engine
    interview/     # question bank, AI interviewer/evaluator interfaces, scoring, reports
    models/        # SQLAlchemy models
    repositories/  # database access
    schemas/       # Pydantic request/response models
    services/      # business logic, independent of HTTP
    storage/       # storage backends (local; S3 later)
  migrations/      # Alembic
  tests/
frontend/          # React SPA (see docs/FRONTEND.md)
```
