from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deliver_with_gh_install", ROOT / "scripts" / "install.py")
assert SPEC and SPEC.loader
INSTALL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INSTALL
SPEC.loader.exec_module(INSTALL)


class InstallerTests(unittest.TestCase):
    def write_source(self, root: Path, marker: str = "first") -> None:
        for name in INSTALL.PACKAGES:
            package = root / "skills" / name
            package.mkdir(parents=True)
            (package / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: public-safe test package\n---\n{marker}\n",
                encoding="utf-8",
            )
            (package / "references").mkdir()
            (package / "references" / "contract.md").write_text(marker, encoding="utf-8")

    def snapshot(self, root: Path, marker: str = "first", commit: str = "a" * 40):
        source = root / f"source-{marker}-{commit[0]}"
        self.write_source(source, marker)
        package_root = root / f"snapshot-{marker}-{commit[0]}"
        package_root.mkdir()
        digests = {}
        for name in INSTALL.PACKAGES:
            INSTALL._copy_package(source / "skills" / name, package_root / name, name)
            digests[name] = INSTALL._package_digest(package_root / name)
        return INSTALL.Snapshot(package_root, "https://example.invalid/deliver-with-gh.git", commit, digests)

    def skill_root(self, target: Path) -> Path:
        return target / INSTALL.AGENT_SKILL_ROOTS["codex"]

    def test_fresh_install_copies_all_packages_and_records_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            snapshot = self.snapshot(root)
            states, manifest = INSTALL.inspect_installation(
                self.skill_root(target), snapshot, INSTALL.PACKAGES
            )
            INSTALL.apply_installation(self.skill_root(target), snapshot, states, manifest)

            recorded = json.loads(
                (self.skill_root(target) / INSTALL.MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                {"commit": snapshot.commit, "source": snapshot.source, "packages": snapshot.digests},
                recorded,
            )
            for name in INSTALL.PACKAGES:
                self.assertEqual(
                    INSTALL._relative_files(snapshot.root / name),
                    INSTALL._relative_files(self.skill_root(target) / name),
                )

    def test_selected_subset_installs_in_one_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            snapshot = self.snapshot(root)
            selected = ("deliver-with-gh", "gh-work-planning")
            states, manifest = INSTALL.inspect_installation(self.skill_root(target), snapshot, selected)
            INSTALL.apply_installation(self.skill_root(target), snapshot, states, manifest)
            self.assertTrue((self.skill_root(target) / "deliver-with-gh").is_dir())
            self.assertTrue((self.skill_root(target) / "gh-work-planning").is_dir())
            self.assertFalse((self.skill_root(target) / "gh-change-delivery").exists())

    def test_noop_reinstall_reports_current_and_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            snapshot = self.snapshot(root)
            states, manifest = INSTALL.inspect_installation(self.skill_root(target), snapshot, INSTALL.PACKAGES)
            INSTALL.apply_installation(self.skill_root(target), snapshot, states, manifest)
            manifest_path = self.skill_root(target) / INSTALL.MANIFEST_NAME
            before = manifest_path.stat().st_mtime_ns
            states, _ = INSTALL.inspect_installation(self.skill_root(target), snapshot, INSTALL.PACKAGES)
            self.assertTrue(all(state.action == "current" for state in states))
            self.assertEqual(before, manifest_path.stat().st_mtime_ns)

    def test_upstream_ahead_is_reported_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            first = self.snapshot(root, "first", "a" * 40)
            second = self.snapshot(root, "second", "b" * 40)
            states, manifest = INSTALL.inspect_installation(self.skill_root(target), first, INSTALL.PACKAGES)
            INSTALL.apply_installation(self.skill_root(target), first, states, manifest)
            original = (self.skill_root(target) / "deliver-with-gh" / "SKILL.md").read_bytes()
            states, _ = INSTALL.inspect_installation(
                self.skill_root(target), second, INSTALL.PACKAGES, baseline=first
            )
            self.assertTrue(all(state.action == "behind" for state in states))
            self.assertEqual(original, (self.skill_root(target) / "deliver-with-gh" / "SKILL.md").read_bytes())
            with self.assertRaisesRegex(INSTALL.InstallError, "--migrate"):
                INSTALL.apply_installation(self.skill_root(target), second, states, None)
            manifest = INSTALL._load_manifest(self.skill_root(target) / INSTALL.MANIFEST_NAME)
            INSTALL.apply_installation(
                self.skill_root(target), second, states, manifest, migrate=True
            )
            self.assertEqual(
                (second.root / "deliver-with-gh" / "SKILL.md").read_bytes(),
                (self.skill_root(target) / "deliver-with-gh" / "SKILL.md").read_bytes(),
            )

    def test_matching_migration_records_manifest_without_recopy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            snapshot = self.snapshot(root)
            skill_root = self.skill_root(target)
            skill_root.mkdir(parents=True)
            INSTALL._copy_package(snapshot.root / "gh-work-planning", skill_root / "gh-work-planning", "gh-work-planning")
            package_file = skill_root / "gh-work-planning" / "SKILL.md"
            before = package_file.stat().st_mtime_ns
            states, manifest = INSTALL.inspect_installation(skill_root, snapshot, ("gh-work-planning",))
            self.assertEqual("migrate-match", states[0].action)
            INSTALL.apply_installation(skill_root, snapshot, states, manifest, migrate=True)
            self.assertEqual(before, package_file.stat().st_mtime_ns)
            self.assertTrue((skill_root / INSTALL.MANIFEST_NAME).is_file())

    def test_differing_migration_lists_paths_and_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            snapshot = self.snapshot(root)
            skill_root = self.skill_root(target)
            skill_root.mkdir(parents=True)
            INSTALL._copy_package(snapshot.root / "gh-work-planning", skill_root / "gh-work-planning", "gh-work-planning")
            changed = skill_root / "gh-work-planning" / "references" / "contract.md"
            changed.write_text("manual copy differs", encoding="utf-8")
            states, manifest = INSTALL.inspect_installation(skill_root, snapshot, ("gh-work-planning",))
            self.assertEqual("migrate-differ", states[0].action)
            self.assertEqual(("references/contract.md",), states[0].differing_paths)
            with self.assertRaisesRegex(INSTALL.InstallError, "--migrate"):
                INSTALL.apply_installation(skill_root, snapshot, states, manifest)

            output = io.StringIO()
            with patch.object(INSTALL, "fetch_snapshot", return_value=snapshot), redirect_stdout(output):
                result = INSTALL.main(
                    ["--target", str(target), "--agent", "codex", "--package", "gh-work-planning", "--migrate"],
                    input_fn=lambda _: "no",
                )
            self.assertEqual(0, result)
            self.assertIn("references/contract.md", output.getvalue())
            self.assertEqual("manual copy differs", changed.read_text(encoding="utf-8"))

            with patch.object(INSTALL, "fetch_snapshot", return_value=snapshot):
                result = INSTALL.main(
                    ["--target", str(target), "--agent", "codex", "--package", "gh-work-planning", "--migrate", "--yes"]
                )
            self.assertEqual(0, result)
            self.assertEqual(
                (snapshot.root / "gh-work-planning" / "references" / "contract.md").read_text(encoding="utf-8"),
                changed.read_text(encoding="utf-8"),
            )

    def test_local_modification_is_rejected_with_path_and_no_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            snapshot = self.snapshot(root)
            skill_root = self.skill_root(target)
            states, manifest = INSTALL.inspect_installation(skill_root, snapshot, ("gh-change-delivery",))
            INSTALL.apply_installation(skill_root, snapshot, states, manifest)
            changed = skill_root / "gh-change-delivery" / "SKILL.md"
            changed.write_text("local modification", encoding="utf-8")
            states, manifest = INSTALL.inspect_installation(
                skill_root, snapshot, ("gh-change-delivery",), baseline=snapshot
            )
            self.assertEqual("local-modifications", states[0].action)
            self.assertEqual(("SKILL.md",), states[0].differing_paths)
            with self.assertRaisesRegex(INSTALL.InstallError, "--migrate"):
                INSTALL.apply_installation(skill_root, snapshot, states, manifest)
            self.assertEqual("local modification", changed.read_text(encoding="utf-8"))

    def test_commit_change_requires_all_previously_installed_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            first = self.snapshot(root, "first", "a" * 40)
            second = self.snapshot(root, "second", "b" * 40)
            skill_root = self.skill_root(target)
            states, manifest = INSTALL.inspect_installation(skill_root, first, INSTALL.PACKAGES)
            INSTALL.apply_installation(skill_root, first, states, manifest)
            states, manifest = INSTALL.inspect_installation(
                skill_root, second, ("deliver-with-gh",), baseline=first
            )
            with self.assertRaisesRegex(INSTALL.InstallError, "all previously installed packages"):
                INSTALL.apply_installation(skill_root, second, states, manifest, migrate=True)

    def test_fetch_uses_fresh_remote_ref_and_removes_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            self.write_source(source)
            subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(source), "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid", "commit", "-m", "init"],
                check=True,
                capture_output=True,
            )
            snapshot = INSTALL.fetch_snapshot(str(source), "main", root / "workspace")
            self.assertRegex(snapshot.commit, r"^[0-9a-f]{40}$")
            self.assertFalse(any(path.name == ".git" for path in snapshot.root.rglob("*")))

    def test_fetch_accepts_relative_local_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            source = Path(temp)
            self.write_source(source)
            subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(source), "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid", "commit", "-m", "init"],
                check=True,
                capture_output=True,
            )
            relative = source.relative_to(ROOT).as_posix()
            snapshot = INSTALL.fetch_snapshot(relative, "main", source / "workspace")
            self.assertEqual(relative, snapshot.source)


if __name__ == "__main__":
    unittest.main()
