#!/usr/bin/env python3
"""Resolve one authorized repository-scoped GitHub change-delivery workflow.

This dependency-free resolver performs no Git or GitHub mutation. It composes
the branch-policy resolver, determines idempotent effects from observations,
and emits an attributable handoff for reconciliation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


BRANCH_RESOLVER_PATH = Path(__file__).with_name("resolve_branch_policy.py")
SPEC = importlib.util.spec_from_file_location("change_delivery_branch_policy", BRANCH_RESOLVER_PATH)
branch_policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(branch_policy)

GOVERNANCE_ADAPTER_PATH = Path(__file__).with_name("resolve_governed_branch_policy.py")
GOVERNANCE_SPEC = importlib.util.spec_from_file_location(
    "change_delivery_governance_adapter", GOVERNANCE_ADAPTER_PATH
)
governance_adapter = importlib.util.module_from_spec(GOVERNANCE_SPEC)
assert GOVERNANCE_SPEC.loader is not None
GOVERNANCE_SPEC.loader.exec_module(governance_adapter)


SUPPORTED_EFFECTS = {
    "branch_create",
    "commit_create",
    "push",
    "pr_create",
    "pr_update",
    "review_submit",
    "checks_trigger",
    "merge",
}
FAILED_CHECK_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "timed_out",
}
AUTHORITY_NOTICE = (
    "Only effects listed as apply are authorized candidates; this resolution performs no mutation. "
    "GitHub observations, including merge, do not establish canonical WorkItem completion or acceptance."
)


class DeliveryBlock(Exception):
    def __init__(
        self,
        code: str,
        reason: str,
        owner: str = "change envelope owner",
        effect: str | None = None,
    ):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.owner = owner
        self.effect = effect


def block(
    code: str,
    reason: str,
    owner: str = "change envelope owner",
    effect: str | None = None,
) -> None:
    raise DeliveryBlock(code, reason, owner, effect)


def exact_string(mapping: dict[str, Any], key: str, owner: str = "change envelope owner") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        block("missing_change_input", f"{key} must be a non-empty string", owner)
    return value


def validate_repository(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        block("missing_repository", "repository must be an exact owner/repo string")
    return value


def validate_envelope(payload: dict[str, Any]) -> tuple[str, dict[str, Any], str, list[dict[str, str]], list[str]]:
    repository = validate_repository(payload.get("repository"))
    envelope = payload.get("change_envelope")
    if not isinstance(envelope, dict):
        block("missing_change_envelope", "change_envelope must be an object")
    work_item_ref = exact_string(envelope, "work_item_ref")
    change = envelope.get("change")
    if not isinstance(change, dict):
        block("missing_change_input", "change_envelope.change must be an object")
    exact_string(change, "work_item_id")
    exact_string(change, "title")

    scope = envelope.get("immutable_scope")
    if not isinstance(scope, list) or not scope:
        block("missing_scope", "immutable_scope must be a non-empty list")
    normalized_scope: list[dict[str, str]] = []
    for index, entry in enumerate(scope):
        if not isinstance(entry, dict):
            block("malformed_scope", f"immutable_scope[{index}] must be an object")
        entry_repository = validate_repository(entry.get("repository"))
        path = exact_string(entry, "path")
        if entry_repository != repository:
            block(
                "cross_repository_scope",
                f"scope entry {entry_repository}:{path} requires a separate repository-scoped change envelope",
            )
        normalized_scope.append({"repository": entry_repository, "path": path})

    criteria = envelope.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or any(not isinstance(value, str) or not value for value in criteria):
        block("missing_acceptance_criteria", "acceptance_criteria must contain non-empty strings")
    return repository, change, work_item_ref, normalized_scope, list(criteria)


def scope_digest(scope: list[dict[str, str]]) -> str:
    encoded = json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_requested_effects(payload: dict[str, Any]) -> list[str]:
    requested = payload.get("requested_effects", [])
    if not isinstance(requested, list) or any(not isinstance(effect, str) for effect in requested):
        block("malformed_effects", "requested_effects must be a list of effect names", "operation owner")
    if len(requested) != len(set(requested)):
        block("malformed_effects", "requested_effects cannot contain duplicates", "operation owner")
    unsupported = [effect for effect in requested if effect not in SUPPORTED_EFFECTS]
    if unsupported:
        block("unsupported_effect", f"unsupported effects: {', '.join(unsupported)}", "operation owner")
    return requested


def validate_authority(payload: dict[str, Any]) -> dict[str, Any]:
    authority = payload.get("authority", {})
    if not isinstance(authority, dict) or any(not isinstance(value, bool) for value in authority.values()):
        block("malformed_authority", "authority must map effect names to booleans", "authority owner")
    unknown = sorted(set(authority) - SUPPORTED_EFFECTS)
    if unknown:
        block("malformed_authority", f"authority contains unsupported effects: {', '.join(unknown)}", "authority owner")
    return authority


def validate_observations(
    raw: Any,
    repository: str,
    branch_name: str,
    pull_request_base: str | None,
    work_item_ref: str,
) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        block("malformed_observations", "observations must be an object", "GitHub evidence provider")
    observations = json.loads(json.dumps(raw))

    branch = observations.get("branch")
    if branch is not None:
        if not isinstance(branch, dict):
            block("malformed_observations", "observations.branch must be an object", "GitHub evidence provider")
        observed_repository = validate_repository(branch.get("repository"))
        if observed_repository != repository:
            block("cross_repository_evidence", "branch observation belongs to another repository", "GitHub evidence provider")
        if exact_string(branch, "name", "GitHub evidence provider") != branch_name:
            block("branch_conflict", "observed branch does not match the resolved branch contract", "GitHub evidence provider")
        if not isinstance(branch.get("exists"), bool):
            block("malformed_observations", "observations.branch.exists must be boolean", "GitHub evidence provider")

    remote_branch = observations.get("remote_branch")
    if remote_branch is not None:
        if not isinstance(remote_branch, dict):
            block("malformed_observations", "observations.remote_branch must be an object", "GitHub evidence provider")
        if validate_repository(remote_branch.get("repository")) != repository:
            block("cross_repository_evidence", "remote branch observation belongs to another repository", "GitHub evidence provider")
        if exact_string(remote_branch, "name", "GitHub evidence provider") != branch_name:
            block("branch_conflict", "remote branch does not match the resolved branch", "GitHub evidence provider")
        exact_string(remote_branch, "head_sha", "GitHub evidence provider")

    commits = observations.get("commits", [])
    if not isinstance(commits, list):
        block("malformed_observations", "observations.commits must be a list", "GitHub evidence provider")
    for commit in commits:
        if not isinstance(commit, dict):
            block("malformed_observations", "each commit observation must be an object", "GitHub evidence provider")
        if validate_repository(commit.get("repository")) != repository:
            block("cross_repository_evidence", "commit observation belongs to another repository", "GitHub evidence provider")
        if exact_string(commit, "branch", "GitHub evidence provider") != branch_name:
            block("branch_conflict", "commit observation is not on the resolved branch", "GitHub evidence provider")
        exact_string(commit, "sha", "GitHub evidence provider")
        if exact_string(commit, "work_item_ref", "GitHub evidence provider") != work_item_ref:
            block("traceability_conflict", "commit observation has a different WorkItem reference", "GitHub evidence provider")

    pull_request = observations.get("pull_request")
    if pull_request is not None:
        if not isinstance(pull_request, dict):
            block("malformed_observations", "observations.pull_request must be an object", "GitHub evidence provider")
        if validate_repository(pull_request.get("repository")) != repository:
            block("cross_repository_evidence", "pull request observation belongs to another repository", "GitHub evidence provider")
        number = pull_request.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            block("malformed_observations", "pull request number must be positive", "GitHub evidence provider")
        exact_string(pull_request, "url", "GitHub evidence provider")
        if exact_string(pull_request, "head", "GitHub evidence provider") != branch_name:
            block("branch_conflict", "pull request head does not match the resolved branch", "GitHub evidence provider")
        observed_base = exact_string(pull_request, "base", "GitHub evidence provider")
        if pull_request_base is None or observed_base != pull_request_base:
            block(
                "pull_request_contract_conflict",
                "pull request base does not match the resolved branch contract",
                "GitHub evidence provider",
            )
        if exact_string(pull_request, "work_item_ref", "GitHub evidence provider") != work_item_ref:
            block("traceability_conflict", "pull request has a different WorkItem reference", "GitHub evidence provider")
        if not isinstance(pull_request.get("merged", False), bool):
            block("malformed_observations", "pull request merged must be boolean", "GitHub evidence provider")

    for collection, required in (("reviews", ("id", "decision", "url")), ("checks", ("name", "status", "url")), ("workflows", ("id", "status", "url"))):
        values = observations.get(collection, [])
        if not isinstance(values, list):
            block("malformed_observations", f"observations.{collection} must be a list", "GitHub evidence provider")
        for value in values:
            if not isinstance(value, dict):
                block("malformed_observations", f"each {collection} observation must be an object", "GitHub evidence provider")
            for key in required:
                if key == "id":
                    if value.get(key) is None:
                        block("malformed_observations", f"{collection} observation requires id", "GitHub evidence provider")
                else:
                    exact_string(value, key, "GitHub evidence provider")
    return observations


def desired_object(payload: dict[str, Any], effect: str) -> dict[str, Any]:
    desired = payload.get("desired", {})
    if not isinstance(desired, dict):
        block("malformed_desired", "desired must be an object", "operation owner")
    key = {
        "commit_create": "commit",
        "push": "push",
        "pr_create": "pull_request",
        "pr_update": "pull_request",
        "review_submit": "review",
        "checks_trigger": "checks",
        "merge": "merge",
    }.get(effect)
    if key is None:
        return {}
    value = desired.get(key)
    if not isinstance(value, dict):
        block("missing_desired_effect", f"desired.{key} is required for {effect}", "operation owner", effect)
    return value


def is_exact_subset(desired: dict[str, Any], observed: dict[str, Any]) -> bool:
    return all(key in observed and observed[key] == value for key, value in desired.items())


def determine_action(
    effect: str,
    payload: dict[str, Any],
    observations: dict[str, Any],
    branch_contract: dict[str, Any],
    repository: str,
    work_item_ref: str,
) -> str:
    branch_name = branch_contract["branch_name"]
    if effect == "branch_create":
        if not branch_contract["requires_new_branch"]:
            return "none"
        branch = observations.get("branch")
        return "none" if branch and branch.get("exists") else "apply"

    if effect == "merge":
        pull_request = observations.get("pull_request")
        if pull_request is None:
            block("missing_pull_request", "merge requires an existing pull request observation", "GitHub evidence provider", effect)
        return "none" if pull_request.get("merged", False) else "apply"

    desired = desired_object(payload, effect)
    if effect == "commit_create":
        exact_string(desired, "idempotency_key", "operation owner")
        target = {**desired, "repository": repository, "branch": branch_name, "work_item_ref": work_item_ref}
        return "none" if any(is_exact_subset(target, commit) for commit in observations.get("commits", [])) else "apply"
    if effect == "push":
        head_sha = exact_string(desired, "head_sha", "operation owner")
        remote = observations.get("remote_branch")
        if remote is not None and not isinstance(remote, dict):
            block("malformed_observations", "observations.remote_branch must be an object", "GitHub evidence provider")
        return "none" if remote and remote.get("name") == branch_name and remote.get("head_sha") == head_sha else "apply"
    if effect in {"pr_create", "pr_update"}:
        if not branch_contract["requires_pull_request"]:
            block(
                "incompatible_effect",
                f"{effect} conflicts with a branch contract that does not require a pull request",
                "operation owner",
                effect,
            )
        exact_string(desired, "title", "operation owner")
        body = exact_string(desired, "body", "operation owner")
        if work_item_ref not in body:
            block(
                "traceability_conflict",
                "desired pull request body must contain the exact WorkItem reference",
                "operation owner",
                effect,
            )
        desired_target = {
            **desired,
            "repository": repository,
            "head": branch_name,
            "base": branch_contract["pull_request_base"],
            "work_item_ref": work_item_ref,
        }
        observed = observations.get("pull_request")
        if effect == "pr_create":
            if observed is None:
                return "apply"
            if is_exact_subset(desired_target, observed):
                return "none"
            block("existing_pr_conflict", "an existing pull request does not match the exact create target", "operation owner", effect)
        if observed is None:
            block("missing_pull_request", "pr_update requires an existing pull request observation", "GitHub evidence provider", effect)
        return "none" if is_exact_subset(desired_target, observed) else "apply"
    if effect == "review_submit":
        exact_string(desired, "reviewer", "operation owner")
        exact_string(desired, "decision", "operation owner")
        exact_string(desired, "head_sha", "operation owner")
        target = dict(desired)
        return "none" if any(is_exact_subset(target, review) for review in observations.get("reviews", [])) else "apply"
    if effect == "checks_trigger":
        head_sha = exact_string(desired, "head_sha", "operation owner")
        all_runs = observations.get("checks", []) + observations.get("workflows", [])
        return "none" if any(run.get("head_sha") == head_sha for run in all_runs) else "apply"
    raise AssertionError(effect)


def delivery_blockers(observations: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for check in observations.get("checks", []):
        if check.get("conclusion") in FAILED_CHECK_CONCLUSIONS:
            blockers.append({"code": "failed_check", "reference": check["url"], "detail": check["name"]})
    for review in observations.get("reviews", []):
        if review.get("decision") == "CHANGES_REQUESTED":
            blockers.append({"code": "changes_requested", "reference": review["url"], "detail": str(review["id"])})
    pull_request = observations.get("pull_request")
    branch = observations.get("branch")
    if pull_request and branch and branch.get("head_sha") and pull_request.get("head_sha") != branch.get("head_sha"):
        blockers.append(
            {"code": "stale_head", "reference": pull_request["url"], "detail": "pull request head differs from branch head"}
        )
    return blockers


def build_handoff(
    repository: str,
    work_item_ref: str,
    branch_contract: dict[str, Any],
    observations: dict[str, Any],
    criteria: list[str],
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    pull_request = observations.get("pull_request")
    merged = bool(pull_request and pull_request.get("merged"))
    return {
        "repository": repository,
        "work_item_ref": work_item_ref,
        "branch": observations.get("branch") or {
            "repository": repository,
            "name": branch_contract["branch_name"],
            "exists": False,
        },
        "commits": observations.get("commits", []),
        "pull_request": pull_request,
        "reviews": observations.get("reviews", []),
        "checks": observations.get("checks", []),
        "workflows": observations.get("workflows", []),
        "acceptance_criteria": criteria,
        "delivery_blockers": blockers,
        "merge_observed": merged,
        "canonical_completion": "not_determined",
    }


def resolve(payload: Any) -> dict[str, Any]:
    repository: str | None = None
    try:
        if not isinstance(payload, dict):
            block("malformed_input", "resolver input must be an object", "operation owner")
        repository, change, work_item_ref, scope, criteria = validate_envelope(payload)
        requested = validate_requested_effects(payload)
        authority = validate_authority(payload)

        governed_policy = governance_adapter.resolve(
            {
                "repository": repository,
                "direct_consumer_policy": payload.get("consumer_policy"),
                "context_governance": payload.get("context_governance"),
            }
        )
        if governed_policy["status"] == "blocked":
            result = dict(governed_policy)
            result["blocker_source"] = "context_governance"
            return result

        branch_input = {
            "repository": repository,
            "repository_default_branch": payload.get("repository_default_branch"),
            "change": change,
            "consumer_policy": governed_policy["consumer_policy"],
            "operation_override": payload.get("operation_override"),
        }
        branch_result = branch_policy.resolve(branch_input)
        if branch_result["status"] == "blocked":
            result = dict(branch_result)
            result["blocker_source"] = "branch_policy"
            return result

        observations = validate_observations(
            payload.get("observations"),
            repository,
            branch_result["branch_name"],
            branch_result["pull_request_base"],
            work_item_ref,
        )
        blockers = delivery_blockers(observations)
        effects: list[dict[str, str]] = []
        for effect in requested:
            action = determine_action(effect, payload, observations, branch_result, repository, work_item_ref)
            if action == "apply":
                if authority.get(effect) is not True:
                    block(
                        "unauthorized_effect",
                        f"{effect} requires explicit authority",
                        "authority owner",
                        effect,
                    )
                if effect == "merge" and blockers:
                    block(
                        "merge_prerequisite_blocked",
                        "merge is blocked by review, check, or stale-head observations",
                        "change delivery owner",
                        effect,
                    )
            effects.append({"effect": effect, "action": action})

        pull_request = observations.get("pull_request")
        phase = "merged_evidence" if pull_request and pull_request.get("merged") else "pr_handoff" if pull_request else "change_execution"
        result = {
            "status": "resolved",
            "phase": phase,
            "repository": repository,
            "work_item_ref": work_item_ref,
            "scope_digest": scope_digest(scope),
            "immutable_scope": scope,
            "branch_contract": branch_result,
            "effects": effects,
            "handoff": build_handoff(repository, work_item_ref, branch_result, observations, criteria, blockers),
            "authority": AUTHORITY_NOTICE,
        }
        if governed_policy["source"] == "context_governance":
            result["policy_source"] = "context_governance"
            result["governance_provenance"] = governed_policy["governance_provenance"]
        return result
    except DeliveryBlock as exc:
        result: dict[str, Any] = {
            "status": "blocked",
            "code": exc.code,
            "reason": exc.reason,
            "owner": exc.owner,
            "authority": AUTHORITY_NOTICE,
        }
        if repository is not None:
            result["repository"] = repository
        if exc.effect is not None:
            result["effect"] = exc.effect
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
    return 0 if result["status"] == "resolved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
