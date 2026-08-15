---
name: calibrate-threshold
description: >-
  Use when introducing, changing, or debugging a numeric threshold or cutoff
  in this codebase, or when a scoring gate rejects everything or flags
  everything. Both thresholds in this system were wrong when first measured,
  so this encodes how to measure one against real data before trusting it.
  A development task, not something to run for a product user.
---

# Calibrating a threshold

A threshold written before the measurement is a guess. This repository has
shipped two that were wrong:

| Threshold | Written as | Measured | Consequence |
|-----------|-----------|----------|-------------|
| PR merge rate, "healthy" | 0.60 | flask merges 3 of 50 and is healthy | flags nearly every serious repo as high rejection risk |
| Issue similarity floor | 0.40 | best real match scored 0.3412 | the matcher never fires; every roadmap falls back to browse-manually |

Both were plausible numbers. Neither survived contact with data.

## Why they fail

Scores are scale-dependent on whatever produces them. Cosine similarity
depends on the embedding model; a merge rate depends on how the project uses
pull requests. A number carried over from a spec written before that choice
was made does not transfer, and it fails silently: the code runs, the output
looks well formed, and the gate is simply always open or always shut.

## How to calibrate

1. **Check the ordering separately from the cutoff.** These fail
   independently. The matcher ranks relevant issues above irrelevant ones
   cleanly and still returns nothing, because the cutoff sits above the whole
   range. A correct ranking says nothing about whether the gate is calibrated.
2. **Measure against real inputs**, not fixtures. Print the score for a
   handful of cases you can label yourself: clearly relevant, clearly
   irrelevant, and borderline.
3. **Read the spread, not one number.** Put the cutoff where the labelled
   classes actually separate.
4. **Confirm on the real path.** `/run-pipeline` against a real repository,
   and check the gate does what you intended.
5. **Record the measurement next to the number**, in the spec. The next person
   needs the evidence, not just the constant.

## Rules

- Keep every threshold in a named constant. Retuning must be a one-line change.
- Do not change a spec's number silently. Implement as specced, record the
  measurement, and let the owner decide. That is a product call.
- A stand-in that is not semantic proves nothing about a threshold.
  `DeterministicEmbeddings` hashes tokens; scores from it say nothing about
  where a real cutoff belongs.
