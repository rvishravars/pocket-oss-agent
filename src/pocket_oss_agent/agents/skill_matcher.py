"""skill-matcher: pick the best-fit issue for this developer.

Implements `specs/agents/skill-matcher.md`. Consumes `developer_context`,
`interview_context` and `repo_facts`; produces `top_match`.

Three stages, deliberately separate: hard filters from the interview remove
issues the developer said they don't want, cosine similarity ranks what
survives, and the boost model adjusts that ranking. Keeping them apart is what
makes `score_breakdown` explainable rather than a single opaque number.
"""

from __future__ import annotations

from ..embeddings import EmbeddingProvider, cosine_similarity
from ..errors import MissingUpstreamOutput
from ..state import (
    DeveloperContext,
    GoodFirstIssue,
    InterviewContext,
    IssueIntelligence,
    RepoFacts,
    RepoIntelligence,
    TopMatch,
)
from ..vector_store import VectorRecord, VectorStore, require_matching_model
from .resume_parser import profile_text

#: Interview tag to the issue labels it keeps.
TYPE_LABELS: dict[str, tuple[str, ...]] = {
    "bugfix": ("bug",),
    "docs": ("documentation", "docs"),
    "feature": ("enhancement", "feature"),
    "tests": ("tests", "test", "coverage"),
    "refactor": ("refactor", "performance"),
}

COMPLEXITY_LABELS = ("high-complexity", "hard", "complex")

LANGUAGE_BOOST = 0.10
TYPE_BOOST = 0.08
RISK_PENALTY = -0.15
COLLAB_BOOST = 0.05
GUIDED_COMMENT_THRESHOLD = 3

#: Measured against real repos with `sentence-transformers/all-MiniLM-L6-v2`;
#: see the calibration table in `specs/agents/skill-matcher.md` for the
#: evidence. Retuning is a one-line change here, but do it from a fresh
#: measurement, not by feel.
CONFIDENT_SCORE = 0.32
MINIMUM_SCORE = 0.25
TOP_N = 5


def issue_text(issue: GoodFirstIssue) -> str:
    """The text embedded to represent an issue.

    Title plus labels. The spec also names the first 200 characters of the
    body, but `repo_facts` never carries bodies: the investigator's token
    budget forbids it. Labels are the closest available stand-in.
    """
    return ", ".join([issue.title, *issue.labels])


def apply_hard_filters(
    issues: list[GoodFirstIssue], interview: InterviewContext
) -> tuple[list[GoodFirstIssue], list[str]]:
    """Drop issues the developer's stated preferences exclude.

    Returns the survivors and the filters applied. An issue carrying no
    recognised type label survives: absent labels mean the repo does not use
    that vocabulary, not that the issue is unsuitable.
    """
    filters: list[str] = []
    types = [t for t in interview.contribution_types if t != "any"]
    if not types or "any" in interview.contribution_types:
        return list(issues), filters

    wanted = {label for t in types for label in TYPE_LABELS.get(t, ())}
    if not wanted:
        return list(issues), filters

    filters.append(f"contribution_types:{','.join(types)}")
    kept = [
        issue for issue in issues if not _recognised_type_labels(issue) or _labels(issue) & wanted
    ]
    return kept, filters


def score_adjustments(
    issue: GoodFirstIssue, developer: DeveloperContext, interview: InterviewContext
) -> dict[str, float]:
    """The spec's boost model, itemized so a recommendation can be explained."""
    labels = _labels(issue)
    haystack = f"{issue.title} {' '.join(issue.labels)}".lower()

    top_languages = [lang.lower() for lang in developer.languages[:3]]
    language_boost = LANGUAGE_BOOST if any(lang in haystack for lang in top_languages) else 0.0

    wanted = {
        label
        for t in interview.contribution_types
        if t != "any"
        for label in TYPE_LABELS.get(t, ())
    }
    type_boost = TYPE_BOOST if wanted & labels else 0.0

    risky = interview.risk_tolerance == "low" and bool(labels & set(COMPLEXITY_LABELS))
    risk_penalty = RISK_PENALTY if risky else 0.0

    guided = (
        interview.collaboration_style == "guided"
        and issue.comment_count >= GUIDED_COMMENT_THRESHOLD
    )
    collab_boost = COLLAB_BOOST if guided else 0.0

    return {
        "language_boost": language_boost,
        "interview_type_boost": type_boost,
        "risk_penalty": risk_penalty,
        "collab_boost": collab_boost,
    }


def build_rationale(
    issue: GoodFirstIssue,
    developer: DeveloperContext,
    interview: InterviewContext,
    issue_intelligence: IssueIntelligence | None = None,
) -> str:
    """Two sentences: one from the resume, one from the interview.

    When `repo-analyst` has read this specific issue, its own one-sentence
    technical summary replaces the generic interview-intent sentence: "add
    an asyncio-based client variant" says more than "matches your goal to
    build a portfolio" ever could, because it came from actually reading the
    issue body and its comments rather than restating what the developer
    already told the interview.
    """
    language = developer.languages[0] if developer.languages else "software"
    years = developer.years_experience
    experience = (
        f"You have {years} years of {language} experience." if years else f"You work in {language}."
    )
    if issue_intelligence is not None:
        return f"{experience} {issue_intelligence.summary}"
    intent = interview.intent_summary.rstrip(".") or "your stated goal"
    return f"{experience} Matches {intent[0].lower() + intent[1:]}."


def drop_stale_or_claimed(
    issues: list[GoodFirstIssue], repo_intelligence: RepoIntelligence | None
) -> tuple[list[GoodFirstIssue], list[str]]:
    """Remove issues `repo-analyst` read as already claimed or abandoned.

    A label or title-similarity signal has no way to know this; repo-analyst
    read the actual comment thread. Only acts on issues `repo_intelligence`
    covers - one with no matching entry (a stale cache, a repo analyzed
    before this issue was opened) is left in rather than dropped for missing
    data, since absence of a read is not evidence the issue is claimed.
    """
    if repo_intelligence is None:
        return list(issues), []
    stale_ids = repo_intelligence.stale_issue_ids
    if not stale_ids:
        return list(issues), []
    kept = [issue for issue in issues if issue.id not in stale_ids]
    filters = ["repo_intelligence:stale_or_claimed"] if len(kept) < len(issues) else []
    return kept, filters


def match_issues(
    developer_context: DeveloperContext | None,
    interview_context: InterviewContext | None,
    repo_facts: RepoFacts | None,
    *,
    embeddings: EmbeddingProvider,
    store: VectorStore | None = None,
    repo_intelligence: RepoIntelligence | None = None,
) -> tuple[TopMatch | None, list[str], list[TopMatch]]:
    """Rank candidate issues and return ``(top_match, filters, all_matches)``.

    `top_match` is None when nothing clears `MINIMUM_SCORE`. That is a
    contractual null, not a failure: `contribution-strategy-generator` renders
    a browse-manually section for it.

    `store` is optional. Ranking a single repo's candidates is a one-shot
    comparison against vectors built in this call, so a persistent index buys
    nothing; pass one to persist the issue vectors for reuse.

    `repo_intelligence` is optional too - it is a cache-backed enrichment
    from `repo-analyst` that may not have run yet for this repository. When
    present, it removes issues read as already claimed and replaces the
    generic rationale with `repo-analyst`'s own technical summary; its
    absence changes nothing about how a candidate is scored.
    """
    for key, value in (
        ("developer_context", developer_context),
        ("interview_context", interview_context),
        ("repo_facts", repo_facts),
    ):
        if value is None:
            raise MissingUpstreamOutput(agent="skill-matcher", key=key)

    assert developer_context and interview_context and repo_facts

    candidates, filters = apply_hard_filters(repo_facts.good_first_issues, interview_context)
    candidates, stale_filters = drop_stale_or_claimed(candidates, repo_intelligence)
    filters += stale_filters
    if not candidates:
        return None, filters, []

    if store is not None:
        require_matching_model(store, embeddings.model_id)

    texts = [profile_text(developer_context)] + [issue_text(i) for i in candidates]
    vectors = embeddings.embed(texts)
    developer_vector, issue_vectors = vectors[0], vectors[1:]

    if store is not None:
        store.upsert(
            [
                VectorRecord(id=f"issue:{issue.id}", vector=vector, metadata={"title": issue.title})
                for issue, vector in zip(candidates, issue_vectors, strict=True)
            ]
        )

    intelligence_by_id = {
        i.issue_id: i for i in (repo_intelligence.issues if repo_intelligence else [])
    }

    ranked: list[TopMatch] = []
    for issue, vector in zip(candidates, issue_vectors, strict=True):
        similarity = cosine_similarity(developer_vector, vector)
        adjustments = score_adjustments(issue, developer_context, interview_context)
        breakdown = {"semantic_similarity": round(similarity, 4), **adjustments}
        ranked.append(
            TopMatch(
                issue_id=issue.id,
                title=issue.title,
                url=issue.url,
                score=round(similarity + sum(adjustments.values()), 4),
                score_breakdown=breakdown,
                rationale=build_rationale(
                    issue, developer_context, interview_context, intelligence_by_id.get(issue.id)
                ),
            )
        )

    ranked.sort(key=lambda match: match.score, reverse=True)
    ranked = ranked[:TOP_N]

    best = ranked[0] if ranked else None
    if best is None or best.score < MINIMUM_SCORE:
        return None, filters, ranked
    return best, filters, ranked


def is_confident(match: TopMatch | None) -> bool:
    """Whether the spec would call this a confident match."""
    return match is not None and match.score > CONFIDENT_SCORE


def _labels(issue: GoodFirstIssue) -> set[str]:
    return {label.lower() for label in issue.labels}


def _recognised_type_labels(issue: GoodFirstIssue) -> set[str]:
    known = {label for labels in TYPE_LABELS.values() for label in labels}
    return _labels(issue) & known
