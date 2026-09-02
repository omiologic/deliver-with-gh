# GitHub evidence normalization contract

Use this contract after GitHub activity has produced observations. The
normalizer is read-only: it creates evidence input for platform-neutral
`delivery-reconciliation` and never selects an assessment or lifecycle state.

## Inputs

Supply an exact canonical `work_item_ref`, a non-empty list of acceptance
`criteria`, optional consumer policy, and GitHub `observations`. Each criterion
has an exact `id`, text, and one narrow `evidence_kind`: `behavior`,
`integration`, `review`, `source_change`, `artifact`, or `planning`.

Every observation declares non-empty `criterion_ids`. This declaration is the
coverage boundary: a successful check, job, or workflow can support only those
criteria. The package never expands coverage from a workflow name, repository,
Project, Issue, or overall success result.

Supported observation kinds are Issue, Project item, pull request, commit,
review, check, workflow, job, and artifact. Jobs and artifacts may be nested in
a workflow. Exact repository, object IDs, URLs, SHAs, Project references, and
parent workflow references are retained when available.

## Classification

Each observation/criterion pair becomes exactly one of:

- `supporting`: the bounded observation positively supports that criterion;
- `contradicting`: the bounded observation reports failure, cancellation, or
  another result contrary to the criterion;
- `missing`: required evidence is absent, incomplete, skipped, stale, expired,
  or otherwise non-conclusive;
- `projection_only`: GitHub state is retained but is not verification for that
  criterion.

A merged PR supports only a criterion explicitly typed `integration`. It is
projection-only for behavior, acceptance, and completion criteria. A commit
supports only `source_change`; approval supports only `review`. Issue state and
Project status are projection-only by default.

Consumers may define a narrower Issue or Project meaning with
`consumer_policy.projection_evidence`. A mapping must name the exact kind,
criterion, field/value match, classification, and meaning. This grants evidence
meaning only to that one criterion; it does not grant GitHub canonical state.

## Required and fresh evidence

`consumer_policy.required_evidence` maps criterion IDs to exact check,
workflow, job, artifact, or reviewer names and optional repository identity.
An unmatched requirement emits `missing` evidence. Observed skipped results are
missing; failed and cancelled results are contradicting.

`consumer_policy.expected_heads` maps exact `owner/repo` to the SHA currently
being reconciled. Evidence with a different head SHA is classified `missing`
as stale, even when its conclusion is successful.

## Output

The output uses schema version `delivery-reconciliation-evidence/v1` and
contains:

- exact WorkItem reference;
- `criterion_evidence` with attributable classifications and references;
- material `gaps` and `conflicts`;
- separate repository evidence and cross-repository Project metadata
  provenance;
- empty drift/uncertainty inputs for downstream enrichment;
- an explicit declaration that no canonical transition was performed or
  implied.

This is directly usable as the comparison evidence required by
`delivery-reconciliation`. That owner still chooses an advisory assessment and
bounded recommendation.

Run:

```bash
python3 skills/gh-delivery-reconciliation/scripts/normalize_github_evidence.py input.json
```

Exit status is zero for normalized evidence and two for invalid input or a
bounded normalization blocker.
