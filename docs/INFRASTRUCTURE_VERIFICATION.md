# Infrastructure verification runbook

Several checks need services that were **not installed** on the development machine
(Docker Desktop, PostgreSQL, Redis) or credentials that must not be committed. Nothing
below has been run by the author of this document unless the "Status" column says so.
Run these steps on a machine that has the services, then record the real results in the
table at the end.

## 1. Start PostgreSQL and Redis

```powershell
copy .env.example .env          # then set POSTGRES_PASSWORD, JWT_SECRET_KEY, DATABASE_URL
docker compose up -d postgres redis
docker compose ps               # both should become "healthy"
```

`docker-compose.yml` publishes both ports on `127.0.0.1` only.

## 2. Migrations against PostgreSQL

```powershell
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check          # model/migration drift check
.venv\Scripts\python.exe -m alembic downgrade base
.venv\Scripts\python.exe -m alembic upgrade head
```

Migrations 0001–0005 have only been run on SQLite; their PostgreSQL SQL was generated
offline (`alembic upgrade 0003:0004 --sql`) and inspected, not executed.

## 3. PostgreSQL test suite (including the concurrency tests)

Create a **separate, disposable** database whose name contains `test` (the fixtures drop
and recreate every table and refuse to run otherwise):

```powershell
docker compose exec postgres createdb -U interview interview_test
$env:TEST_DATABASE_URL = "postgresql://interview:<password>@localhost:5432/interview_test"
cd backend
.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

Without `TEST_DATABASE_URL`, 8 tests are skipped: the PostgreSQL migration test, the
`postgresql` variants of `test_refresh_concurrency.py`, and two in `test_interviews_api.py`.
They should all run and pass. Pay particular attention to:

* refresh-token rotation under concurrency (`SELECT … FOR UPDATE`);
* **account deletion** (`test_account_deletion.py`): the SQLite run proves the cascade through
  `PRAGMA foreign_keys=ON`; on PostgreSQL the same `ON DELETE CASCADE` constraints must produce
  the same table-by-table result.

## 4. Redis rate limiting

```powershell
$env:REDIS_URL = "redis://localhost:6379/0"
pip install "redis>=5.0"        # listed in requirements.txt
```

Start the API with **two workers** and confirm the limit is shared:

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --workers 2
# 11 wrong logins for the same e-mail within 60 s must return 429 on the 11th,
# regardless of which worker answered.
docker compose exec redis redis-cli --scan --pattern "ratelimit:*"   # keys are SHA-256 digests
docker compose stop redis       # the API must keep answering; /health/ready shows redis "degraded"
```

The limiter's Lua script (`app/core/rate_limit.py`) has only been exercised through an
in-memory fake that emulates `INCR`/`PEXPIRE`/`PTTL`; the real script and the real `redis`
client are unverified.

## 5. Live frontend + backend

```powershell
cd backend ; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd frontend ; npm run dev      # http://localhost:5173, /api is proxied to port 8000
```

Walk through: register → profile → upload a TXT résumé → add a job → compare → start and
finish an interview → read the report → delete the account (the stored file directory
`backend/storage/<user id>` must disappear). Check `GET /health/ready` shows `database: ok`.

## 6. Real AI provider (needs your explicit approval first)

Set `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL` (and optionally
`OPENAI_BASE_URL`) **in your own `.env` only**. Exercise CV analysis, job analysis,
integration analysis, AI interview questions, follow-ups and answer evaluation. These calls
are billed by the provider and send résumé/job text to it. The application never needs the
key in the browser, and no test in this repository calls a real provider.

## Status

| Check | Status |
| --- | --- |
| Docker Desktop / Compose, PostgreSQL, Redis | **Not installed on the development machine; not run** |
| Alembic migrations on PostgreSQL | **Not run** |
| PostgreSQL test suite and concurrency tests | **Not run** (8 tests skipped) |
| Redis rate limiter against a real server | **Not run** (fake only) |
| Live frontend ↔ FastAPI walkthrough | **Not run** |
| Real browser / device testing | **Not run** |
| Real AI provider | **Not run; requires approval** |
