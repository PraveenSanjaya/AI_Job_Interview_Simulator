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
| Phase 2 development log update | Completed | N/A (docs only) | 4f49c7a | PraveenSanjaya |
| Phase 2.1: registration enumeration fix (uniform 202) | Completed | 146 passed (SQLite) at commit time | 25ac865 | PraveenSanjaya |
| Phase 2.1: API doc repair (previous commit emptied the file by mistake) | Completed | N/A (docs only) | 346f237 | PraveenSanjaya |
| Phase 2.1: ResourceWarning fix (unclosed sqlite3 connection in test helper) | Completed | 150 passed, 0 warnings | 1a30e69 | PraveenSanjaya |
| Phase 2.1: refresh rotation row lock and concurrency tests | Completed on SQLite; PostgreSQL cases written but **not run** | 155 passed, 5 skipped (PostgreSQL) | 61a3d35 | PraveenSanjaya |
| Phase 2.1: PostgreSQL migration test (gated) | Written, **not run** | skipped without TEST_DATABASE_URL | 28cd26c | PraveenSanjaya |
| Phase 2.1: testing guide and PostgreSQL runbook | Completed | N/A (docs only) | c183ceb | PraveenSanjaya |
| Phase 2.1 development log update | Completed | N/A (docs only) | ad2ef15 | PraveenSanjaya |
| Phase 3: resume processing dependencies | Completed | imports verified | b223115 | PraveenSanjaya |
| Phase 3: secure storage service (local adapter, S3 reserved) | Completed | 17 storage tests | c118cfe | PraveenSanjaya |
| Phase 3: content-based upload validation | Completed | 45 validation tests | 6b1c9c8 | PraveenSanjaya |
| Phase 3: PDF/DOCX/TXT extraction (OCR-required detection) | Completed | 17 extraction tests | 645c551 | PraveenSanjaya |
| Phase 3: resume models and migration 0002 | Completed on SQLite; PostgreSQL SQL generated only | migration up/down/drift on SQLite | 85ef456 | PraveenSanjaya |
| Phase 3: authenticated resume uploads | Completed | 266 passed (suite at commit time) | e32829b | PraveenSanjaya |
| Phase 3: AI provider abstraction | Completed (committed with one failing test, fixed in 25889a1) | provider tests passed | 8b64290 | PraveenSanjaya |
| Phase 3: fix test broken by OPENAI_API_KEY becoming a setting | Completed | 289 passed | 25889a1 | PraveenSanjaya |
| Phase 3: structured CV analysis service | Completed | 334 passed (suite at commit time) | f6a8164 | PraveenSanjaya |
| Phase 3: resume analysis API | Completed | 358 passed (suite at commit time) | 3200bd0 | PraveenSanjaya |
| Phase 3: user-approved profile updates | Completed | 384 passed (suite at commit time) | fa16cbe | PraveenSanjaya |
| Phase 3: end-to-end security tests | Completed | 393 passed | e45ff7a | PraveenSanjaya |
| Phase 3: resume API and security documentation | Completed | N/A (docs only) | 90cfcdb | PraveenSanjaya |
| Phase 3: README and database design update | Completed | N/A (docs only) | bc79178 | PraveenSanjaya |
| Phase 3 development log update | Completed | N/A (docs only) | 72f4430 | PraveenSanjaya |
| Phase 4: integration source/analysis models, migration 0003, settings | Completed on SQLite; PostgreSQL SQL generated only | 394 passed (suite at commit time) | ce9415f | PraveenSanjaya |
| Phase 4: GitHub client (public REST, no credentials) and snapshot builder | Completed | 452 passed (suite at commit time) | e243b58 | PraveenSanjaya |
| Phase 4: GitHub integration API | Completed | 472 passed (suite at commit time) | 19b03fc | PraveenSanjaya |
| Phase 4: SSRF-hardened web page fetcher | Completed | 588 passed (suite at commit time) | 992b87c | PraveenSanjaya |
| Phase 4: portfolio extraction and bounded same-host crawler | Completed | 603 passed (suite at commit time) | bc1ccf0 | PraveenSanjaya |
| Phase 4: portfolio integration API | Completed | 632 passed (suite at commit time) | a1b8dc5 | PraveenSanjaya |
| Phase 4: structured AI analysis of connected sources | Completed | 655 passed (suite at commit time) | fcb36bb | PraveenSanjaya |
| Phase 4: integration analysis API (consent, profile approval) | Completed | 686 passed (suite at commit time) | c4af643 | PraveenSanjaya |
| Phase 4: end-to-end integration security tests | Completed | 696 passed | a953415 | PraveenSanjaya |
| Phase 4: integrations documentation and API reference | Completed | N/A (docs only) | 735737f | PraveenSanjaya |
| Phase 4: README and database design update | Completed | N/A (docs only) | 39f065f | PraveenSanjaya |

## Notes

- Pre-existing commit `1190526` ("Initial commit") is authored as "Praveen Sanjaya Perera". It is preserved unchanged and was not rewritten.
- Environment at start: Python 3.13.5, Node 22.19.0. Docker, PostgreSQL and Redis are not installed.
- Phase 2 was verified against SQLite and in-process HTTP tests, plus a manual end-to-end run (Alembic migration, `uvicorn`, register, login and profile via `curl`) on a SQLite file. **PostgreSQL, Redis and Docker have never been run** in this environment, so PostgreSQL behaviour is unverified.
- Rate limiting is in-memory and per process, not Redis-backed.
- `origin/main` and local `main` were identical at the Phase 2.1 check (no divergence). No push was issued from this session; the reflog records no push, and the remote was updated by something else (possibly an editor auto-sync). Authorship does not identify who pushed.
- Phase 2.1 PostgreSQL verification is **still pending**: Docker and PostgreSQL are not installed here and no embedded PostgreSQL wheel exists for Windows.
- Phase 3 was verified with SQLite, scripted fake AI providers and a mocked HTTP endpoint, plus a manual end-to-end run on a real `uvicorn` server (migration, register, login, TXT upload, `analyze` returning `503 ai_unavailable` with no provider, `.exe` upload rejected, delete removing the stored file). **No real AI provider was ever called**, so extraction quality and prompt-injection resistance of a real model are unverified. **PostgreSQL, Redis and Docker are still unverified.**
- `8b64290` was committed while one unrelated test was failing (a test used `OPENAI_API_KEY` as its "unknown variable"); it was repaired in `25889a1`. Later commits were gated on a green suite.
- Known gap: deleting a user does not delete their stored resume files (no account-deletion flow yet). Documented in `docs/RESUME_PROCESSING.md`.
- Phase 4 verification: SQLite and in-process HTTP tests with fake GitHub/AI/DNS/web transports, plus a manual run on a real `uvicorn` server that made **real external calls**: one unauthenticated read-only GitHub API request set for the public account `octocat` (8 repositories, 4 READMEs), and one real HTTPS fetch of `https://example.com/` through the pinned-IP connection with the original host name as SNI (succeeded, title "Example Domain"). Seven internal-target URLs (metadata address, localhost, loopback v4/v6, decimal-encoded 127.0.0.1, 10.0.0.1, `file://`) were rejected with 422 by the real server. **No real AI provider was called.** PostgreSQL, Redis and Docker remain unverified.
- Git synchronisation finding (Phase 4): the remote `main` is updated by account `PraveenSanjaya` roughly 10-90 seconds after each local commit (GitHub activity API). No git hook, push config or session command explains it; the reflog shows no push from this session. A git-ignored workspace `.vscode/settings.json` disabling post-commit push and auto-fetch was added but pushes continued, so the cause is elsewhere (an editor extension, another tool, or user-level configuration). Not resolved.
