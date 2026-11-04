# Job Descriptions and Candidate Matching

Candidates save job descriptions, the server turns each one into a structured list of requirements, and a **match report** compares those requirements with everything the candidate has recorded. API details are in [API_DOCUMENTATION.md](API_DOCUMENTATION.md); the evidence sources are described in [RESUME_PROCESSING.md](RESUME_PROCESSING.md) and [INTEGRATIONS.md](INTEGRATIONS.md).

## Principles

1. **Deterministic first, AI optional.** Parsing and scoring are fixed rules. They work with no AI provider, no credentials and no network. AI can enrich the parse and write advice, but it can never change a score or a status.
2. **Say only what the text says.** Every extracted requirement quotes the sentence it came from. When a description does not say whether a skill is required, the report says "importance unclear" instead of guessing.
3. **Absence of evidence is not evidence of absence.** A skill with nothing on record is `not_found` ("no evidence found in the data on record"), and `unknown` when there is no candidate data at all. The report lists which sources were not available.
4. **Untrusted input.** A job description is third-party text. It is stored as data, parsed by code, and shown to an AI only as delimited data. Instructions inside it cannot change a score.
5. **History is preserved.** A match report is a snapshot; later edits to the profile, CV, GitHub, portfolio or job never alter it.
6. **No promises.** Reports carry a disclaimer; nothing predicts an interview or an offer.

## Saving a job

`POST /jobs` takes `title`, optional `company`, and either `description` (pasted text) or a public `source_url`.

| Rule | Behaviour |
| --- | --- |
| Text length | 40 to 30,000 characters after cleaning; control characters are removed |
| Link without text | the server fetches that one page through the same `SafeFetcher` as portfolio pages (scheme/port/credential checks, public addresses only, every DNS answer checked, pinned IP with SNI, validated redirects, size and type limits, no JavaScript) |
| Link with text | the text wins and the link is stored as a reference only; nothing is fetched |
| Restricted sites | LinkedIn, Indeed, Glassdoor, ZipRecruiter, Monster, Naukri, Facebook, Instagram, X/Twitter are **never fetched** (`job_platform_not_supported`), also when a redirect lands on them. The candidate pastes the text instead. A page with no readable text (for example a JavaScript-rendered job board) gives `job_text_not_found` |
| Ownership | every query is scoped by the authenticated user; another user's job is `404 job_not_found` |

Saving parses the job immediately (deterministically). `status` is `parsed` when a current analysis exists, `failed` if the parser raised unexpectedly (nothing from the text is logged), and `saved` only transiently. Editing the title, text or link re-parses and discards any AI-enriched analysis; existing match reports are kept. Deleting a job deletes its analysis and its match reports.

## Parsing

Implemented in `app/jobs/parser.py` with a small explicit vocabulary in `app/jobs/taxonomy.py` (languages, frameworks, libraries, tools, databases, cloud, concepts, soft skills, domains, certifications). It recognises what is literally written, with whole-word matching and spelling variants (`Postgres` is PostgreSQL, `k8s` is Kubernetes). It never infers one technology from another. Ordinary words and single letters are not matched in running text: `Go`, `R` and `C` are recognised only when a whole skills-list item equals them (or as `golang`, `RStudio`), and `Spark`, `React`, `Swift`, `REST` and `RAG` only in their unambiguous forms (`Apache Spark`, capitalised `React`, `Swift`, `REST`, `RAG`). A capitalised `React` at the start of a sentence can therefore still match.

| Extracted | How |
| --- | --- |
| Required / preferred skills | section headings (Requirements, Qualifications, Nice to have, Bonus…) and wording in the sentence ("required", "must", "preferred", "a plus") |
| Importance unclear | stated nowhere: reported as `unspecified` with a warning; never promoted to required |
| Company-context skills | mentioned only under "About us", benefits and similar: flagged `context_only` and **not scored** |
| Alternatives | "Python **or** Java" are linked; either one satisfies the requirement and they count once. A slash or "and" never links ("HTML/CSS") |
| Languages, frameworks and tools | derived views by skill kind |
| Experience | "N+ years" / "N-M years" phrases about experience; years tied to a technology are kept per technology |
| Education | degree level (associate, bachelor, master, doctorate, unspecified degree), field, "or equivalent experience" |
| Responsibilities, qualifications | the bullet or sentence as written (capped) |
| Soft skills, certifications, domains | vocabulary matches with the quoted sentence |
| Seniority | stated words in the title or opening lines (`basis: stated`), otherwise inferred from stated years only (`basis: inferred_from_years`, with a warning), otherwise `not_found` |

### Optional AI enrichment

`POST /jobs/{id}/analyze` with `use_ai=true` asks the provider for items the vocabulary missed. The result is merged into the deterministic parse only after checks:

* every item needs a `quote` that occurs in the description, and the item's name must occur in its own quote; failures are dropped and counted in `unverified_items_removed`;
* importance is **derived by code from where the quote sits** (section heading or cue words); the model's own importance claim is ignored, and it can only raise a skill the parser left unspecified;
* education, years of experience and seniority are never taken from the model;
* AI-added items are labelled `source: "ai"`.

The job text is sent as a delimited block with a random per-request boundary, the system prompt is fixed and declares the block untrusted. External providers require `allow_external_ai=true` (`403 ai_consent_required` otherwise, nothing sent). AI errors leave the previous analysis untouched.

## Matching

`POST /jobs/{id}/match` builds the candidate's evidence, runs the engine in `app/matching/engine.py`, stores the report, and (optionally) adds AI advice.

### Candidate evidence

| Source | Used for |
| --- | --- |
| Confirmed profile (including anything the candidate previously approved from CV or GitHub suggestions) | skills, projects, work history, education, certifications, stated experience level |
| Analysed resume (selected, or the newest analysed one) | skills, projects, roles, certifications, degrees; dates only when the profile has no work history |
| GitHub snapshot | own (non-fork) repositories: description, topics, primary language, README excerpt, bio |
| Portfolio snapshot | page title, headings and text |

Evidence has two strengths. **Demonstrated**: the skill appears in the description of a concrete project, job, repository or page. **Declared**: it is only listed (skills list, bio, certification title). A repository's **name is never evidence** (`kubernetes-playground` shows nothing), and forks are ignored.

**Avoiding double counting.** The same project often exists in the profile, the CV, GitHub and the portfolio. Items are merged by normalised project name; a portfolio page that names a known project is folded into it. A skill listed in both the profile and the CV is one declaration. Independent-evidence counts use the merged items, and every contributing source is still listed as a reference. Work periods are merged before years are counted, so overlapping jobs count once, and CV dates are used only when the profile has no work history. Name-based merging is a heuristic: two different projects sharing a name would be merged, and one project named differently in two places would be counted twice.

### Requirement status

| Status | Meaning | Credit |
| --- | --- | --- |
| `supported` | demonstrated in at least one concrete item | 1.0 |
| `weakly_supported` | only declared | `declared_only_credit` (default 0.5) |
| `not_found` | nothing found in the sources that exist; the sources that were not available are listed on the item | 0 |
| `unknown` | there is no candidate evidence at all, so nothing can be judged | 0 (score withheld) |

### Dimensions and default weights

| Dimension | Default weight | Value |
| --- | --- | --- |
| Required skills | 0.40 | mean credit over required skills (alternatives count once) |
| Preferred skills | 0.10 | the same over preferred skills. Skills with unclear importance are scored here by default (`unspecified_importance: "as_preferred"`) or left out (`"ignore"`) |
| Experience | 0.15 | candidate years of recorded work ÷ the job's overall years requirement, capped at 1 |
| Education | 0.05 | 1 if the candidate's highest recognised degree meets the required level; otherwise candidate rank ÷ required rank (at least 0.5 when the job accepts equivalent experience) |
| Project relevance | 0.10 | best single project's share of the job's technologies, where 50% counts as fully relevant |
| Technology alignment | 0.10 | mean credit over the job's languages and frameworks |
| Evidence strength | 0.10 | over matched skills: listed only 0.4, one independent piece of evidence 0.7, two or more 1.0 |

The dimensions overlap by design (a missing language also lowers technology alignment); the weights are adjustable. Soft skills and certifications are reported next to the score but **not scored**, because they cannot be verified from records.

**Not assessed dimensions.** A dimension the job does not ask for (no years or degree stated) or the candidate has not recorded (no work history, no education, no projects) is *left out* and the remaining weights are rescaled to 100 points, so missing data is neither rewarded nor punished. The report names what was left out. Technology-specific years ("3+ years of Python") are listed but not computed.

```
score = round( 100 x sum( effective_weight_i x value_i ) )
effective_weight_i = weight_i / (sum of weights of the assessed dimensions)
```

`report.score.explanation` spells out the arithmetic for each match, e.g. `77/100 = Required skills 43.8 + Preferred skills 0.0 + Project relevance 12.5 + …`.

**Score status and confidence.** `scored`, `insufficient_evidence` (no candidate data at all: score `null`), or `insufficient_job_detail` (nothing comparable in the job: score `null`). Confidence is `low`, `medium` or `high` from how many evidence sources have content (1, 2, 3 or more) and is lowered when few dimensions could be assessed.

### Configurable weights

Defaults come from the code, can be overridden for the whole server with the `MATCH_WEIGHTS` environment variable (JSON, validated at startup), and again per request in `weights`. Unknown names, negative values and all-zero sets are rejected (`422 invalid_scoring_weights`). The configuration actually used is stored with every match.

### The report

`report` contains: the score breakdown; `required_skills` and `preferred_skills` (each item with status, credit, independent-evidence count, evidence references `{source, kind, ref}`, the job's quote and a plain-language note); `technical_strengths`; `experience` and `education` alignment; `project_relevance` (with the relevant projects and the technologies they cover); `missing_requirements`, `weakly_supported_requirements`, `unverifiable_requirements`; `soft_skills` and `certifications`; `evidence_by_source` (`profile`, `resume`, `github`, `portfolio`); `sources` (what was used and why anything was unavailable); `improvement_areas` and `preparation_topics` (rule-based templates); `caveats`; and the disclaimer.

### Stored records

A `job_matches` row holds the score, confidence, the scoring configuration, `evidence_used` and the full report. `evidence_used` identifies the exact inputs (profile `updated_at` and item counts, resume and analysis ids and dates, GitHub and portfolio source ids and fetch times, the job's id, title, text digest and analysis id) **without copying personal text**. There are no foreign keys to candidate data, so deleting a resume or reconnecting GitHub leaves old reports intact. Only deleting the job (or the user) deletes its matches.

## AI advice

`use_ai=true` on `POST /jobs/{id}/match` asks the provider for a plain-language summary, improvement areas, learning topics, project ideas and interview preparation. It is stored in `ai_advice`, separate from the report.

**What is sent** (only on request, and to an external provider only with `allow_external_ai=true`): the job title and company, requirement names with importance and status, the computed scores, experience and education status, the candidate's stated experience level and preferred roles, and up to ten duties quoted from the job text. **Not sent:** the candidate's name or contact details, employers, project or repository names, URLs, or any profile/CV text.

**Safeguards on the reply.** The JSON is validated. References to requirements must match the report (unknown names are dropped; a project idea tied to nothing is dropped). Any text that promises an outcome ("guarantee", "you will get the job") or states a score that differs from the computed one is dropped. The advice cannot alter the report or the profile (the schema has no such fields), and it is labelled AI-generated with a notice that the computed report is authoritative. Failures (`503`, `403`, `502`, `504`, `429`) store no match.

## Known limitations

* The vocabulary is English-only and finite; technologies it does not know are invisible to the parser unless AI enrichment finds them (and quotes them).
* Years are computed from recorded work only, not per technology, and not from education or projects.
* Project de-duplication is name-based.
* Evidence is self-published; a high score means the candidate's records cover the posting, not that the candidate is skilled.
* Importance depends on the description's own structure; unstructured text yields "importance unclear" for many skills.
* Parsing and matching run inside the request; a worker would be needed for very large volumes.
* Per-process rate limiting applies to job creation, analysis and matching.
* PostgreSQL behaviour of migration `0004` is unverified (see [TESTING.md](TESTING.md)).
