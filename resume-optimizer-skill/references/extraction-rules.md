# Extraction Rules

## Project boundary heuristics
High-confidence signals: explicit project title, new date range, new role, section heading, strong entity shift. Repeated technologies alone are not enough.

## Key-point granularity
A useful point should answer one interviewable question. Avoid splitting one statement into tiny technology-name points, and avoid merging architecture, reliability, and outcomes into one vague summary.

## Multi-chunk evidence
Merge evidence when several source fragments jointly establish one fact. If the normalized fact is specifically about one subsystem, only attach chunks that support that subsystem.

## Evidence quote rules
Use the smallest useful original span; never paraphrase inside `quote`; put explanation in `support`; keep 1-6 evidence chunks per point by default.

## Conflict handling
If chunks conflict, do not silently choose one. Lower confidence, add a warning, and preserve conflicting evidence when useful.

## Missing information
Do not infer team size, exact ownership, performance gains, production scale, deployment status, or metrics unless stated by evidence.
