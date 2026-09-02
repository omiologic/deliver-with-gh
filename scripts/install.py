#!/usr/bin/env python3
"""Install pinned Deliver With GitHub skill packages with drift detection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_SOURCE = "https://github.com/omiologic/deliver-with-gh.git"
DEFAULT_REF = "main"
MANIFEST_NAME = ".deliver-with-gh-install.json"
PACKAGES = (
    "deliver-with-gh",
    "gh-work-planning",
    "gh-change-delivery",
    "gh-delivery-reconciliation",
)
AGENT_SKILL_ROOTS = {
    "codex": Path(".agents/skills"),
    "claude": Path(".claude/skills"),
}


class InstallError(RuntimeError):
    """A safe, actionable installer failure."""


@dataclass(frozen=True)
class Snapshot:
    root: Path
    source: str
    commit: str
    digests: dict[str, str]


@dataclass(frozen=True)
class PackageState:
    name: str
    action: str
    differing_paths: tuple[str, ...] = ()


def _package_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _is_package(path: Path, name: str) -> bool:
    skill = path / "SKILL.md"
    if not skill.is_file():
        return False
    try:
        text = skill.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(rf"(?m)^name:\s*{re.escape(name)}\s*$", text))


def _copy_package(source: Path, destination: Path, name: str) -> None:
    if not _is_package(source, name):
        raise InstallError(f"source is not the {name} Skill package: {source}")
    entries = [source, *source.rglob("*")]
    symlink = next((path for path in entries if path.is_symlink()), None)
    if symlink is not None:
        raise InstallError(
            f"source package contains an unsupported symlink: {symlink.relative_to(source)}"
        )
    shutil.copytree(source, destination)


def fetch_snapshot(
    source: str,
    ref: str,
    workspace: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Snapshot:
    """Fetch ref directly from the configured remote and materialize package-only content."""
    workspace.mkdir(parents=True)
    checkout = workspace / "checkout"
    checkout.mkdir()
    local_source = Path(source)
    fetch_source = str(local_source.resolve()) if local_source.exists() else source
    commands = (
        ["git", "-C", str(checkout), "init", "--quiet"],
        ["git", "-C", str(checkout), "remote", "add", "origin", fetch_source],
        ["git", "-C", str(checkout), "fetch", "--quiet", "--depth", "1", "origin", ref],
        ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
    )
    for command in commands:
        result = runner(command, text=True, capture_output=True)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "git fetch failed"
            raise InstallError(f"cannot fetch Deliver With GitHub: {detail}")
    revision = runner(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    commit = revision.stdout.strip().lower()
    if revision.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise InstallError("cannot resolve fetched source commit")

    package_root = workspace / "packages"
    package_root.mkdir()
    digests: dict[str, str] = {}
    for name in PACKAGES:
        source_package = checkout / "skills" / name
        destination = package_root / name
        _copy_package(source_package, destination, name)
        digests[name] = _package_digest(destination)
    return Snapshot(package_root, source, commit, digests)


def _manifest(snapshot: Snapshot, packages: Iterable[str]) -> dict[str, object]:
    return {
        "commit": snapshot.commit,
        "source": snapshot.source,
        "packages": {name: snapshot.digests[name] for name in packages},
    }


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"invalid installation manifest: {path}") from exc
    if not isinstance(data, dict) or set(data) != {"commit", "source", "packages"}:
        raise InstallError(f"invalid installation manifest: {path}")
    if not isinstance(data["source"], str) or not data["source"]:
        raise InstallError("installation manifest source must be a non-empty string")
    if not isinstance(data["commit"], str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", data["commit"]
    ):
        raise InstallError("installation manifest commit must be a full Git SHA")
    packages = data["packages"]
    if not isinstance(packages, dict) or any(
        name not in PACKAGES
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
        for name, digest in packages.items()
    ):
        raise InstallError("installation manifest packages are invalid")
    return data


def _relative_files(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def differing_paths(installed: Path, expected: Path) -> tuple[str, ...]:
    installed_files = _relative_files(installed)
    expected_files = _relative_files(expected)
    return tuple(
        sorted(
            path
            for path in installed_files.keys() | expected_files.keys()
            if installed_files.get(path) != expected_files.get(path)
        )
    )


def inspect_installation(
    skill_root: Path,
    snapshot: Snapshot,
    packages: Iterable[str],
    *,
    baseline: Snapshot | None = None,
) -> tuple[list[PackageState], dict[str, object] | None]:
    manifest_path = skill_root / MANIFEST_NAME
    manifest = _load_manifest(manifest_path) if manifest_path.is_file() else None
    recorded = manifest["packages"] if manifest else {}
    assert isinstance(recorded, dict)
    source_matches = manifest is None or manifest["source"] == snapshot.source
    states: list[PackageState] = []

    for name in packages:
        destination = skill_root / name
        source_package = snapshot.root / name
        if not destination.exists():
            states.append(PackageState(name, "install"))
            continue
        recorded_digest = recorded.get(name)
        if not destination.is_dir() or (
            recorded_digest is None and not _is_package(destination, name)
        ):
            raise InstallError(f"installation destination is already occupied: {destination}")
        actual = _package_digest(destination)
        if recorded_digest is None:
            paths = differing_paths(destination, source_package)
            states.append(PackageState(name, "migrate-match" if not paths else "migrate-differ", paths))
            continue
        if actual != recorded_digest:
            expected = baseline.root / name if baseline and name in baseline.digests else source_package
            states.append(PackageState(name, "local-modifications", differing_paths(destination, expected)))
            continue
        if not source_matches:
            paths = differing_paths(destination, source_package)
            states.append(
                PackageState(
                    name,
                    "migrate-source-match" if not paths else "migrate-source-differ",
                    paths,
                )
            )
            continue
        if actual == snapshot.digests[name]:
            states.append(PackageState(name, "current"))
        else:
            states.append(PackageState(name, "behind", differing_paths(destination, source_package)))
    return states, manifest


def _replace_packages(
    skill_root: Path,
    snapshot: Snapshot,
    names: Iterable[str],
) -> None:
    backups: list[tuple[Path, Path]] = []
    staged: list[tuple[Path, Path]] = []
    skill_root.mkdir(parents=True, exist_ok=True)
    try:
        for name in names:
            destination = skill_root / name
            staging = Path(tempfile.mkdtemp(prefix=f".{name}-stage-", dir=skill_root))
            shutil.rmtree(staging)
            _copy_package(snapshot.root / name, staging, name)
            staged.append((staging, destination))
        for staging, destination in staged:
            if destination.exists():
                backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}-backup-", dir=skill_root))
                shutil.rmtree(backup)
                destination.rename(backup)
                backups.append((backup, destination))
            staging.rename(destination)
        for backup, _ in backups:
            shutil.rmtree(backup)
    except Exception:
        for staging, _ in staged:
            if staging.exists():
                shutil.rmtree(staging)
        for backup, destination in reversed(backups):
            if destination.exists():
                shutil.rmtree(destination)
            if backup.exists():
                backup.rename(destination)
        raise


def apply_installation(
    skill_root: Path,
    snapshot: Snapshot,
    states: Iterable[PackageState],
    existing_manifest: dict[str, object] | None,
    *,
    migrate: bool = False,
) -> None:
    states = list(states)
    protected = [
        state
        for state in states
        if state.action
        in {"local-modifications", "migrate-differ", "migrate-source-differ"}
    ]
    unmanaged = [state for state in states if state.action.startswith("migrate-")]
    if (protected or unmanaged) and not migrate:
        details = ", ".join(state.name for state in protected or unmanaged)
        raise InstallError(f"existing packages require --migrate: {details}")
    if any(state.action == "behind" for state in states) and not migrate:
        raise InstallError("behind packages require --migrate before they can be updated")
    state_names = {state.name for state in states}
    changing_commit = bool(existing_manifest) and existing_manifest["commit"] != snapshot.commit
    unselected_tracked = (
        set(existing_manifest["packages"]) - state_names if existing_manifest else set()
    )
    if changing_commit and unselected_tracked:
        names = ", ".join(sorted(unselected_tracked))
        raise InstallError(
            "a commit-changing installation must include all previously installed packages; "
            f"also select: {names}"
        )
    replacements = [
        state.name
        for state in states
        if state.action
        in {
            "install",
            "local-modifications",
            "migrate-differ",
            "migrate-source-differ",
        }
        or (migrate and state.action == "behind")
    ]
    _replace_packages(skill_root, snapshot, replacements)

    previous_packages: dict[str, str] = {}
    if existing_manifest:
        previous_packages.update(existing_manifest["packages"])  # type: ignore[arg-type]
    for state in states:
        if state.action != "behind" or migrate:
            previous_packages[state.name] = snapshot.digests[state.name]
    manifest_snapshot = Snapshot(snapshot.root, snapshot.source, snapshot.commit, previous_packages)
    (skill_root / MANIFEST_NAME).write_text(
        json.dumps(_manifest(manifest_snapshot, sorted(previous_packages)), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prompt_choice(prompt: str, input_fn: Callable[[str], str]) -> str:
    while True:
        value = input_fn(prompt).strip().lower()
        if value in {"yes", "no"}:
            return value
        print("Choose one of: no, yes")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--agent", choices=sorted(AGENT_SKILL_ROOTS))
    parser.add_argument("--package", action="append", choices=PACKAGES, dest="packages")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--yes", action="store_true", help="accept required installation confirmation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, input_fn: Callable[[str], str] = input) -> int:
    args = _arguments(argv)
    target = args.target.resolve()
    if not target.is_dir():
        raise InstallError(f"target directory does not exist: {target}")
    if args.agent is None:
        if args.yes:
            raise InstallError("--agent is required with --yes")
        while args.agent not in AGENT_SKILL_ROOTS:
            args.agent = input_fn("Agent [codex/claude]: ").strip().lower()
    selected = tuple(dict.fromkeys(args.packages or PACKAGES))
    skill_root = target / AGENT_SKILL_ROOTS[args.agent]

    with tempfile.TemporaryDirectory(prefix="deliver-with-gh-install-") as temp:
        workspace = Path(temp)
        snapshot = fetch_snapshot(args.source, args.ref, workspace / "latest")
        manifest_path = skill_root / MANIFEST_NAME
        manifest = _load_manifest(manifest_path) if manifest_path.is_file() else None
        baseline = None
        if manifest and manifest["source"] == snapshot.source and manifest["commit"] != snapshot.commit:
            baseline = fetch_snapshot(
                str(manifest["source"]), str(manifest["commit"]), workspace / "installed"
            )
        states, manifest = inspect_installation(skill_root, snapshot, selected, baseline=baseline)

        print(f"Agent: {args.agent}")
        print(f"Skill root: {skill_root}")
        print(f"Source: {snapshot.source}")
        print(f"Fetched commit: {snapshot.commit}")
        for state in states:
            print(f"{state.name}: {state.action}")
            for path in state.differing_paths:
                print(f"  {path}")

        local = [state for state in states if state.action == "local-modifications"]
        unmanaged = [state for state in states if state.action.startswith("migrate-")]
        if (local or unmanaged) and not args.migrate:
            raise InstallError("local or unmanaged package content requires --migrate")

        changes = [
            state
            for state in states
            if state.action != "current" and (state.action != "behind" or args.migrate)
        ]
        if not changes:
            return 0
        destructive = any(
            state.action
            in {
                "local-modifications",
                "migrate-differ",
                "migrate-source-differ",
                "behind",
            }
            for state in changes
        )
        if destructive and not args.yes:
            if _prompt_choice("Overwrite the reported differing paths? [yes/no]: ", input_fn) != "yes":
                print("No changes made.")
                return 0
        elif not args.yes:
            if _prompt_choice("Apply the displayed installation? [yes/no]: ", input_fn) != "yes":
                print("No changes made.")
                return 0
        apply_installation(skill_root, snapshot, states, manifest, migrate=args.migrate)
        print("Installation manifest updated.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
