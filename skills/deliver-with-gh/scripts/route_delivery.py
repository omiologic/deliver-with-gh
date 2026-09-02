#!/usr/bin/env python3
"""Route one explicit Delivery stage to one narrow GitHub delivery skill.

The router validates routing prerequisites and exact handoff references only.
It never runs child procedure, interprets branch policy, normalizes evidence,
performs effects, or infers canonical lifecycle state.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


STAGES = {"planning", "execution", "reconciliation"}
ACTIONS = {"planning_projection", "change_delivery", "evidence_reconciliation", "none"}
DESTINATIONS = {
    "planning_projection": "gh-work-planning",
    "change_delivery": "gh-change-delivery",
    "evidence_reconciliation": "gh-delivery-reconciliation",
}
AUTHORITY_NOTICE = (
    "Routing performs no GitHub effect and infers no canonical approval, readiness, completion, "
    "acceptance, deployment, release, or other lifecycle state."
)


class RoutingBlock(Exception):
    def __init__(self, code: str, reason: str, owner: str = "routing request owner"):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.owner = owner


def block(code: str, reason: str, owner: str = "routing request owner") -> None:
    raise RoutingBlock(code, reason, owner)


def exact_string(mapping: dict[str, Any], key: str, owner: str = "routing request owner") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        block("missing_reference", f"{key} must be a non-empty string", owner)
    return value


def validate_repository(value: Any, owner: str = "routing request owner") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        block("missing_repository", "repository-scoped routing requires exact owner/repo", owner)
    return value


def validate_project_ref(value: Any) -> Any:
    if isinstance(value, str) and value:
        return copy.deepcopy(value)
    if isinstance(value, dict) and value:
        node_id = value.get("node_id")
        owner = value.get("owner")
        number = value.get("number")
        has_node = isinstance(node_id, str) and bool(node_id)
        has_number = (
            isinstance(owner, str)
            and bool(owner)
            and not isinstance(number, bool)
            and isinstance(number, int)
            and number > 0
        )
        if has_node or has_number:
            return copy.deepcopy(value)
    block("missing_project", "planning projection requires an exact project_ref")


def validate_owner_state(raw: Any, flag: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        block("missing_owner_state", "owner_state must be an object", "Delivery state owner")
    if raw.get(flag) is not True:
        block(
            f"missing_{flag}",
            f"owner_state.{flag} must be explicitly true",
            "Delivery state owner",
        )
    exact_string(raw, "state_ref", "Delivery state owner")
    return raw


def validate_child_input(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        block("missing_child_input", "child_input must be an object")
    return raw


def planning_references(child_input: dict[str, Any]) -> dict[str, Any]:
    project_ref = validate_project_ref(child_input.get("project_ref"))
    work_items = child_input.get("work_items")
    if not isinstance(work_items, list) or not work_items:
        block("missing_bounded_work", "planning child_input requires non-empty work_items", "Planning owner")
    repositories: list[str] = []
    work_refs: list[str] = []
    plan_refs: list[str] = []
    for index, item in enumerate(work_items):
        if not isinstance(item, dict) or item.get("kind") not in {"issue", "draft"}:
            block("malformed_bounded_work", f"work_items[{index}] requires issue or draft kind", "Planning owner")
        if item["kind"] == "issue":
            repository = validate_repository(item.get("repository"), "Planning owner")
            if repository not in repositories:
                repositories.append(repository)
        elif "repository" in item:
            block("draft_repository_conflict", "draft planning items cannot supply repository identity", "Planning owner")
        canonical_refs = item.get("canonical_refs", {})
        if not isinstance(canonical_refs, dict):
            block("malformed_bounded_work", "canonical_refs must be an object", "Planning owner")
        work_ref = canonical_refs.get("work_item")
        plan_ref = canonical_refs.get("plan")
        if work_ref is not None:
            if not isinstance(work_ref, str) or not work_ref:
                block("missing_reference", "canonical work_item reference must be exact", "Planning owner")
            work_refs.append(work_ref)
        if plan_ref is not None:
            if not isinstance(plan_ref, str) or not plan_ref:
                block("missing_reference", "canonical plan reference must be exact", "Planning owner")
            if plan_ref not in plan_refs:
                plan_refs.append(plan_ref)
    return {
        "project_ref": project_ref,
        "repository_refs": repositories,
        "work_item_refs": work_refs,
        "plan_refs": plan_refs,
    }


def change_references(child_input: dict[str, Any]) -> dict[str, Any]:
    repository = validate_repository(child_input.get("repository"), "Change envelope owner")
    envelope = child_input.get("change_envelope")
    if not isinstance(envelope, dict):
        block("missing_change_envelope", "change delivery requires change_envelope", "Change envelope owner")
    work_item_ref = exact_string(envelope, "work_item_ref", "Change envelope owner")
    if not isinstance(child_input.get("consumer_policy"), dict):
        block("missing_consumer_policy", "consumer_policy must be passed to change delivery", "Consumer policy owner")
    requested = child_input.get("requested_effects")
    authority = child_input.get("authority")
    if not isinstance(requested, list) or not requested or any(not isinstance(value, str) or not value for value in requested):
        block("missing_authority", "change delivery requires non-empty requested_effects", "Authority owner")
    if not isinstance(authority, dict):
        block("missing_authority", "change delivery requires an authority object", "Authority owner")
    unauthorized = [effect for effect in requested if authority.get(effect) is not True]
    if unauthorized:
        block(
            "missing_authority",
            f"requested effects lack explicit authority: {', '.join(unauthorized)}",
            "Authority owner",
        )
    return {"repository_ref": repository, "work_item_ref": work_item_ref}


def reconciliation_references(child_input: dict[str, Any]) -> dict[str, Any]:
    work_item_ref = exact_string(child_input, "work_item_ref", "Delivery expectation owner")
    criteria = child_input.get("criteria")
    observations = child_input.get("observations")
    if not isinstance(criteria, list) or not criteria:
        block("missing_criteria", "reconciliation child_input requires criteria", "Delivery expectation owner")
    if not isinstance(observations, list) or not observations:
        block("missing_github_evidence", "reconciliation child_input requires GitHub observations")
    repositories: list[str] = []
    projects: list[Any] = []
    evidence_refs: list[str] = []
    for observation in observations:
        if not isinstance(observation, dict):
            block("malformed_github_evidence", "GitHub observations must be objects")
        repository = observation.get("repository")
        if repository is not None:
            repository = validate_repository(repository)
            if repository not in repositories:
                repositories.append(repository)
        project_ref = observation.get("project_ref")
        if project_ref is not None:
            project_ref = validate_project_ref(project_ref)
            if project_ref not in projects:
                projects.append(project_ref)
        for key in ("url", "sha", "head_sha", "merge_commit_sha", "item_id"):
            value = observation.get(key)
            if value is not None:
                if not isinstance(value, str) or not value:
                    block("missing_reference", f"observation {key} must be exact")
                evidence_refs.append(value)
    return {
        "work_item_ref": work_item_ref,
        "repository_refs": repositories,
        "project_refs": projects,
        "evidence_refs": evidence_refs,
    }


def routed(destination: str, basis: str, child_input: dict[str, Any], references: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "routed",
        "destination": destination,
        "routing_basis": basis,
        "handoff": {"references": references, "child_input": copy.deepcopy(child_input)},
        "canonical_state_inferences": [],
        "authority": AUTHORITY_NOTICE,
    }


def returned(reason: str) -> dict[str, Any]:
    return {
        "status": "returned",
        "destination": "deliver-product",
        "reason": reason,
        "canonical_state_inferences": [],
        "authority": AUTHORITY_NOTICE,
    }


def resolve(payload: Any) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            block("malformed_input", "router input must be an object")
        stage = payload.get("delivery_stage")
        if stage not in STAGES:
            return returned("delivery_stage_unresolved")
        action = payload.get("github_action", "none")
        if action not in ACTIONS:
            block("unsupported_action", f"unsupported github_action: {action!r}")
        if action == "none":
            return returned("no_github_specific_action")

        pending = payload.get("unreconciled_github_evidence")
        if action == "change_delivery" and pending is not None:
            child_input = validate_child_input(pending)
            references = reconciliation_references(child_input)
            return routed(
                DESTINATIONS["evidence_reconciliation"],
                "unreconciled_github_evidence_precedes_change_delivery",
                child_input,
                references,
            )

        expected_stage = {
            "planning_projection": "planning",
            "change_delivery": "execution",
            "evidence_reconciliation": "reconciliation",
        }[action]
        if stage != expected_stage:
            block(
                "stage_action_conflict",
                f"delivery_stage {stage!r} does not match github_action {action!r}",
                "Delivery state owner",
            )
        child_input = validate_child_input(payload.get("child_input"))

        if action == "planning_projection":
            validate_owner_state(payload.get("owner_state"), "bounded")
            references = planning_references(child_input)
        elif action == "change_delivery":
            validate_owner_state(payload.get("owner_state"), "ready")
            references = change_references(child_input)
        else:
            references = reconciliation_references(child_input)
        return routed(DESTINATIONS[action], f"explicit_{stage}_{action}", child_input, references)
    except RoutingBlock as exc:
        return {
            "status": "blocked",
            "code": exc.code,
            "reason": exc.reason,
            "owner": exc.owner,
            "canonical_state_inferences": [],
            "authority": AUTHORITY_NOTICE,
        }


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
            "owner": "routing request owner",
            "canonical_state_inferences": [],
            "authority": AUTHORITY_NOTICE,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    result = resolve(payload)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
