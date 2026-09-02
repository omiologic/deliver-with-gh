#!/usr/bin/env python3
"""Validate the deliver-with-gh package or independently installed skills."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "package-contract.json"
EXPECTED_CONTRACT = {
    "package": "deliver-with-gh",
    "install_manifest": ".deliver-with-gh-install.json",
    "dependency_direction": "deliver-with-gh -> deliver-product",
    "canonical_state_owner": "consumer runtime or responsible owner",
    "github_state_role": "projection_or_evidence",
    "project_repository_identity": "independent",
    "branch_policy_owner": "consumer",
    "optional_policy_sources": ["context-governance resolved_context"],
    "router": "deliver-with-gh",
    "router_children": [
        "gh-work-planning",
        "gh-change-delivery",
        "gh-delivery-reconciliation",
    ],
    "skills": [
        "deliver-with-gh",
        "gh-work-planning",
        "gh-change-delivery",
        "gh-delivery-reconciliation",
    ],
    "work_projection_mapping_surfaces": [
        "issue_type",
        "labels",
        "milestone",
        "project_fields",
    ],
    "work_projection_mapping_owner": "consumer",
}
WORK_PROJECTION_RESOLVER = ROOT / "skills/gh-work-planning/scripts/resolve_work_projection.py"
MAPPING_SURFACES_PATTERN = re.compile(r"^MAPPING_SURFACES = \{(.+)\}$", re.MULTILINE)
TEST_PATTERNS = {
    "deliver-with-gh": ("test_delivery_router.py",),
    "gh-work-planning": ("test_work_projection_resolver.py",),
    "gh-change-delivery": (
        "test_branch_policy_resolver.py",
        "test_change_delivery_resolver.py",
        "test_governed_branch_policy.py",
    ),
    "gh-delivery-reconciliation": ("test_github_evidence_normalizer.py",),
}
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REPOSITORY_PATTERN = re.compile(r"^[^/\s]+/[^/\s]+$")
SECRET_PATTERNS = {
    "GitHub classic token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "GitHub fine-grained token": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "private workspace path": re.compile(r"/(?:Users|home)/[^/\s]+/(?:Work|workspace)/"),
}


@dataclass(frozen=True)
class Diagnostic:
    path: str
    message: str


def load_json(path: Path, diagnostics: list[Diagnostic]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diagnostics.append(Diagnostic(str(path), f"invalid JSON: {exc}"))
        return None


def parse_frontmatter(path: Path, diagnostics: list[Diagnostic]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        diagnostics.append(Diagnostic(str(path), f"cannot read SKILL.md: {exc}"))
        return {}
    if not lines or lines[0] != "---":
        diagnostics.append(Diagnostic(str(path), "missing YAML frontmatter opener"))
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        diagnostics.append(Diagnostic(str(path), "missing YAML frontmatter closer"))
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            diagnostics.append(Diagnostic(str(path), f"malformed frontmatter line: {line}"))
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    return metadata


def validate_links(markdown: Path, package_root: Path, diagnostics: list[Diagnostic]) -> None:
    text = markdown.read_text(encoding="utf-8")
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            continue
        resolved = (markdown.parent / target).resolve()
        try:
            resolved.relative_to(package_root.resolve())
        except ValueError:
            diagnostics.append(Diagnostic(str(markdown), f"link escapes package: {raw_target}"))
            continue
        if not resolved.exists():
            diagnostics.append(Diagnostic(str(markdown), f"broken package-local link: {raw_target}"))


def walk_repository_values(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "repository" and isinstance(child, str):
                yield child
            yield from walk_repository_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_repository_values(child)


def validate_fixture_safety(
    path: Path,
    data: Any,
    allowed_namespaces: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    text = path.read_text(encoding="utf-8")
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            diagnostics.append(Diagnostic(str(path), f"public fixture contains possible {label}"))
    for repository in walk_repository_values(data):
        if not REPOSITORY_PATTERN.fullmatch(repository):
            diagnostics.append(Diagnostic(str(path), f"fixture repository is not exact owner/repo: {repository}"))
            continue
        namespace = repository.split("/", 1)[0]
        if namespace not in allowed_namespaces:
            diagnostics.append(Diagnostic(str(path), f"fixture repository uses non-public namespace: {repository}"))


def validate_python(path: Path, diagnostics: list[Diagnostic]) -> None:
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
    except (OSError, SyntaxError) as exc:
        diagnostics.append(Diagnostic(str(path), f"invalid Python: {exc}"))


def validate_skill(skill_dir: Path, expected_name: str, diagnostics: list[Diagnostic]) -> None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        diagnostics.append(Diagnostic(str(skill_dir), "missing SKILL.md"))
        return
    metadata = parse_frontmatter(skill_file, diagnostics)
    allowed_metadata = {"name", "description", "license", "allowed-tools", "metadata"}
    unexpected = sorted(set(metadata) - allowed_metadata)
    if unexpected:
        diagnostics.append(
            Diagnostic(str(skill_file), f"unsupported frontmatter keys: {', '.join(unexpected)}")
        )
    if metadata.get("name") != expected_name:
        diagnostics.append(
            Diagnostic(str(skill_file), f"frontmatter name must be {expected_name!r}")
        )
    description = metadata.get("description", "")
    if not description:
        diagnostics.append(Diagnostic(str(skill_file), "frontmatter description is required"))
    elif len(description) > 1024 or "<" in description or ">" in description:
        diagnostics.append(Diagnostic(str(skill_file), "frontmatter description is invalid"))
    if (
        len(expected_name) > 64
        or not re.fullmatch(r"[a-z0-9-]+", expected_name)
        or expected_name.startswith("-")
        or expected_name.endswith("-")
        or "--" in expected_name
    ):
        diagnostics.append(Diagnostic(str(skill_dir), "skill directory name is invalid"))
    skill_text = skill_file.read_text(encoding="utf-8")
    if re.search(r"(?:^|\n)[ ]{0,3}\[TODO:[^\n]*\](?:\n|$)", skill_text):
        diagnostics.append(Diagnostic(str(skill_file), "unfinished TODO placeholder"))
    for markdown in sorted(skill_dir.rglob("*.md")):
        validate_links(markdown, skill_dir, diagnostics)
    for script in sorted(skill_dir.rglob("*.py")):
        validate_python(script, diagnostics)
    for fixture in sorted(skill_dir.rglob("*.json")):
        load_json(fixture, diagnostics)


def validate_mapping_surfaces(surfaces: Any, diagnostics: list[Diagnostic]) -> None:
    """Keep the contract's surface list and the resolver's surface set identical.

    The surfaces are consumer-owned mapping names only. Enumerating them does
    not give the package a default label, milestone, Issue type, or field value.
    """
    if not isinstance(surfaces, list):
        return
    try:
        source = WORK_PROJECTION_RESOLVER.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.append(Diagnostic(str(WORK_PROJECTION_RESOLVER), f"cannot read resolver: {exc}"))
        return
    match = MAPPING_SURFACES_PATTERN.search(source)
    if match is None:
        diagnostics.append(Diagnostic(str(WORK_PROJECTION_RESOLVER), "missing MAPPING_SURFACES declaration"))
        return
    declared = sorted(entry.strip().strip("\"'") for entry in match.group(1).split(","))
    if declared != sorted(surfaces):
        diagnostics.append(
            Diagnostic(
                str(WORK_PROJECTION_RESOLVER),
                f"MAPPING_SURFACES {declared} does not match contract {sorted(surfaces)}",
            )
        )


def validate_contract(diagnostics: list[Diagnostic]) -> dict[str, Any]:
    contract = load_json(CONTRACT_PATH, diagnostics)
    if not isinstance(contract, dict):
        return {}
    if contract.get("schema_version") != 1:
        diagnostics.append(Diagnostic(str(CONTRACT_PATH), "schema_version must be 1"))
    for key, expected in EXPECTED_CONTRACT.items():
        if contract.get(key) != expected:
            diagnostics.append(Diagnostic(str(CONTRACT_PATH), f"architecture invariant mismatch for {key}"))
    validate_mapping_surfaces(contract.get("work_projection_mapping_surfaces"), diagnostics)
    namespaces = contract.get("public_fixture_namespaces")
    if not isinstance(namespaces, list) or not namespaces or any(not isinstance(value, str) for value in namespaces):
        diagnostics.append(Diagnostic(str(CONTRACT_PATH), "public_fixture_namespaces must be non-empty strings"))
    return contract


def run_tests(skill: str | None) -> int:
    patterns = TEST_PATTERNS[skill] if skill is not None else ("test*.py",)
    for pattern in patterns:
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            pattern,
        ]
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", choices=EXPECTED_CONTRACT["skills"], help="validate one skill independently")
    parser.add_argument("--skills-root", type=Path, help="validate skills installed beneath this directory")
    parser.add_argument("--skip-tests", action="store_true", help="skip scenario tests")
    args = parser.parse_args()

    diagnostics: list[Diagnostic] = []
    contract = validate_contract(diagnostics) if args.skills_root is None else load_json(CONTRACT_PATH, diagnostics) or {}
    skills = [args.skill] if args.skill else EXPECTED_CONTRACT["skills"]
    skills_root = args.skills_root.resolve() if args.skills_root else ROOT / "skills"
    for skill in skills:
        validate_skill(skills_root / skill, skill, diagnostics)

    if args.skills_root is None:
        allowed = set(contract.get("public_fixture_namespaces", []))
        fixture_root = ROOT / "skills" / args.skill if args.skill else ROOT
        for fixture in sorted(fixture_root.rglob("*.json")):
            if ".git" in fixture.parts:
                continue
            data = load_json(fixture, diagnostics)
            if data is not None and ("fixtures" in fixture.parts or fixture.parent.name == "fixtures"):
                validate_fixture_safety(fixture, data, allowed, diagnostics)
        for markdown in (ROOT / "README.md", ROOT / "ARCHITECTURE.md", ROOT / "AGENTS.md"):
            validate_links(markdown, ROOT, diagnostics)
        for script in sorted((ROOT / "scripts").glob("*.py")):
            validate_python(script, diagnostics)

    if diagnostics:
        for diagnostic in diagnostics:
            print(f"ERROR {diagnostic.path}: {diagnostic.message}", file=sys.stderr)
        print(f"validation failed with {len(diagnostics)} error(s)", file=sys.stderr)
        return 2
    if not args.skip_tests and args.skills_root is None and run_tests(args.skill) != 0:
        print("scenario tests failed", file=sys.stderr)
        return 2
    scope = args.skill or "all four skills"
    location = f" under {skills_root}" if args.skills_root else ""
    print(f"validated {scope}{location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
