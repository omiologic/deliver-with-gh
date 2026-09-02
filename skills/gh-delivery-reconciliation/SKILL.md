---
name: gh-delivery-reconciliation
description: Normalize GitHub Project, Issue, pull-request, review, check, workflow, and merge observations into attributable criterion-level evidence for platform-neutral Delivery Reconciliation. Use after GitHub activity produces evidence that must be compared with delivery expectations.
---

# GitHub Delivery Reconciliation

Turn GitHub observations into evidence without treating GitHub state as canonical completion.

## Gather exact references

Use exact repository, Issue, Project item, PR, commit, review, check, workflow-run, artifact, and canonical WorkItem/Plan references when available. Preserve provenance and distinguish repository-scoped evidence from cross-repository Project metadata.

## Normalize evidence

Read [evidence normalization contract](references/evidence-normalization-contract.md).
Pass exact criteria, GitHub observations, and consumer-required evidence to
`scripts/normalize_github_evidence.py`. Preserve its criterion coverage and
provenance boundaries when handing the result to platform-neutral reconciliation.

For each applicable acceptance criterion, report supporting, contradicting, or missing GitHub evidence.

Examples:

- merged PR: change-integration observation;
- approved required review: review evidence;
- successful unit-check job: supporting test evidence for the bounded behavior it actually covers;
- failed integration workflow: contradicting evidence;
- closed Issue or Project status `Done`: planning projection state, not completion proof;
- skipped/missing workflow: missing evidence when that workflow is required by the criterion or consumer policy.

Do not claim broader proof than an artifact or check actually establishes.

## Handoff to Delivery Reconciliation

Return criterion-level evidence, gaps, conflicts, drift, and exact GitHub references to the platform-neutral `delivery-reconciliation` skill or responsible owner.

Do not select canonical WorkItem/Plan state, silently reopen/retry GitHub work, or infer `SUCCESS` solely from merge, Issue closure, Project status, or workflow success.
