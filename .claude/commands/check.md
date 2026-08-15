# Run everything CI runs

Local equivalent of the CI workflow, in the order CI runs it.

```bash
./.venv/bin/ruff format --check .
./.venv/bin/ruff check .
./.venv/bin/pytest -q --cov
grep -rn $'—' --include='*.md' --include='*.py' . | grep -v './.git/'
```

- Coverage is gated at 100% of statements and branches in `pyproject.toml`.
  If a new branch is uncovered, prefer deleting the dead branch over writing a
  contrived test for it.
- The last command must print nothing. The em dash is forbidden by `CLAUDE.md`
  and enforced by the `Doc rules` CI job.
- The suite is fully offline. A test that reaches the network is a bug in the
  test, not a reason to set a token.
- Green here is necessary, not sufficient. Run `/run-pipeline` before trusting a
  change that touches agent behaviour.
