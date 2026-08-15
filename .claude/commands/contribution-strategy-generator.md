# Generate Contribution Strategy

Synthesize all upstream outputs into the final one-page OSS contribution roadmap.

## Prerequisites
All 6 inputs must be present in session state. Abort with a clear error if any is missing:
- `developer_context` (from `/resume-parser`)
- `interview_context` (from `/interviewer-agent`)
- `repo_facts` (from `/github-repo-investigator`)
- `setup_steps` (from `/env-setup-validator`)
- `vibe_summary` (from `/repo-vibe-checker`)
- `top_match` (from `/skill-matcher`)

## Output Format

Generate a Markdown document with **exactly these 4 sections**. Total ≤ 60 lines.

```markdown
# OSS Contribution Roadmap: {repo_name}
> Generated for {developer_name} · {seniority} {domain} engineer
> 🎯 Goal: {interview_context.goal} · ⏱️ Availability: {interview_context.time_commitment}

## 🗺️ Architecture Snapshot
- `{dir}/` — {description}
[3–5 bullets from repo_facts.architecture_snapshot]

## 🚀 First Mile Setup
[numbered list from setup_steps — mark each ✅ validated or ⚠️ unverified]
[if time:light — prepend each step with estimated time e.g. `~2 min`]

## 🎯 Your First Contribution
**Issue:** [{top_match.title}]({top_match.url})
**Why you:** {top_match.rationale}
[if goal:learning — add: "**What you'll learn:** ..."]
[if goal:career — add: "**Career signal:** ..."]
[if risk:low — open with: "This is a well-scoped, low-risk issue ideal for getting familiar with the codebase."]

## 💬 Vibe Check
{vibe_summary.text}
```

## Tone Adaptations
Apply at least one based on `interview_context`:
- `goal:learning` → add "What you'll learn" callout
- `goal:career` → add "How this helps your job search" callout
- `time:light` → prepend each setup step with estimated time
- `risk:low` → open Target section with a reassurance line

## Verification
Before outputting, confirm:
- [ ] All 4 sections present
- [ ] Total line count ≤ 60 (truncate with `…` if needed)
- [ ] Issue URL starts with `https://`
- [ ] Header includes `goal` and `time_commitment`
- [ ] At least one tone adaptation applied
