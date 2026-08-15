# Run everything CI runs

Local equivalent of the CI workflow, in the order CI runs it.

```bash
./.venv/bin/ruff format --check .
./.venv/bin/ruff check .
./.venv/bin/pytest -q --cov
grep -rn "$(printf '\xe2\x80\x94')" --include='*.md' --include='*.py' \
     --exclude-dir=.git --exclude-dir=.venv .
```

- Coverage is gated at 100% of statements and branches in `pyproject.toml`.
  If a new branch is uncovered, prefer deleting the dead branch over writing a
  contrived test for it.
- The last command must print nothing. U+2014 is forbidden by `CLAUDE.md` and
  enforced by the `Doc rules` CI job.
- The byte escape `\xe2\x80\x94` avoids depending on `printf` supporting
  `\uHHHH`, which is not in every shell's builtin.
- Filter with `--exclude-dir`, never by piping to `grep -v './.git/'`.
  `grep -v` matches the whole output line, not just the path, so any line whose
  *content* mentions that path exempts itself. That is not hypothetical: this
  file used to do exactly that, the self-exemption hid a real violation, and the
  local check reported clean while CI failed on the same commit.
- The suite is fully offline. A test that reaches the network is a bug in the
  test, not a reason to set a token.
- Green here is necessary, not sufficient. Run `/run-pipeline` before trusting a
  change that touches agent behaviour.
