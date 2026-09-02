---
name: gh-work-planning
description: Project bounded delivery work into GitHub Issues and GitHub Projects while preserving exact repository and canonical work references. Use when GitHub is the planning surface, including Projects that coordinate work across multiple repositories.
---

# GitHub Work Planning

Represent bounded delivery work in GitHub without turning GitHub planning state into canonical Delivery state.

## Load the projection contract

For Issue, draft-item, Project metadata, field-mapping, or idempotence work,
read [references/work-projection-contract.md](references/work-projection-contract.md).
Use `scripts/resolve_work_projection.py` to produce a deterministic desired
projection and bounded mapping blockers before performing any authorized GitHub
operation.

## Require explicit scope

Use the bounded planning output supplied by the platform-neutral Delivery layer or responsible owner. Preserve exact Plan and WorkItem references when available.

Treat GitHub Project identity and repository identity independently. A single Project may contain Issues and draft items from many repositories; never infer `owner/repo` from Project membership.

## Project work

When authorized, create or update the smallest useful GitHub projection:

- repository Issue for one bounded WorkItem;
- Project item for coordination, prioritization, iteration, or portfolio visibility;
- association of Issues from multiple repositories with one Project;
- consumer-defined Issue types, labels, milestones, fields, or iteration values;
- a sub-issue parent link when the bounded work owner supplied an exact parent
  reference.

Keep outcome, scope, acceptance criteria, dependencies, and canonical references attributable. Do not copy unrelated planning context into every Issue.

Mappings are consumer-owned and optional. Never supply package defaults for
Issue types, labels, milestones, Project fields, iterations, priorities, or
statuses. If a consumer marks a mapping required and its source or mapped value
is unavailable, return the resolver's bounded blocker instead of guessing.

Native Issue types and sub-issue parent links are projection structure. Do not
read an organization's configured types, infer a type from a title or label, or
infer hierarchy from existing GitHub state. A parent link never propagates
readiness, acceptance, or completion between parent and child.

## Preserve ownership

GitHub Issue open/closed state and Project fields are projections. They do not create or transition canonical Plan or WorkItem state.

Do not manufacture readiness, completion, priority, assignment, or acceptance from GitHub defaults. Consumer policy controls field mappings and synchronization behavior.

## Handoff

Return exact GitHub Project, repository, Issue/item references and the projection changes performed. Report any mapping that could not be resolved without consumer policy rather than inventing one.
