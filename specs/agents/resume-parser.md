---
agent: resume-parser
position: 1
consumes: [resume_pdf]
produces: developer_context
tooling: pypdf, Claude structured outputs, pgvector
status: implemented
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
  "name": "Ada Okafor",
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
   - Backed by `pypdf`, called in process. There is no extraction script and no
     `artifacts/` file: the text goes straight to the extractor, so nothing has
     to be cleaned up and no stale intermediate can be read by mistake.
   - Abort if extraction yields fewer than 200 characters.
     A near-empty result usually means a scanned image resume, which needs OCR
     rather than a silent empty profile.

2. **Structure the profile with the LLM**
   - One `messages.parse()` call against `claude-opus-5` with a Pydantic schema
     attached. Not an agent loop: the inputs fully determine the output.
   - Check `stop_reason` before reading the parsed output. A refusal returns
     HTTP 200 with empty content, so reading the profile first turns a policy
     decline into an unrelated attribute error.
   - Send no sampling parameters; they are rejected on this model.
   - Send the raw text with the extraction prompt:
     ```
     You are a technical recruiter. From the resume text below, extract:
     - Full name of the candidate, or null if not clearly present
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
   - `name` is the one optional field.
     `contribution-strategy-generator` greets the developer by name in the
     roadmap header and drops the greeting when it is null, so an unparseable
     name must not fail an otherwise usable profile.

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
