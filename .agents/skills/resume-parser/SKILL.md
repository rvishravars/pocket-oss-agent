---
name: resume-parser
description: >-
  Use this skill when the user asks to parse a developer's PDF resume and extract
  a structured technical profile. Outputs languages, frameworks, tools, and seniority
  level as a structured "Developer Context" object for downstream agents.
---

# Resume Parser Skill

Extracts a structured developer profile from a PDF resume. The output feeds into
the `skill-matcher` and `contribution-strategy-generator` skills.

## Prerequisites

- A PDF resume file path or upload URL is available.
- An LLM with PDF reading capability or a PDF-to-text extraction tool is configured.

## Steps

1. **Extract Text from PDF**
   - If using a PDF library (e.g., `pdfplumber`, `PyMuPDF`), run:
     ```bash
     python scripts/extract_pdf.py <path-to-resume.pdf>
     ```
   - This outputs raw text to `artifacts/resume_raw.txt`.

2. **Prompt the LLM to Structure the Profile**
   - Send the raw text to the LLM with the following extraction prompt:
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

3. **Validate the Output**
   - Ensure the JSON contains all required keys: `languages`, `frameworks`, `tools`, `years_experience`, `seniority`, `domain`.
   - If any key is missing, re-prompt with the missing field explicitly requested.

4. **Store the Developer Context**
   - Save the structured JSON to the database as the `developer_context` for the current user session.
   - Optionally generate an embedding from the concatenated profile text and store it in pgvector.

5. **Verify**
   - Log the extracted profile and confirm seniority + language list look correct.
   - Surface a one-line summary: `"Detected: [seniority] [domain] engineer skilled in [top 3 languages]"`

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

## References

- [PDF extraction script](./scripts/extract_pdf.py)
- [Example parsed output](./examples/parsed_profile.json)
