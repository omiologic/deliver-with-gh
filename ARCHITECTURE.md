# Deliver With GitHub Architecture

## Purpose

`deliver-with-gh` provides GitHub-specific procedural intelligence for the platform-neutral Delivery lifecycle defined by `deliver-product`.

It does not own canonical Plan, WorkItem, Execution, Context, acceptance, or completion state. It projects work onto GitHub, performs authorized GitHub change workflows, and translates GitHub observations into evidence for Delivery Reconciliation.

## Architectural invariant

> Delivery defines what stage of work is occurring. Deliver With GitHub applies that stage to GitHub. Consumer/runtime owners keep canonical state. GitHub supplies projections, effects, and evidence.

## System position

```text
requested delivery outcome
          │
          ▼
    deliver-product
          │
          │ platform-neutral stage contract
          ▼
    deliver-with-gh
          │
    ┌─────┼───────────────┐
    ▼     ▼               ▼
 work   change       reconciliation
planning delivery       evidence
    │     │               │
    └─────┼───────────────┘
          ▼
       GitHub
```

The dependency direction is one-way: this repository may consume `deliver-product` contracts and consumer governance/policy, but `deliver-product` must not depend on GitHub-specific behavior.

## Skill boundaries

### `deliver-with-gh`

Thin router for GitHub-specific delivery behavior.

It selects one narrow lane from explicit user intent, platform-neutral Delivery stage, owner-produced state, and available GitHub evidence. It does not reproduce child-skill procedures and does not perform GitHub effects merely because a lane was selected.

### `gh-work-planning`

Owns GitHub planning projection procedure.

It maps bounded delivery work into GitHub Issues, draft Project items, and GitHub Project metadata without treating those objects as canonical delivery state.

A GitHub Project is a cross-repository planning surface:

```text
GitHub Project
├── organization/repo-a#12
├── organization/repo-b#44
├── organization/repo-c#8
└── draft coordination item
```

The skill must never assume one Project equals one repository. Every repository-scoped Issue or work projection carries exact repository identity independently from Project identity.

Typical responsibilities:

- create or update a repository Issue projection for one bounded WorkItem when authorized;
- preserve exact canonical Plan/WorkItem references when provided;
- associate Issues from different repositories with one GitHub Project;
- map consumer-owned priority, iteration, milestone, labels, or status fields without treating them as canonical runtime transitions;
- represent cross-repository coordination without inventing repository ownership.

### `gh-change-delivery`

Owns GitHub-specific source-change procedure for one exact repository-scoped unit of work.

Typical workflow:

```text
exact WorkItem/change
       │
       ▼
consumer repository policy
       │
       ▼
deterministic branch contract
       │
       ▼
branch → commits → pull request → reviews/checks
```

The skill may use GitHub operations only under explicit authority. It does not infer WorkItem readiness or completion, and a merged PR remains evidence rather than canonical completion.

Branch policy is repository-scoped even when the surrounding GitHub Project spans several repositories.

### `gh-delivery-reconciliation`

Owns GitHub evidence normalization.

It converts GitHub observations such as PR state, merge commit, review decisions, check runs, Actions workflows, issue state, and Project metadata into criterion-level evidence suitable for `delivery-reconciliation`.

It must not collapse GitHub status into Delivery assessment by assumption.

For example:

```text
PR merged                     -> observation
required review approved      -> observation/evidence
unit checks passed            -> criterion evidence
integration workflow failed   -> contradicting evidence
Issue closed                  -> projection state only
```

The platform-neutral `delivery-reconciliation` skill remains responsible for comparing the complete expected outcome with evidence and recommending the next owner-controlled action.

## GitHub Project and repository identity

Project identity and repository identity are independent dimensions.

A planning projection should be able to carry:

```text
project_ref: GitHub Project node/number
repository_ref: exact owner/name when repository-scoped
issue_ref: exact repository + issue number when applicable
canonical_plan_ref: optional exact owner-produced Plan reference
canonical_work_item_ref: optional exact owner-produced WorkItem reference
```

Do not derive repository identity from Project membership or vice versa.

Cross-repository coordination belongs at the Project/planning surface. Branches, commits, PRs, checks, and repository rules remain repository-scoped.

## Branching strategy contract

The reusable package supplies a small strategy catalog. Consumers own strategy selection and repository-specific values.

Initial strategy identifiers:

| Strategy | Meaning |
| --- | --- |
| `trunk` | Use the configured integration/default branch according to consumer policy. A short-lived branch is created only when policy requires it. |
| `feature` | One short-lived branch per exact bounded WorkItem/change. |
| `release` | Use consumer-declared integration and/or release branches before the stable target. |
| `custom` | Consumer provides explicit deterministic rules; missing behavior blocks rather than being inferred. |

The strategy names are intentionally mechanical rather than branded methodology labels such as GitFlow or GitHub Flow.

Resolution precedence should remain deterministic:

```text
explicit allowed operation override
        ↓
repository consumer policy
        ↓
repository default branch for base resolution only
        ↓
block if strategy semantics are still unknown
```

A policy example:

```yaml
github_delivery:
  branching:
    strategy: feature
    base_branch: main
    branch_pattern: "{type}/{work_item_id}-{slug}"
    allowed_types:
      - feature
      - fix
      - chore
    protected_branches:
      - main
```

Branch-name derivation should be deterministic and testable. The package should eventually provide a resolver that returns an exact branch contract or a bounded blocker. Policy resolution never authorizes creating the branch, committing, pushing, opening a PR, or merging.

## Ownership and authority

| Concern | Owner |
| --- | --- |
| Platform-neutral Planning, Execution, Reconciliation procedure | `deliver-product` family |
| GitHub work projections and GitHub-specific procedure | applicable `deliver-with-gh` skill |
| Canonical Plan, WorkItem, Execution, Context, Inbox, Capability state | consumer runtime or responsible owner |
| Durable policy, conventions, constraints, Git/version governance | consumer governance owner |
| GitHub repository, Project, Issue, PR, review, Actions effects | authorized GitHub operation/tool |
| Acceptance/completion | owning runtime or person using reconciliation evidence |

No skill declaration grants operational authority.

## Evidence rules

GitHub state is evidence or projection unless an owning consumer contract explicitly says otherwise.

Never infer:

- Issue closed -> WorkItem done;
- Project status Done -> Plan completed;
- PR merged -> acceptance criteria satisfied;
- Actions success -> full delivery success;
- review approval -> merge authority;
- branch policy -> permission to mutate GitHub.

## Repository structure

```text
deliver-with-gh/
├── package-contract.json
├── scripts/
│   ├── install.py
│   └── validate.py
├── tests/
├── README.md
├── INSTALLATION.md
├── ARCHITECTURE.md
├── AGENTS.md
└── skills/
    ├── deliver-with-gh/
    │   ├── SKILL.md
    │   ├── fixtures/
    │   ├── references/
    │   └── scripts/
    ├── gh-work-planning/
    │   ├── SKILL.md
    │   ├── fixtures/
    │   ├── references/
    │   └── scripts/
    ├── gh-change-delivery/
    │   ├── SKILL.md
    │   ├── fixtures/
    │   ├── references/
    │   └── scripts/
    └── gh-delivery-reconciliation/
        ├── SKILL.md
        ├── fixtures/
        ├── references/
        └── scripts/
```

Future scripts, fixtures, tests, and adapters should remain package-local where possible and should not make consumer-specific layouts universal.

`package-contract.json` is the machine-readable validation projection of the
ownership and dependency invariants in this document. It does not replace this
architecture or create runtime state. `scripts/validate.py` checks that
projection, all four independently discoverable skills, public-safe fixtures,
and the scenario suite without requiring `deliver-product` to import or depend
on this repository.

## Initial non-goals

Do not add provider-neutral lifecycle state machines, release/publishing behavior, automatic model routing, arbitrary subagent spawning, or a GitHub-object skill for every API resource.

A future `gh-release-delivery` skill may be justified when an actual release workflow demonstrates separate authority and evidence needs, but it is intentionally outside the initial scaffold.
