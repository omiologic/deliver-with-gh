import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "skills/gh-change-delivery/scripts/resolve_governed_branch_policy.py"
BRANCH_PATH = ROOT / "skills/gh-change-delivery/scripts/resolve_branch_policy.py"
CHANGE_PATH = ROOT / "skills/gh-change-delivery/scripts/resolve_change_delivery.py"
FIXTURE_PATH = ROOT / "skills/gh-change-delivery/fixtures/context-governance-branch-policy-scenarios.json"
CHANGE_FIXTURE_PATH = ROOT / "skills/gh-change-delivery/fixtures/change-delivery-scenarios.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


adapter = load_module("governed_policy_adapter", ADAPTER_PATH)
branch = load_module("governed_policy_branch_resolver", BRANCH_PATH)
change = load_module("governed_policy_change_resolver", CHANGE_PATH)


class GovernedBranchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.by_name = {scenario["name"]: scenario for scenario in self.scenarios}

    def test_fixture_scenarios(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = adapter.resolve(scenario["input"])
                for key, value in scenario["expect"].items():
                    self.assertEqual(result.get(key), value)

    def test_valid_records_produce_complete_existing_target_contract(self):
        scenario = self.by_name["context-governance-valid-applicable-records"]
        adapted = adapter.resolve(scenario["input"])
        self.assertEqual(
            adapted["consumer_policy"],
            {
                "github_delivery": {
                    "branching": {
                        "strategy": "feature",
                        "base_branch": "main",
                        "branch_pattern": "{type}/{work_item_id}-{slug}",
                        "allowed_types": ["feature", "fix"],
                        "protected_branches": ["main"],
                        "requires_pull_request": True,
                    }
                }
            },
        )
        resolved = branch.resolve(
            {
                "repository": "example/widgets",
                "change": {
                    "work_item_id": "WX-142",
                    "type": "feature",
                    "title": "Add organization delete",
                },
                "consumer_policy": adapted["consumer_policy"],
            }
        )
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["branch_name"], "feature/WX-142-add-organization-delete")
        self.assertEqual(resolved["pull_request_base"], "main")

    def test_absent_context_governance_preserves_policy_and_branch_output(self):
        scenario = self.by_name["context-governance-absent"]
        direct_policy = scenario["input"]["direct_consumer_policy"]
        adapted = adapter.resolve(scenario["input"])
        self.assertEqual(adapted["consumer_policy"], direct_policy)
        branch_input = {
            "repository": "example/widgets",
            "change": {"work_item_id": "WX-9", "type": "feature", "title": "Search"},
            "consumer_policy": direct_policy,
        }
        direct_result = branch.resolve(branch_input)
        adapted_input = copy.deepcopy(branch_input)
        adapted_input["consumer_policy"] = adapted["consumer_policy"]
        self.assertEqual(branch.resolve(adapted_input), direct_result)

    def test_no_applicable_records_preserve_policy_and_branch_output(self):
        scenario = self.by_name["context-governance-installed-no-applicable-records"]
        direct_policy = scenario["input"]["direct_consumer_policy"]
        adapted = adapter.resolve(scenario["input"])
        self.assertEqual(adapted["consumer_policy"], direct_policy)
        branch_input = {
            "repository": "example/widgets",
            "change": {"work_item_id": "WX-10", "type": "feature", "title": "Filter"},
            "consumer_policy": direct_policy,
        }
        expected = branch.resolve(branch_input)
        branch_input["consumer_policy"] = adapted["consumer_policy"]
        self.assertEqual(branch.resolve(branch_input), expected)

        change_fixture = json.loads(CHANGE_FIXTURE_PATH.read_text(encoding="utf-8"))["base_input"]
        baseline = change.resolve(change_fixture)
        with_empty_context = copy.deepcopy(change_fixture)
        with_empty_context["context_governance"] = copy.deepcopy(scenario["input"]["context_governance"])
        self.assertEqual(change.resolve(with_empty_context), baseline)

    def test_explicit_not_installed_preserves_direct_policy(self):
        scenario = copy.deepcopy(self.by_name["context-governance-absent"]["input"])
        scenario["context_governance"] = {"installed": False}
        result = adapter.resolve(scenario)
        self.assertEqual(result["source"], "direct")
        self.assertEqual(result["consumer_policy"], scenario["direct_consumer_policy"])

    def test_violated_and_unknown_constraints_are_owner_attributed_blockers(self):
        violated = self.by_name["context-governance-violated-constraint"]["input"]
        for check in ("violated", "unknown"):
            with self.subTest(check=check):
                payload = copy.deepcopy(violated)
                constraint = payload["context_governance"]["resolved_context"]["constraints"][0]
                constraint["check"] = check
                payload["context_governance"]["resolved_context"]["blockers"][0]["kind"] = f"constraint_{check}"
                result = adapter.resolve(payload)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["code"], f"governance_constraint_{check}")
                self.assertEqual(result["owner"], ".github/rules/main")
                self.assertEqual(result["record"], "constraints/review-required.md")

    def test_unrelated_governance_records_are_ignored(self):
        payload = copy.deepcopy(
            self.by_name["context-governance-installed-no-applicable-records"]["input"]
        )
        payload["context_governance"]["resolved_context"]["conventions"] = [
            {
                "convention_id": "convention-typed-client",
                "scope": "workspace",
                "strength": "default",
                "statement": "Use the typed catalog client.",
                "record": "conventions/typed-client.md",
            }
        ]
        result = adapter.resolve(payload)
        self.assertEqual(result["source"], "direct_no_applicable_governance")
        self.assertEqual(result["consumer_policy"], payload["direct_consumer_policy"])

    def test_malformed_or_conflicting_governed_policy_blocks(self):
        base = copy.deepcopy(self.by_name["context-governance-valid-applicable-records"]["input"])
        convention = base["context_governance"]["resolved_context"]["conventions"][0]
        convention["statement"] = "github_delivery.branching = not-json"
        malformed = adapter.resolve(base)
        self.assertEqual(malformed["code"], "malformed_governed_policy")

        conflict = copy.deepcopy(self.by_name["context-governance-valid-applicable-records"]["input"])
        conflict["direct_consumer_policy"] = {"strategy": "trunk"}
        conflicting = adapter.resolve(conflict)
        self.assertEqual(conflicting["code"], "policy_source_conflict")

    def test_change_delivery_composes_governed_policy_without_hard_dependency(self):
        change_fixture = json.loads(CHANGE_FIXTURE_PATH.read_text(encoding="utf-8"))["base_input"]
        payload = copy.deepcopy(change_fixture)
        payload["consumer_policy"] = None
        payload["context_governance"] = copy.deepcopy(
            self.by_name["context-governance-valid-applicable-records"]["input"]["context_governance"]
        )
        result = change.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["policy_source"], "context_governance")
        self.assertEqual(len(result["governance_provenance"]), 2)
        self.assertEqual(result["branch_contract"]["strategy"], "feature")

    def test_change_delivery_surfaces_constraint_blocker_before_branch_resolution(self):
        change_fixture = json.loads(CHANGE_FIXTURE_PATH.read_text(encoding="utf-8"))["base_input"]
        payload = copy.deepcopy(change_fixture)
        payload["context_governance"] = copy.deepcopy(
            self.by_name["context-governance-violated-constraint"]["input"]["context_governance"]
        )
        result = change.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "governance_constraint_violated")
        self.assertEqual(result["blocker_source"], "context_governance")
        self.assertNotIn("branch_contract", result)

    def test_only_existing_target_contract_is_declared(self):
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        fixture = FIXTURE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("git_governance", source)
        self.assertNotIn("git_governance", fixture)
        self.assertIn("github_delivery.branching", source)
        self.assertIs(adapter.TARGET_FIELDS, adapter.branch_policy.SUPPORTED_POLICY_FIELDS)
        for skill_file in (ROOT / "skills/gh-change-delivery").rglob("SKILL.md"):
            frontmatter = skill_file.read_text(encoding="utf-8").split("---", 2)[1]
            self.assertNotIn("context_governance", frontmatter)

    def test_cli_returns_two_for_constraint_blocker(self):
        payload = self.by_name["context-governance-violated-constraint"]["input"]
        completed = subprocess.run(
            [sys.executable, str(ADAPTER_PATH)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["code"], "governance_constraint_violated")


if __name__ == "__main__":
    unittest.main()
