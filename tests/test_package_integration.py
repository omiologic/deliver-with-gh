import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_FIXTURE = ROOT / "tests/fixtures/deliver-product-integration.json"
VALIDATOR = ROOT / "scripts/validate.py"
INSTALLER = ROOT / "scripts/install.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


router = load_module("integration_router", ROOT / "skills/deliver-with-gh/scripts/route_delivery.py")
planning = load_module(
    "integration_planning",
    ROOT / "skills/gh-work-planning/scripts/resolve_work_projection.py",
)
change = load_module(
    "integration_change",
    ROOT / "skills/gh-change-delivery/scripts/resolve_change_delivery.py",
)
reconciliation = load_module(
    "integration_reconciliation",
    ROOT / "skills/gh-delivery-reconciliation/scripts/normalize_github_evidence.py",
)


class PackageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(INTEGRATION_FIXTURE.read_text(encoding="utf-8"))
        self.flows = {flow["name"]: flow for flow in self.fixture["flows"]}

    def child_input(self, flow):
        source = json.loads((ROOT / flow["child_fixture"]).read_text(encoding="utf-8"))
        selector = flow["fixture_selector"]
        if isinstance(selector, int):
            return copy.deepcopy(source[selector]["input"])
        if isinstance(selector, str):
            return copy.deepcopy(source[selector])
        return copy.deepcopy(source)

    def route(self, flow, child_input):
        payload = {
            "delivery_stage": flow["delivery_stage"],
            "github_action": flow["github_action"],
            "child_input": child_input,
        }
        if flow["owner_state"] is not None:
            payload["owner_state"] = flow["owner_state"]
        result = router.resolve(payload)
        self.assertEqual(result["status"], "routed")
        self.assertEqual(result["destination"], flow["expected_destination"])
        return result

    def test_planning_handoff_projects_three_repositories_without_policy_defaults(self):
        flow = self.flows["planning-to-github-work-projection"]
        child_input = self.child_input(flow)
        child_input.pop("consumer_policy", None)
        routed = self.route(flow, child_input)
        projected = planning.resolve(routed["handoff"]["child_input"])
        self.assertEqual(projected["status"], "resolved")
        repositories = [
            item.get("repository") for item in projected["projection"]["items"]
        ]
        self.assertEqual(
            repositories,
            ["example-org/api", "example-org/web", "partner-org/docs", None],
        )
        serialized = json.dumps(projected["projection"], sort_keys=True)
        self.assertNotIn("canonical_completion", serialized)
        self.assertNotIn("canonical_readiness", serialized)

    def test_execution_handoff_preserves_consumer_branch_policy(self):
        flow = self.flows["execution-to-github-change-workflow"]
        child_input = self.child_input(flow)
        exact_policy = copy.deepcopy(child_input["consumer_policy"])
        child_input["requested_effects"] = ["pr_create"]
        child_input["authority"] = {"pr_create": True}
        child_input["desired"] = {
            "pull_request": {
                "title": "WX-142: Add organization delete",
                "body": "WorkItem: plan://launch/work-items/WX-142",
            }
        }
        routed = self.route(flow, child_input)
        self.assertEqual(routed["handoff"]["child_input"]["consumer_policy"], exact_policy)
        resolved = change.resolve(routed["handoff"]["child_input"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["effects"], [{"effect": "pr_create", "action": "none"}])
        self.assertEqual(resolved["handoff"]["canonical_completion"], "not_determined")

    def test_change_integration_blocks_without_consumer_branch_policy(self):
        flow = self.flows["execution-to-github-change-workflow"]
        child_input = self.child_input(flow)
        child_input.pop("consumer_policy")
        routed = router.resolve(
            {
                "delivery_stage": flow["delivery_stage"],
                "github_action": flow["github_action"],
                "owner_state": flow["owner_state"],
                "child_input": child_input,
            }
        )
        self.assertEqual(routed["status"], "blocked")
        self.assertEqual(routed["code"], "missing_consumer_policy")

    def test_evidence_handoff_is_noncanonical_without_consumer_policy(self):
        flow = self.flows["github-evidence-to-delivery-reconciliation"]
        child_input = self.child_input(flow)
        child_input.pop("consumer_policy", None)
        routed = self.route(flow, child_input)
        normalized = reconciliation.resolve(routed["handoff"]["child_input"])
        self.assertEqual(normalized["status"], "normalized")
        self.assertEqual(normalized["handoff_for"], "delivery-reconciliation")
        self.assertEqual(
            normalized["canonical_transition"],
            {"performed": False, "implied": False},
        )
        self.assertNotIn("assessment", normalized)

    def test_integration_contract_has_one_way_dependency_without_runtime_import(self):
        self.assertEqual(
            self.fixture["platform_contract"],
            {
                "owner": "deliver-product",
                "modified_by_integration": False,
                "canonical_state_owner": "consumer runtime or responsible owner",
            },
        )
        for script in (ROOT / "skills").rglob("*.py"):
            source = script.read_text(encoding="utf-8")
            self.assertNotIn("import deliver_product", source)
            self.assertNotIn("from deliver_product", source)

    def test_package_and_each_skill_validate_independently(self):
        package = subprocess.run(
            [sys.executable, str(VALIDATOR), "--skip-tests"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(package.returncode, 0, package.stderr)
        for skill in (
            "deliver-with-gh",
            "gh-work-planning",
            "gh-change-delivery",
            "gh-delivery-reconciliation",
        ):
            with self.subTest(skill=skill):
                result = subprocess.run(
                    [sys.executable, str(VALIDATOR), "--skill", skill, "--skip-tests"],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_installer_supports_one_skill_and_complete_ecosystem(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            one_root = temporary_path / "one"
            one = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    "--destination",
                    str(one_root),
                    "--skill",
                    "gh-work-planning",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(one.returncode, 0, one.stderr)
            self.assertTrue((one_root / "gh-work-planning/SKILL.md").is_file())
            installed_one = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--skills-root",
                    str(one_root),
                    "--skill",
                    "gh-work-planning",
                    "--skip-tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(installed_one.returncode, 0, installed_one.stderr)

            all_root = temporary_path / "all"
            all_skills = subprocess.run(
                [sys.executable, str(INSTALLER), "--destination", str(all_root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(all_skills.returncode, 0, all_skills.stderr)
            installed_all = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--skills-root",
                    str(all_root),
                    "--skip-tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(installed_all.returncode, 0, installed_all.stderr)

    def test_installer_refuses_to_replace_existing_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            target = destination / "deliver-with-gh"
            target.mkdir()
            marker = target / "user-owned.txt"
            marker.write_text("preserve", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    "--destination",
                    str(destination),
                    "--skill",
                    "deliver-with-gh",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
