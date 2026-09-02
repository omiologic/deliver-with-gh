---
name: deliver-with-gh
description: Route GitHub-specific delivery work among work planning, change delivery, and delivery reconciliation using explicit delivery stage, owner-produced state, authority, and GitHub evidence. Use when GitHub is the delivery platform; use a narrower child skill when the GitHub stage is already known.
---

# Deliver With GitHub

Coordinate one GitHub-specific delivery responsibility without becoming a canonical state owner.

## Load the routing contract

Read [routing contract](references/routing-contract.md). Use
`scripts/route_delivery.py` when the lane must be selected or validated from a
Delivery stage, requested GitHub action, owner state, authority, references, or
unreconciled GitHub evidence.

## Route

Use explicit user intent, platform-neutral Delivery stage, owner-produced state, repository identity, and available GitHub evidence.

Select exactly one lane:

- `gh-work-planning` when bounded work needs to be projected into GitHub Issues and/or GitHub Projects.
- `gh-change-delivery` when one exact repository-scoped change is approved/ready by its owner and GitHub branch/PR work is authorized.
- `gh-delivery-reconciliation` when GitHub has produced Issue, Project, PR, review, check, workflow, or merge observations that must become attributable delivery evidence.
- Return to the platform-neutral Delivery router when no GitHub-specific operation is needed or the delivery stage itself is unresolved.

## Preserve boundaries

Do not infer canonical approval, readiness, completion, acceptance, deployment success, or release authority from GitHub state.

A GitHub Project may span multiple repositories. Require exact repository identity before any repository-scoped Issue, branch, commit, PR, check, or rule operation.

Hand off only the inputs required by the selected child skill. Skill selection does not authorize a GitHub mutation.

## Report

State the selected lane, exact Project/repository/work references supplied to it, and any missing owner-produced state or authority that blocks routing.
