"""Mock interview sessions: planning, state transitions, answers, follow-ups, evaluation, reports.

Invariants:

* every lookup is scoped to the owner; another user's session is "not found";
* a session only moves along ``app.interview.config.TRANSITIONS``, each move being one
  conditional UPDATE, so two racing requests cannot both win;
* an answer is accepted by a conditional version bump, so concurrent submissions based on the
  same state cannot both be applied (the loser gets ``409 concurrent_submission``);
* AI problems never lose an answer: the answer is saved and its evaluation is marked
  ``unavailable``/``failed`` with a reason. Nothing is ever fabricated;
* candidate answers and AI replies are never logged.
"""

import logging
import random
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.ai.cv_schemas import CVAnalysisResult
from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.integrations.github.snapshot import GitHubSnapshot
from app.interview.ai import (
    AIAnswerEvaluator,
    AIFeedbackWriter,
    AIFollowUpGenerator,
    AIQuestionGenerator,
)
from app.interview.bank import (
    job_specific_prompts,
    normalise,
    pick_for_category,
    tags_for_skills,
)
from app.interview.config import (
    TRANSITIONS,
    InterviewScoringConfig,
    resolve_scoring,
    sources_for,
)
from app.interview.context import InterviewContext, PlannedQuestion, ProjectContext
from app.interview.schemas import AIFeedback, EvaluationResult, InterviewReportData
from app.interview.scoring import Record, build_report
from app.jobs.schemas import JobAnalysisResult
from app.matching.report import MatchReport
from app.models import (
    InterviewAnswer,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewReport,
    InterviewSession,
    User,
)
from app.models.enums import EvaluationStatus, IntegrationKind, InterviewStatus, InterviewType
from app.repositories.integrations import IntegrationRepository
from app.repositories.interviews import InterviewRepository
from app.repositories.jobs import JobRepository
from app.repositories.resumes import ResumeRepository
from app.schemas.interviews import AnswerCreate, InterviewCreate, Progress
from app.services.profile import ProfileService

logger = logging.getLogger(__name__)

RECENT_QUESTIONS = 60
MAX_CONTEXT_PROJECTS = 5


class InvalidInterviewConfigError(AppError):
    status_code = 422
    code = "invalid_interview_config"


class InterviewStateError(ConflictError):
    code = "invalid_interview_state"


class InterviewNotFoundError(NotFoundError):
    code = "interview_not_found"

    def __init__(self) -> None:
        super().__init__("Interview not found")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InterviewService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: LLMProvider,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session = session
        self._settings = settings
        self._provider = provider
        self._clock = clock
        self._repo = InterviewRepository(session)
        self._jobs = JobRepository(session)

    # -------------------------------------------------------------- lookups

    async def get(self, user: User, session_id: uuid.UUID) -> InterviewSession:
        interview = await self._repo.get_session(user.id, session_id)
        if interview is None:
            raise InterviewNotFoundError
        return await self._refresh(interview)

    async def list_all(self, user: User) -> list[InterviewSession]:
        return [await self._refresh(s) for s in await self._repo.list_sessions(user.id)]

    async def _refresh(self, interview: InterviewSession) -> InterviewSession:
        """Apply time-based transitions lazily: an idle running interview becomes
        ``interrupted`` (resumable); an unstarted one eventually ``expired``."""
        now = self._clock()
        target: InterviewStatus | None = None
        if interview.status == InterviewStatus.IN_PROGRESS:
            idle = timedelta(minutes=self._settings.interview_idle_minutes)
            if now - interview.last_activity_at > idle:
                target = InterviewStatus.INTERRUPTED
        elif interview.status == InterviewStatus.CREATED:
            limit = timedelta(hours=self._settings.interview_created_expiry_hours)
            if now - interview.created_at > limit:
                target = InterviewStatus.EXPIRED
        if target is None:
            return interview
        moved = await self._repo.transition(
            interview.user_id,
            interview.id,
            allowed_from={interview.status},
            to=target,
            values={},
        )
        if moved:
            await self._session.commit()
        refreshed = await self._repo.get_session(interview.user_id, interview.id)
        assert refreshed is not None  # noqa: S101 - it existed a moment ago
        return refreshed

    # --------------------------------------------------------------- create

    async def create(self, user: User, data: InterviewCreate) -> InterviewSession:
        types = [t.value for t in data.interview_types]
        if data.question_count > self._settings.interview_max_questions:
            raise InvalidInterviewConfigError(
                f"At most {self._settings.interview_max_questions} questions are allowed",
                code="too_many_questions",
            )
        followups = (
            self._settings.interview_default_followups
            if data.max_followups is None
            else data.max_followups
        )
        if followups > self._settings.interview_max_followups:
            raise InvalidInterviewConfigError(
                f"At most {self._settings.interview_max_followups} follow-ups per question "
                "are allowed",
                code="too_many_followups",
            )
        if InterviewType.JOB_SPECIFIC.value in types and data.job_id is None:
            raise InvalidInterviewConfigError(
                "A job_specific interview needs a job_id", code="job_required"
            )
        if data.question_count < len(types):
            raise InvalidInterviewConfigError(
                "question_count must be at least the number of interview types",
                code="too_few_questions",
            )
        try:
            scoring = resolve_scoring(self._settings.interview_scoring, data.scoring)
        except ValidationError:
            raise InvalidInterviewConfigError(
                "Invalid scoring rules: check the dimension names, weights (0 to 100, at "
                "least one above 0), followup_weight (0 to 1) and thresholds",
                code="invalid_scoring_rules",
            ) from None

        job_id = None
        snapshot: dict[str, Any] | None = None
        if data.job_id is not None:
            job = await self._jobs.get_job(user.id, data.job_id)
            if job is None:
                raise NotFoundError("Job not found", code="job_not_found")
            job_id = job.id
            snapshot = {
                "job_id": str(job.id),
                "title": job.title,
                "company": job.company,
                "description_sha256": job.description_sha256,
            }
        interview = InterviewSession(
            user_id=user.id,
            job_id=job_id,
            job_snapshot=snapshot,
            interview_types=types,
            difficulty=data.difficulty,
            question_count=data.question_count,
            max_followups=followups,
            use_ai=data.use_ai,
            consent_external_ai=data.allow_external_ai,
            scoring_config=scoring.model_dump(mode="json"),
            last_activity_at=self._clock(),
        )
        self._repo.add_session(interview)
        await self._session.commit()
        return interview

    # ---------------------------------------------------------------- start

    async def start(self, user: User, session_id: uuid.UUID) -> InterviewSession:
        interview = await self.get(user, session_id)
        if InterviewStatus.IN_PROGRESS not in TRANSITIONS[interview.status]:
            raise InterviewStateError(
                f"An interview that is {interview.status.value} cannot be started"
            )
        resuming = interview.status == InterviewStatus.INTERRUPTED
        now = self._clock()
        moved = await self._repo.transition(
            user.id,
            interview.id,
            allowed_from=sources_for(InterviewStatus.IN_PROGRESS),
            to=InterviewStatus.IN_PROGRESS,
            values={
                "last_activity_at": now,
                **({} if resuming else {"started_at": now}),
            },
        )
        if not moved:  # another request changed the state first
            raise InterviewStateError("The interview state changed; reload and try again")
        if not resuming:
            await self._plan(user, interview, now)
        await self._session.commit()
        refreshed = await self._repo.get_session(user.id, interview.id)
        assert refreshed is not None  # noqa: S101
        return refreshed

    async def _plan(self, user: User, interview: InterviewSession, now: datetime) -> None:
        context = await self._build_context(user, interview)
        avoid = await self._repo.recent_question_texts(user.id, RECENT_QUESTIONS)
        types = list(interview.interview_types)
        count = interview.question_count

        mode, ai_status = "question_bank", "disabled_by_user"
        planned: list[PlannedQuestion] = []
        if interview.use_ai:
            if not self._provider.available:
                ai_status = "provider_unavailable"
            elif self._provider.is_external and not interview.consent_external_ai:
                ai_status = "consent_not_given"
            else:
                mode, ai_status = "ai", "ok"
                try:
                    planned, rejected = await AIQuestionGenerator(self._provider).generate(
                        context, types, interview.difficulty.value, count, avoid
                    )
                    if rejected:
                        logger.info("Rejected %d generated questions", rejected)
                except AppError as error:
                    mode, ai_status = "question_bank", f"generation_failed:{error.code}"
                    planned = []

        planned = self._complete_plan(planned, types, count, interview, context, avoid)
        for index, question in enumerate(planned):
            self._repo.add_questions(
                [
                    InterviewQuestion(
                        session_id=interview.id,
                        user_id=user.id,
                        main_index=index,
                        followup_index=0,
                        category=question.category,
                        text=question.text,
                        source=question.source,
                        skill_tags=list(question.tags),
                        expected_points=list(question.expected_points),
                        asked_at=now if index == 0 else None,
                    )
                ]
            )
        interview.mode = mode
        interview.ai_status = ai_status
        interview.current_index = 0
        interview.question_count = len(planned)
        if mode == "ai":
            interview.ai_provider = self._provider.name
            interview.ai_model = self._provider.model
        await self._session.flush()

    def _complete_plan(
        self,
        planned: list[PlannedQuestion],
        types: list[str],
        count: int,
        interview: InterviewSession,
        context: InterviewContext,
        avoid: list[str],
    ) -> list[PlannedQuestion]:
        """Give every requested type its share, filling gaps from the curated bank."""
        rng = random.Random(str(interview.id))  # noqa: S311 - variety, not security
        base, extra = divmod(count, len(types))
        targets = {t: base + (1 if i < extra else 0) for i, t in enumerate(types)}
        by_type: dict[str, list[PlannedQuestion]] = {t: [] for t in types}
        for question in planned:
            if len(by_type[question.category]) < targets[question.category]:
                by_type[question.category].append(question)

        used = {normalise(t) for t in avoid} | {normalise(q.text) for q in planned}
        job_tags = tags_for_skills([*context.job_required, *context.job_preferred])
        focus_tags = tags_for_skills(context.focus_topics)
        preferred = list(dict.fromkeys([*job_tags, *focus_tags, *tags_for_skills(context.skills)]))
        difficulty = interview.difficulty.value
        for category in types:
            need = targets[category] - len(by_type[category])
            if need <= 0:
                continue
            if category == InterviewType.JOB_SPECIFIC.value:
                prompts = [
                    PlannedQuestion(category, text, tuple(job_tags[:2]), (duty,))
                    for text, duty in job_specific_prompts(context.job_duties, difficulty, need)
                    if normalise(text) not in used
                ]
                if len(prompts) < need:  # no duties: use technical questions for the job's skills
                    prompts += [
                        PlannedQuestion(category, q.text, q.tags, q.key_points)
                        for q in pick_for_category(
                            "technical",
                            difficulty,
                            need - len(prompts),
                            preferred_tags=job_tags or preferred,
                            exclude=used,
                            rng=rng,
                        )
                    ]
                filled = prompts[:need]
            else:
                tags = preferred if category in ("technical", "programming") else []
                filled = [
                    PlannedQuestion(category, q.text, q.tags, q.key_points)
                    for q in pick_for_category(
                        category, difficulty, need, preferred_tags=tags, exclude=used, rng=rng
                    )
                ]
            for question in filled:
                used.add(normalise(question.text))
            by_type[category].extend(filled)

        # Interleave the types so one kind of question does not dominate a stretch.
        ordered: list[PlannedQuestion] = []
        queues = [list(by_type[t]) for t in types]
        while any(queues):
            for queue in queues:
                if queue:
                    ordered.append(queue.pop(0))
        return ordered

    async def _build_context(self, user: User, interview: InterviewSession) -> InterviewContext:
        profile = await ProfileService(self._session).get(user)
        context = InterviewContext(
            experience_level=profile.experience_level.value if profile.experience_level else None,
            preferred_roles=list(profile.preferred_roles),
            skills=[s.name for s in profile.skills if s.category.value == "technical"],
        )
        projects: dict[str, ProjectContext] = {}

        def add(name: str | None, description: str | None, technologies: tuple[str, ...]) -> None:
            key = "".join(c for c in (name or "").casefold() if c.isalnum())
            if key and key not in projects:
                projects[key] = ProjectContext(name or "", description, technologies)

        for p in profile.projects:
            add(p.name, p.description, tuple(p.technologies))
        for resume in await ResumeRepository(self._session).list_for_user(user.id):
            if resume.analysis is not None:
                facts = CVAnalysisResult.model_validate(resume.analysis.result).facts
                for rp in facts.projects:
                    add(rp.name, rp.description, tuple(rp.technologies))
                context.skills.extend(
                    s
                    for s in facts.technical_skills + facts.tools_and_technologies
                    if s not in context.skills
                )
                break
        github = await IntegrationRepository(self._session).get_source(
            user.id, IntegrationKind.GITHUB
        )
        if github is not None:
            snapshot = GitHubSnapshot.model_validate(github.snapshot)
            for repo in snapshot.repositories:
                if not repo.is_fork and repo.description:
                    add(repo.name, repo.description, tuple(filter(None, [repo.primary_language])))
        context.projects = list(projects.values())[:MAX_CONTEXT_PROJECTS]

        if interview.job_id is not None:
            await self._add_job(user, interview, context)
        previous = await self._repo.latest_report(user.id)
        if previous is not None:
            try:
                report = InterviewReportData.model_validate(previous.result)
                context.focus_topics.extend(t.topic or "" for t in report.study_topics[:5])
            except ValidationError:
                pass
        context.focus_topics = [t for t in dict.fromkeys(context.focus_topics) if t]
        return context

    async def _add_job(
        self, user: User, interview: InterviewSession, context: InterviewContext
    ) -> None:
        job = await self._jobs.get_job(user.id, interview.job_id) if interview.job_id else None
        snapshot = interview.job_snapshot or {}
        context.job_title = snapshot.get("title") or (job.title if job else None)
        context.job_company = snapshot.get("company")
        if job is None:
            return
        analysis = await self._jobs.get_analysis(user.id, job.id)
        if analysis is not None:
            parsed = JobAnalysisResult.model_validate(analysis.result).parsed
            context.job_required = parsed.required_technical_skills
            context.job_preferred = parsed.preferred_technical_skills + (
                parsed.unspecified_importance_skills
            )
            context.job_duties = [d.text for d in parsed.responsibilities]
            context.job_seniority = parsed.seniority.level
        matches = await self._jobs.list_matches(user.id, job.id)
        if matches:  # the latest report tells which requirements deserve probing
            report = MatchReport.model_validate(matches[0].result["report"])
            context.focus_topics.extend(
                [*report.missing_requirements[:4], *report.weakly_supported_requirements[:4]]
            )

    # ------------------------------------------------------ questions & state

    async def questions(
        self, user: User, session_id: uuid.UUID
    ) -> tuple[InterviewSession, list[tuple[InterviewQuestion, InterviewAnswer | None]]]:
        interview = await self.get(user, session_id)
        answers = {a.question_id: a for a in await self._repo.list_answers(interview.id)}
        asked = [q for q in await self._repo.list_questions(interview.id) if q.asked_at]
        return interview, [(q, answers.get(q.id)) for q in asked]

    async def current(
        self, user: User, session_id: uuid.UUID
    ) -> tuple[InterviewSession, InterviewQuestion | None, bool]:
        """``(session, open question or None, all main questions answered)``."""
        interview = await self.get(user, session_id)
        question, all_done = await self._open_question(interview)
        if interview.status not in (InterviewStatus.IN_PROGRESS, InterviewStatus.INTERRUPTED):
            question = None
        return interview, question, all_done

    async def _open_question(
        self, interview: InterviewSession
    ) -> tuple[InterviewQuestion | None, bool]:
        questions = await self._repo.list_questions(interview.id)
        answered = {a.question_id for a in await self._repo.list_answers(interview.id)}
        for question in questions:
            if question.asked_at and question.id not in answered:
                return question, False
        mains = [q for q in questions if q.followup_index == 0]
        return None, bool(mains) and all(q.asked_at and q.id in answered for q in mains)

    async def progress(self, interview: InterviewSession) -> Progress:
        questions = await self._repo.list_questions(interview.id)
        answers = await self._repo.list_answers(interview.id)
        mains = [q for q in questions if q.followup_index == 0]
        asked_mains = [q for q in mains if q.asked_at]
        return Progress(
            main_questions_total=len(mains) or interview.question_count,
            main_questions_asked=len(asked_mains),
            answered=sum(1 for a in answers if not a.skipped),
            skipped=sum(1 for a in answers if a.skipped),
            followups_asked=sum(1 for q in questions if q.followup_index > 0),
            remaining_main_questions=len(mains) - len(asked_mains),
        )

    # -------------------------------------------------------------- answers

    async def answer(
        self, user: User, session_id: uuid.UUID, data: AnswerCreate
    ) -> tuple[InterviewAnswer, InterviewEvaluation, InterviewQuestion | None, bool, str | None]:
        interview = await self.get(user, session_id)
        if interview.status != InterviewStatus.IN_PROGRESS:
            raise InterviewStateError(
                f"Answers can only be submitted while the interview is in progress "
                f"(it is {interview.status.value})"
            )
        current, _ = await self._open_question(interview)
        if current is None:
            raise ConflictError(
                "There is no open question; complete the interview to get your report",
                code="no_open_question",
            )
        if current.id != data.question_id:
            raise ConflictError("That is not the current question", code="not_current_question")

        now = self._clock()
        if not await self._repo.claim_answer_slot(user.id, interview.id, interview.version, now):
            raise ConflictError(
                "Another answer was submitted at the same time; reload and try again",
                code="concurrent_submission",
            )
        answer = InterviewAnswer(
            question_id=current.id,
            session_id=interview.id,
            user_id=user.id,
            text=None if data.skip else data.text,
            skipped=data.skip,
            submitted_at=now,
        )
        self._repo.add_answer(answer)
        try:
            await self._session.flush()
        except IntegrityError:
            raise ConflictError(
                "This question has already been answered", code="already_answered"
            ) from None

        evaluation = await self._evaluate(interview, current, answer)
        self._repo.add_evaluation(evaluation)
        await self._session.flush()

        next_question, note = await self._advance(interview, current, answer, evaluation)
        await self._session.commit()
        return (
            answer,
            evaluation,
            next_question,
            next_question is not None and next_question.followup_index > 0,
            note,
        )

    async def _evaluate(
        self, interview: InterviewSession, question: InterviewQuestion, answer: InterviewAnswer
    ) -> InterviewEvaluation:
        def make(
            status: EvaluationStatus, reason: str | None, result: EvaluationResult | None = None
        ) -> InterviewEvaluation:
            used_ai = status == EvaluationStatus.EVALUATED
            return InterviewEvaluation(
                answer_id=answer.id,
                session_id=interview.id,
                user_id=interview.user_id,
                status=status,
                reason=reason,
                provider=self._provider.name if used_ai else None,
                model=self._provider.model if used_ai else None,
                result=result.model_dump(mode="json") if result else None,
            )

        if answer.skipped:
            return make(EvaluationStatus.NOT_EVALUATED, "skipped")
        if interview.mode != "ai":
            return make(
                EvaluationStatus.UNAVAILABLE,
                f"ai_not_used:{interview.ai_status or 'unknown'}",
            )
        if not self._provider.available:
            return make(EvaluationStatus.UNAVAILABLE, "provider_unavailable")
        try:
            result = await AIAnswerEvaluator(self._provider).evaluate(
                question=question.text,
                category=question.category,
                expected_points=list(question.expected_points),
                answer=answer.text or "",
                difficulty=interview.difficulty.value,
            )
        except AppError as error:
            return make(EvaluationStatus.FAILED, error.code)
        return make(EvaluationStatus.EVALUATED, None, result)

    async def _advance(
        self,
        interview: InterviewSession,
        current: InterviewQuestion,
        answer: InterviewAnswer,
        evaluation: InterviewEvaluation,
    ) -> tuple[InterviewQuestion | None, str | None]:
        """Ask a follow-up if one is warranted and allowed, else move to the next question."""
        questions = await self._repo.list_questions(interview.id)
        thread = [q for q in questions if q.main_index == current.main_index]
        used = len(thread) - 1
        note: str | None = None

        if interview.mode != "ai":
            note = "Adaptive follow-ups are unavailable: this interview uses the question bank."
        elif used >= interview.max_followups or answer.skipped:
            note = None
        elif evaluation.status != EvaluationStatus.EVALUATED or not evaluation.result:
            note = "No follow-up was asked because this answer could not be evaluated."
        else:
            try:
                item = await AIFollowUpGenerator(self._provider).generate(
                    question=current.text,
                    category=current.category,
                    answer=answer.text or "",
                    evaluation=EvaluationResult.model_validate(evaluation.result),
                    difficulty=interview.difficulty.value,
                    avoid=[q.text for q in questions],
                )
            except AppError:
                item = None
                note = "No follow-up was asked because the AI provider did not respond usably."
            if item is not None and item.text:
                follow = InterviewQuestion(
                    session_id=interview.id,
                    user_id=interview.user_id,
                    main_index=current.main_index,
                    followup_index=used + 1,
                    category=current.category,
                    text=item.text,
                    source="ai",
                    followup_kind=item.kind,
                    skill_tags=list(current.skill_tags),
                    expected_points=[],
                    asked_at=self._clock(),
                )
                self._repo.add_questions([follow])
                await self._session.flush()
                return follow, None

        following = [
            q for q in questions if q.main_index == current.main_index + 1 and not q.followup_index
        ]
        if following:
            nxt = following[0]
            nxt.asked_at = self._clock()
            interview.current_index = nxt.main_index
            await self._session.flush()
            return nxt, note
        return None, note

    # ------------------------------------------------------ cancel / complete

    async def cancel(self, user: User, session_id: uuid.UUID) -> InterviewSession:
        interview = await self.get(user, session_id)
        if InterviewStatus.CANCELLED not in TRANSITIONS[interview.status]:
            raise InterviewStateError(
                f"An interview that is {interview.status.value} cannot be cancelled"
            )
        moved = await self._repo.transition(
            user.id,
            interview.id,
            allowed_from=sources_for(InterviewStatus.CANCELLED),
            to=InterviewStatus.CANCELLED,
        )
        if not moved:
            raise InterviewStateError("The interview state changed; reload and try again")
        await self._session.commit()
        return await self.get(user, session_id)

    async def complete(self, user: User, session_id: uuid.UUID) -> InterviewReport:
        interview = await self.get(user, session_id)
        if InterviewStatus.COMPLETED not in TRANSITIONS[interview.status]:
            raise InterviewStateError(
                f"An interview that is {interview.status.value} cannot be completed"
            )
        moved = await self._repo.transition(
            user.id,
            interview.id,
            allowed_from=sources_for(InterviewStatus.COMPLETED),
            to=InterviewStatus.COMPLETED,
            values={"completed_at": self._clock()},
        )
        if not moved:
            raise InterviewStateError("The interview state changed; reload and try again")
        interview = await self._repo.get_session(user.id, session_id) or interview

        records = await self._records(interview)
        config = InterviewScoringConfig.model_validate(interview.scoring_config)
        job_title = (interview.job_snapshot or {}).get("title")
        planned = interview.question_count
        base_args: dict[str, Any] = {
            "session_id": str(interview.id),
            "interview_types": list(interview.interview_types),
            "difficulty": interview.difficulty.value,
            "mode": interview.mode,
            "job_title": job_title,
            "planned": planned,
            "records": records,
            "config": config,
        }
        report = build_report(**base_args, ai_feedback=None, ai_feedback_status="not_requested")
        feedback, status = await self._feedback(interview, report)
        if feedback is not None or status != "not_requested":
            report = build_report(**base_args, ai_feedback=feedback, ai_feedback_status=status)

        stored = InterviewReport(
            session_id=interview.id,
            user_id=user.id,
            overall_score=report.overall_score,
            result=report.model_dump(mode="json"),
        )
        self._repo.add_report(stored)
        await self._session.commit()
        return stored

    async def _feedback(
        self, interview: InterviewSession, report: InterviewReportData
    ) -> tuple[AIFeedback | None, str]:
        if interview.mode != "ai":
            return None, "unavailable:question_bank_session"
        if report.score_status != "scored":
            return None, "skipped:nothing_evaluated"
        if not self._provider.available:
            return None, "unavailable:provider_unavailable"
        try:
            return await AIFeedbackWriter(self._provider).write(report), "ok"
        except AppError as error:
            return None, f"failed:{error.code}"

    async def _records(self, interview: InterviewSession) -> list[Record]:
        questions = await self._repo.list_questions(interview.id)
        answers = {a.question_id: a for a in await self._repo.list_answers(interview.id)}
        evaluations = {e.answer_id: e for e in await self._repo.list_evaluations(interview.id)}
        records: list[Record] = []
        for question in questions:
            if not question.asked_at:
                continue
            answer = answers.get(question.id)
            evaluation = evaluations.get(answer.id) if answer else None
            records.append(
                Record(
                    question_id=str(question.id),
                    main_index=question.main_index,
                    followup_index=question.followup_index,
                    category=question.category,
                    text=question.text,
                    tags=list(question.skill_tags),
                    expected_points=list(question.expected_points),
                    answered=answer is not None,
                    skipped=bool(answer and answer.skipped),
                    eval_status=evaluation.status if evaluation else None,
                    evaluation=(
                        EvaluationResult.model_validate(evaluation.result)
                        if evaluation and evaluation.result
                        else None
                    ),
                )
            )
        return records

    # --------------------------------------------------------------- reports

    async def report(self, user: User, session_id: uuid.UUID) -> InterviewReport:
        interview = await self.get(user, session_id)
        report = await self._repo.get_report(user.id, interview.id)
        if report is None:
            raise ConflictError(
                "The report is available once the interview is completed",
                code="report_not_ready",
            )
        return report

    async def evaluations(
        self, user: User, session_id: uuid.UUID
    ) -> list[tuple[InterviewEvaluation, uuid.UUID]]:
        interview = await self.get(user, session_id)
        answers = {a.id: a for a in await self._repo.list_answers(interview.id)}
        return [
            (e, answers[e.answer_id].question_id)
            for e in await self._repo.list_evaluations(interview.id)
            if e.answer_id in answers
        ]
