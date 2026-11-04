"""Saving, editing, importing and parsing job descriptions.

Job text is untrusted. It is stored as data, parsed by deterministic code, and only ever
shown to an AI model as delimited data (see ``app.ai.job_analysis``). A job's status is
``parsed`` exactly when it has a current analysis.
"""

import hashlib
import logging
import re
import uuid
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import PortfolioFetchError, PortfolioUrlRejectedError
from app.integrations.portfolio.crawler import PageFetcher
from app.integrations.portfolio.extract import extract_page
from app.integrations.portfolio.safe_fetch import parse_public_url
from app.jobs.errors import (
    InvalidJobDescriptionError,
    JobAnalysisNotFoundError,
    JobFetchError,
    JobNotFoundError,
    JobPlatformNotSupportedError,
    JobUrlRejectedError,
)
from app.jobs.parser import parse_job
from app.jobs.schemas import JobAnalysisResult
from app.models import JobAnalysis, JobDescription, User
from app.models.enums import JobStatus
from app.repositories.jobs import JobRepository
from app.schemas.jobs import (
    MAX_DESCRIPTION_CHARS,
    MIN_DESCRIPTION_CHARS,
    JobCreate,
    JobUpdate,
)

logger = logging.getLogger(__name__)

# Sites whose terms forbid automated access or that require a login. They are never
# fetched; the candidate pastes the text instead.
RESTRICTED_JOB_HOSTS = (
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "naukri.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_RUNS = re.compile(r"\n{3,}")


def clean_description(text: str) -> str:
    """Remove control characters and normalise line endings and blank lines."""
    normalised = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in normalised.split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def description_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_restricted(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in RESTRICTED_JOB_HOSTS)


def _require_enough_text(text: str) -> str:
    cleaned = clean_description(text)
    if len(cleaned) < MIN_DESCRIPTION_CHARS:
        raise InvalidJobDescriptionError(
            f"The job description is too short to analyse (at least {MIN_DESCRIPTION_CHARS} "
            "characters of text are needed)"
        )
    if len(cleaned) > MAX_DESCRIPTION_CHARS:
        raise InvalidJobDescriptionError(
            f"The job description is longer than {MAX_DESCRIPTION_CHARS} characters"
        )
    return cleaned


class JobService:
    def __init__(self, session: AsyncSession, pages: PageFetcher) -> None:
        self._session = session
        self._pages = pages
        self._repo = JobRepository(session)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def check_source_url(url: str, *, will_fetch: bool) -> str:
        """Validate a job link (syntax, scheme, port, public host) without making any
        request; when the server is going to fetch it, also refuse restricted sites. A
        link that is only a reference next to pasted text may point anywhere public.
        Returns the normalised address."""
        try:
            parsed = parse_public_url(url)
        except PortfolioUrlRejectedError as error:
            raise JobUrlRejectedError(error.message) from None
        if will_fetch and _is_restricted(parsed.host):
            raise JobPlatformNotSupportedError(
                "This site does not allow automated access or needs a login. "
                "Please paste the job description text instead."
            )
        return f"{parsed.scheme}://{parsed.host}{parsed.path_and_query}"

    async def _fetch_text(self, url: str) -> str:
        try:
            result = await self._pages.fetch(url)
        except PortfolioUrlRejectedError as error:
            raise JobUrlRejectedError(error.message) from None
        except PortfolioFetchError as error:
            raise JobFetchError(error.message, code=error.code) from None
        final_host = urlsplit(result.url).hostname or ""
        if _is_restricted(final_host):  # redirected to a restricted site
            raise JobPlatformNotSupportedError(
                "The link leads to a site that does not allow automated access. "
                "Please paste the job description text instead."
            )
        page = extract_page(result.body, result.url)
        if len(page.text) < MIN_DESCRIPTION_CHARS:
            raise InvalidJobDescriptionError(
                "No readable job text was found at that address (the page may need "
                "JavaScript or a login). Please paste the job description text instead.",
                code="job_text_not_found",
            )
        return page.text[:MAX_DESCRIPTION_CHARS]

    def _parse_and_attach(self, job: JobDescription) -> JobAnalysis | None:
        """Run the deterministic parser. On an unexpected failure the job is marked
        ``failed`` (nothing from the text is logged) and has no analysis."""
        try:
            parsed = parse_job(job.title, job.description)
        except Exception:
            logger.warning("Job parsing failed", extra={"job_id": str(job.id)})
            job.status = JobStatus.FAILED
            return None
        job.status = JobStatus.PARSED
        return JobAnalysis(
            job_id=job.id,
            user_id=job.user_id,
            parser="deterministic",
            description_sha256=job.description_sha256,
            result=JobAnalysisResult(parsed=parsed).model_dump(mode="json"),
        )

    async def _store_analysis(self, job: JobDescription) -> None:
        analysis = self._parse_and_attach(job)
        if analysis is None:
            await self._repo.delete_analysis(job.user_id, job.id)
        else:
            await self._repo.replace_analysis(analysis)

    # ------------------------------------------------------------------- CRUD

    async def create(self, user: User, data: JobCreate) -> JobDescription:
        source_url = (
            self.check_source_url(data.source_url, will_fetch=data.description is None)
            if data.source_url
            else None
        )
        if data.description is not None:
            text = _require_enough_text(data.description)
        elif source_url is not None:
            text = _require_enough_text(await self._fetch_text(source_url))
        else:  # unreachable: JobCreate requires text or a link
            raise InvalidJobDescriptionError("Provide the job description text")
        job = JobDescription(
            id=uuid.uuid4(),
            user_id=user.id,
            title=data.title,
            company=data.company,
            description=text,
            source_url=source_url,
            status=JobStatus.SAVED,
            description_sha256=description_digest(text),
        )
        self._repo.add_job(job)
        await self._session.flush()
        await self._store_analysis(job)
        await self._session.commit()
        return job

    async def update(self, user: User, job_id: uuid.UUID, data: JobUpdate) -> JobDescription:
        job = await self.get(user, job_id)
        fields = data.model_fields_set
        reparse = False

        if "source_url" in fields:
            job.source_url = (
                self.check_source_url(data.source_url, will_fetch="description" not in fields)
                if data.source_url
                else None
            )
        if "description" in fields and data.description is not None:
            job.description = _require_enough_text(data.description)
            reparse = True
        elif "source_url" in fields and job.source_url:
            # A new link without new text: read the text from the new link.
            job.description = _require_enough_text(await self._fetch_text(job.source_url))
            reparse = True
        if "title" in fields and data.title is not None and data.title != job.title:
            job.title = data.title
            reparse = True
        if "company" in fields:
            job.company = data.company

        if reparse:
            job.description_sha256 = description_digest(job.description)
            await self._store_analysis(job)  # any AI-enriched analysis is replaced
        await self._session.commit()
        return job

    async def get(self, user: User, job_id: uuid.UUID) -> JobDescription:
        job = await self._repo.get_job(user.id, job_id)
        if job is None:
            raise JobNotFoundError
        return job

    async def list_all(self, user: User) -> list[JobDescription]:
        return await self._repo.list_jobs(user.id)

    async def delete(self, user: User, job_id: uuid.UUID) -> None:
        """Delete the job and, by cascade, its analysis and match reports."""
        if not await self._repo.delete_job(user.id, job_id):
            raise JobNotFoundError
        await self._session.commit()

    async def get_analysis(self, user: User, job_id: uuid.UUID) -> JobAnalysis:
        await self.get(user, job_id)  # ownership check first
        analysis = await self._repo.get_analysis(user.id, job_id)
        if analysis is None:
            raise JobAnalysisNotFoundError
        return analysis
