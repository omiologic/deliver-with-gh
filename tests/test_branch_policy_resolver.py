import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "skills/gh-change-delivery/scripts/resolve_branch_policy.py"
FIXTURE_PATH = ROOT / "skills/gh-change-delivery/fixtures/branch-policy-scenarios.json"
SPEC = importlib.util.spec_from_file_location("branch_policy_resolver", RESOLVER_PATH)
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolver)


class BranchPolicyFixtureTests(unittest.TestCase):
    def test_scenarios(self):
        scenarios = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = resolver.resolve(scenario["input"])
                for key, value in scenario["expect"].items():
                    self.assertEqual(result.get(key), value)

    def test_identical_inputs_produce_identical_output(self):
        scenario = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
        first = resolver.resolve(scenario["input"])
        second = resolver.resolve(scenario["input"])
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_project_context_cannot_change_repository_contract(self):
        scenario = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[5]
        with_project = resolver.resolve(scenario["input"])
        without_project_input = dict(scenario["input"])
        without_project_input.pop("project_context")
        without_project = resolver.resolve(without_project_input)
        self.assertEqual(with_project, without_project)

    def test_work_item_identifier_is_not_normalized(self):
        payload = {
            "repository": "example/widgets",
            "change": {
                "work_item_id": "Plan-A.WorkItem_0042",
                "type": "fix",
                "title": "Repair timeout",
            },
            "consumer_policy": {
                "strategy": "feature",
                "base_branch": "main",
                "branch_pattern": "{type}/{work_item_id}-{slug}",
                "allowed_types": ["fix"],
                "requires_pull_request": True,
            },
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["branch_name"], "fix/Plan-A.WorkItem_0042-repair-timeout")

    def test_default_branch_is_not_available_to_release_strategy(self):
        payload = {
            "repository": "example/widgets",
            "repository_default_branch": "main",
            "change": {"work_item_id": "WX-9", "title": "Release"},
            "consumer_policy": {
                "strategy": "release",
                "use_repository_default_as_base": True,
            },
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "default_branch_not_permitted")

    def test_valid_trunk_strategy(self):
        payload = {
            "repository": "example/widgets",
            "repository_default_branch": "main",
            "change": {"work_item_id": "WX-12", "title": "Update docs"},
            "consumer_policy": {
                "strategy": "trunk",
                "use_repository_default_as_base": True,
                "direct_work_allowed": True,
                "requires_pull_request": False,
            },
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["branch_name"], "main")
        self.assertFalse(result["requires_new_branch"])

    def test_valid_release_strategy(self):
        payload = {
            "repository": "example/widgets",
            "change": {"work_item_id": "WX-13", "type": "fix", "title": "Patch release"},
            "consumer_policy": {
                "strategy": "release",
                "branch_roles": {
                    "integration": "develop",
                    "release": "release/2.x",
                    "stable": "main",
                },
                "required_branch_roles": ["integration", "release", "stable"],
                "base_role": "integration",
                "pull_request_target_role": "release",
                "requires_new_branch": True,
                "requires_pull_request": True,
                "branch_pattern": "{type}/{work_item_id}-{slug}",
                "allowed_types": ["fix"],
            },
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["base_branch"], "develop")
        self.assertEqual(result["pull_request_base"], "release/2.x")

    def test_valid_custom_strategy(self):
        payload = {
            "repository": "example/widgets",
            "change": {"work_item_id": "WX-14", "title": "Vendor sync"},
            "consumer_policy": {
                "strategy": "custom",
                "custom_contract": {
                    "base_branch": "vendor/upstream",
                    "branch_name": "vendor/incoming",
                    "requires_new_branch": True,
                    "requires_pull_request": True,
                    "pull_request_base": "vendor/upstream",
                },
                "branch_name_regex": "vendor/[a-z]+",
                "max_branch_length": 32,
            },
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["branch_name"], "vendor/incoming")

    def test_allowed_override_has_precedence(self):
        payload = {
            "repository": "example/widgets",
            "change": {"work_item_id": "WX-10", "type": "fix", "title": "Repair"},
            "consumer_policy": {
                "strategy": "feature",
                "base_branch": "main",
                "branch_pattern": "{type}/{work_item_id}-{slug}",
                "allowed_types": ["fix"],
                "requires_pull_request": True,
                "allowed_operation_overrides": ["base_branch"],
            },
            "operation_override": {"base_branch": "maintenance"},
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["base_branch"], "maintenance")
        self.assertEqual(result["pull_request_base"], "maintenance")

    def test_disallowed_override_blocks(self):
        payload = {
            "repository": "example/widgets",
            "change": {"work_item_id": "WX-11", "type": "fix", "title": "Repair"},
            "consumer_policy": {"strategy": "feature", "base_branch": "main"},
            "operation_override": {"base_branch": "other"},
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "disallowed_override")

    def test_max_length_only_truncates_slug(self):
        payload = {
            "repository": "example/widgets",
            "change": {"work_item_id": "EXACT-0099", "type": "fix", "title": "A very long repair title"},
            "consumer_policy": {
                "strategy": "feature",
                "base_branch": "main",
                "branch_pattern": "{type}/{work_item_id}-{slug}",
                "allowed_types": ["fix"],
                "requires_pull_request": True,
                "max_branch_length": 25,
            },
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertIn("EXACT-0099", result["branch_name"])
        self.assertLessEqual(len(result["branch_name"]), 25)


if __name__ == "__main__":
    unittest.main()
