# Mock Interviews

Text-based mock interviews: configure, start, answer, receive follow-ups and evaluations, complete, read a report. API details are in [API_DOCUMENTATION.md](API_DOCUMENTATION.md); job data and matching are in [JOB_MATCHING.md](JOB_MATCHING.md).

## Principles

1. **Works without AI.** With no provider (the default) the curated question bank runs the interview and answers are saved with an honest `unavailable` evaluation. Nothing is invented.
2. **Deterministic scoring.** The AI only *judges individual answers* (per-dimension 0-10 with a rationale). Everything that turns those judgements into numbers is fixed, configurable code (`app/interview/scoring.py`). The report separates computed scores, AI-written feedback, and what could not be evaluated.
3. **Candidate answers are untrusted data.** They are delimited blocks with a random boundary in the prompt, never instructions. An answer that tries to instruct the evaluator is flagged `suspicious_instructions` and judged on substance only. Every AI reply is validated before it is stored.
4. **Privacy.** Only structured data (skills, project names/descriptions/technologies, job requirements and duties, topics to probe) and the current answer are sent to a provider. Not sent: name, e-mail, phone, employers, URLs, CV text. External providers need explicit consent (`allow_external_ai`); without it nothing is sent and the bank is used. Answers, prompts and replies are never logged.
5. **No outcome claims.** The report says it is practice feedback, not a predictor of hiring, and says nothing about personality, confidence or honesty.

## Interview types, difficulty, length

`hr`, `behavioral`, `technical`, `programming`, `project`, `system_design`, `job_specific` (needs a saved job). Several types can be combined; questions are shared evenly (remainder to the earlier types) and interleaved. Difficulty: `beginner`, `intermediate`, `advanced`. Length 1 to 30 main questions (at least one per type). Follow-ups do not count towards the length. Interviews work with or without a saved job.

## Session state machine

```
created ──start──▶ in_progress ──complete──▶ completed
   │  ╲                │  ▲  ╲
   │   ╲(72 h)         │  │   ╲(idle 120 min)
   │    ▼              │  │    ▼
   │  expired          │  └─start (resume)── interrupted ──complete──▶ completed
   └─cancel─▶ cancelled ◀─cancel─┘                       └─cancel─▶ cancelled
```

* The table is `app/interview/config.py::TRANSITIONS`; every move is **one conditional UPDATE** that names the allowed source states, so racing requests cannot both win and illegal moves return `409 invalid_interview_state`.
* `completed`, `cancelled` and `expired` are final. `interrupted` and `expired` are applied lazily when a session is read (idle and expiry limits are `INTERVIEW_IDLE_MINUTES`, `INTERVIEW_CREATED_EXPIRY_HOURS`). An interrupted interview keeps its questions and is resumed with `start`.
* A session stores its owner, types, difficulty, length, follow-up limit, mode and `ai_status`, a snapshot of the targeted job (the job itself is only a nullable reference, so deleting it does not break the session), the scoring rules used, a `version` counter, current index, timestamps, questions, answers, evaluations and the report. Every lookup is scoped to the owner (`404 interview_not_found` otherwise).

### Concurrency

Submitting an answer first bumps `version` with `UPDATE … WHERE version = :seen AND status = 'in_progress'`; of several simultaneous submissions based on the same state exactly one succeeds and the rest get `409 concurrent_submission` (or `not_current_question`). A unique constraint on `answers.question_id` is a second guard. Starting is the conditional transition above, so concurrent starts create questions once. Tests run these races on a file-backed SQLite database with independent connections; the PostgreSQL variants are skipped without `TEST_DATABASE_URL` (unverified).

## Questions

Questions are planned when the interview is **started**, never at creation.

* **Personalisation (AI mode).** Context = experience level, preferred roles, skills, up to five projects (profile, newest analysed CV, non-fork GitHub repositories with descriptions), the job's required/preferred skills and duties, the requirements the latest match report found weak or missing, and the study topics of the candidate's previous interview report. The prompt demands practical, scenario-based questions at the chosen difficulty, no definitions, no answers, and no assumed facts.
* **Validation.** Questions must be in a requested category, long enough, not near-duplicates (normalised equality or ≥80% word overlap) of earlier questions or each other; project questions must **name a real project from the supplied evidence** that appears in the question; job-specific questions need a job. Rejected ones are dropped and any shortfall is filled from the bank.
* **No repetition.** The user's 60 most recent questions across sessions are passed as "already asked" to the AI and excluded from bank picks.
* **Bank** (`app/interview/bank.py`, 90 entries): every category and difficulty, with skill tags and `key_points`. Technical picks prefer the job's skills, then weak topics from earlier interviews, then the candidate's skills, served round-robin per tag, closest difficulty first, seeded by the session id (varied but reproducible). Project questions are generic ("Choose a project you built…") and assume nothing. Job-specific questions quote the job's own duties. Key points and expected points are never returned while the interview runs; they only inform study topics in the report.

## Follow-ups

After an **evaluated** answer (AI mode) the follow-up generator may return one short follow-up of kind `clarification`, `rationale`, `trade_offs`, `example`, `challenge` or `alternatives`, or none. It is validated (a question, long enough, not repeating anything asked in the session, same topic). The limit is `max_followups` per main question (default `INTERVIEW_DEFAULT_FOLLOWUPS`=2, ceiling `INTERVIEW_MAX_FOLLOWUPS`=3); skipped and unevaluated answers get none. In question-bank mode follow-ups are unavailable and the response says so (`adaptive_followups: false`, `followups_note`).

## Evaluation

For each answer the evaluator returns, per dimension, an integer 0-10 or `null` ("cannot be judged") plus a rationale:

| Group | Dimensions | Nature |
| --- | --- | --- |
| knowledge | `technical_correctness`, `relevance`, `completeness` | objective content |
| approach | `problem_solving`, `practical_application` | reasoning and application |
| communication | `clarity`, `evidence_examples` | **subjective**, about the written answer only |

Also: correct points, missing/incorrect points, strengths, improvements, a summary, and for `behavioral` questions a STAR assessment (situation, task, action, result, reflection each `present: true/false/null`). The prompt forbids rewarding verbosity or confident tone, requires fair partial credit, forbids inferring emotions, personality, honesty or confidence, and forbids inventing facts about the candidate. Answer length is not an input to any score.

If evaluation is impossible the answer is still saved and the evaluation has status `unavailable` (no AI in use or provider gone), `failed` (timeout, rate limit, invalid or score-less reply; with the reason code) or `not_evaluated` (skipped). Scores are never fabricated.

## Scoring (all configurable)

```
question score   = weighted mean of the dimensions the evaluator could judge (0-10)
thread score     = (main answer x 1 + follow-up answers x followup_weight) / their total weight
overall score    = round(10 x mean of thread scores)
```

Defaults: weights technical_correctness 0.30, relevance 0.15, completeness 0.15, problem_solving 0.15, practical_application 0.10, clarity 0.10, evidence_examples 0.05; `followup_weight` 0.5; `skipped_counts_as_zero` true; `strong_threshold` 7.5; `weak_threshold` 5.0. A skipped **main** question scores 0 (a skipped follow-up is not penalised); questions never asked, questions asked but unanswered when the interview was completed, and answers that could not be evaluated are **excluded**, never zero. With nothing evaluated the score is `null`. Rules can be overridden server-wide (`INTERVIEW_SCORING`, JSON, validated at startup) and per interview (`scoring`); the rules used are stored with the session and the report.

## Report

Stored once at completion (`GET /interviews/{id}/report`, never recomputed, so later changes to jobs or settings cannot alter it): overall score with an explanation, counts, per-dimension means, group scores (knowledge, approach, communication marked subjective), per-category scores, STAR coverage, strong answers (≥ strong threshold), weak answers (< weak threshold), answers not evaluated, knowledge gaps (the evaluator's missing/incorrect points for answers below the strong threshold, plus the expected points of skipped questions), study topics (tags of weak or skipped questions), practice questions (bank questions on those topics not yet asked), calculation notes, scoring rules, and the disclaimer. Everything above is deterministic given the evaluations. Optionally `ai_feedback` (summary, study topics, practice questions, labelled AI-generated) is added by the feedback writer; its text is dropped if it promises an outcome or states a score different from the computed one, and a feedback failure never loses the report.

## Known limitations

* Evaluation quality and prompt-injection resistance of a **real** model are untested; automated tests use scripted fake providers. A cleverly worded answer could still sway a real model; the injection flag and the fixed, validated structure limit but do not eliminate that.
* Scores are only as good as the evaluator's per-dimension judgements; they have not been calibrated against human raters or hiring outcomes.
* The bank is English-only and finite (90 questions); heavy users will see repeats once a category is exhausted.
* AI calls (planning, evaluation, follow-up) run inside the request and the answer transaction; a slow provider makes that request slow. A worker/queue would be the next step.
* Idle/expiry transitions are lazy (applied on access), not scheduled.
* Text only; voice is a later phase. Per-process rate limiting. PostgreSQL behaviour (migration `0005`, concurrency) is unverified.
