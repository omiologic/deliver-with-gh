# Repository-scoped change-delivery workflow

Use this contract for one exact change envelope after its owner has established
readiness. The resolver plans and normalizes the workflow but performs no Git
or GitHub effects.

## Change envelope

The input requires:

- exact top-level `repository` in `owner/repo` form;
- `change_envelope.work_item_ref` and branch-policy `change` inputs;
- non-empty `immutable_scope`, where every entry repeats that same exact
  repository and one path;
- non-empty `acceptance_criteria`;
- applicable `consumer_policy` for the branch-policy resolver;
- explicit `requested_effects` and per-effect `authority`.

Repeating repository identity on every source path is intentional. A path for
another repository blocks with `cross_repository_scope`; it requires a separate
change envelope and branch contract. The resolver returns a SHA-256 digest of
the ordered scope snapshot so callers can retain the exact boundary.

## Branch policy composition

`resolve_change_delivery.py` passes the exact repository, change, policy,
repository default observation, and permitted override to
`resolve_branch_policy.py`. It returns branch-policy blockers unchanged, with
`blocker_source: branch_policy`. It never selects or repairs strategy semantics.

## Effects and authority

Supported effects are:

- `branch_create`
- `commit_create`
- `push`
- `pr_create`
- `pr_update`
- `review_submit`
- `checks_trigger`
- `merge`

Each requested effect is resolved independently to `apply` or `none`. Exact
existing targets resolve to `none`, making branch, commit, push, PR, review, and
check handling idempotent. An `apply` result requires the matching authority
key to be exactly `true`; authority for one effect never authorizes another.
PR creation, PR update, review submission, check triggering, and merge are
therefore distinct decisions.

Inputs under `desired` provide the exact effect target:

```json
{
  "desired": {
    "commit": {"idempotency_key": "WI-42-implementation"},
    "push": {"head_sha": "exact commit SHA"},
    "pull_request": {"title": "WI-42: Outcome", "body": "WorkItem: exact-ref"},
    "review": {"reviewer": "octocat", "decision": "APPROVED", "head_sha": "exact SHA"},
    "checks": {"head_sha": "exact SHA"}
  }
}
```

The repository, resolved head/base, and WorkItem reference are invariant parts
of commit and PR targets. A create request conflicts rather than silently
updating a different existing PR.

## Observations and handoff

`observations` may contain the exact branch, remote branch, commits, pull
request, reviews, checks, and workflow runs. Repository, branch, and WorkItem
references are validated before being returned. Failed checks, requested
changes, and a stale PR head become factual `delivery_blockers`.

The handoff preserves exact GitHub references and acceptance criteria for
reconciliation. A merged PR changes the phase to `merged_evidence` and sets
`merge_observed: true`; `canonical_completion` remains `not_determined`.
Neither a merge nor successful checks manufacture acceptance or completion.

Run:

```bash
python3 skills/gh-change-delivery/scripts/resolve_change_delivery.py input.json
```

Exit status is zero for a resolved workflow and two for a bounded blocker or
invalid JSON.
