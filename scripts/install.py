#!/usr/bin/env python3
"""Install one or all deliver-with-gh skills into an explicit skills root."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
SKILLS = (
    "deliver-with-gh",
    "gh-work-planning",
    "gh-change-delivery",
    "gh-delivery-reconciliation",
)


def validate_sources(skills: list[str]) -> None:
    for skill in skills:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate.py"), "--skill", skill, "--skip-tests"],
            cwd=ROOT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"source validation failed for {skill}")


def install(destination: Path, skills: list[str], mode: str, dry_run: bool) -> list[Path]:
    destination = destination.expanduser().resolve()
    targets = [destination / skill for skill in skills]
    existing = [target for target in targets if target.exists() or target.is_symlink()]
    if existing:
        joined = ", ".join(str(target) for target in existing)
        raise FileExistsError(f"refusing to replace existing skill paths: {joined}")
    if dry_run:
        return targets
    destination.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for skill, target in zip(skills, targets):
            source = SKILLS_ROOT / skill
            if mode == "copy":
                shutil.copytree(source, target)
            else:
                target.symlink_to(source.resolve(), target_is_directory=True)
            created.append(target)
    except Exception:
        for target in reversed(created):
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
        raise
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path, help="explicit consumer skills root")
    parser.add_argument("--skill", action="append", choices=SKILLS, help="install one skill; repeat as needed")
    parser.add_argument("--mode", choices=("copy", "symlink"), default="copy")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    skills = list(dict.fromkeys(args.skill or SKILLS))
    try:
        validate_sources(skills)
        targets = install(args.destination, skills, args.mode, args.dry_run)
    except (OSError, RuntimeError) as exc:
        print(f"installation failed: {exc}", file=sys.stderr)
        return 2
    verb = "would install" if args.dry_run else "installed"
    for target in targets:
        print(f"{verb} {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
