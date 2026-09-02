# AGENTS.md

## Repository purpose

This repository contains GitHub-specific procedural skills that adapt the platform-neutral `deliver-product` lifecycle to GitHub Projects, Issues, repositories, branches, pull requests, reviews, checks, and Actions evidence.

## Required architecture

Preserve these boundaries:

1. `deliver-with-gh` stays a thin router.
2. `gh-work-planning` owns GitHub planning projections, including Projects spanning multiple repositories.
3. `gh-change-delivery` owns repository-scoped branch/commit/PR procedure and must resolve consumer branch policy deterministically before acting.
4. `gh-delivery-reconciliation` normalizes GitHub evidence but does not decide canonical completion.
5. Consumer/runtime owners retain canonical Plan, WorkItem, Execution, Context, acceptance, and completion state.
6. GitHub state is projection or evidence unless an owning consumer contract explicitly grants it a different role.

## Multi-repository rule

Never assume a GitHub Project maps to one repository. A single Project may contain Issues and draft items from multiple repositories. Repository identity must be explicit for repository-scoped operations.

Cross-repository coordination belongs to the planning/Project surface. Branch, commit, pull-request, repository-rule, and check behavior remains repository-scoped.

## Branch policy rule

Consumers choose branching policy. Skills may provide a small shared strategy catalog and deterministic resolver, but must not invent missing strategy semantics.

Policy is input, not authority. Resolving a branch contract never grants permission to create a branch, commit, push, open or merge a PR, tag, release, or change repository settings.

## Skill design

Separate skills by materially different delivery reasoning, authority, or evidence needs—not by GitHub API object type.

Prefer small entrypoints with selectively loaded references and deterministic scripts over broad procedural documents. Avoid duplicating `deliver-product` lifecycle logic.

## Development rules

- Keep public examples free of secrets and private repository data.
- Make policy resolution and evidence normalization deterministic where practical.
- Add scenario-driven tests for ambiguous, missing, conflicting, cross-repository, and authority-boundary cases.
- Do not make consumer-specific labels, Project fields, repository paths, or branching rules package defaults without demonstrated reusable need.
- Preserve exact `owner/repo`, Issue, PR, Project, Plan, and WorkItem references when available.
- Treat Actions/check results as evidence with provenance, not as acceptance by themselves.

## Initial validation target

The initial implementation should eventually prove:

- cross-repository Project projection works without repository inference;
- branch-policy selection and branch-name derivation are deterministic;
- missing branch strategy blocks instead of being guessed;
- GitHub Issue/Project state cannot manufacture canonical readiness or completion;
- PR/check/review evidence is normalized criterion-by-criterion;
- the GitHub orchestrator routes to one narrow skill without reproducing child policy.
