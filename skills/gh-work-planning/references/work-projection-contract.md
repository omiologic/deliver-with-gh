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
- optional consumer-domain `planning_values` used by explicit mappings.

An `issue` must carry an exact `repository` in `owner/repo` form. An existing
Issue may also carry `issue_number`. A `draft` carries neither repository nor
Issue identity, so it can represent coordination before repository ownership
is known. Project owner or membership is never a repository default.

The resolver renders a lean body from only the five supported content groups.
This keeps bounded outcome, scope, criteria, dependencies, and traceability
near the work without copying a whole Plan or unrelated context into each
Issue.

## Consumer mappings

Mappings are optional and live under `consumer_policy.mappings`. The package
provides no label names, milestones, Project fields, priority scale, iteration
cadence, or status vocabulary.

Supported surfaces are:

```json
{
  "consumer_policy": {
    "mappings": {
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

## Output and idempotence

A resolved result contains a deterministic desired `projection` and an
`action`: `create` when no current projection was supplied, `update` when it
differs, or `none` when `existing_projection` is exactly equal to the desired
projection. Exact canonical references remain attributed data; they do not
become GitHub-owned state.

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
