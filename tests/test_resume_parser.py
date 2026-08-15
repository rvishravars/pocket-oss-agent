"""Coverage for resume parsing, PDF extraction, and profile persistence."""

import pytest

from pocket_oss_agent.agents.resume_parser import (
    MIN_RESUME_CHARS,
    extract_pdf_text,
    parse_resume,
    parse_resume_text,
    profile_text,
    summarize,
)
from pocket_oss_agent.embeddings import DeterministicEmbeddings
from pocket_oss_agent.errors import EmbeddingModelMismatch, ResumeUnreadable
from pocket_oss_agent.state import DeveloperContext
from pocket_oss_agent.vector_store import InMemoryVectorStore

RESUME = (
    "Ada Okafor. Senior backend engineer with 8 years building distributed systems. "
    "Languages: Python, Go, Rust. Frameworks: FastAPI, Django, gRPC. "
    "Infrastructure: Docker, Kubernetes, AWS, Terraform. "
    "Led the migration of a monolith to event-driven services handling 40k requests per second."
)


class FakeExtractor:
    """Stands in for the Claude call."""

    def __init__(self, context: DeveloperContext | None = None) -> None:
        self.context = context or DeveloperContext(
            name="Ada Okafor",
            languages=["Python", "Go", "Rust"],
            frameworks=["FastAPI", "Django"],
            tools=["Docker", "AWS"],
            years_experience=8,
            seniority="senior",
            domain="backend",
        )
        self.seen: list[str] = []

    def extract(self, resume_text: str) -> DeveloperContext:
        self.seen.append(resume_text)
        return self.context


def write_pdf(path, pages: list[str]) -> str:
    """Build a real PDF so extraction is tested against the actual format."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in pages:
        # add_blank_page already appends; calling add_page on the result too
        # creates a cyclic page reference that pypdf refuses to read back.
        writer.add_blank_page(width=612, height=792)
    target = str(path)
    with open(target, "wb") as handle:
        writer.write(handle)
    return target


class TestExtractPdfText:
    def test_missing_file_names_the_path(self, tmp_path) -> None:
        with pytest.raises(ResumeUnreadable, match="does not exist"):
            extract_pdf_text(tmp_path / "nope.pdf")

    def test_a_non_pdf_is_reported_not_crashed(self, tmp_path) -> None:
        junk = tmp_path / "resume.pdf"
        junk.write_bytes(b"this is not a pdf")
        with pytest.raises(ResumeUnreadable) as excinfo:
            extract_pdf_text(junk)
        assert "resume.pdf" in str(excinfo.value)

    def test_a_text_free_pdf_aborts_rather_than_returning_nothing(self, tmp_path) -> None:
        """A scanned resume extracts to whitespace; a profile built from that
        looks like a real profile with unlucky formatting.
        """
        blank = write_pdf(tmp_path / "scan.pdf", ["", ""])
        with pytest.raises(ResumeUnreadable, match="OCR"):
            extract_pdf_text(blank)


class TestParseResumeText:
    def test_returns_the_extracted_profile(self) -> None:
        extractor = FakeExtractor()
        context = parse_resume_text(RESUME, extractor)

        assert context.name == "Ada Okafor"
        assert context.seniority == "senior"
        assert extractor.seen == [RESUME]

    def test_rejects_text_below_the_floor(self) -> None:
        with pytest.raises(ResumeUnreadable, match=str(MIN_RESUME_CHARS)):
            parse_resume_text("Ada Okafor, engineer.", FakeExtractor())

    def test_whitespace_does_not_count_toward_the_floor(self) -> None:
        with pytest.raises(ResumeUnreadable):
            parse_resume_text(" " * 5000, FakeExtractor())

    def test_text_is_stripped_before_extraction(self) -> None:
        extractor = FakeExtractor()
        parse_resume_text(f"\n\n  {RESUME}  \n", extractor)
        assert extractor.seen[0] == RESUME


class TestProfileText:
    def test_embeds_skills_only(self) -> None:
        """Name, seniority and years carry no signal about issue fit, and a name
        in the vector would let unrelated candidates match each other.
        """
        text = profile_text(FakeExtractor().context)

        assert "Python" in text and "FastAPI" in text and "Docker" in text
        assert "Ada" not in text
        assert "senior" not in text
        assert "8" not in text

    def test_survives_an_empty_profile(self) -> None:
        assert profile_text(DeveloperContext()) == ""


class TestPersistence:
    def test_writes_the_profile_vector(self) -> None:
        embeddings = DeterministicEmbeddings(dimensions=64)
        store = InMemoryVectorStore(model_id=embeddings.model_id)

        parse_resume_text(RESUME, FakeExtractor(), embeddings=embeddings, store=store, user_id="u1")

        assert len(store) == 1
        hits = store.search(embeddings.embed([profile_text(FakeExtractor().context)])[0])
        assert hits[0].id == "developer:u1"
        assert hits[0].score == pytest.approx(1.0)

    def test_a_store_without_a_user_id_is_an_error_not_a_silent_skip(self) -> None:
        """Skipping the write would leave skill-matcher with nothing to search
        and no indication why.
        """
        embeddings = DeterministicEmbeddings(dimensions=64)
        store = InMemoryVectorStore(model_id=embeddings.model_id)

        with pytest.raises(ValueError, match="user_id"):
            parse_resume_text(RESUME, FakeExtractor(), embeddings=embeddings, store=store)

    def test_a_store_without_embeddings_is_an_error(self) -> None:
        store = InMemoryVectorStore(model_id="anything")
        with pytest.raises(ValueError, match="embeddings"):
            parse_resume_text(RESUME, FakeExtractor(), store=store, user_id="u1")

    def test_mismatched_embedding_models_abort_before_writing(self) -> None:
        embeddings = DeterministicEmbeddings(dimensions=64)
        store = InMemoryVectorStore(model_id="text-embedding-004")

        with pytest.raises(EmbeddingModelMismatch) as excinfo:
            parse_resume_text(
                RESUME, FakeExtractor(), embeddings=embeddings, store=store, user_id="u1"
            )

        assert "text-embedding-004" in str(excinfo.value)
        assert len(store) == 0

    def test_no_store_means_no_persistence_requirement(self) -> None:
        assert parse_resume_text(RESUME, FakeExtractor()).name == "Ada Okafor"


class TestParseResumeFromPdf:
    def test_reports_an_unreadable_pdf_without_calling_the_model(self, tmp_path) -> None:
        extractor = FakeExtractor()
        junk = tmp_path / "resume.pdf"
        junk.write_bytes(b"not a pdf")

        with pytest.raises(ResumeUnreadable):
            parse_resume(junk, extractor)

        assert extractor.seen == []


class TestSummarize:
    def test_reads_as_the_spec_describes(self) -> None:
        assert summarize(FakeExtractor().context) == (
            "Detected: senior backend engineer skilled in Python, Go, Rust"
        )

    def test_degrades_when_fields_are_missing(self) -> None:
        summary = summarize(DeveloperContext())
        assert "unknown-seniority" in summary
        assert "generalist" in summary
        assert "no listed languages" in summary


class TestParseResumeEndToEnd:
    def test_reads_a_real_pdf_and_persists_the_profile(self, tmp_path) -> None:
        """Exercises the whole agent: PDF bytes in, vector out."""
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        target = tmp_path / "resume.pdf"
        pdf = canvas.Canvas(str(target), pagesize=letter)
        y = 740
        for line in RESUME.split(". "):
            pdf.drawString(60, y, line)
            y -= 16
        pdf.save()

        embeddings = DeterministicEmbeddings(dimensions=64)
        store = InMemoryVectorStore(model_id=embeddings.model_id)
        extractor = FakeExtractor()

        context = parse_resume(target, extractor, embeddings=embeddings, store=store, user_id="u9")

        assert context.name == "Ada Okafor"
        assert "Ada Okafor" in extractor.seen[0]
        assert len(store) == 1
        assert store.search(embeddings.embed(["Python Go Rust"])[0])[0].id == "developer:u9"

    def test_a_pdf_path_with_a_store_still_requires_a_user_id(self, tmp_path) -> None:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        target = tmp_path / "resume.pdf"
        pdf = canvas.Canvas(str(target), pagesize=letter)
        y = 740
        for line in RESUME.split(". "):
            pdf.drawString(60, y, line)
            y -= 16
        pdf.save()

        embeddings = DeterministicEmbeddings(dimensions=32)
        store = InMemoryVectorStore(model_id=embeddings.model_id)

        with pytest.raises(ValueError, match="user_id"):
            parse_resume(target, FakeExtractor(), embeddings=embeddings, store=store)
