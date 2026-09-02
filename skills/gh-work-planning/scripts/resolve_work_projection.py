#!/usr/bin/env python3
"""Resolve bounded work into a deterministic GitHub planning projection.

The resolver is deliberately read-only. It accepts one JSON object on stdin
(or from a file argument) and emits a desired projection plus a create, update,
or no-op decision. It never calls GitHub and never changes canonical Delivery
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


AUTHORITY_NOTICE = (
    "GitHub Issue and Project state is a projection only; it does not establish "
    "canonical readiness, priority, assignment, acceptance, or completion."
)
MAPPING_SURFACES = {"issue_type", "labels", "milestone", "project_fields"}
PARENT_REF_PATTERN = re.compile(r"[^/\s]+/[^/\s]+#[1-9][0-9]*")


class ProjectionBlock(Exception):
    def __init__(
        self,
        code: str,
        reason: str,
        owner: str = "planning projection owner",
        item_index: int | None = None,
        mapping: str | None = None,
    ):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.owner = owner
        self.item_index = item_index
        self.mapping = mapping


def block(
    code: str,
    reason: str,
    owner: str = "planning projection owner",
    item_index: int | None = None,
    mapping: str | None = None,
) -> None:
    raise ProjectionBlock(code, reason, owner, item_index, mapping)


def exact_string(value: Any, field: str, item_index: int | None = None) -> str:
    if not isinstance(value, str) or not value:
        block("missing_reference", f"{field} must be a non-empty string", item_index=item_index)
    return value


def validate_repository(value: Any, item_index: int) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        block(
            "missing_repository",
            "repository-scoped Issue items require an exact owner/repo",
            "bounded work owner",
            item_index,
        )
    return value


def validate_project_ref(value: Any) -> Any:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and value:
        # Project identity is intentionally opaque. The owning caller supplies
        # the exact node/number reference, which is preserved without deriving
        # repository identity from it.
        node_id = value.get("node_id")
        owner = value.get("owner")
        number = value.get("number")
        has_node_identity = isinstance(node_id, str) and bool(node_id)
        has_number_identity = (
            isinstance(owner, str)
            and bool(owner)
            and not isinstance(number, bool)
            and isinstance(number, int)
            and number > 0
        )
        if not has_node_identity and not has_number_identity:
            block(
                "missing_project",
                "project_ref object requires node_id or exact owner and positive number",
            )
        return copy.deepcopy(value)
    block("missing_project", "project_ref must be a non-empty string or object")


def validate_string_list(value: Any, field: str, item_index: int) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(entry, str) or not entry for entry in value):
        block("malformed_work_item", f"{field} must be a list of non-empty strings", item_index=item_index)
    return list(value)


def render_issue_body(item: dict[str, Any], canonical_refs: dict[str, str], item_index: int) -> str:
    content = item.get("content", {})
    if not isinstance(content, dict):
        block("malformed_work_item", "content must be an object", item_index=item_index)

    sections: list[str] = []
    for key, heading in (("outcome", "Outcome"), ("scope", "Scope")):
        value = content.get(key)
        if value is not None:
            if not isinstance(value, str) or not value:
                block("malformed_work_item", f"content.{key} must be a non-empty string", item_index=item_index)
            sections.append(f"## {heading}\n\n{value}")

    acceptance = content.get("acceptance_criteria")
    if acceptance is not None:
        criteria = validate_string_list(acceptance, "content.acceptance_criteria", item_index)
        sections.append("## Acceptance criteria\n\n" + "\n".join(f"- [ ] {criterion}" for criterion in criteria))

    dependencies = content.get("dependencies")
    if dependencies is not None:
        dependency_list = validate_string_list(dependencies, "content.dependencies", item_index)
        sections.append("## Dependencies\n\n" + "\n".join(f"- {dependency}" for dependency in dependency_list))

    traceability = content.get("traceability", [])
    if traceability is not None:
        traceability_list = validate_string_list(traceability, "content.traceability", item_index)
    else:
        traceability_list = []
    exact_refs = [f"{name}: {value}" for name, value in canonical_refs.items()]
    traceability_list = exact_refs + traceability_list
    if traceability_list:
        sections.append("## Traceability\n\n" + "\n".join(f"- {entry}" for entry in traceability_list))

    return "\n\n".join(sections)


def map_scalar(raw: Any, config: dict[str, Any]) -> tuple[bool, Any]:
    values = config.get("values")
    if values is None:
        return True, copy.deepcopy(raw)
    if not isinstance(values, dict):
        block("malformed_mapping", "mapping values must be an object", "consumer mapping owner")
    try:
        if raw in values:
            return True, copy.deepcopy(values[raw])
    except TypeError:
        pass
    return False, None


def read_mapping_config(config: Any, mapping_name: str) -> tuple[str, bool]:
    if not isinstance(config, dict):
        block("malformed_mapping", f"{mapping_name} mapping must be an object", "consumer mapping owner")
    source = config.get("source")
    required = config.get("required", False)
    if not isinstance(source, str) or not source or not isinstance(required, bool):
        block(
            "malformed_mapping",
            f"{mapping_name} requires a source string and optional boolean required flag",
            "consumer mapping owner",
        )
    return source, required


def resolve_one_mapping(
    planning_values: dict[str, Any],
    surface: str,
    target: str,
    config: Any,
    item_index: int,
) -> tuple[bool, Any, str | None]:
    mapping_name = f"{surface}.{target}" if surface == "project_fields" else surface
    source, required = read_mapping_config(config, mapping_name)
    if source not in planning_values:
        if required:
            block(
                "mapping_unavailable",
                f"required source {source!r} is unavailable for {mapping_name}",
                "consumer mapping owner",
                item_index,
                mapping_name,
            )
        return False, None, f"optional mapping {mapping_name} omitted: source {source!r} unavailable"

    raw = planning_values[source]
    if surface == "labels":
        if not isinstance(raw, list):
            block("malformed_work_item", f"planning_values.{source} must be a list", item_index=item_index)
        mapped: list[Any] = []
        for entry in raw:
            available, value = map_scalar(entry, config)
            if not available:
                if required:
                    block(
                        "mapping_unavailable",
                        f"required value {entry!r} has no mapping for {mapping_name}",
                        "consumer mapping owner",
                        item_index,
                        mapping_name,
                    )
                return False, None, f"optional mapping {mapping_name} omitted: value {entry!r} unavailable"
            mapped.append(value)
        return True, mapped, None

    available, value = map_scalar(raw, config)
    if not available:
        if required:
            block(
                "mapping_unavailable",
                f"required value {raw!r} has no mapping for {mapping_name}",
                "consumer mapping owner",
                item_index,
                mapping_name,
            )
        return False, None, f"optional mapping {mapping_name} omitted: value {raw!r} unavailable"
    return True, value, None


def resolve_metadata(
    planning_values: Any, mappings: dict[str, Any], kind: str, item_index: int
) -> tuple[dict[str, Any], list[str]]:
    if planning_values is None:
        planning_values = {}
    if not isinstance(planning_values, dict):
        block("malformed_work_item", "planning_values must be an object", item_index=item_index)
    metadata: dict[str, Any] = {}
    omissions: list[str] = []
    for surface in sorted(mappings):
        config = mappings[surface]
        if surface not in MAPPING_SURFACES:
            block("unsupported_mapping", f"unsupported mapping surface: {surface}", "consumer mapping owner")
        if surface == "project_fields":
            if not isinstance(config, dict):
                block("malformed_mapping", "project_fields mapping must be an object", "consumer mapping owner")
            fields: dict[str, Any] = {}
            for target in sorted(config):
                available, value, omission = resolve_one_mapping(
                    planning_values, surface, target, config[target], item_index
                )
                if available:
                    fields[target] = value
                elif omission:
                    omissions.append(omission)
            if fields:
                metadata[surface] = fields
        elif surface == "issue_type" and kind != "issue":
            # A native Issue type belongs to an Issue. A draft item carries no
            # Issue identity, so the surface is unavailable rather than invalid.
            _, required = read_mapping_config(config, surface)
            if required:
                block(
                    "mapping_unavailable",
                    "required mapping issue_type is unavailable for a draft item",
                    "consumer mapping owner",
                    item_index,
                    surface,
                )
            omissions.append(
                "optional mapping issue_type omitted: a draft item carries no native Issue type"
            )
        else:
            available, value, omission = resolve_one_mapping(
                planning_values, surface, surface, config, item_index
            )
            if available:
                metadata[surface] = value
            elif omission:
                omissions.append(omission)
    return metadata, omissions


def resolve_parent(item: dict[str, Any], kind: str, repository: str | None, item_index: int) -> Any:
    """Normalize an optional sub-issue parent reference.

    The resolver never asks GitHub whether the parent exists. It only forwards
    an exact reference an authorized caller can use to create the sub-issue
    link, or blocks on a reference it cannot normalize.
    """
    parent = item.get("parent")
    if parent is None:
        return None
    if kind == "issue":
        if not isinstance(parent, bool) and isinstance(parent, int):
            if parent < 1:
                block(
                    "malformed_parent",
                    "a same-repository parent Issue number must be a positive integer",
                    "bounded work owner",
                    item_index,
                )
            return f"{repository}#{parent}"
        if isinstance(parent, str) and PARENT_REF_PATTERN.fullmatch(parent):
            return parent
        block(
            "malformed_parent",
            "an Issue parent must be a positive same-repository Issue number or an exact owner/repo#number",
            "bounded work owner",
            item_index,
        )
    if not isinstance(parent, dict) or set(parent) != {"item_index"}:
        block(
            "malformed_parent",
            "a draft parent must be an object containing only item_index",
            "bounded work owner",
            item_index,
        )
    index = parent["item_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        block(
            "malformed_parent",
            "parent.item_index must be a non-negative integer",
            "bounded work owner",
            item_index,
        )
    if index >= item_index:
        block(
            "parent_out_of_range",
            f"parent.item_index {index} must reference an earlier item in the same batch",
            "bounded work owner",
            item_index,
        )
    return {"item_index": index}


def resolve_item(item: Any, mappings: dict[str, Any], item_index: int) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(item, dict):
        block("malformed_work_item", "each work item must be an object", item_index=item_index)
    kind = item.get("kind")
    if kind not in {"issue", "draft"}:
        block("unsupported_item_kind", "kind must be 'issue' or 'draft'", item_index=item_index)
    title = exact_string(item.get("title"), "title", item_index)

    canonical_refs = item.get("canonical_refs", {})
    if not isinstance(canonical_refs, dict):
        block("malformed_work_item", "canonical_refs must be an object", item_index=item_index)
    for name, value in canonical_refs.items():
        if not isinstance(name, str) or not name or not isinstance(value, str) or not value:
            block(
                "malformed_work_item",
                "canonical_refs must map non-empty names to exact non-empty references",
                item_index=item_index,
            )
    canonical_refs = copy.deepcopy(canonical_refs)
    metadata, omissions = resolve_metadata(item.get("planning_values"), mappings, kind, item_index)

    projected: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "body": render_issue_body(item, canonical_refs, item_index),
        "canonical_refs": canonical_refs,
        "github_metadata": metadata,
    }
    if kind == "issue":
        repository = validate_repository(item.get("repository"), item_index)
        projected["repository"] = repository
        issue_number = item.get("issue_number")
        if issue_number is not None:
            if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
                block("malformed_issue", "issue_number must be a positive integer", item_index=item_index)
            projected["issue_ref"] = f"{repository}#{issue_number}"
    else:
        if "repository" in item or "issue_number" in item:
            block(
                "draft_repository_conflict",
                "draft items cannot carry repository or Issue identity",
                "bounded work owner",
                item_index,
            )
    parent = resolve_parent(item, kind, projected.get("repository"), item_index)
    if parent is not None:
        projected["parent"] = parent
    item_id = item.get("project_item_id")
    if item_id is not None:
        projected["project_item_id"] = exact_string(item_id, "project_item_id", item_index)
    return projected, omissions


def extract_mappings(payload: dict[str, Any]) -> dict[str, Any]:
    policy = payload.get("consumer_policy", {})
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        block("malformed_policy", "consumer_policy must be an object", "consumer mapping owner")
    mappings = policy.get("mappings", {})
    if not isinstance(mappings, dict):
        block("malformed_mapping", "consumer_policy.mappings must be an object", "consumer mapping owner")
    return mappings


def resolve(payload: Any) -> dict[str, Any]:
    project_ref: Any = None
    try:
        if not isinstance(payload, dict):
            block("malformed_input", "resolver input must be an object", "operation owner")
        project_ref = validate_project_ref(payload.get("project_ref"))
        mappings = extract_mappings(payload)
        work_items = payload.get("work_items")
        if not isinstance(work_items, list) or not work_items:
            block("missing_work_items", "work_items must be a non-empty list", "bounded work owner")

        projected_items: list[dict[str, Any]] = []
        omissions: list[dict[str, Any]] = []
        for item_index, item in enumerate(work_items):
            projected, item_omissions = resolve_item(item, mappings, item_index)
            projected_items.append(projected)
            omissions.extend({"item_index": item_index, "reason": reason} for reason in item_omissions)

        desired = {"project_ref": project_ref, "items": projected_items}
        existing = payload.get("existing_projection")
        if existing is None:
            action = "create"
        elif existing == desired:
            action = "none"
        else:
            action = "update"

        return {
            "status": "resolved",
            "action": action,
            "projection": desired,
            "omissions": omissions,
            "authority": AUTHORITY_NOTICE,
        }
    except ProjectionBlock as exc:
        result: dict[str, Any] = {
            "status": "blocked",
            "code": exc.code,
            "reason": exc.reason,
            "owner": exc.owner,
            "authority": AUTHORITY_NOTICE,
        }
        if project_ref is not None:
            result["project_ref"] = project_ref
        if exc.item_index is not None:
            result["item_index"] = exc.item_index
        if exc.mapping is not None:
            result["mapping"] = exc.mapping
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
