# Testing

## Quick start

```bash
cd backend
pytest --cov=app --cov-report=term-missing   # tests
ruff check . && ruff format --check .        # lint and format
mypy                                         # strict type checking
```

By default every test uses an isolated in-memory SQLite database. SQLite is a **testing fallback only**, so passing tests do not prove PostgreSQL works.

## Running the suite against PostgreSQL

The same tests (registration, login, profile CRUD, refresh rotation, cascade deletion, isolation) run unchanged against PostgreSQL, plus the tests that are skipped on SQLite (PostgreSQL migration and PostgreSQL concurrency).

1. Start PostgreSQL, for example with the provided Compose file (needs Docker and `POSTGRES_PASSWORD` in `.env`):

   ```bash
   docker compose up -d postgres
   ```

2. Create a **disposable** database whose name contains `test`:

   ```bash
   docker compose exec postgres createdb -U interview interview_test
   ```

3. Run the suite:

   ```bash
   cd backend
   TEST_DATABASE_URL=postgresql://interview:<password>@localhost:5432/interview_test pytest -rs
   ```

Safety: the fixtures drop and recreate every table, so they refuse to run unless the database name contains `test`. Never point `TEST_DATABASE_URL` at a real database.

### PostgreSQL verification checklist

| Check | Where it is tested | Status |
| --- | --- | --- |
| Compose starts PostgreSQL and Redis | manual (`docker compose up`) | **Not run** (Docker unavailable here) |
| Alembic upgrade, drift check, downgrade | `test_migrations_apply_and_revert_on_postgresql` | **Not run** |
| Registration and login | `test_auth_register_login.py` | **Not run on PostgreSQL** |
| Profile CRUD | `test_profile.py` | **Not run on PostgreSQL** |
| Refresh rotation | `test_auth_refresh_logout.py` | **Not run on PostgreSQL** |
| Concurrent refresh and registration | `test_refresh_concurrency.py` (`postgresql` cases) | **Not run** |
| User deletion cascades | `test_models.py` | **Not run on PostgreSQL** |

Update this table with real results when the suite has been run on PostgreSQL. All rows currently pass on SQLite only.

## Concurrency tests

`tests/test_refresh_concurrency.py` fires simultaneous requests at one refresh token, at login, and at registration. It uses a file-backed SQLite database (separate connections) and, when configured, PostgreSQL. On PostgreSQL the refresh path takes a row lock (`SELECT … FOR UPDATE`) so concurrent rotations queue and later ones see the token as already used. SQLite has no row locks; there, the atomic conditional `UPDATE` guarantees a single winner.

Semantics under a race: exactly one request receives new tokens, the others receive `401`, and the reuse is treated as a replay (the token family is revoked, which may also end the winner's new session). A client that refreshes from two tabs at once can therefore be signed out. If that proves too disruptive, a short reuse-grace window can be added later as a deliberate security trade-off.

## Test layout

| File | Covers |
| --- | --- |
| `test_config.py`, `test_tokens.py`, `test_passwords.py` | settings validation, JWT and refresh-token primitives, Argon2id |
| `test_database.py`, `test_models.py`, `test_migrations.py` | engine/session, models and cascades, Alembic |
| `test_auth_*.py`, `test_rate_limit.py` | registration, login, refresh, logout, current user, rate limiting |
| `test_profile.py`, `test_isolation_and_security.py` | profile API and cross-user isolation, secret leakage |
| `test_refresh_concurrency.py` | race conditions |
| `test_job_models.py` | job tables: cascades, one analysis per job, matches independent of analyses |
| `test_job_parser.py`, `samples_jobs.py` | deterministic job parsing, importance, alternatives, seniority |
| `test_jobs_api.py` | job CRUD, validation, ownership, URL import and SSRF/restricted-site protection |
| `test_job_ai_analysis.py` | AI enrichment: grounding, consent, failures, prompt-injection handling |
| `test_matching_engine.py` | scoring maths, weights, boundaries, evidence rules, de-duplication, honesty rules |
| `test_match_api.py`, `test_match_ai.py` | match API: sources, history preservation, privacy, isolation; AI advice safeguards |
| `test_health.py`, `test_errors_and_logging.py` | health endpoints, error shape, logging |

## Warnings policy

The suite is expected to run with zero warnings. Resource warnings usually mean a connection was not closed (for example, `sqlite3`'s `with` block does not close the connection; use `contextlib.closing`).
