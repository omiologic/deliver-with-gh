#!/usr/bin/env python3
"""Adapt optional bounded Context Governance output to consumer branch policy.

The adapter performs no Context Governance discovery itself and has no hard
dependency on that package. When installed, its compact resolved context is
supplied as input. Relevant record statements contain exact fragments of the
existing github_delivery.branching contract.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


DECLARATION_PREFIX = "github_delivery.branching ="
BRANCH_RESOLVER_PATH = Path(__file__).with_name("resolve_branch_policy.py")
SPEC = importlib.util.spec_from_file_location("governance_adapter_branch_policy", BRANCH_RESOLVER_PATH)
branch_policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(branch_policy)
TARGET_FIELDS = branch_policy.SUPPORTED_POLICY_FIELDS
AUTHORITY_NOTICE = (
    "Governed records are policy input only. Adaptation grants no branch, commit, push, "
    "pull-request, review, merge, lifecycle, or Constraint-waiver authority."
)


class GovernanceBlock(Exception):
    def __init__(
        self,
        code: str,
        reason: str,
        owner: str,
        record: str | None = None,
    ):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.owner = owner
        self.record = record


def block(code: str, reason: str, owner: str, record: str | None = None) -> None:
    raise GovernanceBlock(code, reason, owner, record)


def validate_repository(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        block(
            "missing_repository",
            "repository must be an exact owner/repo string",
            "change envelope owner",
        )
    return value


def extract_direct_branching(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        block("malformed_policy", "direct_consumer_policy must be an object", "consumer policy owner")
    if "github_delivery" in raw:
        delivery = raw["github_delivery"]
        if not isinstance(delivery, dict) or not isinstance(delivery.get("branching"), dict):
            block(
                "malformed_policy",
                "direct_consumer_policy.github_delivery.branching must be an object",
                "consumer policy owner",
            )
        return copy.deepcopy(delivery["branching"])
    if "branching" in raw:
        if not isinstance(raw["branching"], dict):
            block("malformed_policy", "direct_consumer_policy.branching must be an object", "consumer policy owner")
        return copy.deepcopy(raw["branching"])
    return copy.deepcopy(raw)


def validate_context(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        block(
            "missing_governance_resolution",
            "installed Context Governance requires bounded resolved_context",
            "Context Governance owner",
        )
    for collection in ("conventions", "constraints", "blockers"):
        if not isinstance(raw.get(collection, []), list):
            block(
                "malformed_governance_context",
                f"resolved_context.{collection} must be a list",
                "Context Governance owner",
            )
    target = raw.get("target")
    if not isinstance(target, str) or not target:
        block(
            "malformed_governance_context",
            "resolved_context.target must be a non-empty repository-relative target",
            "Context Governance owner",
        )
    return raw


def constraint_owner(entry: dict[str, Any]) -> str:
    source = entry.get("source")
    return source if isinstance(source, str) and source else "Constraint owner"


def enforce_context_blockers(context: dict[str, Any]) -> None:
    constraints_by_id: dict[str, dict[str, Any]] = {}
    for entry in context.get("constraints", []):
        if not isinstance(entry, dict):
            block(
                "malformed_governance_context",
                "each resolved Constraint must be an object",
                "Context Governance owner",
            )
        constraint_id = entry.get("constraint_id")
        if not isinstance(constraint_id, str) or not constraint_id:
            block(
                "malformed_governance_context",
                "resolved Constraint requires constraint_id",
                "Context Governance owner",
            )
        constraints_by_id[constraint_id] = entry
        check = entry.get("check")
        if check not in {"satisfied", "violated", "unknown"}:
            block(
                "malformed_governance_context",
                f"Constraint {constraint_id} has invalid check state",
                "Context Governance owner",
                entry.get("record"),
            )
        if check in {"violated", "unknown"}:
            block(
                f"governance_constraint_{check}",
                f"Constraint {constraint_id} is {check}; branch policy resolution cannot proceed",
                constraint_owner(entry),
                entry.get("record"),
            )
    for blocker in context.get("blockers", []):
        if not isinstance(blocker, dict):
            block(
                "malformed_governance_context",
                "each governance blocker must be an object",
                "Context Governance owner",
            )
        kind = blocker.get("kind")
        if kind in {"constraint_unknown", "constraint_violated"}:
            reference = blocker.get("reference")
            constraint = constraints_by_id.get(reference) if isinstance(reference, str) else None
            state = kind.removeprefix("constraint_")
            block(
                f"governance_constraint_{state}",
                blocker.get("reason")
                if isinstance(blocker.get("reason"), str) and blocker["reason"]
                else f"Constraint {reference!r} is {state}",
                constraint_owner(constraint) if constraint else "Context Governance owner",
                constraint.get("record") if constraint else reference,
            )
        reference = blocker.get("reference")
        reason = blocker.get("reason")
        block(
            "governance_context_blocked",
            reason if isinstance(reason, str) and reason else f"Context Governance reported blocker {kind!r}",
            "Context Governance owner",
            reference if isinstance(reference, str) else None,
        )


def parse_fragment(entry: dict[str, Any], kind: str) -> dict[str, Any] | None:
    identifier_key = "convention_id" if kind == "convention" else "constraint_id"
    identifier = entry.get(identifier_key)
    record = entry.get("record")
    if not isinstance(identifier, str) or not identifier:
        block(
            "malformed_governance_context",
            f"resolved {kind} requires {identifier_key}",
            "Context Governance owner",
            record if isinstance(record, str) else None,
        )
    statement = entry.get("statement")
    if not isinstance(statement, str):
        block(
            "malformed_governance_context",
            f"resolved {kind} {identifier} requires a statement",
            "Context Governance owner",
            record if isinstance(record, str) else None,
        )
    stripped = statement.strip()
    if not stripped.startswith(DECLARATION_PREFIX):
        return None
    encoded = stripped[len(DECLARATION_PREFIX) :].strip()
    try:
        fragment = json.loads(encoded)
    except json.JSONDecodeError as exc:
        block(
            "malformed_governed_policy",
            f"{identifier} has invalid github_delivery.branching JSON: {exc.msg}",
            constraint_owner(entry) if kind == "constraint" else "Convention owner",
            record if isinstance(record, str) else None,
        )
    if not isinstance(fragment, dict) or not fragment:
        block(
            "malformed_governed_policy",
            f"{identifier} must declare a non-empty branching object",
            constraint_owner(entry) if kind == "constraint" else "Convention owner",
            record if isinstance(record, str) else None,
        )
    unsupported = sorted(set(fragment) - TARGET_FIELDS)
    if unsupported:
        block(
            "unsupported_governed_policy",
            f"{identifier} declares fields outside github_delivery.branching: {', '.join(unsupported)}",
            constraint_owner(entry) if kind == "constraint" else "Convention owner",
            record if isinstance(record, str) else None,
        )
    return fragment


def merge_field(
    target: dict[str, Any],
    sources: dict[str, str],
    key: str,
    value: Any,
    source: str,
) -> None:
    if key in target and target[key] != value:
        block(
            "policy_source_conflict",
            f"branch policy field {key!r} conflicts between {sources[key]} and {source}",
            "consumer governance owner",
            source,
        )
    target[key] = copy.deepcopy(value)
    sources[key] = source


def resolve(payload: Any) -> dict[str, Any]:
    repository: str | None = None
    try:
        if not isinstance(payload, dict):
            block("malformed_input", "adapter input must be an object", "operation owner")
        repository = validate_repository(payload.get("repository"))
        direct_policy = payload.get("direct_consumer_policy")
        integration = payload.get("context_governance")
        if integration is None:
            return {
                "status": "resolved",
                "source": "direct",
                "consumer_policy": copy.deepcopy(direct_policy),
                "governance_provenance": [],
                "authority": AUTHORITY_NOTICE,
            }
        if not isinstance(integration, dict) or not isinstance(integration.get("installed"), bool):
            block(
                "malformed_governance_integration",
                "context_governance must declare boolean installed",
                "operation owner",
            )
        if integration["installed"] is False:
            return {
                "status": "resolved",
                "source": "direct",
                "consumer_policy": copy.deepcopy(direct_policy),
                "governance_provenance": [],
                "authority": AUTHORITY_NOTICE,
            }

        context = validate_context(integration.get("resolved_context"))
        enforce_context_blockers(context)
        fragments: list[tuple[str, dict[str, Any]]] = []
        provenance: list[dict[str, Any]] = []
        for kind, collection in (("convention", "conventions"), ("constraint", "constraints")):
            for entry in context.get(collection, []):
                if not isinstance(entry, dict):
                    block(
                        "malformed_governance_context",
                        f"each resolved {kind} must be an object",
                        "Context Governance owner",
                    )
                if kind == "convention" and entry.get("strength") == "recommended":
                    continue
                fragment = parse_fragment(entry, kind)
                if fragment is None:
                    continue
                identifier = entry[f"{kind}_id"]
                record = entry.get("record")
                source = record if isinstance(record, str) and record else identifier
                fragments.append((source, fragment))
                provenance.append(
                    {
                        "kind": kind,
                        "id": identifier,
                        "record": record,
                        "fields": sorted(fragment),
                    }
                )

        if not fragments:
            return {
                "status": "resolved",
                "source": "direct_no_applicable_governance",
                "consumer_policy": copy.deepcopy(direct_policy),
                "governance_provenance": [],
                "authority": AUTHORITY_NOTICE,
            }

        branching = extract_direct_branching(direct_policy)
        sources = {key: "direct consumer policy" for key in branching}
        for source, fragment in fragments:
            for key, value in fragment.items():
                merge_field(branching, sources, key, value, source)
        policy_repository = branching.get("repository")
        if policy_repository is not None and policy_repository != repository:
            block(
                "repository_conflict",
                f"governed policy repository {policy_repository!r} conflicts with {repository!r}",
                "consumer governance owner",
            )
        return {
            "status": "resolved",
            "source": "context_governance",
            "consumer_policy": {"github_delivery": {"branching": branching}},
            "governance_provenance": provenance,
            "authority": AUTHORITY_NOTICE,
        }
    except GovernanceBlock as exc:
        result: dict[str, Any] = {
            "status": "blocked",
            "code": exc.code,
            "reason": exc.reason,
            "owner": exc.owner,
            "authority": AUTHORITY_NOTICE,
        }
        if repository is not None:
            result["repository"] = repository
        if exc.record is not None:
            result["record"] = exc.record
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
