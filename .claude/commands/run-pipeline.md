# Run the pipeline against a real repository

Runs every implemented agent against a live repo and prints the roadmap.

## Usage
Target repository (`owner/name` or a URL): $ARGUMENTS

## Steps

1. Run the harness, defaulting to `pallets/flask` if `$ARGUMENTS` is empty:

   ```bash
   GITHUB_TOKEN="$(gh auth token)" ./.venv/bin/python scripts/run_pipeline.py <repo>
   ```

2. Read the output critically rather than just checking that it exited zero.
   Every significant bug in this codebase passed its mocked tests first and was
   caught by looking at real output. Specifically check:
   - Does any step read as something a user could paste into a terminal?
   - Are the numbers plausible against the repo's actual GitHub page?
   - Does any section claim a fact that no agent established?
   - Does the advice match the diagnosis, or contradict it?
   - Is anything marked verified that was never executed?

3. Try a repo unlike the last one: a monorepo, a dormant project, one with no
   beginner labels. The defects show up at the edges, not on the happy path.

4. If something is wrong, reproduce it as a failing test before fixing it, then
   fix the spec in the same change if the spec was wrong too.

`resume-parser` and `skill-matcher` are stand-ins inside the harness, so their
sections of the roadmap are not yet real output.
