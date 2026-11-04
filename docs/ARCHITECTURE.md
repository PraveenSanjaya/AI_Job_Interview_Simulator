# System Architecture

## 1. Style
A **modular monolith**. A single FastAPI service has clearly separated modules, and the boundaries are enforced by layering. Microservices are not introduced until scale or operations justify them.

```
React + TS (Vite)
      | REST /api/v1, WebSocket
      v
FastAPI backend
  api (routers) -> services -> repositories -> models (SQLAlchemy)
                      |
                      +-> ai (LLM provider interface, LangGraph interview graph)
                      +-> rag / memory (chunking, embeddings, retrieval)
                      +-> voice (STT / TTS / transport provider interfaces)
                      +-> integrations (GitHub, portfolio fetcher, storage)
                      +-> tasks (background document processing)
      |
      v
PostgreSQL + pgvector | Redis | File storage (local / S3)
      |
      v
OpenAI | Deepgram | ElevenLabs | LiveKit | GitHub API
```

## 2. Layering Rules
1. **Routers** handle HTTP only: validation through Pydantic schemas, auth dependency, status codes.
2. **Services** hold business logic and are framework-agnostic. They receive dependencies by injection.
3. **Repositories** are the only code that touches the database. Every query on user data is scoped by `user_id`.
4. **Providers** are interfaces (`LLMProvider`, `EmbeddingProvider`, `STTProvider`, `TTSProvider`, `StorageBackend`). Concrete implementations are chosen from configuration, and tests use fakes.
5. A missing optional provider disables its feature with a clear message. It never breaks startup or text mode.

## 3. Backend Modules
auth, profile, resume, github, portfolio, jobs, interview engine, evaluation, memory/RAG, skill gaps, analytics, voice.

## 4. Interview Engine
A LangGraph state machine. The state is kept in Redis while the interview is active and persisted to PostgreSQL at each transition.

```
configure -> retrieve_memory -> generate_question -> await_answer
          -> evaluate_answer -> decide (follow-up | next question | finish)
          -> generate_report -> update_memory + skill_assessments
```

- Question generation is grounded in profile, job, GitHub and portfolio data plus retrieved memories (top-k only).
- Evaluation is structured output validated against Pydantic schemas, with one score per dimension.
- Prompts treat uploaded and fetched content as untrusted data, delimited and never merged into system instructions.

## 5. Memory and RAG
- **PostgreSQL:** sessions, questions, answers, evaluations, feedback, skill assessments.
- **pgvector:** `document_embeddings` and `memory_records` with a `user_id` filter on every similarity query. Cross-user isolation is covered by tests.
- Users can list and delete memories. Retention controls are applied on deletion.

## 6. Voice
```
mic -> LiveKit transport -> STT provider -> interview engine -> TTS provider -> audio out
```
The transcript is stored as the text answer, so the voice path reuses the text pipeline. Provider failures or disconnects fall back to text input.

## 7. Security Architecture
- Argon2id password hashing. Short-lived JWT access tokens. Refresh tokens are stored hashed and rotated.
- Redis-backed rate limiting, with a stricter limit on login.
- Uploads: allow-list of types, size cap, content sniffing, stored under generated names, never executed.
- Portfolio fetcher: resolves DNS and blocks private, loopback and link-local addresses (including after redirects), with timeouts and size limits.
- Centralized exception handling returns safe error bodies. Log scrubbing removes secrets and resume content.

## 8. Observability
Structured JSON logs with request correlation IDs, a Prometheus `/metrics` endpoint (request, LLM latency, token usage, voice latency, DB pool), Grafana dashboards, Sentry, LangSmith tracing.

## 9. Deployment Topology
- **Development:** Docker Compose runs api, postgres+pgvector, redis, and the Vite dev server.
- **Production:** backend container on AWS, S3 for files, managed Postgres and Redis. Frontend on Vercel. GitHub Actions run lint, tests and build, then deploy.

## 10. Planned Repository Layout
`frontend/`, `backend/app/{api,core,models,schemas,repositories,services,ai,rag,memory,voice,integrations,tasks}`, `backend/migrations/`, `database/`, `docs/`, `monitoring/`, `infrastructure/`, `.github/workflows/`. Folders are created when first needed.

## 11. Key Risks
| Risk | Mitigation |
|---|---|
| No local Postgres, Redis or Docker | Docker Compose and Testcontainers config written. DB-dependent tests are marked unverified until Docker is available. |
| No API credentials | Provider interfaces and fakes. Live behavior is not claimed as verified. |
| Prompt injection via CV, README or portfolio | Untrusted-content delimiting, structured outputs, no tool execution from document text. |
| LLM score reliability | Scores are labeled as AI estimates and the matching method is documented. |
| Scope size | Incremental phases, one feature per commit. |
