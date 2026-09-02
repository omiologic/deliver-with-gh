# GitHub delivery routing contract

The router selects exactly one narrow GitHub skill from explicit Delivery
stage, requested GitHub action, owner-produced state, exact references, and
unreconciled evidence. It performs no child procedure.

## Inputs

`delivery_stage` is one of `planning`, `execution`, or `reconciliation`.
`github_action` is one of `planning_projection`, `change_delivery`,
`evidence_reconciliation`, or `none`. Missing or unknown Delivery stage returns
to platform-neutral `deliver-product`; `none` does the same because no
GitHub-specific action is needed.

The lane-specific payload is passed as `child_input`. The router preserves that
object exactly and separately reports the exact Project, repository, WorkItem,
Plan, and available GitHub evidence references handed off.

## Lane gates

### Planning projection

Planning requires owner-produced `owner_state.bounded: true` plus its exact
`state_ref`, an exact Project reference, and non-empty bounded work. Every Issue
item must carry its own exact `owner/repo`. Draft Project items carry no
repository. Project owner, membership, and neighboring Issue repositories are
never repository defaults.

### Change delivery

Change delivery requires owner-produced `owner_state.ready: true` plus its exact
`state_ref`, exact repository and WorkItem references, a consumer-policy object,
and explicit authority for every requested effect.

The router checks only that policy is present and passes it through unchanged.
It does not inspect strategy, derive a branch, select effects, or reproduce any
`gh-change-delivery` procedure.

### Evidence reconciliation

Reconciliation requires an exact WorkItem reference, criteria, and GitHub
observations. When a requested change also supplies
`unreconciled_github_evidence`, that evidence routes to
`gh-delivery-reconciliation` before readiness, authority, policy, or another
change attempt is considered.

The router preserves observations without classifying them. Evidence
normalization remains wholly owned by `gh-delivery-reconciliation`.

## Output

A routed result names one destination, its explicit routing basis, exact
handoff references, and the unchanged child input. A return names
`deliver-product` and the reason. A bounded routing failure names its code and
responsible owner.

Every result contains an empty `canonical_state_inferences` list and explicitly
states that routing performs no GitHub effect or lifecycle inference.

Run:

```bash
python3 skills/deliver-with-gh/scripts/route_delivery.py input.json
```

Exit status is two only for a bounded/invalid-input blocker. Routed and
platform-return results exit zero.
