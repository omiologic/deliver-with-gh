#!/usr/bin/env python3
"""Resolve repository-scoped branching policy into a deterministic contract.

The resolver intentionally performs no Git or GitHub mutations. It accepts one
JSON object on stdin (or from a file argument) and emits one JSON object.
"""

from __future__ import annotations

import argparse
import json
import re
import string
import sys
import unicodedata
from pathlib import Path
from typing import Any


SUPPORTED_STRATEGIES = {"trunk", "feature", "release", "custom"}
SUPPORTED_PLACEHOLDERS = {"type", "work_item_id", "slug"}
OVERRIDABLE_FIELDS = {
    "base_branch",
    "branch_pattern",
    "change_type",
    "pull_request_base",
    "requires_pull_request",
    "strategy",
}
AUTHORITY_NOTICE = (
    "Resolution does not authorize branch, commit, push, pull-request, merge, "
    "tag, release, or repository-setting mutations."
)


class PolicyBlock(Exception):
    def __init__(self, code: str, reason: str, owner: str = "consumer repository policy"):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.owner = owner


def block(code: str, reason: str, owner: str = "consumer repository policy") -> None:
    raise PolicyBlock(code, reason, owner)


def require_bool(policy: dict[str, Any], key: str) -> bool:
    value = policy.get(key)
    if not isinstance(value, bool):
        block("missing_semantics", f"{key} must be explicitly configured as a boolean")
    return value


def require_string(mapping: dict[str, Any], key: str, owner: str = "consumer repository policy") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        block("missing_semantics", f"{key} must be a non-empty string", owner)
    return value


def extract_branching_policy(raw: Any) -> dict[str, Any]:
    if raw is None:
        block("missing_policy", "branch strategy is not configured")
    if not isinstance(raw, dict):
        block("malformed_policy", "consumer_policy must be an object")

    if "github_delivery" in raw:
        delivery = raw["github_delivery"]
        if not isinstance(delivery, dict) or not isinstance(delivery.get("branching"), dict):
            block("malformed_policy", "consumer_policy.github_delivery.branching must be an object")
        return dict(delivery["branching"])
    if "branching" in raw:
        if not isinstance(raw["branching"], dict):
            block("malformed_policy", "consumer_policy.branching must be an object")
        return dict(raw["branching"])
    return dict(raw)


def validate_repository(repository: Any) -> str:
    if not isinstance(repository, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        block(
            "missing_repository",
            "repository must be an exact owner/repo string",
            "change envelope owner",
        )
    return repository


def apply_override(policy: dict[str, Any], operation_override: Any) -> dict[str, Any]:
    allowed = policy.get("allowed_operation_overrides", [])
    if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
        block("malformed_policy", "allowed_operation_overrides must be a list of field names")
    unsupported_allowed = sorted(set(allowed) - OVERRIDABLE_FIELDS)
    if unsupported_allowed:
        block(
            "malformed_policy",
            f"allowed_operation_overrides contains unsupported fields: {', '.join(unsupported_allowed)}",
        )
    if operation_override is None:
        return policy
    if not isinstance(operation_override, dict):
        block("malformed_override", "operation_override must be an object", "operation owner")

    unsupported = sorted(set(operation_override) - OVERRIDABLE_FIELDS)
    if unsupported:
        block(
            "unsupported_override",
            f"operation override contains unsupported fields: {', '.join(unsupported)}",
            "operation owner",
        )
    disallowed = sorted(set(operation_override) - set(allowed))
    if disallowed:
        block(
            "disallowed_override",
            f"operation override is not allowed for: {', '.join(disallowed)}",
            "consumer repository policy",
        )
    resolved = dict(policy)
    resolved.update(operation_override)
    return resolved


def validate_branch_name(name: str, field: str) -> None:
    invalid = (
        not name
        or name == "@"
        or name.startswith("-")
        or name.startswith("/")
        or name.endswith("/")
        or name.endswith(".")
        or "//" in name
        or ".." in name
        or "@{" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or any(char in " ~^:?*[\\" for char in name)
        or any(part.startswith(".") or part.endswith(".lock") for part in name.split("/"))
    )
    if invalid:
        block("invalid_branch", f"{field} is not a valid Git branch name: {name!r}")


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return re.sub(r"-+", "-", slug)


def render_branch_name(pattern: Any, change: dict[str, Any], policy: dict[str, Any]) -> str:
    if not isinstance(pattern, str) or not pattern:
        block("missing_semantics", "branch_pattern must be a non-empty string")

    formatter = string.Formatter()
    try:
        parsed = list(formatter.parse(pattern))
    except ValueError as exc:
        block("malformed_pattern", f"branch_pattern is malformed: {exc}")

    placeholders = [field for _, field, spec, conversion in parsed if field is not None]
    unknown = sorted(set(placeholders) - SUPPORTED_PLACEHOLDERS)
    if unknown:
        block("unknown_placeholder", f"branch_pattern contains unknown placeholders: {', '.join(unknown)}")
    if any(spec or conversion for _, field, spec, conversion in parsed if field is not None):
        block("malformed_pattern", "branch_pattern placeholders cannot use conversions or format specs")
    if len(placeholders) != len(set(placeholders)):
        block("malformed_pattern", "branch_pattern may use each placeholder at most once")

    values: dict[str, str] = {}
    if "type" in placeholders:
        change_type = policy.get("change_type", change.get("type"))
        if not isinstance(change_type, str) or not change_type:
            block("missing_change_input", "change type is required by branch_pattern", "WorkItem/change owner")
        allowed_types = policy.get("allowed_types")
        if not isinstance(allowed_types, list) or not allowed_types:
            block("missing_semantics", "allowed_types is required when branch_pattern contains {type}")
        if any(not isinstance(item, str) or not item for item in allowed_types):
            block("malformed_policy", "allowed_types must contain non-empty strings")
        if change_type not in allowed_types:
            block("disallowed_type", f"change type {change_type!r} is not allowed")
        values["type"] = change_type
    if "work_item_id" in placeholders:
        values["work_item_id"] = require_string(change, "work_item_id", "WorkItem/change owner")
    if "slug" in placeholders:
        title = require_string(change, "title", "WorkItem/change owner")
        values["slug"] = slugify(title)
        if not values["slug"]:
            block("invalid_slug", "change title does not produce a usable slug", "WorkItem/change owner")

    max_length = policy.get("max_branch_length")
    if max_length is not None:
        if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
            block("malformed_policy", "max_branch_length must be a positive integer")
        if "slug" in values:
            without_slug = pattern.format(**{**values, "slug": ""})
            available = max_length - len(without_slug)
            values["slug"] = values["slug"][:available].rstrip("-") if available > 0 else ""
            if not values["slug"]:
                block("maximum_length", "max_branch_length leaves no room for the required slug")

    try:
        branch_name = pattern.format(**values)
    except (KeyError, ValueError) as exc:
        block("malformed_pattern", f"branch_pattern could not be rendered: {exc}")
    if max_length is not None and len(branch_name) > max_length:
        block("maximum_length", "rendered branch name exceeds max_branch_length")

    validate_branch_name(branch_name, "rendered branch_name")
    regex = policy.get("branch_name_regex")
    if regex is not None:
        if not isinstance(regex, str) or not regex:
            block("malformed_policy", "branch_name_regex must be a non-empty string")
        try:
            matches = re.fullmatch(regex, branch_name) is not None
        except re.error as exc:
            block("malformed_policy", f"branch_name_regex is invalid: {exc}")
        if not matches:
            block("branch_pattern_mismatch", "rendered branch name does not match branch_name_regex")
    return branch_name


def resolve_base(policy: dict[str, Any], payload: dict[str, Any], strategy: str) -> str:
    base = policy.get("base_branch")
    if base is None:
        use_default = policy.get("use_repository_default_as_base", False)
        if not isinstance(use_default, bool):
            block("malformed_policy", "use_repository_default_as_base must be a boolean")
        if use_default and strategy in {"trunk", "feature"}:
            base = payload.get("repository_default_branch")
        elif use_default:
            block(
                "default_branch_not_permitted",
                f"repository default branch fallback is not defined for {strategy} strategy",
            )
    if not isinstance(base, str) or not base:
        block("missing_base", "base_branch is not configured and no permitted default fallback resolved")
    validate_branch_name(base, "base_branch")
    return base


def resolve_standard_strategy(
    strategy: str,
    policy: dict[str, Any],
    payload: dict[str, Any],
    change: dict[str, Any],
) -> dict[str, Any]:
    base = resolve_base(policy, payload, strategy)
    protected = policy.get("protected_branches", [])
    if not isinstance(protected, list) or any(not isinstance(item, str) for item in protected):
        block("malformed_policy", "protected_branches must be a list of branch names")

    if strategy == "feature":
        requires_new_branch = True
        requires_pull_request = require_bool(policy, "requires_pull_request")
    else:
        direct_work_allowed = require_bool(policy, "direct_work_allowed")
        requires_pull_request = require_bool(policy, "requires_pull_request")
        if direct_work_allowed and requires_pull_request:
            block("conflicting_policy", "direct_work_allowed conflicts with requires_pull_request")
        if not direct_work_allowed and not requires_pull_request:
            block("conflicting_policy", "trunk policy forbids direct work but does not require a pull request")
        requires_new_branch = requires_pull_request

    branch_name = render_branch_name(policy.get("branch_pattern"), change, policy) if requires_new_branch else base
    pull_request_base = policy.get("pull_request_base", base) if requires_pull_request else None
    if not requires_pull_request and policy.get("pull_request_base") is not None:
        block("conflicting_policy", "pull_request_base is configured when no pull request is required")
    if pull_request_base is not None:
        if not isinstance(pull_request_base, str) or not pull_request_base:
            block("missing_semantics", "pull_request_base must be a non-empty string")
        validate_branch_name(pull_request_base, "pull_request_base")

    protected_target = branch_name in protected
    if protected_target:
        block("protected_target", f"resolved work branch {branch_name!r} is protected")

    return {
        "base_branch": base,
        "branch_name": branch_name,
        "requires_new_branch": requires_new_branch,
        "requires_pull_request": requires_pull_request,
        "pull_request_base": pull_request_base,
    }


def resolve_release(policy: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    use_default = policy.get("use_repository_default_as_base", False)
    if not isinstance(use_default, bool):
        block("malformed_policy", "use_repository_default_as_base must be a boolean")
    if use_default:
        block(
            "default_branch_not_permitted",
            "repository default branch fallback is not defined for release strategy",
        )
    roles = policy.get("branch_roles")
    required_roles = policy.get("required_branch_roles")
    if not isinstance(roles, dict) or not isinstance(required_roles, list) or not required_roles:
        block("missing_semantics", "release strategy requires branch_roles and required_branch_roles")
    if any(not isinstance(role, str) or not role for role in required_roles):
        block("malformed_policy", "required_branch_roles must contain non-empty strings")
    missing = sorted(role for role in required_roles if not isinstance(roles.get(role), str) or not roles[role])
    if missing:
        block("missing_branch_roles", f"release strategy is missing branch roles: {', '.join(missing)}")
    for role, branch in roles.items():
        if not isinstance(role, str) or not isinstance(branch, str) or not branch:
            block("malformed_policy", "branch_roles must map role names to branch names")
        validate_branch_name(branch, f"branch_roles.{role}")

    base_role = require_string(policy, "base_role")
    target_role = require_string(policy, "pull_request_target_role")
    if base_role not in roles or target_role not in roles:
        block("missing_branch_roles", "base_role and pull_request_target_role must reference declared branch_roles")
    requires_new_branch = require_bool(policy, "requires_new_branch")
    requires_pull_request = require_bool(policy, "requires_pull_request")
    if requires_new_branch:
        branch_name = render_branch_name(policy.get("branch_pattern"), change, policy)
    else:
        work_role = require_string(policy, "work_role")
        if work_role not in roles:
            block("missing_branch_roles", "work_role must reference a declared branch role")
        branch_name = roles[work_role]

    return {
        "base_branch": roles[base_role],
        "branch_name": branch_name,
        "requires_new_branch": requires_new_branch,
        "requires_pull_request": requires_pull_request,
        "pull_request_base": roles[target_role] if requires_pull_request else None,
        "branch_roles": {role: roles[role] for role in sorted(roles)},
    }


def resolve_custom(policy: dict[str, Any]) -> dict[str, Any]:
    use_default = policy.get("use_repository_default_as_base", False)
    if not isinstance(use_default, bool):
        block("malformed_policy", "use_repository_default_as_base must be a boolean")
    if use_default:
        block(
            "default_branch_not_permitted",
            "repository default branch fallback is not defined for custom strategy",
        )
    contract = policy.get("custom_contract")
    if not isinstance(contract, dict):
        block("incomplete_custom_semantics", "custom strategy requires an explicit custom_contract")
    required = {
        "base_branch",
        "branch_name",
        "requires_new_branch",
        "requires_pull_request",
        "pull_request_base",
    }
    missing = sorted(required - set(contract))
    extra = sorted(set(contract) - required)
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if extra:
            detail.append(f"unsupported: {', '.join(extra)}")
        block("incomplete_custom_semantics", f"custom_contract is incomplete ({'; '.join(detail)})")
    base = require_string(contract, "base_branch")
    branch = require_string(contract, "branch_name")
    validate_branch_name(base, "custom_contract.base_branch")
    validate_branch_name(branch, "custom_contract.branch_name")
    requires_new = require_bool(contract, "requires_new_branch")
    requires_pr = require_bool(contract, "requires_pull_request")
    if not requires_new and branch != base:
        block(
            "conflicting_policy",
            "custom_contract.branch_name must equal base_branch when no new branch is required",
        )
    pr_base = contract["pull_request_base"]
    if requires_pr:
        if not isinstance(pr_base, str) or not pr_base:
            block("incomplete_custom_semantics", "custom_contract.pull_request_base is required for a pull request")
        validate_branch_name(pr_base, "custom_contract.pull_request_base")
    elif pr_base is not None:
        block("conflicting_policy", "custom_contract.pull_request_base must be null when no pull request is required")
    return {
        "base_branch": base,
        "branch_name": branch,
        "requires_new_branch": requires_new,
        "requires_pull_request": requires_pr,
        "pull_request_base": pr_base,
    }


def validate_resolved_contract(
    contract: dict[str, Any], policy: dict[str, Any], change: dict[str, Any]
) -> None:
    branch_name = contract["branch_name"]
    max_length = policy.get("max_branch_length")
    if max_length is not None:
        if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
            block("malformed_policy", "max_branch_length must be a positive integer")
        if len(branch_name) > max_length:
            block("maximum_length", "resolved branch name exceeds max_branch_length")

    regex = policy.get("branch_name_regex")
    if regex is not None:
        if not isinstance(regex, str) or not regex:
            block("malformed_policy", "branch_name_regex must be a non-empty string")
        try:
            matches = re.fullmatch(regex, branch_name) is not None
        except re.error as exc:
            block("malformed_policy", f"branch_name_regex is invalid: {exc}")
        if not matches:
            block("branch_pattern_mismatch", "resolved branch name does not match branch_name_regex")

    protected = policy.get("protected_branches", [])
    if not isinstance(protected, list) or any(not isinstance(item, str) for item in protected):
        block("malformed_policy", "protected_branches must be a list of branch names")
    if branch_name in protected:
        block("protected_target", f"resolved work branch {branch_name!r} is protected")

    allowed_types = policy.get("allowed_types")
    if allowed_types is not None:
        if (
            not isinstance(allowed_types, list)
            or not allowed_types
            or any(not isinstance(item, str) or not item for item in allowed_types)
        ):
            block("malformed_policy", "allowed_types must contain non-empty strings")
        change_type = policy.get("change_type", change.get("type"))
        if not isinstance(change_type, str) or not change_type:
            block("missing_change_input", "change type is required when allowed_types is configured", "WorkItem/change owner")
        if change_type not in allowed_types:
            block("disallowed_type", f"change type {change_type!r} is not allowed")


def resolve(payload: Any) -> dict[str, Any]:
    repository: str | None = None
    try:
        if not isinstance(payload, dict):
            block("malformed_input", "resolver input must be an object", "operation owner")
        repository = validate_repository(payload.get("repository"))
        policy = extract_branching_policy(payload.get("consumer_policy"))
        policy_repository = policy.get("repository")
        if policy_repository is not None and policy_repository != repository:
            block(
                "repository_conflict",
                f"policy repository {policy_repository!r} conflicts with change repository {repository!r}",
            )
        policy = apply_override(policy, payload.get("operation_override"))
        strategy = policy.get("strategy")
        if not isinstance(strategy, str) or not strategy:
            block("missing_strategy", "branch strategy is not configured")
        if strategy not in SUPPORTED_STRATEGIES:
            block("unsupported_strategy", f"unsupported branch strategy: {strategy!r}")
        change = payload.get("change")
        if not isinstance(change, dict):
            block("missing_change", "change must be an object", "WorkItem/change owner")
        work_item_id = require_string(change, "work_item_id", "WorkItem/change owner")

        if strategy in {"trunk", "feature"}:
            contract = resolve_standard_strategy(strategy, policy, payload, change)
        elif strategy == "release":
            contract = resolve_release(policy, change)
        else:
            contract = resolve_custom(policy)
        validate_resolved_contract(contract, policy, change)

        return {
            "status": "resolved",
            "strategy": strategy,
            "repository": repository,
            **contract,
            "work_item_id": work_item_id,
            "authority": AUTHORITY_NOTICE,
        }
    except PolicyBlock as exc:
        result = {
            "status": "blocked",
            "code": exc.code,
            "reason": exc.reason,
            "owner": exc.owner,
            "authority": AUTHORITY_NOTICE,
        }
        if repository is not None:
            result["repository"] = repository
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
