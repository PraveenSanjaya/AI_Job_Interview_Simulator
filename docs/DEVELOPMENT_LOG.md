# Development Log

One row per completed and verified feature. Hashes and results are copied from the actual Git history and test runs. A feature is only marked Completed after it has been implemented and verified.

| Feature | Implementation | Tests | Commit Hash | Author |
| --- | --- | --- | --- | --- |
| Project planning (`.gitignore`, `.env.example`) | Completed | N/A (config only) | 1235cac | PraveenSanjaya |
| Project requirements doc | Completed | N/A (docs only) | ead72ac | PraveenSanjaya |
| System architecture doc | Completed | N/A (docs only) | a821c04 | PraveenSanjaya |
| Development log | Completed | N/A (docs only) | a1d70b2 | PraveenSanjaya |
| Line-ending normalization (`.gitattributes`) | Completed | N/A (config only) | 6bb428f | PraveenSanjaya |
| Backend project structure | Completed | N/A (scaffolding) | 164d4eb | PraveenSanjaya |
| FastAPI application entry point | Completed | Smoke-tested (docs endpoints 200) | 387af2c | PraveenSanjaya |
| Configuration and health endpoints | Completed | Smoke-tested; covered by later tests | cab26c5 | PraveenSanjaya |
| Error handling and structured logging | Completed | Smoke-tested; covered by later tests | ed92e89 | PraveenSanjaya |
| Backend foundation tests | Completed | 19 passed, 98% coverage | 9507d17 | PraveenSanjaya |
| Backend code quality tools (Ruff, MyPy) | Completed | Ruff, format, MyPy strict clean; 19 passed | cfb44d4 | PraveenSanjaya |
| Backend setup instructions (README) | Completed | Server run manually; health endpoints returned 200 | f294810 | PraveenSanjaya |
| Markdown lint cleanup (requirements, architecture) | Completed | N/A (docs only) | 5fdfeb5 | PraveenSanjaya |
| Development log update (Phase 1) | Completed | N/A (docs only) | 31235fa | PraveenSanjaya |
| Database foundation (async SQLAlchemy, session, readiness probe) | Completed | SQLite only; 28 passed at commit time | cde7fd0 | PraveenSanjaya |
| Database and auth dependencies declared | Completed | N/A (packaging) | 52c2e44 | PraveenSanjaya |
| User and candidate profile models | Completed | SQLite only; 35 passed at commit time | 5bf925f | PraveenSanjaya |
| Alembic migrations | Completed | SQLite upgrade/downgrade/drift check; PostgreSQL SQL generated offline only (not executed) | 45849eb | PraveenSanjaya |
| Docker Compose (PostgreSQL, Redis) | Written, **not run** (Docker not installed) | YAML parsed only | 784dd63 | PraveenSanjaya |
| Argon2id password hashing | Completed | 6 passed | 6086d55 | PraveenSanjaya |
| JWT access/refresh token utilities | Completed | 58 passed (suite at commit time) | 89259d8 | PraveenSanjaya |
| Registration and login (+ in-memory rate limiting) | Completed | 84 passed (suite at commit time) | db4b945 | PraveenSanjaya |
| Refresh rotation and logout | Completed | 96 passed (suite at commit time) | d47faf1 | PraveenSanjaya |
| Authenticated user endpoint and role guard | Completed | 110 passed (suite at commit time) | 981fcbe | PraveenSanjaya |
| Candidate profile management | Completed | 139 passed (suite at commit time) | 3875d71 | PraveenSanjaya |
| Isolation and security tests | Completed | 148 passed, 98% coverage | e3d3e24 | PraveenSanjaya |
| API documentation | Completed | N/A (docs only) | ab260da | PraveenSanjaya |
| Database design doc and README update | Completed | N/A (docs only) | 80e03bb | PraveenSanjaya |

## Notes

- Pre-existing commit `1190526` ("Initial commit") is authored as "Praveen Sanjaya Perera". It is preserved unchanged and was not rewritten.
- Environment at start: Python 3.13.5, Node 22.19.0. Docker, PostgreSQL and Redis are not installed.
- Phase 2 was verified against SQLite and in-process HTTP tests, plus a manual end-to-end run (Alembic migration, `uvicorn`, register, login and profile via `curl`) on a SQLite file. **PostgreSQL, Redis and Docker have never been run** in this environment, so PostgreSQL behaviour is unverified.
- Rate limiting is in-memory and per process, not Redis-backed.
