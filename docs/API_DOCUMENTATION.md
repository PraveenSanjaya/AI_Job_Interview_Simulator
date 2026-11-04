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

## Integrations (GitHub, portfolio, analysis)

All endpoints require a Bearer token and operate only on the caller's own data; another user's analysis behaves like a missing one (`404 analysis_not_found`). Design, SSRF controls and privacy are described in [INTEGRATIONS.md](INTEGRATIONS.md). The candidate profile is never modified by connecting a source.

### POST `/integrations/github` → 200

Body: `{"username": "octocat"}`. The value may be a username, `@username`, or a `github.com` profile URL. Connects, or refreshes/replaces, the caller's single GitHub source and returns the observed-fact snapshot:

```json
{"source_ref": "octocat", "fetched_at": "…",
 "snapshot": {"login": "octocat", "profile_url": "https://github.com/octocat", "bio": "…",
   "followers": 0, "public_repos_total": 8, "repos_listed": 8, "repos_truncated": false,
   "repositories": [{"name": "…", "url": "…", "description": "…", "primary_language": "…",
                      "topics": [], "stars": 0, "is_fork": false, "is_archived": false,
                      "pushed_at": "…", "readme_excerpt": "…", "readme_truncated": false}],
   "language_distribution": {"Python": 3}, "total_stars_own_repos": 0,
   "activity": {"own_repos_pushed_last_90_days": 1, "own_repos_pushed_last_365_days": 2,
                "most_recent_push": "…"},
   "readmes_fetched": 4, "readme_fetch_incomplete": false, "notice": "…"}}
```

Replacing a connection also deletes analyses derived from the previous one. A failed refresh keeps the existing connection.

| Status | Code | Meaning |
| --- | --- | --- |
| 422 | `invalid_github_username` | not a valid username or `github.com` URL (nothing was requested) |
| 422 | `github_not_a_user` | the account is an organization |
| 404 | `github_user_not_found` | nonexistent, deleted, suspended or private |
| 429 | `github_rate_limited` | GitHub's API limit; `Retry-After` is set when known |
| 502 | `github_unavailable` | GitHub unreachable, slow or returned an unexpected response |

### GET `/integrations/github` → 200, DELETE `/integrations/github` → 204

Return the stored snapshot / disconnect and delete the snapshot and analyses derived from it. `404 source_not_connected` if nothing is connected.

### POST `/integrations/portfolio` → 200

Body: `{"url": "https://jane.example/"}`. Fetches the page and a few relevant same-host pages (see INTEGRATIONS.md) and returns:

```json
{"source_ref": "https://jane.example/", "fetched_at": "…",
 "snapshot": {"requested_url": "…", "host": "jane.example",
   "pages": [{"url": "…", "title": "…", "description": "…", "headings": [],
              "text_excerpt": "…", "text_truncated": false,
              "external_links": [{"url": "…", "text": "GitHub"}]}],
   "skipped_pages": [{"url": "…", "reason": "disallowed by robots.txt"}],
   "robots_txt_checked": true, "fetched_at": "…", "notice": "…"}}
```

Text is what the site says (untrusted, not verified). Errors: `422 portfolio_url_rejected` (scheme, port, credentials, internal or non-public host/address, unsafe redirect target; no request is made for syntactic rejections) and `502` with `portfolio_timeout`, `portfolio_too_large`, `portfolio_unsupported_content_type`, `portfolio_http_error`, `portfolio_redirects` or `portfolio_unreachable`.

### GET `/integrations/portfolio` → 200, DELETE `/integrations/portfolio` → 204

As for GitHub.

### POST `/integrations/analysis` → 201

Body (all optional): `{"include": ["github", "portfolio"], "resume_id": "…", "allow_external_ai": false}`. `include` defaults to every connected source; `resume_id` adds the verified details of one of your analysed resumes for comparison; `allow_external_ai` is the explicit consent needed when the AI provider is external.

| Status | Code | Meaning |
| --- | --- | --- |
| 503 | `ai_unavailable` | no AI provider configured (connecting sources still works) |
| 403 | `ai_consent_required` | external provider and no explicit consent; nothing was sent |
| 409 | `no_sources_connected` | nothing to analyse |
| 404 | `source_not_connected` / `resume_not_found` | an explicitly requested source or resume is not yours / not connected |
| 409 | `resume_not_analyzed` | analyse the resume first |
| 502 / 504 / 429 | `invalid_ai_response` / `ai_timeout` / `ai_rate_limited` | AI failure; nothing is stored |

Response: `{"id", "created_at", "provider", "model", "consent_external_ai", "input_truncated", "github_source_id", "portfolio_source_id", "resume_id", "result", "profile_suggestion", "suggestion_notes"}` where

* `result.facts`: **computed by code**: `sources_used`, `github` (login, language distribution, notable repositories, activity count), `portfolio` (host and pages), `consistency` (CV skills with or without a literal match in the public sources).
* `result.assessment`: **AI opinion**: `summary`, `strengths`, `potential_skill_gaps`, `project_assessments` (each with a source reference, technologies demonstrated, relevance, `complexity` of `basic|moderate|advanced|unclear` and its basis), `demonstrated_skills` (each with evidence references), `consistency_notes`, `caveats`. Claims the sources do not support are removed.
* `result.unverified_items_removed`: how many AI claims were removed.
* `profile_suggestion`: **not applied**; `suggestion_notes` lists anything left out.

Neither facts nor assessment measure programming ability; repository counts and activity are descriptive only.

### GET `/integrations/analysis` → 200, GET `/integrations/analysis/{id}` → 200, DELETE `/integrations/analysis/{id}` → 204

List (newest first, with `sources_used`), retrieve, and delete your analyses.

### POST `/integrations/analysis/{id}/apply-to-profile` → 200

Same request, merge rules and response as `POST /resumes/{id}/apply-to-profile`: only the fields and sections you send are applied, existing profile data is preserved unless you explicitly choose `mode="replace"` or `overwrite_existing`, and skipped items are reported.

## Jobs and matching

All endpoints require a Bearer token and operate only on the caller's own data; another user's job, analysis or match behaves like a missing one (`404 job_not_found` / `match_not_found`). Design, scoring rules and privacy are described in [JOB_MATCHING.md](JOB_MATCHING.md). Creating, updating, analysing and matching are rate limited per user (per process).

### POST `/jobs` → 201

Body: `{"title": "…", "company": "…" | null, "description": "…" | null, "source_url": "…" | null}`. Provide `description` (40 to 30,000 characters) **or** a public `source_url` (then the text is read from that page through the SSRF-safe fetcher). When both are given the text is used and the link is only stored. Saving parses the job (no AI). Response: `{id, title, company, description, source_url, status, has_analysis, created_at, updated_at}`.

| Status | Code | Meaning |
| --- | --- | --- |
| 422 | `validation_error` | neither text nor link, empty title, unknown field, text over 30,000 characters |
| 422 | `invalid_job_description` | text shorter than 40 characters |
| 422 | `job_url_rejected` | scheme, port, credentials, internal or non-public host or redirect target (no request is made for syntactic rejections) |
| 422 | `job_platform_not_supported` | the link is on a site that forbids automated access or needs a login (LinkedIn, Indeed, Glassdoor, …); paste the text instead |
| 422 | `job_text_not_found` | the page has no readable text (for example it needs JavaScript) |
| 502 | `portfolio_http_error` and other fetch codes | the page could not be retrieved; nothing is saved |

### GET `/jobs` → 200, GET `/jobs/{id}` → 200

List (newest first, without the text) and retrieve.

### PUT `/jobs/{id}` → 200

Changes only the fields sent (`title`, `company`, `description`, `source_url`; `company` and `source_url` may be `null` to clear them). Changing the title, text or link re-parses the job and discards an AI-enriched analysis; match reports already made are kept. A new `source_url` without `description` reads the text from the new link. `422` if the body is empty, the title or text would become empty, or the text is too short.

### DELETE `/jobs/{id}` → 204

Deletes the job, its analysis and all of its match reports.

### POST `/jobs/{id}/analyze` → 200

Body (all optional): `{"use_ai": false, "allow_external_ai": false}`. Re-runs the built-in parser; with `use_ai` the configured provider may add items the parser missed, each of which must quote the description. `allow_external_ai` is the explicit consent needed when the provider is external. On any error the previous analysis is kept.

| Status | Code | Meaning |
| --- | --- | --- |
| 503 | `ai_unavailable` | `use_ai` requested and no provider is configured |
| 403 | `ai_consent_required` | external provider and no explicit consent; nothing was sent |
| 502 / 504 / 429 | `invalid_ai_response` / `ai_timeout` / `ai_rate_limited` | AI failure |

### GET `/jobs/{id}/analysis` → 200

`{job_id, parser ("deterministic" | "deterministic+ai"), provider, model, consent_external_ai, input_truncated, created_at, result}` where `result.parsed` holds `technical_skills` (each with `name`, `kind`, `importance` `required|preferred|unspecified`, `importance_stated`, `source` `text|ai`, `quote`, `context_only`, `alternatives`), `soft_skills`, `certifications`, `domain_knowledge`, `education`, `experience`, `responsibilities`, `qualifications`, `seniority` (`level`, `basis` `stated|inferred_from_years|not_found`), `warnings`, and the derived lists `required_technical_skills`, `preferred_technical_skills`, `unspecified_importance_skills`, `company_context_skills`, `programming_languages`, `frameworks_and_tools`, `overall_min_years`. `result.unverified_items_removed` counts AI items that could not be verified. `404 analysis_not_found` if the job has none (for example its status is `failed`).

### POST `/jobs/{id}/match` → 201

Body (all optional): `{"resume_id": null, "include": ["resume","github","portfolio"], "weights": {"required_skills": 0.5}, "use_ai": false, "allow_external_ai": false}`.

* `resume_id`: an analysed resume of yours; omit for your newest analysed one.
* `include`: evidence sources besides the profile; omit for every available one. Naming one that is unavailable is an error.
* `weights`: per-request overrides of the scoring weights (`required_skills`, `preferred_skills`, `experience`, `education`, `project_relevance`, `technology_alignment`, `evidence_strength`; 0 to 100, at least one above 0).
* `use_ai`: also request plain-language advice (stored apart from the report).

| Status | Code | Meaning |
| --- | --- | --- |
| 404 | `job_not_found` / `resume_not_found` / `source_not_connected` | not yours or not available |
| 409 | `job_not_analyzed` | the job has no usable analysis; re-run analyze |
| 409 | `resume_not_analyzed` | the chosen (or an explicitly included) resume has no analysis |
| 422 | `invalid_scoring_weights` | unknown dimension, negative or out-of-range value, or all zero |
| 503 / 403 / 502 / 504 / 429 | AI codes as above | only with `use_ai`; no match is stored |

Response: `{id, job_id, created_at, overall_score (0-100 or null), confidence, scoring_config, evidence_used, report, ai_advice, ai_provider, ai_model, consent_external_ai}`.

* `report.score`: `score`, `status` (`scored` | `insufficient_evidence` | `insufficient_job_detail`), `confidence`, `formula`, `explanation`, and `dimensions[]` with `weight`, `effective_weight`, `value`, `points`, `applicable`.
* `report.required_skills` / `preferred_skills`: counts, `coverage`, and `items[]` with `status` (`supported` | `weakly_supported` | `not_found` | `unknown`), `credit`, `independent_evidence`, `evidence[]` (`{source: profile|resume|github|portfolio, kind, ref}`), `job_quote`, `satisfied_via`, `unchecked_sources`, `note`.
* Also `technical_strengths`, `experience`, `education`, `project_relevance`, `soft_skills`, `certifications`, `missing_requirements`, `weakly_supported_requirements`, `unverifiable_requirements`, `evidence_by_source`, `sources`, `improvement_areas`, `preparation_topics`, `caveats`, `disclaimer`.
* `ai_advice` (or `null`): AI-generated `summary`, `improvement_areas`, `learning_topics`, `project_ideas`, `interview_preparation`, `caveats`, `notice`, `unverified_items_removed`. It never alters `report`.

A report is a stored snapshot: it does not change when the profile, CV, GitHub, portfolio or the job change later.

### GET `/jobs/{id}/matches` → 200, GET `/jobs/{id}/matches/{match_id}` → 200

List (newest first: `id`, `job_id`, `created_at`, `overall_score`, `score_status`, `confidence`) and retrieve a stored match exactly as it was created.
