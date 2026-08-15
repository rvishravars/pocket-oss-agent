---
name: resume-parser
description: >-
  Use this skill when the user asks to parse a developer's resume (PDF or
  pasted text) and extract a structured technical profile. Outputs languages,
  frameworks, tools, and seniority level as a structured "Developer Context"
  object for downstream skills (skill-matcher, contribution-strategy-generator).
---

# Resume Parser Skill

Extracts a structured developer profile from a resume. The output feeds into
the `skill-matcher` and `contribution-strategy-generator` skills.

## Prerequisites

- A resume is available as a PDF file path, pasted text, or a verbal summary
  from the user.

## Steps

1. **Get the Resume Text**
   - If given a PDF path, read it directly (the Read tool handles PDFs). If
     extraction looks garbled on a complex multi-column layout, fall back to
     a text extraction pass:
     ```bash
     pdftotext -layout resume.pdf -    # poppler
     python3 -c "import pypdf,sys; print('\n'.join(p.extract_text() for p in pypdf.PdfReader(sys.argv[1]).pages))" resume.pdf
     ```
     If neither is installed, ask the user to paste the resume text instead.
   - If given pasted text or a verbal summary, use it as-is.

2. **Structure the Profile**
   - From the resume text, extract:
     - Programming languages (list)
     - Frameworks and libraries (list)
     - Cloud/infra tools (list)
     - Years of experience (integer or range)
     - Seniority level: one of `[junior, mid, senior, staff]`
     - Domain expertise (e.g., backend, frontend, ML, DevOps)
   - Reason over the text yourself and produce the JSON below directly -
     no separate extraction call is needed.

3. **Validate the Output**
   - Ensure the JSON contains all required keys: `languages`, `frameworks`,
     `tools`, `years_experience`, `seniority`, `domain`.
   - If the resume is too sparse to fill a field confidently, use a
     reasonable inferred value and note the uncertainty rather than
     fabricating specifics.

4. **Hand Off**
   - Carry the `developer_context` JSON forward in the conversation for use
     by later phases (`interviewer-agent`, `skill-matcher`,
     `contribution-strategy-generator`). No database write is needed for
     this in-context version.

5. **Verify**
   - Confirm seniority + language list look correct given the source text.
   - Surface a one-line summary: `"Detected: [seniority] [domain] engineer
     skilled in [top 3 languages]"`.

## Output Schema

```json
{
  "languages": ["Python", "Java"],
  "frameworks": ["FastAPI", "Spring Boot"],
  "tools": ["Docker", "AWS", "GitHub Actions"],
  "years_experience": 5,
  "seniority": "mid",
  "domain": "backend"
}
```
