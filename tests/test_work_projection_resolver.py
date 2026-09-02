import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "skills/gh-work-planning/scripts/resolve_work_projection.py"
FIXTURE_PATH = ROOT / "skills/gh-work-planning/fixtures/work-projection-scenarios.json"
SPEC = importlib.util.spec_from_file_location("work_projection_resolver", RESOLVER_PATH)
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolver)


class WorkProjectionFixtureTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_scenarios(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = resolver.resolve(scenario["input"])
                for key, value in scenario["expect"].items():
                    if key == "item_count":
                        self.assertEqual(len(result["projection"]["items"]), value)
                    elif key == "omission_count":
                        self.assertEqual(len(result["omissions"]), value)
                    else:
                        self.assertEqual(result.get(key), value)

    def test_one_project_preserves_three_exact_repositories_and_a_draft(self):
        result = resolver.resolve(self.scenarios[0]["input"])
        items = result["projection"]["items"]
        self.assertEqual(
            [item.get("repository") for item in items],
            ["example-org/api", "example-org/web", "partner-org/docs", None],
        )
        self.assertNotIn("repository", items[3])
        self.assertEqual(
            result["projection"]["project_ref"],
            {"owner": "example-org", "number": 17, "node_id": "PVT_example17"},
        )

    def test_project_identity_never_supplies_issue_repository(self):
        payload = {
            "project_ref": {"owner": "looks-like-a-repo-owner", "number": 4, "repository": "wrong/inference"},
            "work_items": [{"kind": "issue", "title": "No repository"}],
        }
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "missing_repository")

    def test_project_object_requires_exact_identity(self):
        result = resolver.resolve(
            {
                "project_ref": {"repository": "example-org/api"},
                "work_items": [{"kind": "draft", "title": "Coordination"}],
            }
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "missing_project")

    def test_exact_canonical_references_are_preserved(self):
        result = resolver.resolve(self.scenarios[0]["input"])
        first = result["projection"]["items"][0]
        self.assertEqual(
            first["canonical_refs"],
            {"plan": "plans/account-launch", "work_item": "WI-API-12"},
        )
        self.assertIn("- plan: plans/account-launch", first["body"])
        self.assertIn("- work_item: WI-API-12", first["body"])

    def test_github_state_cannot_manufacture_delivery_state(self):
        payload = copy.deepcopy(self.scenarios[0]["input"])
        payload["github_state"] = {"project_status": "Done"}
        payload["work_items"][0]["github_state"] = {"issue_state": "closed"}
        result = resolver.resolve(payload)
        serialized = json.dumps(result["projection"], sort_keys=True)
        self.assertNotIn("readiness", serialized)
        self.assertNotIn("acceptance", result["projection"])
        self.assertNotIn("completion", result["projection"])
        self.assertNotIn("github_state", serialized)

    def test_exact_existing_projection_is_idempotent(self):
        payload = copy.deepcopy(self.scenarios[0]["input"])
        first = resolver.resolve(payload)
        payload["existing_projection"] = copy.deepcopy(first["projection"])
        second = resolver.resolve(payload)
        self.assertEqual(second["status"], "resolved")
        self.assertEqual(second["action"], "none")
        self.assertEqual(second["projection"], first["projection"])

    def test_changed_existing_projection_requests_update(self):
        payload = copy.deepcopy(self.scenarios[0]["input"])
        existing = resolver.resolve(payload)["projection"]
        existing["items"][0]["title"] = "Stale title"
        payload["existing_projection"] = existing
        result = resolver.resolve(payload)
        self.assertEqual(result["action"], "update")

    def test_project_status_mapping_remains_metadata(self):
        result = resolver.resolve(self.scenarios[0]["input"])
        first = result["projection"]["items"][0]
        self.assertEqual(first["github_metadata"]["project_fields"]["Status"], "In progress")
        self.assertNotIn("canonical_state", first)

    def test_identical_inputs_produce_identical_json(self):
        payload = self.scenarios[0]["input"]
        first = resolver.resolve(payload)
        second = resolver.resolve(payload)
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_cli_returns_two_for_bounded_blocker(self):
        completed = subprocess.run(
            [sys.executable, str(RESOLVER_PATH)],
            input=json.dumps(self.scenarios[1]["input"]),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["code"], "mapping_unavailable")


if __name__ == "__main__":
    unittest.main()
