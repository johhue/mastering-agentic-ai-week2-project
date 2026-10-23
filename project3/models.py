"""Typed research artifacts and citation validation at agent boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator
from project3.config import ResearchError


class Source(BaseModel):
    """A Tavily result with stable ID, retrieval time and explicit publication date."""

    id: str
    title: str
    url: str
    content: str
    retrieved_at: str
    published_at: str = ''
    topic: str = 'general'


class Claim(BaseModel):
    """A concise fact or assessment with citations, or a declared knowledge gap."""

    text: str
    source_ids: list[str]
    kind: Literal['fact', 'inference', 'unknown']

    @model_validator(mode='after')
    def check_citations(self) -> Claim:
        """Reject unsupported facts and empty text before anything reaches a report."""
        if not self.text.strip():
            raise ValueError('Claim text must not be empty.')
        if self.kind != 'unknown' and not self.source_ids:
            raise ValueError('Facts and inferences require source IDs.')
        return self


class Competitor(BaseModel):
    """A named competitor and evidence-based explanation of its relevance."""

    name: str
    rationale: Claim


class Discovery(BaseModel):
    """Exactly three evidence-supported competitors for the resolved company."""

    company: str = Field(min_length=1, max_length=180)
    market_scope: str = Field(min_length=1)
    competitors: list[Competitor] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def distinct_companies(self) -> Discovery:
        """Exclude duplicate competitors and the subject company itself."""
        names = [competitor.name.strip().casefold() for competitor in self.competitors]
        if not self.company.strip():
            raise ValueError('The resolved company must not be blank.')
        if any(not name for name in names) or len(set(names)) != 3 or self.company.strip().casefold() in names:
            raise ValueError('Three distinct competitors excluding the subject are required.')
        if any(competitor.rationale.kind == 'unknown' for competitor in self.competitors):
            raise ValueError('Competitor selection needs supporting evidence.')
        return self


class Profile(BaseModel):
    """A company profile covering comparable dimensions and fresh news."""

    company: str
    pricing: list[Claim] = Field(min_length=1)
    features: list[Claim] = Field(min_length=1)
    positioning: list[Claim] = Field(min_length=1)
    news: list[Claim] = Field(min_length=1)
    gaps: list[str]


class Synthesis(BaseModel):
    """The orchestrator's source-grounded strategic assessment."""

    executive_summary: list[Claim] = Field(min_length=1)
    opportunities: list[Claim]
    risks: list[Claim]
    limitations: list[str]


class Briefing(BaseModel):
    """A shareable run with subject, three competitors, analysis and source registry."""

    run_id: str
    company: str
    generated_at: str
    market_scope: str
    target: Profile
    competitors: list[Profile] = Field(min_length=3, max_length=3)
    discovery: Discovery
    synthesis: Synthesis
    sources: list[Source]
    warnings: list[str]
    demo: bool = False


def validate_citations(artifact: BaseModel, sources: list[Source]) -> None:
    """Ensure every cited ID exists in the evidence actually supplied to this agent."""
    valid = {source.id for source in sources}

    def visit(value) -> None:
        """Walk nested typed artifacts without accepting model-invented source IDs."""
        if isinstance(value, dict):
            if 'source_ids' in value and set(value['source_ids']) - valid:
                raise ResearchError('The model returned unknown source references; research was not accepted.')
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(artifact.model_dump())


def usable_url(value: str) -> bool:
    """Limit report links to ordinary HTTPS or HTTP evidence URLs."""
    parsed = urlparse(value)
    return parsed.scheme in {'https', 'http'} and bool(parsed.netloc) and not parsed.username


def utc_now() -> str:
    """Return an explicit UTC retrieval or report timestamp."""
    return datetime.now(timezone.utc).isoformat()
