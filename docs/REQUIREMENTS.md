# Requirements

## 1. Vision
An AI interview coach. It analyzes a candidate's CV, GitHub profile, portfolio and target job descriptions, then runs personalized text and voice mock interviews. It evaluates answers, remembers past performance and recommends how to close skill gaps.

## 2. Functional Requirements

| ID | Module | Summary |
|---|---|---|
| FR-1 | Authentication | Register, login, logout, JWT access + refresh tokens, password reset, optional email verification, roles. Argon2id hashing, login rate limiting. |
| FR-2 | Candidate profile | Headline, objective, education, experience, skills, certifications, projects, preferred roles, level, difficulty. |
| FR-3 | Resume analysis | Upload PDF/DOCX/TXT with size and type validation. Extract text, build a structured profile with AI, let the user review and correct it. Uploaded text is untrusted data. |
| FR-4 | GitHub analysis | Public username (optional OAuth). Repos, languages, READMEs, activity. Generates project-based questions. Respects rate limits. No private repo access without explicit authorization. |
| FR-5 | Portfolio analysis | Fetch public URL with SSRF protection (no localhost, private IPs or internal networks). |
| FR-6 | Job description analysis | Extract title, company, required and preferred skills, responsibilities. Compute match percentage with a documented method. Scores are not hiring probabilities. |
| FR-7 | Interview engine | Eight interview categories, four difficulty levels, configurable duration. State machine (LangGraph) with follow-ups. Never reveals the ideal answer in advance. |
| FR-8 | Evaluation | Separate scores per dimension (correctness, relevance, completeness, approach, clarity, structure, examples). Structured JSON validated by Pydantic. No emotion or facial analysis claims. |
| FR-9 | Long-term memory | pgvector semantic memory plus PostgreSQL records. Retrieve only relevant items. Users can inspect and delete memories. Strict per-user isolation. |
| FR-10 | Skill gap analysis | Strong, developing, weak and missing skills with explanations and recommendations, updated after each interview. |
| FR-11 | Dashboard | Statistics from persisted data only. Useful empty states. |
| FR-12 | History and reports | Own-records-only access. PDF export where practical. |
| FR-13 | Voice | Provider interfaces (LiveKit, Pipecat, Deepgram, ElevenLabs). The app must work fully in text-only mode. |

## 3. Non-Functional Requirements
- **Security:** hashing, JWT, authorization on every private route, CORS, rate limiting, upload validation, SSRF protection, no secrets in code or logs, user data isolation.
- **Quality:** backend coverage of 80% or higher, Ruff, MyPy, ESLint, Prettier, pre-commit hooks.
- **Observability:** structured logs with correlation IDs, Prometheus metrics, Sentry, LangSmith; no PII, resume content or tokens in logs.
- **Portability:** AI, storage and voice providers are replaceable behind interfaces. Optional integrations degrade gracefully with a clear message.
- **Accessibility and UX:** responsive, light and dark themes, loading and error states.

## 4. Technology Stack
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, React Router, TanStack Query, Axios, React Hook Form, Zod, Recharts, Lucide.
- **Backend:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, Uvicorn, WebSockets.
- **Data:** PostgreSQL + pgvector, Redis, S3 (local adapter in development).
- **AI:** OpenAI, LangChain, LangGraph, RAG.
- **Voice:** LiveKit, Pipecat, Deepgram, ElevenLabs.
- **DevOps:** Docker, Docker Compose, GitHub Actions, AWS, Vercel, Prometheus, Grafana.
- **Testing:** Pytest, HTTPX, Testcontainers, Vitest, React Testing Library, Playwright, Locust.

## 5. Definition of Done
**Feature:** works, validated, error handling, relevant tests actually run, docs updated, dedicated commit with verified author `PraveenSanjaya`.

**Project:** the 20 completion criteria in the original specification (register through to separate verified feature commits).

## 6. Assumptions and Constraints
- Only the local toolchain is available: Python 3.13, Node 22. Docker, PostgreSQL and Redis are not installed, so DB-dependent behavior needs Docker to be verified.
- No third-party API credentials exist yet. Live AI and voice behavior cannot be verified without them.
- Commits are local only. No push without explicit owner authorization.
