# Frontend

A single-page React application in `frontend/` that talks to the FastAPI backend (`/api/v1`). It adds no endpoints and invents no data: every number, score and piece of feedback on screen comes from a backend response.

## Stack

React 18, TypeScript (strict), Vite, Tailwind CSS 3, React Router 6, TanStack Query 5, Axios, React Hook Form + Zod, Recharts, Lucide icons. Tests: Vitest, Testing Library, MSW. Quality: ESLint (typescript-eslint, react-hooks, jsx-a11y) and Prettier.

## Running it

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

In development the browser calls `/api/v1/...` on the Vite server, which proxies to `VITE_DEV_API_TARGET` (default `http://localhost:8000`), so no CORS setup is needed. For a production build set `VITE_API_BASE_URL` to the API's public URL **and** let the backend allow the site's origin (`FRONTEND_URL`, optionally `CORS_ALLOWED_ORIGINS`, a JSON list), or serve both behind one reverse proxy. Only public configuration belongs in `VITE_*` variables: they are embedded in the bundle. No API keys or secrets are ever used by the frontend; AI providers are configured on the server only.

| Command | Purpose |
| --- | --- |
| `npm run dev` / `npm run build` / `npm run preview` | development server, production build (type-checks first), preview of the build |
| `npm run typecheck` | `tsc --noEmit` (strict, `noUncheckedIndexedAccess`) |
| `npm run lint` / `npm run format:check` | ESLint (including accessibility rules) and Prettier |
| `npm test` / `npm run coverage` | Vitest run, with optional V8 coverage |

## Structure

```
src/
  lib/           config, error normalisation (ApiError), token storage, axios client, formatters
  api/           types.ts (API shapes), endpoints.ts (one function per endpoint), queries.ts (TanStack Query hooks and keys)
  auth/          AuthProvider (session state), RequireAuth / GuestOnly route guards
  components/    ui.tsx (buttons, fields, cards, alerts, dialogs...), layout/AppShell, charts, MatchReportView, EvaluationFeedback
  pages/         one file (or two) per screen
  test/          setup, MSW server, fixtures, and the test suites
```

## Screens

| Route | Screen |
| --- | --- |
| `/login`, `/register` | sign in and sign up (Zod validation mirrors the API's password rules) |
| `/` | dashboard: counts, profile completeness, next steps, recent items, score chart, all from the API |
| `/profile` | whole-profile form (skills, work, education, projects, certifications) saved with `PUT /profile` |
| `/resumes` | upload (type and size checked first), status and failure reasons, analysis, **per-item approval** before anything reaches the profile |
| `/connections` | GitHub and portfolio: connect, refresh, disconnect (confirmed) |
| `/jobs`, `/jobs/new`, `/jobs/:id` | job list, add (paste text or link), edit, delete (confirmed), requirements by importance, optional AI enrichment, match reports and history |
| `/interviews`, `/interviews/new` | history with progress chart, and configuration (types, difficulty, length, job, follow-ups, AI consent) |
| `/interviews/:id` | the interview: start/resume, question, answer form, skip (confirmed), follow-ups, per-answer feedback, finish early (confirmed), cancel (confirmed) |
| `/interviews/:id/report` | the stored report |

## Authentication and session handling

* `lib/http.ts` is the only place that talks HTTP. It sends the bearer access token, normalises every failure into an `ApiError` (`status`, `code`, `message`, `requestId`, `retryAfter`, field `details`) and turns 401s on non-auth calls into one **single-flight refresh** (refresh tokens are single-use, so concurrent 401s must share one refresh) followed by one retry of the original request. If the refresh fails the session is cleared and the app returns to the login page with a "Your session expired" notice.
* The access token lives in memory only. The refresh token is stored in `localStorage` so a reload keeps you signed in. **Trade-off:** any script running on the page could read it. Mitigations: the app renders all backend text as plain text (React escaping, never `dangerouslySetInnerHTML`) and loads no third-party scripts; refresh-token rotation with family revocation limits what a stolen token is worth. Moving to an httpOnly cookie would need backend support (and CSRF protection) and is not done.
* `AuthProvider` restores a session on load (refresh, then `GET /auth/me`), exposes `login`, `register` (which signs in afterwards) and `logout` (revokes the session on the server, and always clears local state, even if the server is unreachable). Route guards redirect signed-out visitors to `/login`, remembering where they were going.
* Ownership and validation are the backend's job and are respected, not duplicated: another user's job or interview simply 404s and is shown as an error. Client-side validation only provides early, friendly feedback.

## Honesty rules the UI follows

* **No fabricated results.** A missing evaluation is shown as "No evaluation for this answer" with the reason; scores appear only when the backend returned them. An unscored report says "Not scored" and why. A missing source is "not found/not available", not "you lack this skill".
* **AI is optional and labelled.** Every AI-produced block (analysis opinion, match advice, interview feedback) carries the server's notice and is visually separate from computed facts. Features that need AI explain what happens without it (`ai_unavailable` and `ai_consent_required` are translated into plain language).
* **Consent is explicit.** Consent checkboxes are off by default, appear only when AI is requested, and their value is sent as `allow_external_ai`.
* **Dashboard numbers are real.** Empty accounts show zeros; a failing source shows a dash and a warning, never a made-up figure.
* **Destructive actions are confirmed** (delete resume/job, disconnect source, skip a question, finish early, cancel interview) with a dialog that focuses "Cancel" and closes on Escape.

## Accessibility and responsiveness

Labelled form controls with `aria-invalid`/`aria-describedby` errors, a skip-to-content link, landmark regions, keyboard-operable dialogs, status/alert roles for messages, `aria-label`led progress bars, chart data duplicated in a visually hidden table, and reduced-motion support. Layouts use Tailwind breakpoints (sidebar on large screens, collapsible menu on small ones, stacked cards on phones). ESLint's `jsx-a11y` rules pass.

## Testing

107 tests in 11 files (Vitest + Testing Library + MSW): authentication flows and the HTTP client (refresh single-flight, expiry, error mapping), each screen (loading, empty, error and success states, validation, confirmations, request bodies), the interview interactions (follow-ups, skip, unavailable/failed evaluations, injection notice, conflicts) and **four end-to-end journeys** that drive the whole app against a stateful in-memory API (sign-up through an AI interview and report; the same with no AI; session expiry; session restore).

Honest limits: the journeys run in jsdom, not a real browser (no Playwright/Cypress browser tests were added, as that needs a browser download); responsive layouts were checked only through Tailwind classes and a desktop screenshot of the built app, not on real devices; the multipart upload cannot complete under jsdom's XHR with MSW, so the two upload-UI tests stub the transport; the real upload and the whole API layer were instead checked once against a live backend (see the development log).

## Known limitations

* The refresh token is in `localStorage` (see above).
* No password reset, e-mail verification or profile photo screens: the backend does not offer them yet.
* Integration analysis (Connections page) analyses all connected sources with an optional CV; choosing a subset (`include`) is not exposed. The standalone resume-to-job comparison options (`resume_id`, `include`, custom weights) are also not exposed; matches use all available evidence with default weights.
* Integration analysis was tested only against a mocked API: no real AI provider was available, so real model output has not been seen in the UI.
* Recharts 2 is used (the 3.x migration is a separate task). Pages load on demand (route-level code splitting with a loading and load-failure state); the largest chunk is the charting library (~398 kB, loaded only with pages that draw charts) and the Vite 500 kB warning no longer appears.
* Interview answers are plain text; voice is a later phase.
