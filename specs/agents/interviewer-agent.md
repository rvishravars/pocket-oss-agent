---
agent: interviewer-agent
position: 2
consumes: [developer_context]
produces: interview_context
tooling: UI chat or form flow
---

# Interviewer Agent

Conducts a short discovery interview capturing intent signals that cannot be
derived from a resume.
Runs after `resume-parser` and before `skill-matcher`.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `developer_context` | `resume-parser` | Yes |

Abort with a descriptive error if `developer_context` is absent.
Question phrasing is personalized from `developer_context.seniority`, and an
un-personalized interview is not an acceptable silent fallback.

## Output

Writes `interview_context` to the session state object.

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

## Question Bank

Categories A through D are mandatory.
Category E is optional.

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
| Part-time (5-15 hrs/week) | `time:moderate` |
| Near full-time (15+ hrs/week) | `time:heavy` |

### Category C: Contribution Type Preference (multi-select)
> _"What type of contribution are you most comfortable starting with?"_

| Option | Tag |
|--------|-----|
| Bug fixes | `type:bugfix` |
| Documentation | `type:docs` |
| New features | `type:feature` |
| Tests / code coverage | `type:tests` |
| Performance / refactoring | `type:refactor` |
| Any, surprise me | `type:any` |

### Category D: Risk Tolerance
> _"How do you feel about tackling unfamiliar code areas?"_

| Option | Tag |
|--------|-----|
| Stay in my comfort zone only | `risk:low` |
| Some stretch is fine | `risk:medium` |
| Challenge me | `risk:high` |

### Category E: Collaboration Style (optional)
> _"Do you prefer issues where you work solo or ones with active discussion?"_

| Option | Tag |
|--------|-----|
| Solo, I'll figure it out | `collab:solo` |
| Active thread, I want guidance | `collab:guided` |
| No preference | `collab:any` |

## Steps

1. **Personalize the opening**
   - Set tone from `developer_context.seniority`:
     - `junior` gets encouraging, simpler language.
     - `senior` and `staff` get concise, peer-level phrasing.
   - Opening line: _"Before we dive in, a few quick questions to tailor your roadmap."_

2. **Ask questions sequentially**
   - Present A, B, C, D in order. E is optional.
   - Use the UI's preferred modality: buttons on mobile, dropdown on desktop.
   - Multi-select applies to Category C only.
   - Target total interview time under 90 seconds.

3. **Collect and tag responses**
   - Map each answer to its tag from the tables above.
   - A skipped optional Category E defaults to `collab:any`.
   - A skipped mandatory category is a validation error, not a default.
     Re-prompt for it.

4. **Assemble the interview context**
   - Add a natural-language `intent_summary` of at most 30 words for the
     Strategy Generator.

5. **Verify and hand off**
   - All four mandatory categories carry a non-null tag.
   - `intent_summary` is at most 30 words.
   - Write `interview_context` to session state for `skill-matcher` and
     `contribution-strategy-generator`.

## Downstream Consumers

| Agent | Use |
|-------|-----|
| `skill-matcher` | Hard-filters issues by `contribution_types`; penalizes complexity when `risk:low` |
| `contribution-strategy-generator` | Reflects `goal` and `time_commitment` in the header; adapts the "Why you" rationale |

## References

- `examples/interview_transcripts.json`
- `resources/tag_filter_map.json`
