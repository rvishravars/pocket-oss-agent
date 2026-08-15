# Parse Resume

Extract a structured developer profile from a PDF resume file.

## Usage
Provide the path to the PDF resume: $ARGUMENTS

## Steps

1. Read the file at the path provided in `$ARGUMENTS`.
   If no path is given, ask the user: "Please provide the path to your PDF resume."

2. Extract the following from the resume text:
   - **Programming languages** (list)
   - **Frameworks and libraries** (list)
   - **Cloud / infra tools** (list)
   - **Years of experience** (integer or range)
   - **Seniority level**: one of `junior`, `mid`, `senior`, `staff`
   - **Domain expertise**: e.g. `backend`, `frontend`, `ml`, `devops`, `fullstack`

3. If any field is ambiguous, make a reasonable inference and note it.

4. Output the structured profile as JSON and store it as `developer_context`:

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

5. Print a one-line summary:
   `"Detected: [seniority] [domain] engineer skilled in [top 3 languages]"`

6. Tell the user to run `/interviewer-agent` next.
