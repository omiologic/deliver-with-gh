#!/usr/bin/env python3
"""Normalize GitHub observations into criterion-level reconciliation evidence.

The normalizer is dependency-free and read-only. It classifies only the claim
an exact observation covers and never selects or implies canonical lifecycle
state.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


CLASSIFICATIONS = {"supporting", "contradicting", "missing", "projection_only"}
REPOSITORY_KINDS = {"issue", "pull_request", "commit", "review", "check", "workflow", "job", "artifact"}
SUPPORTED_KINDS = REPOSITORY_KINDS | {"project_item"}
SUCCESS_CONCLUSIONS = {"success", "successful", "passed"}
FAILURE_CONCLUSIONS = {"failure", "failed", "timed_out", "action_required", "startup_failure", "cancelled"}
MISSING_CONCLUSIONS = {"skipped", "neutral", "stale", "missing", "expired"}
AUTHORITY_NOTICE = (
    "This output is evidence input only. It performs and implies no canonical Plan, WorkItem, "
    "Execution, acceptance, completion, retry, merge, or other lifecycle transition."
)


class NormalizationBlock(Exception):
    def __init__(self, code: str, reason: str, owner: str = "GitHub evidence provider"):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.owner = owner


def block(code: str, reason: str, owner: str = "GitHub evidence provider") -> None:
    raise NormalizationBlock(code, reason, owner)


def exact_string(mapping: dict[str, Any], key: str, owner: str = "GitHub evidence provider") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        block("missing_reference", f"{key} must be a non-empty string", owner)
    return value


def validate_repository(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        block("missing_repository", "repository-scoped evidence requires exact owner/repo")
    return value


def validate_criteria(raw: Any) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    if not isinstance(raw, list) or not raw:
        block("missing_criteria", "criteria must be a non-empty list", "Delivery expectation owner")
    criteria: list[dict[str, str]] = []
    by_id: dict[str, dict[str, str]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            block("malformed_criterion", "each criterion must be an object", "Delivery expectation owner")
        criterion_id = exact_string(entry, "id", "Delivery expectation owner")
        text = exact_string(entry, "text", "Delivery expectation owner")
        evidence_kind = entry.get("evidence_kind", "behavior")
        if evidence_kind not in {"behavior", "integration", "review", "source_change", "artifact", "planning"}:
            block("malformed_criterion", f"unsupported evidence_kind for {criterion_id}", "Delivery expectation owner")
        if criterion_id in by_id:
            block("duplicate_criterion", f"duplicate criterion id: {criterion_id}", "Delivery expectation owner")
        criterion = {"id": criterion_id, "text": text, "evidence_kind": evidence_kind}
        criteria.append(criterion)
        by_id[criterion_id] = criterion
    return criteria, by_id


def validate_criterion_ids(raw: Any, criteria: dict[str, dict[str, str]]) -> list[str]:
    if not isinstance(raw, list) or not raw or any(not isinstance(value, str) or not value for value in raw):
        block("missing_coverage", "every observation requires non-empty criterion_ids")
    unknown = [value for value in raw if value not in criteria]
    if unknown:
        block("unknown_criterion", f"observation references unknown criteria: {', '.join(unknown)}")
    if len(raw) != len(set(raw)):
        block("malformed_coverage", "criterion_ids cannot contain duplicates")
    return list(raw)


def require_positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        block("missing_reference", f"{field} must be a positive integer")
    return value


def references_for(observation: dict[str, Any], kind: str, parent: dict[str, Any] | None = None) -> dict[str, Any]:
    references: dict[str, Any] = {}
    if kind in REPOSITORY_KINDS:
        repository = validate_repository(observation.get("repository") if "repository" in observation else (parent or {}).get("repository"))
        references["repository"] = repository
    if kind == "issue":
        number = require_positive(observation.get("number"), "issue number")
        references.update({"issue_ref": f"{references['repository']}#{number}", "issue_url": exact_string(observation, "url")})
    elif kind == "project_item":
        project_ref = observation.get("project_ref")
        if not isinstance(project_ref, (str, dict)) or not project_ref:
            block("missing_reference", "project_item requires exact project_ref")
        references["project_ref"] = copy.deepcopy(project_ref)
        references["project_item_id"] = exact_string(observation, "item_id")
        if observation.get("url") is not None:
            references["project_item_url"] = exact_string(observation, "url")
        if observation.get("repository") is not None:
            references["projected_repository"] = validate_repository(observation["repository"])
    elif kind == "pull_request":
        number = require_positive(observation.get("number"), "pull request number")
        references.update({"pull_request_ref": f"{references['repository']}#{number}", "pull_request_url": exact_string(observation, "url")})
        if observation.get("head_sha") is not None:
            references["head_sha"] = exact_string(observation, "head_sha")
        if observation.get("merge_commit_sha") is not None:
            references["merge_commit_sha"] = exact_string(observation, "merge_commit_sha")
    elif kind == "commit":
        references["commit_sha"] = exact_string(observation, "sha")
        if observation.get("url") is not None:
            references["commit_url"] = exact_string(observation, "url")
    elif kind == "review":
        references["review_id"] = observation.get("id")
        if references["review_id"] is None:
            block("missing_reference", "review requires id")
        references["review_url"] = exact_string(observation, "url")
        exact_string(observation, "reviewer")
        exact_string(observation, "decision")
        if observation.get("pull_request_number") is not None:
            pr_number = require_positive(observation["pull_request_number"], "pull request number")
            references["pull_request_ref"] = f"{references['repository']}#{pr_number}"
    elif kind == "check":
        references.update({"check_name": exact_string(observation, "name"), "check_url": exact_string(observation, "url")})
        if observation.get("id") is not None:
            references["check_run_id"] = observation["id"]
        if observation.get("head_sha") is not None:
            references["head_sha"] = exact_string(observation, "head_sha")
    elif kind == "workflow":
        references.update({"workflow_name": exact_string(observation, "name"), "workflow_run_id": observation.get("run_id"), "workflow_url": exact_string(observation, "url")})
        if references["workflow_run_id"] is None:
            block("missing_reference", "workflow requires run_id")
        if observation.get("head_sha") is not None:
            references["head_sha"] = exact_string(observation, "head_sha")
    elif kind == "job":
        references.update({"job_name": exact_string(observation, "name"), "job_id": observation.get("id"), "job_url": exact_string(observation, "url")})
        if references["job_id"] is None:
            block("missing_reference", "job requires id")
        if parent:
            references["workflow_run_id"] = parent.get("run_id")
            references["workflow_url"] = parent.get("url")
            if observation.get("head_sha") is None and parent.get("head_sha") is not None:
                references["head_sha"] = parent["head_sha"]
        if observation.get("head_sha") is not None:
            references["head_sha"] = exact_string(observation, "head_sha")
    elif kind == "artifact":
        references.update({"artifact_name": exact_string(observation, "name"), "artifact_id": observation.get("id"), "artifact_url": exact_string(observation, "url")})
        if references["artifact_id"] is None:
            block("missing_reference", "artifact requires id")
        if parent:
            references["workflow_run_id"] = parent.get("run_id")
            references["workflow_url"] = parent.get("url")
    return references


def outcome_classification(observation: dict[str, Any], references: dict[str, Any], expected_heads: dict[str, str]) -> tuple[str, str]:
    repository = references.get("repository")
    expected_head = expected_heads.get(repository) if repository else None
    observed_head = references.get("head_sha")
    if expected_head and observed_head and expected_head != observed_head:
        return "missing", "observation is stale for the expected repository head"

    status = str(observation.get("status", "")).lower()
    conclusion = str(observation.get("conclusion", observation.get("result", ""))).lower()
    if conclusion in SUCCESS_CONCLUSIONS:
        return "supporting", f"{observation['kind']} succeeded for its declared coverage"
    if conclusion in FAILURE_CONCLUSIONS:
        return "contradicting", f"{observation['kind']} concluded {conclusion}"
    if conclusion in MISSING_CONCLUSIONS:
        return "missing", f"{observation['kind']} concluded {conclusion}"
    if status in {"queued", "in_progress", "pending", "requested", "waiting"}:
        return "missing", f"{observation['kind']} has not completed"
    return "missing", f"{observation['kind']} has no conclusive result"


def projection_mapping(
    observation: dict[str, Any], criterion_id: str, mappings: list[dict[str, Any]]
) -> tuple[str, str] | None:
    for mapping in mappings:
        if mapping["kind"] != observation["kind"] or mapping["criterion_id"] != criterion_id:
            continue
        field = mapping["field"]
        if observation.get(field) == mapping["value"]:
            return mapping["classification"], mapping["meaning"]
    return None


def classify(
    observation: dict[str, Any],
    criterion: dict[str, str],
    references: dict[str, Any],
    expected_heads: dict[str, str],
    projection_mappings: list[dict[str, Any]],
) -> tuple[str, str]:
    kind = observation["kind"]
    mapped = projection_mapping(observation, criterion["id"], projection_mappings)
    if mapped is not None:
        return mapped
    if kind in {"issue", "project_item"}:
        return "projection_only", f"{kind} state is planning projection metadata"
    if kind == "pull_request":
        if observation.get("merged") is True and criterion["evidence_kind"] == "integration":
            return "supporting", "pull request merge supports only the declared integration criterion"
        return "projection_only", "pull request state does not verify this acceptance criterion"
    if kind == "commit":
        if criterion["evidence_kind"] == "source_change":
            return "supporting", "commit existence supports only the declared source-change criterion"
        return "projection_only", "commit existence does not verify this acceptance criterion"
    if kind == "review":
        decision = str(observation.get("decision", "")).upper()
        if criterion["evidence_kind"] != "review":
            return "projection_only", "review decision does not verify this acceptance criterion"
        if decision == "APPROVED":
            return "supporting", "review approval supports only the declared review criterion"
        if decision == "CHANGES_REQUESTED":
            return "contradicting", "review requested changes"
        return "missing", "review has no conclusive decision"
    if kind in {"check", "workflow", "job", "artifact"}:
        return outcome_classification(observation, references, expected_heads)
    raise AssertionError(kind)


def flatten_observations(raw: Any, criteria: dict[str, dict[str, str]]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    if not isinstance(raw, list):
        block("malformed_observations", "observations must be a list")
    flattened: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for observation in raw:
        if not isinstance(observation, dict) or observation.get("kind") not in SUPPORTED_KINDS:
            block("unsupported_observation", "each observation requires a supported kind")
        validate_criterion_ids(observation.get("criterion_ids"), criteria)
        flattened.append((copy.deepcopy(observation), None))
        if observation["kind"] == "workflow":
            for collection, child_kind in (("jobs", "job"), ("artifacts", "artifact")):
                children = observation.get(collection, [])
                if not isinstance(children, list):
                    block("malformed_observations", f"workflow {collection} must be a list")
                for child in children:
                    if not isinstance(child, dict):
                        block("malformed_observations", f"workflow {collection} entries must be objects")
                    normalized_child = {**copy.deepcopy(child), "kind": child_kind}
                    validate_criterion_ids(normalized_child.get("criterion_ids"), criteria)
                    flattened.append((normalized_child, observation))
    return flattened


def validate_policy(raw: Any, criteria: dict[str, dict[str, str]]) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        block("malformed_policy", "consumer_policy must be an object", "consumer policy owner")
    expected_heads = raw.get("expected_heads", {})
    if not isinstance(expected_heads, dict):
        block("malformed_policy", "expected_heads must be an object", "consumer policy owner")
    for repository, sha in expected_heads.items():
        validate_repository(repository)
        if not isinstance(sha, str) or not sha:
            block("malformed_policy", "expected_heads must map repositories to SHAs", "consumer policy owner")

    mappings = raw.get("projection_evidence", [])
    if not isinstance(mappings, list):
        block("malformed_policy", "projection_evidence must be a list", "consumer policy owner")
    normalized_mappings: list[dict[str, Any]] = []
    for mapping in mappings:
        if not isinstance(mapping, dict) or mapping.get("kind") not in {"issue", "project_item"}:
            block("malformed_policy", "projection evidence mappings require issue or project_item kind", "consumer policy owner")
        criterion_id = exact_string(mapping, "criterion_id", "consumer policy owner")
        if criterion_id not in criteria:
            block("unknown_criterion", f"projection mapping references unknown criterion: {criterion_id}", "consumer policy owner")
        classification = mapping.get("classification")
        if classification not in {"supporting", "contradicting", "missing"}:
            block("malformed_policy", "projection mapping classification is invalid", "consumer policy owner")
        if "value" not in mapping:
            block("malformed_policy", "projection mapping requires an exact value", "consumer policy owner")
        normalized_mappings.append(
            {
                "kind": mapping["kind"],
                "criterion_id": criterion_id,
                "field": exact_string(mapping, "field", "consumer policy owner"),
                "value": copy.deepcopy(mapping.get("value")),
                "classification": classification,
                "meaning": exact_string(mapping, "meaning", "consumer policy owner"),
            }
        )

    required = raw.get("required_evidence", {})
    if not isinstance(required, dict):
        block("malformed_policy", "required_evidence must be an object", "consumer policy owner")
    normalized_required: dict[str, list[dict[str, Any]]] = {}
    for criterion_id, requirements in required.items():
        if criterion_id not in criteria or not isinstance(requirements, list):
            block("malformed_policy", "required_evidence keys must be known criteria with requirement lists", "consumer policy owner")
        normalized_required[criterion_id] = []
        for requirement in requirements:
            if not isinstance(requirement, dict) or requirement.get("kind") not in {"check", "workflow", "job", "artifact", "review"}:
                block("malformed_policy", "required evidence has unsupported kind", "consumer policy owner")
            normalized = copy.deepcopy(requirement)
            exact_string(normalized, "name", "consumer policy owner")
            if normalized.get("repository") is not None:
                validate_repository(normalized["repository"])
            normalized_required[criterion_id].append(normalized)
    return dict(expected_heads), normalized_mappings, normalized_required


def requirement_matches(requirement: dict[str, Any], record: dict[str, Any], criterion_id: str) -> bool:
    observation = record["observation"]
    if observation["kind"] != requirement["kind"] or criterion_id not in observation["criterion_ids"]:
        return False
    observed_name = observation.get("name")
    if observation["kind"] == "review":
        observed_name = observation.get("reviewer")
    if observed_name != requirement["name"]:
        return False
    repository = requirement.get("repository")
    return repository is None or record["references"].get("repository") == repository


def resolve(payload: Any) -> dict[str, Any]:
    work_item_ref: str | None = None
    try:
        if not isinstance(payload, dict):
            block("malformed_input", "normalizer input must be an object", "operation owner")
        work_item_ref = exact_string(payload, "work_item_ref", "Delivery expectation owner")
        criteria, criteria_by_id = validate_criteria(payload.get("criteria"))
        expected_heads, projection_mappings, required = validate_policy(payload.get("consumer_policy"), criteria_by_id)
        flattened = flatten_observations(payload.get("observations", []), criteria_by_id)

        records: list[dict[str, Any]] = []
        evidence_by_criterion: dict[str, list[dict[str, Any]]] = {criterion["id"]: [] for criterion in criteria}
        for observation, parent in flattened:
            references = references_for(observation, observation["kind"], parent)
            record = {"observation": observation, "references": references}
            records.append(record)
            for criterion_id in observation["criterion_ids"]:
                classification, claim = classify(
                    observation,
                    criteria_by_id[criterion_id],
                    references,
                    expected_heads,
                    projection_mappings,
                )
                evidence_by_criterion[criterion_id].append(
                    {
                        "classification": classification,
                        "source_kind": observation["kind"],
                        "claim": claim,
                        "references": copy.deepcopy(references),
                    }
                )

        for criterion_id, requirements in required.items():
            for requirement in requirements:
                if not any(requirement_matches(requirement, record, criterion_id) for record in records):
                    evidence_by_criterion[criterion_id].append(
                        {
                            "classification": "missing",
                            "source_kind": requirement["kind"],
                            "claim": f"required {requirement['kind']} {requirement['name']!r} was not observed",
                            "references": {
                                key: copy.deepcopy(value)
                                for key, value in requirement.items()
                                if key in {"kind", "name", "repository"}
                            },
                        }
                    )

        criterion_evidence: list[dict[str, Any]] = []
        gaps: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []
        for criterion in criteria:
            criterion_id = criterion["id"]
            evidence = evidence_by_criterion[criterion_id]
            probative = [entry for entry in evidence if entry["classification"] != "projection_only"]
            if not probative:
                evidence.append(
                    {
                        "classification": "missing",
                        "source_kind": "github_normalization",
                        "claim": "no attributable GitHub verification covers this criterion",
                        "references": {},
                    }
                )
            for entry in evidence:
                if entry["classification"] == "missing":
                    gaps.append({"criterion_id": criterion_id, "detail": entry["claim"]})
                elif entry["classification"] == "contradicting":
                    conflicts.append({"criterion_id": criterion_id, "detail": entry["claim"]})
            criterion_evidence.append({**criterion, "evidence": evidence})

        project_metadata = [
            {"references": record["references"], "observation": record["observation"]}
            for record in records
            if record["observation"]["kind"] == "project_item"
        ]
        repository_evidence = [
            {"references": record["references"], "observation": record["observation"]}
            for record in records
            if record["observation"]["kind"] != "project_item"
        ]
        return {
            "status": "normalized",
            "schema_version": "delivery-reconciliation-evidence/v1",
            "handoff_for": "delivery-reconciliation",
            "work_item_ref": work_item_ref,
            "criterion_evidence": criterion_evidence,
            "gaps": gaps,
            "conflicts": conflicts,
            "drift": [],
            "uncertainty": [],
            "provenance": {
                "repository_evidence": repository_evidence,
                "project_metadata": project_metadata,
            },
            "canonical_transition": {"performed": False, "implied": False},
            "authority": AUTHORITY_NOTICE,
        }
    except NormalizationBlock as exc:
        result = {
            "status": "blocked",
            "code": exc.code,
            "reason": exc.reason,
            "owner": exc.owner,
            "authority": AUTHORITY_NOTICE,
        }
        if work_item_ref is not None:
            result["work_item_ref"] = work_item_ref
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="JSON input file; defaults to stdin")
    args = parser.parse_args()
    try:
        source = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
        payload = json.loads(source)
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "status": "blocked",
            "code": "invalid_json",
            "reason": str(exc),
            "owner": "operation owner",
            "authority": AUTHORITY_NOTICE,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    result = resolve(payload)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0 if result["status"] == "normalized" else 2


if __name__ == "__main__":
    raise SystemExit(main())
