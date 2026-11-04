"""Request/response models for public-source integrations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.github.snapshot import GitHubSnapshot


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
