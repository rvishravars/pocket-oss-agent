---
agent: resume-parser
position: 1
consumes: [resume_pdf]
produces: developer_context
tooling: PDF extraction, LLM, pgvector
---

# Resume Parser

Extracts a structured technical profile from an uploaded PDF resume.
Runs first in the pipeline, in parallel with `github-repo-investigator`.
Its output personalizes `interviewer-agent` and is a required input to
`skill-matcher` and `contribution-strategy-generator`.

## Inputs

| Source | Value |
|--------|-------|
| User upload | Path or object-store URL of the resume PDF |

Abort with a descriptive error if no resume is supplied.
The pipeline has no fallback profile.

## Output

Writes `developer_context` to the session state object.

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

## Steps

1. **Extract text from the PDF**
   - Run the extraction script over the uploaded file:
     ```bash
     python scripts/extract_pdf.py <path-to-resume.pdf>
     ```
   - Backed by `pdfplumber` or `PyMuPDF`.
   - Raw text is written to `artifacts/resume_raw.txt`.
   - Abort if extraction yields fewer than 200 characters.
     A near-empty result usually means a scanned image resume, which needs OCR
     rather than a silent empty profile.

2. **Structure the profile with the LLM**
   - Send the raw text with the extraction prompt:
     ```
     You are a technical recruiter. From the resume text below, extract:
     - Programming languages (list)
     - Frameworks and libraries (list)
     - Cloud/infra tools (list)
     - Years of experience (integer or range)
     - Seniority level: one of [junior, mid, senior, staff]
     - Domain expertise (e.g., backend, frontend, ML, DevOps)

     Return strictly as JSON. Resume: {resume_text}
     ```

3. **Validate the output**
   - Require all keys: `languages`, `frameworks`, `tools`, `years_experience`,
     `seniority`, `domain`.
   - Re-prompt once with the missing fields named explicitly.
   - Abort if the second attempt is still incomplete.

4. **Persist**
   - Store `developer_context` against the user session in Postgres.
   - Generate an embedding over the concatenated profile text and write it to
     the `developer_profiles` table.
   - The embedding model must match the one used for `repo_embeddings` and for
     issue embeddings in `skill-matcher`.
     A mismatch makes every similarity score meaningless.

5. **Verify**
   - Log the extracted profile.
   - Surface a one-line summary to the UI:
     `"Detected: [seniority] [domain] engineer skilled in [top 3 languages]"`

## References

- `scripts/extract_pdf.py`
- `examples/parsed_profile.json`
