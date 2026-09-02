---
name: gh-change-delivery
description: Apply repository-scoped GitHub branch, commit, pull-request, review, and check procedure to one exact authorized delivery change. Use only when the owning Delivery/runtime layer has supplied exact work scope, readiness, repository identity, and authority.
---

# GitHub Change Delivery

Carry out one exact GitHub repository change without inventing branch policy, readiness, or completion.

## Require the change envelope

Require:

- exact `owner/repo`;
- exact owner-selected WorkItem/change reference;
- owner-produced approval/readiness when the consumer uses those states;
- immutable intended scope and acceptance criteria;
- applicable repository policy;
- explicit authority for every intended GitHub effect.

If any required value is missing or contradictory, report the responsible owner and stop.

## Resolve branching policy

Read [branching strategies](references/branching-strategies.md).

Consumer repository policy owns the strategy selection. Resolve branch behavior deterministically; do not choose a preferred workflow from model judgment.

Pass the exact repository, WorkItem/change inputs, repository-scoped consumer policy, and any permitted operation override to `scripts/resolve_branch_policy.py`. Treat a `blocked` result as an owner-attributed stop condition. Do not supplement missing semantics from a GitHub Project or model judgment.

Branch policy resolution returns an exact branch contract or a blocker. It never authorizes branch creation, commit, push, PR creation, review, merge, tag, release, or repository-setting changes.

## Apply the repository workflow

Within the resolved scope and granted authority, use the minimum GitHub operations required for the change. Preserve exact traceability between WorkItem/change, branch, commits, and PR.

Treat PR state, review decisions, checks, workflow runs, and merge state as observations/evidence. A merged PR does not itself prove acceptance criteria or canonical WorkItem completion.

## Handoff

Return exact repository, branch, commit, PR, review/check, and workflow references plus factual results and blockers to the owning runtime and `gh-delivery-reconciliation`.
