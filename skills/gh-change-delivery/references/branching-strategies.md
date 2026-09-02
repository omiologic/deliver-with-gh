# Branching Strategies

## Purpose

Provide a small reusable strategy catalog that a consumer repository can choose from. The consumer owns policy. `gh-change-delivery` resolves that policy into an exact branch contract and never invents missing semantics.

## Initial strategy catalog

### `trunk`

Use the consumer-declared integration/default branch as the primary line of development. A short-lived branch is used only when consumer policy requires one.

Required consumer semantics:

- exact base/integration branch or permission to use the repository default branch;
- whether direct work on that branch is allowed;
- whether a PR is required.

### `feature`

Use one short-lived branch for one exact bounded WorkItem/change.

Typical required policy:

- base branch;
- branch naming pattern;
- allowed change types when the pattern includes a type;
- PR requirement and target branch.

### `release`

Use explicit consumer-declared integration/release targets before the stable branch.

Required policy must define the relevant branch roles and transitions. The skill must not infer a GitFlow-like topology from the strategy name.

### `custom`

Use exact consumer-provided deterministic rules. Missing values block rather than fall back to model judgment.

## Example consumer policy

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

## Resolution precedence

1. Explicit operation override, only when consumer policy permits that override.
2. Repository-scoped consumer policy.
3. Repository default branch for base resolution only when the selected strategy permits it.
4. Block if strategy semantics remain incomplete.

Do not derive branching policy from the enclosing GitHub Project. A Project may span multiple repositories with different policies.

## Deterministic branch-name derivation

When a pattern is used, resolve only declared placeholders. Initial recommended placeholders are:

- `{type}`
- `{work_item_id}`
- `{slug}`

Recommended normalization for `{slug}`:

1. lowercase;
2. transliterate or remove unsupported characters according to consumer policy;
3. whitespace and separators -> `-`;
4. remove characters outside the allowed branch-name set;
5. collapse repeated `-`;
6. trim separators;
7. apply the configured maximum length.

Preserve the canonical WorkItem identifier exactly when policy places it in the branch name.

## Resolver output

A future deterministic resolver should return either an exact contract such as:

```json
{
  "status": "resolved",
  "strategy": "feature",
  "repository": "owner/repo",
  "base_branch": "main",
  "branch_name": "feature/wx-00142-add-org-delete",
  "requires_new_branch": true,
  "requires_pull_request": true,
  "pull_request_base": "main"
}
```

or a bounded blocker:

```json
{
  "status": "blocked",
  "reason": "branch strategy is not configured",
  "owner": "consumer repository policy"
}
```

## Authority boundary

A resolved contract is a plan for GitHub operations, not permission to perform them. Each branch, commit, push, PR, review, merge, release, or repository-setting effect requires separate existing authority.
