---
name: interviewer-agent
description: >-
  Use this skill when the Interviewer Agent needs to conduct a dynamic,
  conversational discovery session with the developer before any repository
  analysis begins. Clarifies goals, time availability, contribution preferences,
  and risk tolerance. Outputs a structured "Interview Context" object passed
  to the Orchestrator Agent and downstream skill-matcher.
---

# Interviewer Agent Skill

Conducts a short, focused interview with the developer to capture intent signals
that cannot be derived from a resume alone. Runs **after** authentication and
resume upload but **before** repo analysis.

## Prerequisites

- Developer is authenticated (Google OAuth session is active).
- `developer_context` from `resume-parser` is available in session state
  (used to personalize question phrasing).
- UI supports a conversational/chat interface or a structured form flow.

## Interview Question Bank

Ask questions from the following categories. Adapt phrasing based on the
`developer_context` seniority where noted.

### Category A: Contribution Goal
> _"What's your primary goal for contributing to this project?"_

| Option | Tag |
|--------|-----|
| Learn new skills / explore the codebase | `goal:learning` |
| Build portfolio / showcase work | `goal:portfolio` |
| Support a project I use professionally | `goal:professional` |
| Land a job at this company | `goal:career` |
| Give back to open source | `goal:altruism` |

### Category B: Time Availability
> _"How much time can you commit per week?"_

| Option | Tag |
|--------|-----|
| A few hours (< 5 hrs/week) | `time:light` |
| Part-time (5–15 hrs/week) | `time:moderate` |
| Near full-time (15+ hrs/week) | `time:heavy` |

### Category C: Contribution Type Preference
> _"What type of contribution are you most comfortable starting with?"_

| Option | Tag |
|--------|-----|
| Bug fixes | `type:bugfix` |
| Documentation | `type:docs` |
| New features | `type:feature` |
| Tests / code coverage | `type:tests` |
| Performance / refactoring | `type:refactor` |
| Any - surprise me! | `type:any` |

### Category D: Risk Tolerance
> _"How do you feel about tackling unfamiliar code areas?"_

| Option | Tag |
|--------|-----|
| Stay in my comfort zone only | `risk:low` |
| Some stretch is fine | `risk:medium` |
| Challenge me! | `risk:high` |

### Category E: Collaboration Style (Optional)
> _"Do you prefer issues where you work solo or ones with active discussion?"_

| Option | Tag |
|--------|-----|
| Solo - I'll figure it out | `collab:solo` |
| Active thread - I want guidance | `collab:guided` |
| No preference | `collab:any` |

## Steps

1. **Personalize Opening**
   - Use `developer_context.seniority` to set tone:
     - `junior` → encouraging, simpler language
     - `senior/staff` → concise, peer-level tone
   - Opening: _"Before we dive in, a few quick questions to tailor your roadmap."_

2. **Ask Questions Sequentially**
   - Present Categories A → B → C → D in order. Category E is optional.
   - Use the UI's preferred modality (buttons for mobile, dropdown for desktop).
   - Allow multi-select for Category C only.
   - Target total interview time: **< 90 seconds**.

3. **Collect and Tag Responses**
   - Map each answer to its corresponding tag (see tables above).
   - If the user skips a question, assign the `any` or `medium` default.

4. **Generate Interview Context Object**
   - Assemble all tags into the structured output (see schema below).
   - Add a natural-language `intent_summary` (1 sentence) for use by the
     Strategy Generator.
   - Example: _"Developer wants to build their portfolio with lightweight bug
     fixes, committing ~5 hrs/week, staying within familiar territory."_

5. **Store and Hand Off**
   - Persist `interview_context` to the current session state.
   - Emit to the **Orchestrator Agent** to proceed with repo analysis.
   - The `interview_context` must be available to `skill-matcher` and
     `contribution-strategy-generator`.

6. **Verify**
   - Ensure all 4 mandatory categories (A–D) have a non-null tag.
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
| `contribution-strategy-generator` | Reflects `goal` and `time_commitment` in roadmap header; adapts tone of "Why you" rationale |

## References

- [Example interview transcripts](./examples/interview_transcripts.json)
- [Tag-to-filter mapping](./resources/tag_filter_map.json)
