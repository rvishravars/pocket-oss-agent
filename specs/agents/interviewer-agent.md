---
name: interviewer-agent
description: >-
  Use this skill when you need to conduct a short, targeted discovery
  interview with a developer before analyzing a repository or matching them
  to an issue. Clarifies goals, time availability, contribution preferences,
  and risk tolerance. Outputs a structured "Interview Context" object used by
  skill-matcher and contribution-strategy-generator.
---

# Interviewer Agent Skill

Conducts a short, focused interview with the developer to capture intent
signals that can't be derived from a resume alone. Runs **after** the
developer context is available (if any) and **before** matching them to an
issue.

## Prerequisites

- `developer_context` from `resume-parser` is available if it ran first
  (used to personalize question phrasing). Not required - the interview can
  run standalone if the user hasn't provided a resume.

## Interview Question Bank

Ask questions from the following categories, adapting phrasing to
`developer_context.seniority` where available (encouraging/simple for
junior, concise/peer-level for senior+).

### Category A: Contribution Goal (required)
> _"What's your primary goal for contributing to this project?"_

| Option | Tag |
|--------|-----|
| Learn new skills / explore the codebase | `goal:learning` |
| Build portfolio / showcase work | `goal:portfolio` |
| Support a project I use professionally | `goal:professional` |
| Land a job at this company | `goal:career` |
| Give back to open source | `goal:altruism` |

### Category B: Time Availability (required)
> _"How much time can you commit per week?"_

| Option | Tag |
|--------|-----|
| A few hours (< 5 hrs/week) | `time:light` |
| Part-time (5-15 hrs/week) | `time:moderate` |
| Near full-time (15+ hrs/week) | `time:heavy` |

### Category C: Contribution Type Preference (required, multi-select)
> _"What type of contribution are you most comfortable starting with?"_

| Option | Tag |
|--------|-----|
| Bug fixes | `type:bugfix` |
| Documentation | `type:docs` |
| New features | `type:feature` |
| Tests / code coverage | `type:tests` |
| Performance / refactoring | `type:refactor` |
| Any - surprise me! | `type:any` |

### Category D: Risk Tolerance (required)
> _"How do you feel about tackling unfamiliar code areas?"_

| Option | Tag |
|--------|-----|
| Stay in my comfort zone only | `risk:low` |
| Some stretch is fine | `risk:medium` |
| Challenge me! | `risk:high` |

### Category E: Collaboration Style (optional)
> _"Do you prefer issues where you work solo or ones with active discussion?"_

| Option | Tag |
|--------|-----|
| Solo - I'll figure it out | `collab:solo` |
| Active thread - I want guidance | `collab:guided` |
| No preference | `collab:any` |

## Steps

1. **Personalize the Opening**
   - Open with: _"Before I put together your roadmap, a few quick questions
     to tailor it."_ Adjust tone per seniority if known.

2. **Ask Questions**
   - Use the `AskUserQuestion` tool to present Categories A-D (batch what
     you can into one call; keep options to the tags above). Category E is
     optional - skip it unless the flow naturally invites it.
   - Allow multiple selections for Category C only.

3. **Collect and Tag Responses**
   - Map each answer to its corresponding tag from the tables above.
   - If the user skips a question, default to `type:any` / `time:moderate`
     as appropriate.

4. **Generate the Interview Context Object**
   - Assemble all tags into the structured output (see schema below).
   - Add a one-sentence natural-language `intent_summary` for use by the
     Strategy Generator, e.g.: _"Developer wants to build their portfolio
     with lightweight bug fixes, committing ~5 hrs/week, staying within
     familiar territory."_

5. **Hand Off**
   - Carry `interview_context` forward in the conversation for use by
     `skill-matcher` and `contribution-strategy-generator`.

6. **Verify**
   - Ensure all 4 required categories (A-D) have a non-null tag.
   - Confirm `intent_summary` is ≤ 30 words.

## Output Schema

```json
{
  "goal": "portfolio",
  "time_commitment": "light",
  "contribution_types": ["bugfix", "docs"],
  "risk_tolerance": "low",
  "collaboration_style": "guided",
  "intent_summary": "Developer wants to build their portfolio with lightweight bug fixes, committing ~5 hrs/week, staying within familiar territory."
}
```

## Downstream Consumers

| Skill | How it uses `interview_context` |
|-------|---------------------------------|
| `skill-matcher` | Filters issues by `contribution_types`; penalizes high-complexity issues if `risk:low` |
| `contribution-strategy-generator` | Reflects `goal` and `time_commitment` in roadmap header; adapts tone of the "Why you" rationale |
