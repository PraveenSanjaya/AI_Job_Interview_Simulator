# Database Design

PostgreSQL is the intended production database, accessed through SQLAlchemy 2.x (async, `asyncpg`). Schema changes are made with Alembic migrations in `backend/migrations`.

> **Verification status.** Migrations and models are tested against SQLite only (a testing fallback). The PostgreSQL DDL is generated and inspected offline (`alembic upgrade head --sql`) but has **not** been executed against a PostgreSQL server in this environment. pgvector is not used yet and will be added by the feature that needs it.

## Entities (Phases 2-6)

```mermaid
erDiagram
    users ||--o| user_profiles : has
    users ||--o{ refresh_tokens : issues
    user_profiles ||--o{ education : has
    user_profiles ||--o{ work_experience : has
    user_profiles ||--o{ skills : has
    user_profiles ||--o{ projects : has
    user_profiles ||--o{ certifications : has

    users {
        uuid id PK
        varchar email UK "lower-cased"
        varchar hashed_password "Argon2id"
        varchar role "user | admin"
        bool is_active
        timestamptz created_at
        timestamptz updated_at
    }
    refresh_tokens {
        uuid id PK
        uuid user_id FK
        uuid family_id "login session lineage"
        varchar token_hash UK "SHA-256 digest only"
        timestamptz expires_at
        timestamptz revoked_at
        timestamptz created_at
    }
    user_profiles {
        uuid id PK
        uuid user_id FK,UK
        varchar full_name
        varchar headline
        text career_objective
        varchar experience_level
        varchar preferred_difficulty
        json preferred_roles
    }
    skills {
        uuid id PK
        uuid profile_id FK
        varchar name
        varchar category "technical | soft"
        varchar proficiency
        int position
    }
```

`resumes` (migration `0002`): `id`, `user_id` (FK, cascade), `display_name`, `file_format`, `size_bytes`, `sha256`, `storage_key` (unique), `status` (`uploaded|extracting|extracted|analyzing|completed|failed`), `failure_stage`, `error_code`, `error_message`, `page_count`, `char_count`, `word_count`, `extracted_at`, `analyzed_at`, timestamps; indexed by `(user_id, created_at)`. `resume_analyses`: `id`, `resume_id` (FK, cascade, unique: one current analysis per resume), `provider`, `model`, `consent_external_ai`, `input_truncated`, `result` (JSON: verified facts and AI assessment), `created_at`. Extracted text is deliberately not stored. See [RESUME_PROCESSING.md](RESUME_PROCESSING.md).

`integration_sources` (migration `0003`): `id`, `user_id` (FK, cascade), `kind` (`github|portfolio`), `source_ref` (GitHub login or portfolio URL), `snapshot` (JSON of observed facts), `fetched_at`, timestamps; unique on `(user_id, kind)` so a user has at most one source per kind and reconnecting replaces it. `integration_analyses`: `id`, `user_id` (FK, cascade), optional `github_source_id`, `portfolio_source_id` and `resume_id` (FKs, all `ON DELETE CASCADE`, so an analysis disappears with any input it was derived from), `provider`, `model`, `consent_external_ai`, `input_truncated`, `result` (JSON: computed facts plus verified AI assessment), `created_at`; indexed by `(user_id, created_at)`. See [INTEGRATIONS.md](INTEGRATIONS.md).

`job_descriptions` (migration `0004`): `id`, `user_id` (FK, cascade), `title`, `company`, `description` (untrusted text), `source_url`, `status` (`saved|parsed|failed`), `description_sha256`, timestamps; indexed by `(user_id, created_at)`. `job_analyses`: `id`, `job_id` (FK, cascade, unique: one current analysis per job), `user_id`, `parser` (`deterministic|deterministic+ai`), `provider`, `model`, `consent_external_ai`, `input_truncated`, `description_sha256`, `result` (JSON: the parse with a quote per item), `created_at`. `job_matches`: `id`, `job_id` (FK, cascade), `user_id`, `overall_score` (nullable), `confidence`, `scoring_config` (JSON), `evidence_used` (JSON identifiers and versions of the inputs), `result` (JSON: the deterministic `report` and the separate `ai_advice`), `ai_provider`, `ai_model`, `consent_external_ai`, `created_at`; indexed by `(job_id, created_at)`. Matches deliberately hold **no foreign keys to candidate data**, so they survive edits and deletions of the profile, resume and connected sources; they are removed only with the job or the user. See [JOB_MATCHING.md](JOB_MATCHING.md).

`interview_sessions` (migration `0005`): `id`, `user_id` (FK, cascade), `job_id` (FK, **SET NULL**) with `job_snapshot` (JSON), `interview_types` (JSON), `difficulty`, `question_count`, `max_followups`, `status` (`created|in_progress|completed|cancelled|interrupted|expired`), `mode`, `ai_status`, `use_ai`, `consent_external_ai`, `ai_provider`, `ai_model`, `scoring_config` (JSON), `version` (concurrency guard), `current_index`, `started_at`, `completed_at`, `last_activity_at`, timestamps. `interview_questions`: `id`, `session_id` (FK, cascade), `user_id`, `main_index`, `followup_index` (0 = main question; unique with the other two), `category`, `text`, `source` (`ai|question_bank`), `followup_kind`, `skill_tags`, `expected_points` (never returned during an interview), `asked_at`. `interview_answers`: `id`, `question_id` (FK, cascade, **unique**: one answer per question), `session_id`, `user_id`, `text`, `skipped`, `submitted_at`. `interview_evaluations`: `id`, `answer_id` (FK, cascade, unique), `session_id`, `user_id`, `status` (`evaluated|unavailable|failed|not_evaluated`), `reason`, `provider`, `model`, `result` (JSON), `created_at`. `interview_reports`: `id`, `session_id` (FK, cascade, unique), `user_id`, `overall_score` (nullable), `result` (JSON, written once at completion), `created_at`. Answers are personal text: owner-scoped, never logged, deleted with the session or user. See [INTERVIEWS.md](INTERVIEWS.md).

`education`, `work_experience`, `projects` and `certifications` follow the same pattern as `skills`: a `profile_id` foreign key, a `position` column preserving user order, and their own descriptive columns.

## Design decisions

- **UUID primary keys** everywhere (generated in Python, so they are available before flush).
- **Ownership**: every row is reachable only through `users.id`, via `user_profiles.user_id` or `refresh_tokens.user_id`. All foreign keys use `ON DELETE CASCADE`, so deleting a user removes all of their **database rows** (supports the privacy requirement). This is covered by tests, including a plain SQL delete with no ORM involvement. Uploaded resume **files** live outside the database and are not removed by a database cascade; an account-deletion flow must delete them through the storage service first (known gap, see [RESUME_PROCESSING.md](RESUME_PROCESSING.md)).
- **Passwords and tokens**: only an Argon2id hash of the password and a SHA-256 digest of each refresh token are stored.
- **Refresh token families**: `family_id` groups the tokens issued from one login. A reused (already revoked) token revokes the whole family.
- **Emails** are stored trimmed and lower-cased with a unique index, so uniqueness is case-insensitive on every database.
- **Enums** are stored as `VARCHAR` values (no native PostgreSQL ENUM), so adding a value needs no `ALTER TYPE`.
- **Timestamps** are timezone-aware UTC. A `UTCDateTime` type restores the timezone that SQLite drops and rejects naive datetimes.
- **Constraint names** follow a fixed naming convention so migrations are reproducible.
- **Skills** are unique per `(profile, category, name)`.
- **Revocation** uses a conditional `UPDATE … WHERE revoked_at IS NULL`, so concurrent rotation of one token can succeed only once.

## Migrations

```bash
cd backend
export DATABASE_URL=postgresql://user:password@localhost:5432/interview_db
alembic upgrade head      # apply
alembic downgrade -1      # roll back one revision
alembic check             # fail if models and migrations have drifted
alembic upgrade head --sql  # print the SQL without connecting
```

`DATABASE_URL` is read from the environment (never stored in `alembic.ini`). `postgresql://` is automatically upgraded to the `asyncpg` driver. A test (`tests/test_migrations.py`) fails if the models change without a matching migration.
