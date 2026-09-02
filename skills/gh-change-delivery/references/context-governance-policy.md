# Context Governance branch-policy source

Use this adapter only when Context Governance is installed for the consumer and
the target repository has opted into governed Convention or Constraint records.
Context Governance remains optional; `gh-change-delivery` has no import,
filesystem, or installation dependency on it.

## Bounded resolution

Ask Context Governance to resolve its compact governance context for the exact
repository-relative change target. Pass that returned object unchanged as:

```json
{
  "context_governance": {
    "installed": true,
    "resolved_context": {}
  }
}
```

The governance owner determines applicability, scope, status, supersession,
Convention exceptions, and Constraint checks. This adapter does not rediscover
records or make those decisions.

If Context Governance is not installed, omit `context_governance` or set
`installed` to `false`. Direct `consumer_policy` behavior remains unchanged. If
it is installed but returns no relevant declaration, direct behavior and output
also remain unchanged.

## Existing target contract

An applicable record opts into translation only when its compact `statement`
starts exactly with:

```text
github_delivery.branching = <JSON object>
```

The JSON object uses only fields already accepted by
`resolve_branch_policy.py` and documented in
[branching strategies](branching-strategies.md). For example, a Convention may
state:

```text
github_delivery.branching = {"strategy":"feature","base_branch":"main","branch_pattern":"{type}/{work_item_id}-{slug}","allowed_types":["feature","fix"]}
```

A Constraint may state:

```text
github_delivery.branching = {"protected_branches":["main"],"requires_pull_request":true}
```

This is an exact fragment of the existing target policy, not new frontmatter or
a Context Governance schema. Unrelated Convention and Constraint prose is
ignored. A malformed opt-in declaration or unsupported field blocks instead of
being interpreted from natural language.

Recommended Conventions remain advisory and are not promoted into policy.
Default and required Conventions may supply target fields. Satisfied
Constraints may supply target fields. Conflicting direct/governed values block;
the adapter never silently changes owning policy.

## Constraint boundary

Every resolved Constraint must include its evidence-backed `check`. `unknown`
and `violated` both block before branch-policy resolution and report the
Constraint's authoritative `source` as owner. Other governance-context blockers
also remain blockers. This adapter cannot infer satisfaction, waive a
Constraint, or authorize a required-Convention exception.

## Output and composition

`scripts/resolve_governed_branch_policy.py` returns one `consumer_policy`
object. When governed records apply, it always uses the sole target shape:

```json
{"github_delivery":{"branching":{}}}
```

Pass that object to `scripts/resolve_branch_policy.py`. The adapter changes only
the input source; branch strategy semantics, overrides, default-branch fallback,
validation, blockers, authority, and resolver output remain unchanged.

`resolve_change_delivery.py` performs this composition automatically when its
optional `context_governance` input is present.
