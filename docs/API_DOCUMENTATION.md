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
