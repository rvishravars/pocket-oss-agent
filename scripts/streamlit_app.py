#!/usr/bin/env python3
"""Streamlit demo UI: a thin client over the FastAPI surface in `api.py`.

Drives the pipeline through the same four HTTP endpoints a real caller would
use, so this exercises the actual running service rather than calling the
graph directly. No auth, no persistence, one browser tab, one session.

A dev tool verified by running it, like `run_pipeline.py`, not by the pytest
suite, so it lives in `scripts/` rather than the package the coverage gate
tracks.

    uvicorn pocket_oss_agent.api:create_app --factory --reload
    streamlit run scripts/streamlit_app.py
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import httpx
import streamlit as st

from pocket_oss_agent.agents.resume_parser import extract_pdf_text
from pocket_oss_agent.errors import ResumeUnreadable

API_BASE_URL = os.environ.get("POCKET_OSS_API_URL", "http://localhost:8000")
SESSION_KEYS = ("session_id", "status", "interview", "roadmap", "matched_issue_id")

_ORDERED_ITEM = re.compile(r"^(\d+)\.\s+(.*)$")
_BLOCKQUOTE_LINE = re.compile(r"^>\s*(.*)$")


def _defuse_lists_and_quotes(markdown_text: str) -> str:
    """Rewrite numbered lists and blockquotes as plain paragraphs.

    fpdf2's `write_html` mis-renders both for this content: `<ol>` numbers
    overlap the item text when an item contains inline `<code>`, and
    `<blockquote>` leaves a large stray gap after a preceding heading. Neither
    reproduces without the exact markdown this roadmap generates, and both
    disappear once the tag is avoided - so avoid it here rather than fight the
    library's HTML layout engine for a demo export.
    """
    out: list[str] = []
    for line in markdown_text.splitlines():
        ordered = _ORDERED_ITEM.match(line)
        quote = _BLOCKQUOTE_LINE.match(line)
        if ordered:
            out.append(f"**{ordered.group(1)}.** {ordered.group(2)}")
            out.append("")
        elif quote:
            content = quote.group(1).strip()
            out.append(f"_{content}_" if content else "")
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def roadmap_to_pdf_bytes(markdown_text: str) -> bytes:
    """Render the roadmap Markdown to a one-page PDF.

    Needs the `pdf` extra. The core Helvetica font is Latin-1 only, and the
    roadmap's headers and status marks are emoji, so those are dropped rather
    than crashing the export - the text they decorate already carries the
    meaning (e.g. "First Mile Setup" without the leading rocket).
    """
    try:
        import markdown as md
        from fpdf import FPDF
        from fpdf.fonts import TextStyle
    except ImportError as exc:
        raise ImportError('PDF export needs the "pdf" extra: pip install -e ".[pdf]"') from exc

    # Dropping each emoji glyph leaves the space(s) that surrounded it, so
    # collapse runs of spaces/tabs the removal creates (not newlines, which
    # still separate list items and blockquote lines below).
    latin1_only = re.sub(r"[ \t]{2,}", " ", "".join(c for c in markdown_text if ord(c) <= 0xFF))
    html = md.markdown(_defuse_lists_and_quotes(latin1_only), extensions=["extra"])

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.write_html(
        html,
        li_prefix_color=0,
        tag_styles={
            "h1": TextStyle(
                font_family="Helvetica",
                font_style="B",
                font_size_pt=20,
                color=0,
                t_margin=0,
                b_margin=3,
            ),
            "h2": TextStyle(
                font_family="Helvetica",
                font_style="B",
                font_size_pt=14,
                color=0,
                t_margin=5,
                b_margin=2,
            ),
            "li": TextStyle(
                font_family="Helvetica",
                font_size_pt=11,
                color=0,
                l_margin=8,
                t_margin=0,
                b_margin=1,
            ),
            "p": TextStyle(
                font_family="Helvetica", font_size_pt=11, color=0, t_margin=0, b_margin=2
            ),
            "code": TextStyle(font_family="Courier", font_size_pt=10, color=0),
        },
    )
    return bytes(pdf.output())


def pdf_filename(roadmap_markdown: str) -> str:
    """`roadmap-{repo}.pdf`, falling back to a generic name if the heading is missing."""
    match = re.search(r"^# OSS Contribution Roadmap: (.+)$", roadmap_markdown, re.MULTILINE)
    slug = match.group(1).replace("/", "-") if match else "roadmap"
    return f"roadmap-{slug}.pdf"


st.set_page_config(page_title="Pocket OSS Agent", page_icon="🚀", layout="centered")
st.title("🚀 Pocket OSS Agent")
st.caption("Drop a resume, pick a repo, get a one-page contribution roadmap.")

with st.sidebar:
    st.subheader("Backend")
    st.code(API_BASE_URL, language=None)
    st.caption("Start it with: `uvicorn pocket_oss_agent.api:create_app --factory`")
    st.caption("Override with the POCKET_OSS_API_URL environment variable.")


def reset() -> None:
    for key in SESSION_KEYS:
        st.session_state.pop(key, None)


def request(method: str, path: str, **kwargs) -> httpx.Response | None:
    """One HTTP call, surfaced as an `st.error` instead of a traceback.

    A dead backend or a pipeline error (422/409) are both things a demo user
    hits constantly; neither should crash the script.
    """
    try:
        with httpx.Client(base_url=API_BASE_URL, timeout=60) as client:
            response = client.request(method, path, **kwargs)
    except httpx.ConnectError:
        st.error(f"Can't reach the API at {API_BASE_URL}. Is uvicorn running?")
        return None

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        st.error(detail)
        return None
    return response


if "session_id" not in st.session_state:
    st.subheader("1. Start a session")
    repo_url = st.text_input("GitHub repository", placeholder="octocat/Hello-World")
    user_id = st.text_input("Your name or handle", value="anonymous")

    tab_paste, tab_upload = st.tabs(["Paste resume text", "Upload PDF"])
    with tab_paste:
        resume_text = st.text_area("Resume text", height=200)
    with tab_upload:
        uploaded = st.file_uploader("Resume PDF", type=["pdf"])
        uploaded_text = None
        if uploaded is not None:
            # Extracted here, in the UI process, rather than sent to the API
            # as a path: `resume_path` means a path on the API's own
            # filesystem, and the UI and the API are separate containers
            # under Docker Compose, not one shared machine.
            tmp = Path(tempfile.gettempdir()) / f"pocket-oss-agent-{uploaded.name}"
            tmp.write_bytes(uploaded.getvalue())
            try:
                uploaded_text = extract_pdf_text(tmp)
            except ResumeUnreadable as exc:
                st.error(str(exc))
            else:
                st.caption(f"Using uploaded file: {uploaded.name}")

    if st.button("Start", type="primary", disabled=not repo_url):
        payload: dict[str, str] = {"repo_url": repo_url, "user_id": user_id or "anonymous"}
        if uploaded_text:
            payload["resume_text"] = uploaded_text
        elif resume_text:
            payload["resume_text"] = resume_text
        else:
            st.error("Paste resume text or upload a PDF first.")
            st.stop()

        with st.spinner("Parsing the resume and investigating the repo..."):
            response = request("POST", "/sessions", json=payload)
        if response is not None:
            body = response.json()
            st.session_state["session_id"] = body["session_id"]
            st.session_state["status"] = body["status"]
            st.session_state["interview"] = body.get("interview")
            st.rerun()

else:
    session_id = st.session_state["session_id"]
    st.button("Start over", on_click=reset)

    if st.session_state["status"] == "awaiting_interview":
        interview = st.session_state["interview"]
        st.subheader("2. A few quick questions")
        st.write(interview["opening"])

        with st.form("interview_form"):
            answers: dict[str, str | list[str]] = {}
            for question in interview["questions"]:
                label = question["prompt"] + ("" if question["required"] else " (optional)")
                options = {opt["label"]: opt["value"] for opt in question["options"]}
                if question["multi_select"]:
                    # A radio always starts with the first option selected, so
                    # only a multiselect can be submitted empty - mark it.
                    if question["required"]:
                        label += " *"
                    chosen = st.multiselect(label, list(options))
                    answers[question["key"]] = [options[c] for c in chosen]
                else:
                    chosen = st.radio(label, list(options))
                    answers[question["key"]] = options[chosen]
            submitted = st.form_submit_button("Submit answers", type="primary")

        if submitted:
            # The API rejects an empty required answer too, but only after a
            # round trip and with a message that does not say which widget to
            # fix. A multiselect starts empty with no visual cue that it is
            # required, so this is the easiest question to skip by accident.
            unanswered = [
                question["prompt"]
                for question in interview["questions"]
                if question["required"] and not answers[question["key"]]
            ]
            if unanswered:
                st.error("Please answer: " + "; ".join(unanswered))
            else:
                with st.spinner("Matching issues and generating the roadmap..."):
                    response = request(
                        "POST", f"/sessions/{session_id}/interview", json={"answers": answers}
                    )
                if response is not None:
                    st.session_state["status"] = response.json()["status"]
                    st.rerun()

    if st.session_state["status"] == "complete" and "roadmap" not in st.session_state:
        response = request("GET", f"/sessions/{session_id}/roadmap")
        if response is not None:
            body = response.json()
            st.session_state["roadmap"] = body["roadmap"]
            st.session_state["matched_issue_id"] = body["matched_issue_id"]
            st.rerun()

    if "roadmap" in st.session_state:
        st.subheader("3. Your roadmap")
        if st.session_state["matched_issue_id"] is None:
            st.warning(
                "None of this repo's beginner-friendly issues were a strong "
                "match for this profile, so the roadmap falls back to the "
                "browse-manually recommendation. This is expected for some "
                "repos - see specs/agents/skill-matcher.md for how the "
                "matching floor was calibrated against real data."
            )
        st.markdown(st.session_state["roadmap"])

        try:
            pdf_bytes = roadmap_to_pdf_bytes(st.session_state["roadmap"])
        except ImportError as exc:
            st.caption(f"PDF export unavailable: {exc}")
        else:
            st.download_button(
                "📄 Export as PDF",
                data=pdf_bytes,
                file_name=pdf_filename(st.session_state["roadmap"]),
                mime="application/pdf",
            )
