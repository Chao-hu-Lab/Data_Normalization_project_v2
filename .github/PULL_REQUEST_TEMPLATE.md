<!--
The PR body is the review unit. Under squash merge, commit messages evaporate —
this description is the only narrative that survives, for future-you, an agent
reviewer, and the evidence chain. Write decision-first: judgement before evidence.

Short PR? Cut to just "What & Why" + "Verification" and delete the rest — no N/A ritual.
Delete these comments and any section you don't use. No AI-signature footer.
If "What & Why" needs "and" to string together unrelated things, split the PR.
-->

## What & Why
<!-- What behaviour does this PR enable / change, in one paragraph. Why now. -->

## Changes
<!-- Behaviour-contract level, not a file list. Observable before vs after. -->

## Non-goals
<!-- What this deliberately does NOT do. Pre-empts "why no X" and future "was this missed". -->

## Public surface impact
<!-- CLI / config / schema / TSV columns / persisted identifiers / outputs — moved or not.
     Write "None" if nothing — that line is itself the check. -->

## Verification
<!-- What you actually ran and saw. Layered: unit/characterization; semantic
     (representative input -> output, paste key numbers); what's NOT verified + why + risk.
     Do not claim tests pass unless you ran them this round. -->

## Why not X
<!-- Considered-but-rejected paths, one line each. The highest-value section —
     in three months someone will reconsider X. -->

## Reviewer notes
<!-- Assumptions, known limits, where to look hardest. For large test-heavy PRs,
     put a risk-ordered review map here. Note stacked-PR base if applicable. -->
