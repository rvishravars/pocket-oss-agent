"""resume-parser: build a developer profile from a PDF resume.

Implements `specs/agents/resume-parser.md`. Produces `developer_context` and,
when a store is supplied, the profile embedding `skill-matcher` searches
against.

The LLM call, the embedder and the store all arrive as injected collaborators,
so the pipeline is testable without an API key, a model download or a database.
"""

from __future__ import annotations

from pathlib import Path

from ..embeddings import EmbeddingProvider
from ..errors import ResumeUnreadable
from ..llm import ProfileExtractor
from ..state import DeveloperContext
from ..vector_store import VectorRecord, VectorStore, require_matching_model

#: Below this, extraction produces a confidently empty profile rather than
#: failing, which is worse than aborting. The usual cause is a scanned image
#: resume, where the page yields almost no extractable text and needs OCR.
MIN_RESUME_CHARS = 200


def extract_pdf_text(path: str | Path) -> str:
    """Return the text of a PDF resume.

    Aborts on a near-empty result instead of returning it. The spec calls this
    out because a scanned resume extracts to whitespace, and a profile built
    from whitespace looks like a real profile with unlucky formatting.
    """
    source = Path(path)
    if not source.exists():
        raise ResumeUnreadable(str(source), "file does not exist")

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a hard dependency
        raise ImportError('PDF parsing needs pypdf: pip install -e "."') from exc

    try:
        reader = PdfReader(str(source))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ResumeUnreadable(str(source), f"{type(exc).__name__}: {exc}") from exc

    return _require_enough_text(text, str(source))


def profile_text(context: DeveloperContext) -> str:
    """The text embedded to represent the developer.

    Skills only. Name, seniority and years are deliberately excluded: they add
    no signal about which issue suits this person, and a name in the vector
    would let unrelated candidates match each other.
    """
    parts = [*context.languages, *context.frameworks, *context.tools]
    if context.domain:
        parts.append(context.domain)
    return ", ".join(part for part in parts if part)


def parse_resume(
    resume_path: str | Path,
    extractor: ProfileExtractor,
    *,
    embeddings: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
    user_id: str | None = None,
) -> DeveloperContext:
    """Run the parser and return `developer_context`.

    Persisting the embedding is optional so the agent can run before any store
    exists. When a store is given, `embeddings` and `user_id` are required too:
    silently skipping the write would leave `skill-matcher` with nothing to
    search and no indication why.
    """
    return parse_resume_text(
        extract_pdf_text(resume_path),
        extractor,
        embeddings=embeddings,
        store=store,
        user_id=user_id,
    )


def parse_resume_text(
    text: str,
    extractor: ProfileExtractor,
    *,
    embeddings: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
    user_id: str | None = None,
) -> DeveloperContext:
    """As `parse_resume`, for text already extracted from a resume."""
    context = extractor.extract(_require_enough_text(text, "<text>"))
    if store is not None:
        if embeddings is None or user_id is None:
            raise ValueError("persisting a profile embedding needs both embeddings and user_id")
        _persist_profile(context, embeddings=embeddings, store=store, user_id=user_id)
    return context


def summarize(context: DeveloperContext) -> str:
    """The one-line confirmation the spec asks the UI to surface."""
    seniority = context.seniority or "unknown-seniority"
    domain = context.domain or "generalist"
    languages = ", ".join(context.languages[:3]) or "no listed languages"
    return f"Detected: {seniority} {domain} engineer skilled in {languages}"


def _persist_profile(
    context: DeveloperContext,
    *,
    embeddings: EmbeddingProvider,
    store: VectorStore,
    user_id: str,
) -> None:
    require_matching_model(store, embeddings.model_id)
    [vector] = embeddings.embed([profile_text(context)])
    store.upsert(
        [
            VectorRecord(
                id=f"developer:{user_id}",
                vector=vector,
                metadata={"user_id": user_id, "seniority": context.seniority},
            )
        ]
    )


def _require_enough_text(text: str, source: str) -> str:
    stripped = (text or "").strip()
    if len(stripped) < MIN_RESUME_CHARS:
        raise ResumeUnreadable(
            source,
            f"only {len(stripped)} characters of text were recoverable, "
            f"below the {MIN_RESUME_CHARS} needed. A scanned resume needs OCR first.",
        )
    return stripped
