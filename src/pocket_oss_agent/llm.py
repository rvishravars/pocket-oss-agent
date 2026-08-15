"""Structured profile extraction from resume text.

`ProfileExtractor` is the seam. `ClaudeProfileExtractor` is the production
implementation; tests inject a fake, so the suite stays offline and needs no
API key.

Extraction is a single Messages API call with a schema attached, not an agent
loop: the inputs fully determine the output, so there is nothing for a tool
loop to decide.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .errors import ProfileExtractionFailed
from .state import DeveloperContext

#: Resume parsing is single-shot structured extraction: one request, one
#: response, inputs fully determining the output. That is the tier Haiku is
#: for, and it costs roughly a fifth of Opus for this call. Structured outputs
#: are supported here, so the schema path is unchanged.
#:
#: Structured outputs compile a schema on first use and cache it for 24 hours,
#: so keep this stable rather than building it per request.
MODEL = "claude-haiku-4-5"

#: Haiku does not think by default, so this budget is the profile itself with
#: headroom. On a thinking model it would also have to cover the reasoning,
#: since `max_tokens` caps thinking and response together.
MAX_TOKENS = 4_000

SYSTEM_PROMPT = (
    "You are a technical recruiter extracting a structured profile from a resume. "
    "Report only what the resume supports. Leave a field empty rather than "
    "inferring a technology the candidate never mentions, and do not infer "
    "seniority from job titles alone when the dates contradict them."
)


# Kept separate from `DeveloperContext` so the wire schema stays flat and fully
# required while the session-state model keeps its own defaults. Every field is
# required here because a schema of all-optional fields lets the model skip the
# hard ones.
#
# The class docstring below is sent to the model as the schema description, so
# it is written for the model, not for us. Implementation rationale belongs in
# this comment, where it costs no tokens.
class ExtractedProfile(BaseModel):
    """A developer's technical profile as stated by their resume."""

    name: str | None = Field(description="Candidate's full name, or null if not clearly present")
    languages: list[str] = Field(description="Programming languages")
    frameworks: list[str] = Field(description="Frameworks and libraries")
    tools: list[str] = Field(description="Cloud and infrastructure tools")
    years_experience: int | None = Field(description="Total years of professional experience")
    seniority: Literal["junior", "mid", "senior", "staff"] | None = Field(
        description="Overall seniority implied by scope and years, not by job title alone"
    )
    domain: str | None = Field(description="Primary domain, e.g. backend, frontend, ML, DevOps")

    def to_developer_context(self) -> DeveloperContext:
        return DeveloperContext(
            name=self.name,
            languages=self.languages,
            frameworks=self.frameworks,
            tools=self.tools,
            years_experience=self.years_experience,
            seniority=self.seniority,
            domain=self.domain,
        )


class ProfileExtractor(Protocol):
    """Turns resume text into a structured profile."""

    def extract(self, resume_text: str) -> DeveloperContext: ...


class ClaudeProfileExtractor:
    """Extracts a profile with one structured-output call to Claude."""

    def __init__(self, client=None, model: str = MODEL, max_tokens: int = MAX_TOKENS) -> None:
        if client is None:
            import anthropic  # imported lazily so the package works without a key

            client = anthropic.Anthropic()
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def extract(self, resume_text: str) -> DeveloperContext:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Extract the profile from this resume.\n\n{resume_text}",
                }
            ],
            output_format=ExtractedProfile,
        )

        # Check stop_reason before touching content. A refusal returns HTTP 200
        # with empty or partial content, so reading parsed_output first turns a
        # policy decline into an unrelated AttributeError.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise ProfileExtractionFailed(
                "the model declined to process this resume",
                detail=_refusal_detail(response),
            )
        if stop_reason == "max_tokens":
            raise ProfileExtractionFailed(
                "the response hit the token ceiling before the profile was complete",
                detail=f"raise max_tokens above {self._max_tokens}",
            )

        profile = getattr(response, "parsed_output", None)
        if profile is None:
            raise ProfileExtractionFailed(
                "the response carried no parsed profile",
                detail=f"stop_reason was {stop_reason!r}",
            )
        return profile.to_developer_context()


def _refusal_detail(response: object) -> str:
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    return f"refusal category: {category}" if category else "no category reported"
