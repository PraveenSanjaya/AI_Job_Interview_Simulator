# Database Design

PostgreSQL is the intended production database, accessed through SQLAlchemy 2.x (async, `asyncpg`). Schema changes are made with Alembic migrations in `backend/migrations`.

> **Verification status.** Migrations and models are tested against SQLite only (a testing fallback). The PostgreSQL DDL is generated and inspected offline (`alembic upgrade head --sql`) but has **not** been executed against a PostgreSQL server in this environment. pgvector is not used yet and will be added by the feature that needs it.

## Entities (Phases 2-3)

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
