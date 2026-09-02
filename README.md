# Deliver With GitHub

`deliver-with-gh` is a GitHub-specific delivery skill family that applies platform-neutral Delivery contracts to GitHub Projects, Issues, repositories, branches, pull requests, reviews, checks, and Actions evidence.

It complements [`omiologic/deliver-product`](https://github.com/omiologic/deliver-product). `deliver-product` defines the platform-neutral lifecycle; this repository defines how GitHub can project, perform, and evidence that lifecycle without becoming the canonical owner of Plan, WorkItem, Execution, or completion state.

## Skills

| Skill | Responsibility |
| --- | --- |
| `deliver-with-gh` | Thin GitHub delivery router. Selects the smallest GitHub-specific capability from explicit delivery state and requested effects. |
| `gh-work-planning` | Projects bounded delivery work into GitHub Issues and GitHub Projects, including Projects that coordinate Issues across multiple repositories. |
| `gh-change-delivery` | Applies repository-scoped branch, commit, pull-request, review, and check workflows to exact authorized work. |
| `gh-delivery-reconciliation` | Converts attributable GitHub evidence into criterion-level observations suitable for platform-neutral Delivery Reconciliation. |

The skill boundaries follow delivery reasoning, authority, and evidence—not GitHub API object types. Issues, Projects, branches, PRs, and Actions remain GitHub resources used by the applicable skill rather than becoming one skill each.

## Core model

```text
                    deliver-product
                          │
                  platform-neutral
                    Delivery contract
                          │
                          ▼
                  deliver-with-gh
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
       gh-work-       gh-change-   gh-delivery-
       planning       delivery     reconciliation
             │            │            │
             └────────────┼────────────┘
                          ▼
                      GitHub API
```

A GitHub Project is a cross-repository planning surface. It may contain Issues or draft items associated with many repositories. Repository identity therefore belongs on every repository-scoped work/change reference; never infer that a GitHub Project maps to exactly one repository.

```text
GitHub Project
├── repo-a Issue #12
├── repo-b Issue #44
├── repo-c Issue #8
└── draft coordination item
```

## Ownership rules

- GitHub Issue state is not canonical WorkItem state.
- GitHub Project status is not canonical Plan or WorkItem status.
- A merged PR does not imply that a WorkItem is complete.
- A successful Actions run is evidence, not acceptance.
- Branching policy is consumer-owned input; applying it never grants branch, commit, push, PR, merge, or release authority.
- GitHub operations require the authority of the user, owning runtime, or authorized operation that requested them.

## Consumer branching policy

`gh-change-delivery` includes a dependency-free deterministic branching-policy resolver. The consumer selects the strategy in its own policy or conventions; the skill resolves an exact branch contract rather than inventing workflow rules.

Initial strategies:

- `trunk` — operate from the configured integration/default branch according to consumer policy.
- `feature` — use one short-lived branch for one bounded change/WorkItem.
- `release` — use consumer-declared integration/release branches before the stable target.
- `custom` — require explicit consumer rules; do not infer missing behavior.

Branch policy is repository-scoped even when the surrounding GitHub Project spans multiple repositories.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for agent-facing architecture and authority boundaries.

## Status

This repository currently provides the initial contract scaffold and the `gh-change-delivery` branch-policy resolver with scenario fixtures. Additional GitHub API behavior, evidence normalization, package validation, installation tooling, and consumer integration are tracked as follow-up issues.
