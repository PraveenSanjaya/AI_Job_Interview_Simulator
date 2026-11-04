"""Request/response models for public-source integrations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.github.snapshot import GitHubSnapshot
from app.integrations.portfolio.crawler import PortfolioSnapshot


class GitHubConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=1,
        max_length=300,
        description="A GitHub username, @username, or github.com profile URL",
    )


class GitHubSourceResponse(BaseModel):
    """What GitHub's public API reported. These are observed facts, not assessments."""

    source_ref: str
    fetched_at: datetime
    snapshot: GitHubSnapshot


class PortfolioConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        min_length=1,
        max_length=2000,
        description="Public http(s) address of your portfolio site",
    )


class PortfolioSourceResponse(BaseModel):
    """What the public pages said, with source URLs. Untrusted text, not verified facts."""

    source_ref: str
    fetched_at: datetime
    snapshot: PortfolioSnapshot
