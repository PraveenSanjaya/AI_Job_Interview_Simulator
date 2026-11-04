# Resume Processing, CV Analysis and Privacy

Resumes contain sensitive personal data. This document describes how they are handled, what is stored, how long, and what the security controls are. API details are in [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

## Pipeline

```text
upload ──► validate (bytes, size, type) ──► store (server-generated key) ──► extract text
                                                                                  │
   profile ◄── user reviews/edits ◄── suggestion ◄── verify facts ◄── AI analysis ◄┘
```

| Status | Meaning |
| --- | --- |
| `uploaded` | Reserved initial state. |
| `extracting` | File stored; text extraction running (within the upload request). |
| `extracted` | Text could be read; ready for analysis. |
| `analyzing` | An analysis is running. |
| `completed` | An analysis result exists. |
| `failed` | `failure_stage` (`extraction` or `analysis`) and `error_code` say why. An analysis failure can be retried. |

## Upload security controls

- **Authentication required** on every resume route. All queries are scoped to the caller; another user's resume returns the same `404` as a missing one.
- **Type is decided from content.** The filename extension must be `.pdf`, `.docx` or `.txt` **and** the bytes must match (`%PDF-` header, a valid ZIP containing `word/document.xml` for DOCX, decodable text without NUL bytes for TXT). `Content-Type` headers are ignored. Legacy `.doc` and password-protected Office files (OLE containers) are rejected.
- **Size limits.** `MAX_UPLOAD_BYTES` (default 5 MiB) is enforced twice: by a middleware that rejects oversized bodies (by `Content-Length`, or by counting streamed bytes) before they are buffered, and again on the file itself. DOCX files are also checked for zip bombs (entry count and total expanded size).
- **Server-side identifiers.** Files are stored under `<owner id>/<random 128-bit id>`. The storage layer validates keys against a strict pattern and re-checks that the resolved path stays inside the storage root, so a key can never traverse directories. The client filename is reduced to a sanitised display name (no path parts, control characters or special characters) and is never used as a path.
- **Never executed.** Uploaded bytes are only parsed by PyMuPDF/python-docx or decoded as text. No route serves stored files, and the storage root is not part of any static mount.
- **No internal details in responses.** Storage keys, file hashes and raw text are never returned. Error messages never quote document content.
- **Rate limiting** per user for uploads and analyses (in-memory, per process).

### Extraction outcomes

| Situation | Result |
| --- | --- |
| Valid text document | `status=extracted` plus page, character and word counts |
| Image-only/scanned PDF | stored, `status=failed`, `error_code=ocr_required` (OCR is not implemented; nothing is guessed) |
| Password-protected PDF | stored, `failed`, `encrypted_document` |
| Corrupt, empty, too many pages (> 50), or too long (> 200,000 characters) | `corrupt_document`, `empty_document`, `too_many_pages`, `document_too_long` |
| Wrong type, mismatched extension, binary "text", zip bomb, empty file | rejected with 4xx and **not stored** |

## AI analysis

AI is **optional**. With `AI_PROVIDER=none` (default) upload, extraction, listing, deletion and manual profile editing all work; analysis returns `503 ai_unavailable`.

- **Provider abstraction.** `LLMProvider` is a small protocol; `OpenAICompatibleProvider` implements it over `httpx` for the OpenAI API or any OpenAI-compatible server. Model name and base URL come from settings (`OPENAI_MODEL`, `OPENAI_BASE_URL`); no default model is assumed. Automated tests use scripted fake providers and mocked HTTP; no credentials or network are needed.
- **Consent.** A provider counts as *external* unless its base URL is `localhost`/`127.0.0.1`/`::1`. Sending a resume to an external provider requires `allow_external_ai: true` in that analysis request; otherwise `403 ai_consent_required` and nothing is sent. The decision is stored with the analysis (`consent_external_ai`).
- **Facts vs. opinions.** The result has `facts` (taken from the resume) and `assessment` (the model's opinion: summary, strengths, possible gaps). They are never mixed.
- **No fabrication.** The model is instructed to use `null`/`[]` for missing data. In addition, every checkable fact (name, email, phone, location, links, employers, institutions, skills, certifications, projects, the verbatim summary) must appear in the resume text, otherwise it is **removed and counted** in `unverified_items_removed`. `missing_information` is computed by code from what was actually found.
- **Structured output.** Replies are parsed as JSON and validated with Pydantic. Invalid JSON, wrong types or truncated generations produce `502 invalid_ai_response`; provider timeouts, rate limits and rejected credentials produce `504`, `429` and `503`. A failed analysis is recorded on the resume and can be retried.
- **Prompt-injection defences.** The resume is untrusted. It is sent only in the user message, between a random per-request boundary the document cannot predict. The fixed system prompt states that the content is data and that embedded instructions must be ignored. The reply cannot trigger any action: it is only parsed and validated, and unverifiable claims are dropped. Injection resistance of a real model is a probabilistic property that these tests cannot prove (they verify our handling, using scripted fakes); users review everything before it reaches their profile.
- **Input limit.** At most `AI_MAX_INPUT_CHARS` (default 30,000) characters are sent; truncation is recorded (`input_truncated`).

## Profile integration

Nothing is applied automatically. The analysis includes a `profile_suggestion` in the shape of the apply request. The user can edit or deselect parts and send back only what they approve to `POST /resumes/{id}/apply-to-profile`. Existing profile data is preserved: lists are merged without duplicates, scalars that already differ are kept (and reported as skipped) unless `overwrite_existing` is set, and `mode="replace"` is an explicit per-section choice. See the API documentation for details.

## What is stored, and for how long

| Data | Where | Retention |
| --- | --- | --- |
| Original file | storage backend (`LOCAL_STORAGE_PATH`) | until the user deletes the resume |
| Metadata (display name, format, size, hash, status, counts) | `resumes` table | until the user deletes the resume |
| Extracted text | **not stored** (re-extracted from the file when needed) | n/a |
| Analysis result (facts and assessment, JSON) | `resume_analyses` table | until the resume is deleted or re-analysed (replaced) |
| Consent record | `resume_analyses.consent_external_ai` | with the analysis |
| Logs | stdout | contain no resume text, filenames, emails or phone numbers |

### Deletion behaviour

- `DELETE /resumes/{id}` removes the database rows (resume and analysis, by cascade) and then deletes the stored file. If the file deletion fails after the database commit, the failure is logged by storage key (not filename) and the file is orphaned; an orphan sweep is not implemented yet.
- If the database write fails during upload, the freshly stored file is removed again.
- Deleting a **user** removes their rows by database cascade, but this does **not** delete stored files, because no account-deletion flow exists yet. Whoever implements account deletion must delete each resume's stored file (via the service) first. This is a known gap.
- Backups, if any, are outside the application's control.
- The AI provider's own retention of submitted text is governed by that provider's terms; this is why external processing requires explicit consent per request.

### Logging policy

Never logged: resume text, extracted facts, contact details, filenames, prompts, provider responses, API keys. Library debug logging that prints SQL parameters or HTTP details (`aiosqlite`, `asyncpg`, `httpx`, `httpcore`, `multipart`) is capped at WARNING even when `LOG_LEVEL=DEBUG`. Tests assert these properties.

## Known limitations

- **No OCR.** Scanned PDFs are reported as `ocr_required`, not processed.
- **Parsing runs in the API process.** PDF/DOCX parsers handle untrusted input; limits on size, pages and expanded size reduce risk, but a hardened deployment should parse in a sandboxed worker process.
- **No malware scanning** of uploads. Files are never executed, but they are stored as received.
- **Synchronous analysis.** The request waits for the provider (bounded by `AI_TIMEOUT_SECONDS`). A background worker can replace this later; the status model already supports it, and a stuck `analyzing` state is recoverable after 10 minutes.
- **Local storage only.** The S3 adapter is a later phase; `STORAGE_BACKEND=s3` is rejected at startup rather than silently ignored.
- **LangChain/LangSmith are not used yet.** The provider layer is a thin `httpx` client so it adds no dependency; tracing can be added later without changing callers.
- **Rate limiting** is per process (see the API documentation).
- **PostgreSQL** behaviour of the new tables has not been verified (SQLite only); see [TESTING.md](TESTING.md).
