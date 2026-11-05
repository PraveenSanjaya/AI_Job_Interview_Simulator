# Design: moving the refresh token out of `localStorage`

**Status: proposal, not implemented.** Implementing it changes authentication for every
client, so it should be reviewed first.

## 1. Current state

* `POST /auth/login` and `/auth/refresh` return `{access_token, refresh_token}` in the JSON body.
* The frontend keeps both in `localStorage` (`src/lib/tokens.ts`) and sends the access token in
  `Authorization: Bearer`.
* Access tokens last 30 minutes and are bound to a login session (`sid`), so they end with it.
  Refresh tokens last 7 days, are single-use, stored only as SHA-256 digests, and a replayed
  token revokes the whole session family.

## 2. Threat

Anything running JavaScript on the page can read `localStorage`. A single cross-site-scripting
(XSS) bug, or a compromised npm dependency, lets an attacker copy the refresh token and use it
**from their own machine for up to 7 days**, long after the page is closed.

What reduces this today: the frontend contains no HTML-injection sinks (a search for
`dangerouslySetInnerHTML`, `innerHTML`, `eval` and `document.write` in `src/` finds none outside
tests); React escapes output by default; rotation plus family revocation means a stolen token is
noticed if the victim also refreshes. What it does not do: stop the first use.

## 3. Proposed design

### 3.1 Where each token lives

| Token | Storage | Reachable by page JavaScript? |
| --- | --- | --- |
| Refresh token | `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` cookie named `__Host-`-style where possible | **No** |
| Access token | JavaScript memory only (a module variable), never `localStorage`/`sessionStorage` | Yes, but short-lived and lost on reload |
| CSRF token | non-HttpOnly cookie `csrf_token` (`SameSite=Strict`, `Secure`), echoed in a header | Yes (by design) |

After a reload there is no access token in memory; the app calls `POST /auth/refresh`, the browser
attaches the cookie, and a new access token is returned. That already matches how
`AuthContext.restore()` works, minus reading the token from storage.

An XSS attacker can still act *as the user while the page is open* (the access token is in memory
and requests can be made from the page). What disappears is the ability to take a long-lived
credential away and use it later from elsewhere.

### 3.2 Cookie attributes

* `HttpOnly`: hidden from JavaScript.
* `Secure`: HTTPS only. Not set when `APP_ENV=development` (plain `http://localhost`), set otherwise.
  Browsers treat `localhost` as a secure context for some features but still require `Secure`
  cookies to arrive over HTTPS in many versions, so the development flag is explicit.
* `SameSite=Strict`: the cookie is never sent on cross-site requests. The refresh endpoint is only
  called by our own page, so Strict costs nothing.
* `Path=/api/v1/auth`: the cookie is sent only to the authentication endpoints, not to every API call.
* `Max-Age` equal to the refresh-token lifetime. Cleared (`Max-Age=0`) on logout, on detected reuse,
  on account deletion and when refresh fails.
* `Domain` is left unset (host-only cookie), which prevents sibling subdomains from receiving it.

### 3.3 CSRF protection

Cookies are sent automatically, so a hostile site could try to make the user's browser call
`/auth/refresh` or `/auth/logout`. Defence in depth, all cheap:

1. `SameSite=Strict` (primary defence; blocks cross-site sending in current browsers).
2. **Origin check**: for state-changing requests that rely on the cookie, require an `Origin` (or
   `Referer`) header equal to one of `FRONTEND_URL` / `CORS_ALLOWED_ORIGINS`; otherwise `403`.
3. **Double-submit token**: login and refresh also set a random `csrf_token` cookie; the client must
   send it back in an `X-CSRF-Token` header and the server compares the two in constant time. A
   hostile site can neither read the cookie nor set the header.
4. The refresh endpoint accepts only `Content-Type: application/json` with that custom header, which
   a plain cross-site form post cannot produce.

Endpoints that use only the `Authorization` header (everything except refresh/logout) are not
CSRF-prone, because a browser does not attach that header by itself.

### 3.4 Rotation, logout, account deletion

* Rotation is unchanged: each refresh revokes the presented token and sets a new cookie.
* `POST /auth/logout` revokes the family (as now), reads the token from the cookie, and clears the
  cookie. The access token ends immediately through `sid`.
* `POST /auth/delete-account` clears the cookie in the same response (the session no longer exists).
* A refresh failure clears the cookie so a dead credential is not retried.

### 3.5 CORS and credentials

Today `allow_credentials=False` and `Access-Control-Allow-Origin` lists the configured origins. With
cookies:

* `allow_credentials=True` only together with an **explicit** origin list (never `*`); the existing
  `FRONTEND_URL`/`CORS_ALLOWED_ORIGINS` lists are already explicit.
* The frontend sets `withCredentials: true` on the axios instance (or only on the auth calls).
* `allow_headers` gains `X-CSRF-Token`.

### 3.6 Same-site deployment requirement (decision needed)

`SameSite=Strict` cookies are sent only when the frontend and the API are the **same site** (same
registrable domain), for example `app.example.com` and `api.example.com`, or one origin behind a
reverse proxy. If they are on unrelated domains (for example `*.vercel.app` talking to `*.amazonaws.com`),
the browser treats the API as third-party and will not send the cookie; the design then does not
work, and the options are `SameSite=None; Secure` (weaker, and increasingly blocked) or serving the
API under the frontend's domain through a proxy. **This is a deployment decision that must be made
before implementing.**

In development the Vite proxy makes `/api` same-origin, so no change is needed there.

### 3.7 Compatibility and migration

1. Phase A (backend, non-breaking): additionally set the cookie and CSRF cookie on login/refresh and
   accept the refresh token from the cookie **or** the body. Existing clients keep working.
2. Phase B (frontend): stop storing the refresh token and stop sending it in the body; keep the access
   token in memory; restore the session by calling refresh.
3. Phase C (backend): stop returning `refresh_token` in the JSON body to browsers (keep a header or
   body option for non-browser API clients if any exist), and require the CSRF header.

Each phase is independently deployable and testable.

### 3.8 Tests to write with the implementation

Cookie flags per environment; refresh succeeds only with cookie + matching CSRF header + allowed
origin; fails without any of them; cookie cleared on logout/deletion/failed refresh; replay still
revokes the family; CORS credentials only for listed origins; frontend never writes a token to
storage; session restore after reload via the cookie; a real-browser check of `SameSite` behaviour
(cannot be proven in jsdom).

## 4. Trade-offs

* More moving parts (CSRF handling, cookie flags per environment, same-site hosting).
* Access token in memory means a reload costs one refresh call (negligible).
* Does not protect against XSS acting during an open session; the complementary measures are a strict
  `Content-Security-Policy` on the frontend host (no inline scripts, no third-party scripts), keeping
  dependencies minimal and audited, and no HTML injection sinks. A CSP for the static frontend is
  configured on the web host, not in this repository, and has not been written yet.

## 5. Recommendation

Adopt it, in the three phases above, once the hosting decision in 3.6 is made. Until then the
mitigations that exist today (no injection sinks, rotation with reuse detection, session-bound access
tokens that end on logout, 7-day maximum lifetime) remain the protection.
