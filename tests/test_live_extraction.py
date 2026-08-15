"""Live checks against the real Claude API.

Deselected by default, everywhere. CI must never spend money, and a developer
should choose to spend it rather than discover it afterwards. Run explicitly:

    pytest -m live

These exist because no amount of mocking can verify the request shape actually
reaches the model: a wrong parameter, a schema the API rejects, or a response
field that is not where the SDK docs imply all look identical to a fake.
"""

import os

import pytest

from pocket_oss_agent.agents.resume_parser import parse_resume_text, summarize
from pocket_oss_agent.llm import MODEL, ClaudeProfileExtractor

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        reason="no Anthropic credential in the environment",
    ),
]

RESUME = """
MARCUS OKONKWO
Berlin, Germany

SUMMARY
Backend engineer, 6 years building payment and ledger systems at scale.

EXPERIENCE
Senior Backend Engineer, Klarna (2022-present)
  Led the rewrite of the settlement ledger in Go, cutting reconciliation
  time from 6 hours to 11 minutes. Owned the gRPC service mesh migration.
Backend Engineer, Zalando (2020-2022)
  Built merchant payout APIs in Python with FastAPI and Celery.

SKILLS
Languages: Go, Python, SQL
Frameworks: FastAPI, gRPC, Celery
Infrastructure: Kubernetes, Terraform, AWS, PostgreSQL, Kafka
"""


def test_the_request_shape_reaches_the_model() -> None:
    """One real call. Proves the schema compiles server-side and the response
    carries `parsed_output` where the wrapper looks for it.
    """
    context = parse_resume_text(RESUME, ClaudeProfileExtractor())

    assert context.name and "Marcus" in context.name
    assert {lang.lower() for lang in context.languages} >= {"go", "python"}
    assert context.domain and "backend" in context.domain.lower()
    assert context.seniority in {"junior", "mid", "senior", "staff"}
    print(f"\n  model    : {MODEL}")
    print(f"  summary  : {summarize(context)}")


def test_it_does_not_invent_technologies_absent_from_the_resume() -> None:
    """The system prompt tells the model to leave a field empty rather than
    infer. This is the behaviour most likely to regress on a cheaper tier.
    """
    context = parse_resume_text(RESUME, ClaudeProfileExtractor())

    claimed = {item.lower() for item in context.languages + context.frameworks + context.tools}
    for absent in ("rust", "django", "azure", "mongodb"):
        assert absent not in claimed, f"invented {absent!r}, which the resume never mentions"
