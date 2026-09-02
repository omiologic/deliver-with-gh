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

Run the dependency-free resolver with JSON on stdin or from a file:

```shell
python3 scripts/resolve_branch_policy.py input.json
```

The input object contains:

- `repository`: exact `owner/repo`;
- `repository_default_branch`: optional observation, used only when policy explicitly sets `use_repository_default_as_base` and the selected strategy permits fallback;
- `change`: exact `work_item_id`, `type`, and `title` values needed by the selected pattern;
- `consumer_policy`: either the branching object itself or a containing `branching` / `github_delivery.branching` object;
- `operation_override`: optional fields explicitly named by policy in `allowed_operation_overrides`;
- `project_context`: optional planning context that is deliberately ignored for branch resolution.

Shared policy fields include `branch_pattern`, `allowed_types`, `protected_branches`, `max_branch_length`, and optional `branch_name_regex`. Patterns support only `{type}`, `{work_item_id}`, and `{slug}`, at most once each. Maximum-length handling truncates only the slug so an included canonical WorkItem identifier remains exact.

`trunk` requires explicit `direct_work_allowed` and `requires_pull_request` values. `feature` always resolves a short-lived branch and requires `requires_pull_request`. `release` requires explicit `branch_roles`, `required_branch_roles`, `base_role`, `pull_request_target_role`, and work-branch behavior. `custom` requires a complete `custom_contract`; it has no fallback semantics.

The resolver returns either an exact contract such as:

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

Blocked results include a stable `code`, human-readable `reason`, and responsible `owner`. The scenario fixtures at `../fixtures/branch-policy-scenarios.json` cover valid, missing, conflicting, malformed, protected-target, cross-repository, and incomplete custom policies. Run validation from the repository root with:

```shell
python3 -m unittest discover -s tests -v
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
