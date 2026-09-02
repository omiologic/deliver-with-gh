# GitHub work projection contract

Use this contract after the Delivery planning owner has supplied bounded work.
The resolver plans a GitHub projection; it performs no GitHub mutation.

## Input

`project_ref` is an exact GitHub Project reference supplied by the caller. It
may be a non-empty opaque string or an object containing `node_id` or exact
`owner` plus positive `number`. It is independent from repository identity and
is preserved verbatim.

`work_items` is a non-empty list. Every item has:

- `kind`: `issue` or `draft`;
- `title`: the concise Issue or draft-item title;
- optional `content` containing only `outcome`, `scope`,
  `acceptance_criteria`, `dependencies`, and `traceability`;
- optional `canonical_refs`, such as exact `plan` and `work_item` references;
- optional consumer-domain `planning_values` used by explicit mappings;
- optional `parent`, an exact sub-issue parent reference.

An `issue` must carry an exact `repository` in `owner/repo` form. An existing
Issue may also carry `issue_number`. A `draft` carries neither repository nor
Issue identity, so it can represent coordination before repository ownership
is known. Project owner or membership is never a repository default.

The resolver renders a lean body from only the five supported content groups.
This keeps bounded outcome, scope, criteria, dependencies, and traceability
near the work without copying a whole Plan or unrelated context into each
Issue.

## Sub-issue parent references

`parent` is item-level bounded work input, not a consumer mapping. It is always
optional, and the package supplies no parent behavior of its own.

An `issue` item declares `parent` as either an exact same-repository Issue
number (a positive integer) or an exact `owner/repo#number` string. Both
normalize to an exact `owner/repo#number` reference on the desired projection,
so a parent in another repository stays explicit rather than inheriting the
child's repository.

A `draft` item has no Issue identity yet, so it declares `parent` only as
`{"item_index": N}` referencing an earlier item in the same `work_items` batch.
That reference is forwarded unchanged.

```json
{
  "work_items": [
    {
      "kind": "issue",
      "repository": "example-org/api",
      "issue_number": 4,
      "title": "Deliver the account launch"
    },
    {
      "kind": "issue",
      "repository": "partner-org/docs",
      "title": "Document account retrieval",
      "parent": "example-org/api#4"
    },
    {
      "kind": "draft",
      "title": "Coordinate launch communication",
      "parent": {"item_index": 0}
    }
  ]
}
```

The resolver never calls GitHub, so it does not verify that a parent exists, is
open, accepts sub-issues, or is already linked. It normalizes the reference and
forwards it for an authorized caller to act on, or blocks:

- `malformed_parent` — the reference does not match the item kind's accepted
  form, such as a non-positive Issue number, a string that is not exact
  `owner/repo#number`, a batch index on an Issue item, or an Issue reference on
  a draft item;
- `parent_out_of_range` — `item_index` does not reference an earlier item in the
  same batch.

Both carry the affected item index and stay owned by the bounded work owner.
A parent link is projection structure only; it does not roll readiness,
acceptance, or completion up or down a hierarchy.

## Consumer mappings

Mappings are optional and live under `consumer_policy.mappings`. The package
provides no Issue type names, label names, milestones, Project fields, priority
scale, iteration cadence, or status vocabulary.

Supported surfaces are:

```json
{
  "consumer_policy": {
    "mappings": {
      "issue_type": {
        "source": "work_type",
        "required": false,
        "values": {"initiative": "Epic", "story": "Feature", "chore": "Task"}
      },
      "labels": {
        "source": "categories",
        "required": false,
        "values": {"backend": "area:backend"}
      },
      "milestone": {
        "source": "release",
        "required": false,
        "values": {"next": "Next release"}
      },
      "project_fields": {
        "Iteration": {
          "source": "iteration",
          "required": false,
          "values": {"current": "Iteration 8"}
        },
        "Priority": {
          "source": "priority",
          "required": true,
          "values": {"high": "High"}
        },
        "Status": {
          "source": "planning_status",
          "required": false,
          "values": {"active": "In progress"}
        }
      }
    }
  }
}
```

Each mapping reads one exact key from an item's `planning_values`. `values` is
optional; without it, the source value is copied exactly. An unavailable
optional mapping is omitted and reported. An unavailable required mapping
blocks with `mapping_unavailable`, the affected item index, and mapping name.
The resolver never invents a mapping from GitHub defaults.

`issue_type` resolves the organization-defined native GitHub Issue type name,
such as `Epic`, `Feature`, or `Task`. It has the same shape and semantics as
`milestone` and resolves to `github_metadata.issue_type` on the desired
projection. The names are consumer-owned: the package ships no type vocabulary,
never reads the organization's configured types, and never infers a type from a
label, a title, a parent, or existing GitHub state. The resolver does not check
that a resolved name is enabled for the target organization; an authorized
caller applies it.

A native Issue type belongs to an Issue. `issue_type` is therefore never
applied to a `draft` item: a draft carrying the source key is omitted and
reported like any other unavailable optional mapping, and blocks with
`mapping_unavailable` only when the consumer marked the mapping required. A
draft never fails merely because the consumer configured the surface.

There is no `issue_label` surface. Labels stay under `labels`.

## Output and idempotence

A resolved result contains a deterministic desired `projection` and an
`action`: `create` when no current projection was supplied, `update` when it
differs, or `none` when `existing_projection` is exactly equal to the desired
projection. Equality covers the whole projected item, including
`github_metadata.issue_type` and `parent`, so a changed, added, or removed
Issue type or parent link yields `update` rather than `none`. Exact canonical
references remain attributed data; they do not become GitHub-owned state.

A projected item carries `parent` only when the item declared one, and
`github_metadata.issue_type` only when the mapping resolved.

The output intentionally contains no derived readiness, assignment,
acceptance, or completion. Issue open/closed state and Project Status are not
inputs to those decisions. Even when a consumer projects a status field, it is
metadata only. Canonical state remains with the Delivery owner.

## Command

```bash
python3 skills/gh-work-planning/scripts/resolve_work_projection.py input.json
```

Exit status is zero for a resolved projection and two for a bounded blocker or
invalid JSON.
