# API Documentation

Interactive documentation is served by the running backend at `/docs` (Swagger UI) and `/openapi.json`. This file describes behaviour that the schema alone does not.

Base path: `/api/v1`. Health endpoints are unversioned (`/health/live`, `/health/ready`).

## Conventions

**Errors** always use one shape:

```json
{"error": {"code": "validation_error", "message": "Request validation failed",
           "request_id": "…", "details": [{"location": ["body", "email"], "message": "…", "type": "…"}]}}
```

`details` appears only for validation errors. Every response carries an `X-Request-ID` header (a safe inbound value is preserved).

| Status | Meaning |
| --- | --- |
| 401 | Missing, invalid or expired credentials. Includes `WWW-Authenticate: Bearer`. |
| 403 | Authenticated but lacking the required role. |
| 409 | Conflict with the current state of a resource (not used by registration, which never reveals existing emails). |
| 422 | Request validation failed. |
| 429 | Rate limited. Includes `Retry-After` (seconds). |
| 503 | A required dependency, such as the database, is unavailable or unconfigured. |

**Authentication**: send `Authorization: Bearer <access_token>`.

## Authentication

### POST `/auth/register` → 202

Body: `email`, `password` (10–128 characters, at least one letter and one digit), `full_name` (1–200 characters).
Always returns `202 Accepted` with the same body, `{"message": "…"}`, **whether or not the email was already registered**, so the endpoint cannot be used to discover registered addresses.

- New email: the account (with an empty profile) is created and the user can sign in immediately. The email is trimmed and lower-cased.
- Existing email: nothing is changed (the existing account and its password are never modified) and the response is identical. The password is still hashed first, so both paths do the same expensive work.
- Errors: `422` (validation) and `429` (rate limited) only.

Trade-offs: a user who re-registers an existing email with a different password gets `202`, and a later sign-in with that password fails. Once an email provider exists, the existing owner should be notified by email ("someone tried to register with your address"). Residual timing differences between the two paths (one extra database write) are small compared with the shared hashing cost, but have not been measured. Validation errors (`422`) apply to the submitted data only and reveal nothing about existing accounts.

### POST `/auth/login` → 200

Body: `email`, `password`. Returns:

```json
{"access_token": "…", "refresh_token": "…", "token_type": "bearer", "expires_in": 1800}
```

Unknown email, wrong password and disabled account all return the same `401 invalid_credentials` response, and an unknown email still performs a full password verification so the outcomes cannot be told apart by timing.

### POST `/auth/refresh` → 200

Body: `refresh_token`. Returns a new token pair and **revokes the presented token** (rotation). Refresh tokens are single-use. Presenting an already-used token revokes the whole token family (every token descended from that login) and returns `401 invalid_refresh_token`, so a stolen token that is replayed also logs out the thief and the victim.

### POST `/auth/logout` → 204

Body: `refresh_token`. Revokes that login session (its entire token family). Always returns 204, including for unknown or already-revoked tokens, so it does not reveal token validity. Other sessions of the same user remain valid. The short-lived access token is stateless and remains valid until it expires (default 30 minutes).

### GET `/auth/me` → 200

Requires a Bearer token. Returns the authenticated user (`id, email, role, is_active, created_at`).

## Candidate profile

All profile endpoints act on the **authenticated user's own profile**. There is no profile id in any URL, so one user cannot address another's data. All require a Bearer token.

### GET `/profile` → 200

Returns:

- `email` (read-only, from the account).
- `full_name`, `headline`, `career_objective`.
- `experience_level` (`entry|junior|mid|senior|lead`).
- `preferred_difficulty` (`beginner|intermediate|advanced|expert`).
- `preferred_roles` (a list of strings).
- `education`, `work_experience`, `skills`, `projects`, `certifications` (lists, in the order submitted).
- `updated_at`.

### PUT `/profile` → 200

Replaces the whole profile (PUT semantics): omitted optional fields are cleared and omitted lists become empty. The response is the stored profile.

Validation:

- Unknown fields are rejected (`422`), so clients cannot set ids or ownership.
- Text is trimmed and length-limited.
- `preferred_roles` ≤ 20 and unique (case-insensitive).
- `skills` ≤ 100, with unique name per category (case-insensitive).
- `education` ≤ 20, `work_experience` ≤ 30, `projects` ≤ 30, `certifications` ≤ 30.
- `end_date` must not precede `start_date`. A current role (`is_current`) must have no `end_date`.
- URLs must be absolute `http(s)` URLs (≤ 500 characters). `javascript:` and `data:` are rejected.

The API stores text as data and does not sanitise HTML. Clients must escape it on display.

### GET `/profile/skills` → 200

Returns the profile's skills: `[{id, name, category: technical|soft, proficiency}]`.

## Rate limiting

`register`, `login`, `refresh` and `logout` are limited per client IP, and `login` additionally per target account. The defaults are 10 attempts per 60 seconds (`AUTH_RATE_LIMIT_ATTEMPTS`, `AUTH_RATE_LIMIT_WINDOW_SECONDS`, `RATE_LIMIT_ENABLED`).

The limiter is **in-memory and per process**. It is not shared between workers or hosts, and it is not Redis-backed. It sits behind a `RateLimiter` interface so a Redis implementation can replace it later. Behind a reverse proxy, configure trusted proxy headers on the ASGI server so the client IP is the real one.

## Health

- `GET /health/live`: `{"status": "ok"}` while the process is running.
- `GET /health/ready`: dependency checks. `database` is `ok` only after a real `SELECT 1` succeeds, `error` (HTTP 503) if the probe fails or times out, and `not_configured` if there is no `DATABASE_URL`. `redis` is `not_configured` or `unchecked` (there is no Redis client yet), and is never reported `ok`.

## Resumes

All resume endpoints require a Bearer token and only ever act on the caller's own resumes. A resume that belongs to someone else behaves exactly like one that does not exist (`404 resume_not_found`). See [RESUME_PROCESSING.md](RESUME_PROCESSING.md) for the security model, storage and retention.

A resume object contains: `id`, `display_name` (sanitised), `file_format`, `size_bytes`, `status`, `failure_stage`, `error_code`, `error_message`, `page_count`, `char_count`, `word_count`, `has_analysis`, `created_at`, `extracted_at`, `analyzed_at`. Storage keys, hashes and text are never returned.

### POST `/resumes` → 201

`multipart/form-data` with one `file` field (PDF, DOCX or TXT, up to `MAX_UPLOAD_BYTES`, default 5 MiB). The type is determined from the bytes, not the filename or `Content-Type`.

- Rejected and **not stored**: `415 unsupported_file_type`, `422` (`empty_file`, `invalid_document`, `content_mismatch`, `invalid_text_file`, `unsupported_or_encrypted_document`), `413 file_too_large` / `payload_too_large`.
- Accepted but not readable (stored with `status="failed"`, `failure_stage="extraction"`): `ocr_required` (scanned/image-only PDF), `encrypted_document`, `corrupt_document`, `empty_document`, `too_many_pages`, `document_too_long`.
- Success: `status="extracted"` with counts.

### GET `/resumes` → 200, GET `/resumes/{id}` → 200

List (newest first) and retrieve metadata.

### DELETE `/resumes/{id}` → 204

Deletes the resume, its analysis and the stored file.

### POST `/resumes/{id}/analyze` → 200

Body (optional): `{"allow_external_ai": false}`. Runs the configured AI provider and returns the analysis (same shape as `GET …/analysis`).

| Status | Code | Meaning |
| --- | --- | --- |
| 503 | `ai_unavailable` | no provider configured, or credentials rejected. Nothing else is affected |
| 403 | `ai_consent_required` | the provider is external and `allow_external_ai` was not `true`. Nothing was sent |
| 409 | `analysis_in_progress` | another analysis is running (a run stuck for 10+ minutes may be restarted) |
| 409 | `resume_not_extracted` / `file_missing` | text could not be extracted, or the stored file is gone |
| 502 | `invalid_ai_response` | the model did not return valid, schema-conforming JSON |
| 502 / 504 / 429 | `ai_provider_error` / `ai_timeout` / `ai_rate_limited` | provider failure, timeout (`AI_TIMEOUT_SECONDS`), or rate limit (with `Retry-After` when provided) |

Failures after the analysis has started are recorded on the resume (`status="failed"`, `failure_stage="analysis"`, `error_code`) and the call can simply be repeated. Re-analysing replaces the previous result.

### GET `/resumes/{id}/analysis` → 200

```json
{
  "resume_id": "…", "provider": "openai", "model": "…",
  "consent_external_ai": true, "input_truncated": false, "created_at": "…",
  "result": {
    "facts": { "full_name": "…", "email": "…", "phone": "…", "location": "…", "links": [],
               "summary_as_written": "…", "education": [], "work_experience": [],
               "technical_skills": [], "soft_skills": [], "tools_and_technologies": [],
               "projects": [], "certifications": [] },
    "assessment": { "ai_summary": "…", "strengths": [], "potential_skill_gaps": [] },
    "missing_information": ["phone", "certifications"],
    "unverified_items_removed": 0
  },
  "profile_suggestion": { "…": "same shape as the apply-to-profile request" },
  "suggestion_notes": ["An education entry without a degree was left out"]
}
```

- `result.facts` are extracted from the resume and verified against its text (unverifiable items are removed and counted in `unverified_items_removed`). `result.assessment` is **AI-generated opinion** and may be wrong. `missing_information` is computed by code.
- `profile_suggestion` is a starting point and has **not** been applied. Entries that would need invented data (for example an education entry without a degree) are left out and listed in `suggestion_notes`.
- `404 analysis_not_found` if the resume has not been analysed.

### POST `/resumes/{id}/apply-to-profile` → 200

Applies **only what you send**. Typically you take `profile_suggestion`, let the user edit or deselect parts, and post the result. Requires a completed analysis (`409 analysis_required` otherwise).

Body fields (all optional, but at least one must be present; unknown fields are rejected): `full_name`, `headline`, `career_objective`, `education`, `work_experience`, `skills`, `projects`, `certifications` (same item shapes and validation as `PUT /profile`), `mode` (`merge` default, or `replace`) and `overwrite_existing` (default `false`).

- **Lists, `merge`:** new items are appended after existing ones. Items already present are skipped (case-insensitive: skills by category and name, education by institution and degree, jobs by company, title and start date, projects by name, certifications by name and issuer). Existing items are never modified or removed.
- **Lists, `replace`:** the provided section replaces the existing one. Sections you do not send are untouched.
- **Scalars:** filled when empty or identical. When the profile already holds a different value it is kept and reported in `skipped`, unless `overwrite_existing` is `true`.
- Response: `{"applied": {"skills": 4, …}, "skipped": [{"field": "career_objective", "reason": "…"}], "profile": { … }}`.
