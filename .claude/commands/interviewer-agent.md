# Run Interviewer Agent

Conduct a short, focused pre-analysis discovery interview with the developer.
Run this **before** any repository analysis begins.

## Context
Read the session state and confirm `developer_context` is available (from the
resume-parser). If not, ask the user to run `/resume-parser` first.

## Interview Questions (ask sequentially, target < 90 seconds total)

**1. Contribution Goal** - ask the user to pick one:
- Learn new skills / explore the codebase → tag: `goal:learning`
- Build portfolio / showcase work → tag: `goal:portfolio`
- Support a project I use professionally → tag: `goal:professional`
- Land a job at this company → tag: `goal:career`
- Give back to open source → tag: `goal:altruism`

**2. Time Availability** - ask the user to pick one:
- < 5 hrs/week → tag: `time:light`
- 5–15 hrs/week → tag: `time:moderate`
- 15+ hrs/week → tag: `time:heavy`

**3. Contribution Type** - ask the user to pick one or more:
- Bug fixes → `type:bugfix`
- Documentation → `type:docs`
- New features → `type:feature`
- Tests / coverage → `type:tests`
- Refactoring → `type:refactor`
- Any → `type:any`

**4. Risk Tolerance** - ask the user to pick one:
- Stay in comfort zone → `risk:low`
- Some stretch is fine → `risk:medium`
- Challenge me! → `risk:high`

## Output

After collecting responses, produce this JSON and store it as `interview_context`:

```json
{
  "goal": "<tag>",
  "time_commitment": "<tag>",
  "contribution_types": ["<tag>", ...],
  "risk_tolerance": "<tag>",
  "collaboration_style": "any",
  "intent_summary": "<1 sentence summarising developer intent, ≤ 30 words>"
}
```

Confirm: "Got it! Here's what I captured: [repeat back key choices]"
Then tell the user to run `/github-repo-investigator` next.
