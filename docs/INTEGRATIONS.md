# GitHub and Portfolio Integrations

Candidates can connect a public GitHub profile and a public portfolio website. The server stores what those sources say (**observed facts**), can ask an AI provider for an assessment (**opinion**), and lets the candidate decide what, if anything, to copy into their profile. API details are in [API_DOCUMENTATION.md](API_DOCUMENTATION.md); resume handling is in [RESUME_PROCESSING.md](RESUME_PROCESSING.md).

## Principles

1. **Public data only, no credentials.** GitHub is read through the official REST API without any login or OAuth permission. A server-side `GITHUB_TOKEN` is optional and only raises the rate limit for the same public reads (it is never sent to anyone but `api.github.com`, never returned, never logged). Private repositories are never accessed.
2. **Facts and opinions are separate.** Stored snapshots and the `facts` part of an analysis are computed by code from source data. The `assessment` part is AI opinion, and every checkable claim in it is verified against the sources.
3. **Nothing is applied automatically.** Source data never touches the candidate's confirmed profile. The user reviews a suggestion and applies only what they approve.
4. **Source content is untrusted.** Bios, descriptions, READMEs and web pages are third-party text. They are stored as data, delivered to the AI only as delimited data, and can never change server behaviour.

## GitHub

`POST /integrations/github` takes a username, `@username` or `github.com` URL. The username is validated against GitHub's rules before any request is made (and again before it is placed in a URL path).

Collected, all from `api.github.com`:

| Data | Source | Notes |
| --- | --- | --- |
| Profile | `GET /users/{login}` | name, bio, location, blog, followers, creation date. Organizations are rejected |
| Repositories | `GET /users/{login}/repos` | up to `GITHUB_MAX_REPOS` (100) public repos owned by the user, most recently pushed first |
| READMEs | `GET /repos/{login}/{repo}/readme` | only for the `GITHUB_README_REPOS` (5) most-starred own, non-archived repos; at most 40 KB each, 3,000 characters kept |

Derived by arithmetic only:

* **Language distribution:** the number of the user's own (non-fork) repositories per GitHub primary-language label. It is not lines of code.
* **Activity:** how many own repositories were pushed in the last 90 / 365 days, and the most recent push. GitHub's REST API offers no reliable contribution graph or commit counts, so none are reported and none are estimated.
* **Stars:** summed over own repositories only (forks excluded).

Honesty rules: forks are listed but flagged and excluded from "own work"; the snapshot carries a notice that these counts are not a measure of programming ability; `repos_truncated` says when the account has more repositories than were read; `readme_fetch_incomplete` says when a rate limit cut README collection short (the rest of the snapshot is still returned).

Errors: `422 invalid_github_username`, `404 github_user_not_found` (nonexistent, deleted, suspended, renamed or private are indistinguishable), `422 github_not_a_user`, `429 github_rate_limited` (with `Retry-After`; unauthenticated GitHub allows about 60 requests per hour per server IP, and one connection uses at most about 7 requests), `502 github_unavailable`. A failed refresh never removes an existing connection.

## Portfolio websites

`POST /integrations/portfolio` takes a public `http(s)` address. The server fetches that page and at most `PORTFOLIO_MAX_PAGES - 1` more pages **on the same host**, chosen by simple keyword relevance of the link path (`project`, `portfolio`, `about`, `experience`, …). It is deliberately not a general crawler:

* extra pages are fetched only if `robots.txt` allows it (a missing file allows everything; an unreadable one stops extra crawling);
* PDFs, images, archives, scripts and other non-page files are skipped;
* links to other hosts are recorded as outbound links but never followed;
* the page you supplied is fetched on your instruction even if `robots.txt` disallows it; this is a single request made on the candidate's behalf, not automated discovery.

Pages are parsed as static HTML (title, description, headings, visible text, links). Scripts, styles, `noscript`, iframes and embedded objects are discarded; JavaScript is never executed, so single-page apps that render in the browser yield little text. Every page keeps its source URL.

### SSRF protection

The threat is a user submitting a URL that makes the server fetch something internal (localhost services, private networks, cloud metadata) and reading it back. Controls, all in `app/integrations/portfolio/safe_fetch.py`:

| Control | Behaviour |
| --- | --- |
| Scheme / port / credentials | only `http` and `https`, only ports 80 and 443, no `user:pass@` |
| Host syntax | rejects `localhost`, single-label names, `.local/.internal/.lan/…` suffixes, IP literals that are not public, numeric spellings such as `2130706433`, `0x7f.1`, `0177.0.0.1`, IPv6 zone ids, malformed labels |
| Address classes | blocks loopback, private (RFC 1918), link-local (incl. `169.254.169.254` and `fd00:ec2::254`), carrier-grade NAT (incl. `100.100.100.200`), multicast, reserved, unspecified, IPv4-mapped IPv6 of any of these, and IPv6 forms that embed IPv4 (NAT64, 6to4, Teredo, IPv4-compatible) |
| DNS | the name is resolved by the server and **every** returned address must be public; one private address among several rejects the host |
| DNS rebinding | the request is sent to the **validated IP address**, with the original name as `Host` header and TLS SNI/certificate name. The name is never resolved a second time between check and use |
| Redirects | followed manually (max 3); each hop repeats all checks; `https`→`http` downgrades and backslash-tricks are refused |
| Limits | per-request timeout (`INTEGRATION_TIMEOUT_SECONDS`, default 10), response cap (`INTEGRATION_MAX_RESPONSE_BYTES`, default 1 MB) counted **after decompression**, content types limited to HTML, XHTML and plain text |
| Environment | proxy variables (`HTTP(S)_PROXY`) and `.netrc` are ignored so nothing can bypass the checks; no cookies are kept; requests identify themselves with a descriptive `User-Agent` |
| Errors | messages never echo resolved addresses or fetched content |

Verified with unit tests (mocked DNS and HTTP), end-to-end API tests, and a manual run on a real server: seven internal-target URLs were rejected with `422`, and a real HTTPS fetch of `https://example.com/` succeeded through the pinned-IP connection.

Known limits: the checks run in the application, not in the network. For defence in depth in production, also block egress to private ranges and the metadata service at the firewall / security-group level and run the API without cloud credentials reachable from the instance metadata service (IMDSv2 with hop limit 1 on AWS). Server-side requests also reveal the server's IP address to the portfolio host.

Errors: `422 portfolio_url_rejected`, `502 portfolio_fetch_failed` family (`portfolio_timeout`, `portfolio_too_large`, `portfolio_unsupported_content_type`, `portfolio_http_error`, `portfolio_redirects`, `portfolio_unreachable`).

## AI analysis

`POST /integrations/analysis` analyses the connected sources (all, or the `include` list) and optionally an analysed resume (`resume_id`) so the CV can be compared with public evidence. It reuses the same provider abstraction as CV analysis, so a missing provider is `503 ai_unavailable` and the rest of the application is unaffected.

**Consent.** If the provider is external (anything other than a `localhost` endpoint), `allow_external_ai: true` is required in the request; otherwise `403 ai_consent_required` is returned and nothing leaves the server. The choice is stored with the analysis. Order of checks: provider available → sources exist → resume owned and analysed → consent.

**What is computed by code (`result.facts`):** sources used, GitHub login / language distribution / notable repositories (name, URL, description, language, topics, stars), portfolio pages, and the **CV consistency** list: which CV skills have a literal match in the public sources and which do not, with the caveat that absence is not evidence of absence.

**What the AI contributes (`result.assessment`):** a summary, strengths, possible gaps, per-project assessments (technologies demonstrated, what it shows, relevance to the candidate's stated preferred roles, complexity with its basis), demonstrated skills with evidence references, consistency observations and caveats.

**How AI claims are checked before anything is stored:**

* A project or skill must cite a source that exists (a repository name from the snapshot, or an exact page URL). References to unknown sources, forks, or a resume are dropped.
* **A repository name is never evidence.** A technology or skill counts only if it appears in the cited item's descriptive text (description, topics, language label, README excerpt, or page text). `kubernetes-playground` with no description demonstrates nothing.
* Project names for repositories are replaced by the canonical repository name; portfolio project names must appear on the cited page.
* `complexity` becomes `unclear` unless the item has substantial text (200+ characters) and a stated basis.
* The number of removed claims is returned as `unverified_items_removed`.

Prompt-injection defences are the same as for CV analysis: a fixed system prompt declares all source blocks untrusted; each source is wrapped in its own random boundary; the reply is only parsed as JSON and validated; it cannot trigger any action. Whether a real model resists injection is not something these tests can prove; they verify our handling using scripted fake providers.

Output validation failures (`502 invalid_ai_response`), timeouts (`504`), provider rate limits (`429`) and unavailable credentials (`503`) leave nothing stored.

## Profile integration

Analyses include a `profile_suggestion` (same shape as the apply request): the candidate's own described repositories as projects (exactly as GitHub describes them), the languages those repositories are labelled with, and skills the analysis could verify. It is **not applied**. `POST /integrations/analysis/{id}/apply-to-profile` applies only what the user sends, with the same protections as resume application: lists are merged without duplicates (or replaced only when `mode="replace"` is requested), and a scalar that already holds a different value is kept unless `overwrite_existing` is true.

## What is stored, and for how long

| Data | Stored | Removed when |
| --- | --- | --- |
| GitHub snapshot (public profile data, repo metadata, README excerpts) | `integration_sources`, one per user | the user disconnects, reconnects (replaces it), or the account is deleted |
| Portfolio snapshot (page text excerpts, titles, links, source URLs) | `integration_sources`, one per user | same |
| Analyses (computed facts + AI assessment + consent record) | `integration_analyses` | the user deletes the analysis, **or** any source/resume it was derived from is deleted or replaced |

Reconnecting a source deliberately deletes analyses derived from the previous snapshot, because they describe data that no longer exists. Logs never contain snapshot content, page text, usernames beyond what the request path already shows, tokens or API keys. Library debug logging that could print request details is capped at WARNING.

## Known limitations

* **No OAuth.** Private repositories and the contribution graph are not available. Optional OAuth, if ever added, would be a separate, explicitly consented feature.
* **GitHub rate limits** are low without a token. With many users, set `GITHUB_TOKEN` (read-only, no scopes needed for public data) or add caching.
* **JavaScript-rendered portfolios** yield little text because no JavaScript is executed.
* **Language statistics** are repository counts by GitHub's primary-language label, not code volume, and forks are excluded.
* **Per-process rate limiting** applies to connect and analysis calls (see the API documentation).
* **Synchronous fetching:** connecting a portfolio waits for up to a few page fetches within the request. A background worker is a later option.
* **PostgreSQL** behaviour of the new tables (migration `0003`) is unverified; see [TESTING.md](TESTING.md).
