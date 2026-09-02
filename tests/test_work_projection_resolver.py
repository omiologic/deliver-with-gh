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


class WorkProjectionTestCase(unittest.TestCase):
    def setUp(self):
        self.scenarios = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def scenario(self, name):
        for scenario in self.scenarios:
            if scenario["name"] == name:
                return copy.deepcopy(scenario["input"])
        raise AssertionError(f"unknown scenario: {name}")


class WorkProjectionFixtureTests(WorkProjectionTestCase):
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


class IssueTypeSurfaceTests(WorkProjectionTestCase):
    def test_issue_type_maps_through_consumer_values(self):
        result = resolver.resolve(self.scenario("issue-type-mapped-through-consumer-values"))
        self.assertEqual(
            [item["github_metadata"]["issue_type"] for item in result["projection"]["items"]],
            ["Epic", "Feature"],
        )

    def test_issue_type_is_copied_exactly_without_values(self):
        result = resolver.resolve(self.scenario("issue-type-copied-without-values"))
        first = result["projection"]["items"][0]
        self.assertEqual(first["github_metadata"]["issue_type"], "Task")

    def test_package_supplies_no_default_issue_type(self):
        result = resolver.resolve(self.scenarios[0]["input"])
        for item in result["projection"]["items"]:
            self.assertNotIn("issue_type", item["github_metadata"])

    def test_optional_issue_type_is_omitted_and_reported(self):
        result = resolver.resolve(self.scenario("optional-issue-type-unavailable-is-omitted"))
        self.assertEqual(result["status"], "resolved")
        self.assertNotIn("issue_type", result["projection"]["items"][0]["github_metadata"])
        self.assertEqual(result["omissions"][0]["item_index"], 0)
        self.assertIn("issue_type", result["omissions"][0]["reason"])

    def test_optional_issue_type_value_miss_is_omitted(self):
        payload = self.scenario("issue-type-mapped-through-consumer-values")
        payload["consumer_policy"]["mappings"]["issue_type"]["required"] = False
        payload["work_items"][0]["planning_values"]["work_type"] = "unmapped"
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertNotIn("issue_type", result["projection"]["items"][0]["github_metadata"])
        self.assertEqual(result["omissions"], [{"item_index": 0, "reason": result["omissions"][0]["reason"]}])
        self.assertIn("'unmapped'", result["omissions"][0]["reason"])

    def test_required_issue_type_blocks_with_item_index_and_mapping(self):
        result = resolver.resolve(self.scenario("required-issue-type-unavailable-blocks"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "mapping_unavailable")
        self.assertEqual(result["item_index"], 0)
        self.assertEqual(result["mapping"], "issue_type")
        self.assertEqual(result["owner"], "consumer mapping owner")

    def test_draft_item_omits_issue_type_instead_of_erroring(self):
        result = resolver.resolve(self.scenario("optional-issue-type-omitted-for-draft-item"))
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["projection"]["items"][0]["github_metadata"], {})
        self.assertEqual(len(result["omissions"]), 1)
        self.assertIn("draft", result["omissions"][0]["reason"])

    def test_required_issue_type_blocks_for_a_draft_item(self):
        result = resolver.resolve(self.scenario("required-issue-type-blocks-for-draft-item"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "mapping_unavailable")
        self.assertEqual(result["item_index"], 0)
        self.assertEqual(result["mapping"], "issue_type")

    def test_unsupported_issue_label_surface_is_rejected(self):
        payload = self.scenario("issue-type-copied-without-values")
        payload["consumer_policy"]["mappings"]["issue_label"] = {"source": "work_type"}
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "unsupported_mapping")

    def test_malformed_issue_type_mapping_is_rejected(self):
        payload = self.scenario("issue-type-copied-without-values")
        payload["consumer_policy"]["mappings"]["issue_type"] = {"required": True}
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "malformed_mapping")


class ParentReferenceTests(WorkProjectionTestCase):
    def test_same_repository_number_normalizes_to_an_exact_reference(self):
        result = resolver.resolve(self.scenario("parent-by-same-repository-issue-number"))
        self.assertEqual(result["projection"]["items"][0]["parent"], "example-org/api#4")

    def test_cross_repository_parent_reference_is_preserved(self):
        result = resolver.resolve(self.scenario("parent-by-cross-repository-reference"))
        item = result["projection"]["items"][0]
        self.assertEqual(item["repository"], "partner-org/docs")
        self.assertEqual(item["parent"], "example-org/api#4")

    def test_draft_parent_forwards_the_batch_item_index(self):
        result = resolver.resolve(self.scenario("draft-parent-by-batch-item-index"))
        items = result["projection"]["items"]
        self.assertNotIn("parent", items[0])
        self.assertEqual(items[1]["parent"], {"item_index": 0})

    def test_items_without_a_parent_carry_no_parent_field(self):
        result = resolver.resolve(self.scenarios[0]["input"])
        for item in result["projection"]["items"]:
            self.assertNotIn("parent", item)

    def test_out_of_range_batch_index_blocks(self):
        result = resolver.resolve(self.scenario("draft-parent-item-index-out-of-range-blocks"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "parent_out_of_range")
        self.assertEqual(result["item_index"], 0)
        self.assertEqual(result["owner"], "bounded work owner")

    def test_self_referencing_batch_index_blocks(self):
        payload = self.scenario("draft-parent-by-batch-item-index")
        payload["work_items"][1]["parent"] = {"item_index": 1}
        result = resolver.resolve(payload)
        self.assertEqual(result["code"], "parent_out_of_range")
        self.assertEqual(result["item_index"], 1)

    def test_malformed_parent_references_block(self):
        cases = [
            ("issue", "example-org/api", "not-a-reference"),
            ("issue", "example-org/api", "example-org/api#0"),
            ("issue", "example-org/api", 0),
            ("issue", "example-org/api", True),
            ("issue", "example-org/api", {"item_index": 0}),
            ("draft", None, 4),
            ("draft", None, "example-org/api#4"),
            ("draft", None, {"item_index": "0"}),
            ("draft", None, {"item_index": 0, "repository": "example-org/api"}),
        ]
        for kind, repository, parent in cases:
            with self.subTest(kind=kind, parent=parent):
                item = {"kind": kind, "title": "Bounded work", "parent": parent}
                if repository is not None:
                    item["repository"] = repository
                result = resolver.resolve(
                    {"project_ref": "example-org/project/17", "work_items": [item]}
                )
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["code"], "malformed_parent")
                self.assertEqual(result["item_index"], 0)

    def test_parent_existence_is_never_verified(self):
        payload = self.scenario("parent-by-same-repository-issue-number")
        payload["work_items"][0]["parent"] = 999999
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["projection"]["items"][0]["parent"], "example-org/api#999999")

    def test_parent_does_not_become_canonical_state(self):
        result = resolver.resolve(self.scenario("draft-parent-by-batch-item-index"))
        serialized = json.dumps(result["projection"], sort_keys=True)
        self.assertNotIn("readiness", serialized)
        self.assertNotIn("completion", serialized)
        self.assertIn("projection only", result["authority"])


class IssueTypeAndParentIdempotenceTests(WorkProjectionTestCase):
    def test_equal_projection_including_issue_type_and_parent_is_a_no_op(self):
        result = resolver.resolve(self.scenario("issue-type-and-parent-projection-is-idempotent"))
        self.assertEqual(result["action"], "none")
        self.assertEqual(result["projection"]["items"][0]["parent"], "example-org/api#4")
        self.assertEqual(result["projection"]["items"][0]["github_metadata"]["issue_type"], "Feature")

    def test_changed_parent_requests_update(self):
        result = resolver.resolve(self.scenario("changed-parent-requests-update"))
        self.assertEqual(result["action"], "update")
        self.assertEqual(result["projection"]["items"][0]["parent"], "example-org/api#5")

    def test_changed_issue_type_requests_update(self):
        payload = self.scenario("issue-type-and-parent-projection-is-idempotent")
        payload["consumer_policy"]["mappings"]["issue_type"]["values"]["story"] = "Epic"
        result = resolver.resolve(payload)
        self.assertEqual(result["action"], "update")
        self.assertEqual(result["projection"]["items"][0]["github_metadata"]["issue_type"], "Epic")

    def test_added_parent_requests_update(self):
        payload = self.scenario("issue-type-and-parent-projection-is-idempotent")
        del payload["existing_projection"]["items"][0]["parent"]
        result = resolver.resolve(payload)
        self.assertEqual(result["action"], "update")

    def test_removed_parent_requests_update(self):
        payload = self.scenario("issue-type-and-parent-projection-is-idempotent")
        del payload["work_items"][0]["parent"]
        result = resolver.resolve(payload)
        self.assertEqual(result["action"], "update")
        self.assertNotIn("parent", result["projection"]["items"][0])


class IssueTypeAndParentCliTests(WorkProjectionTestCase):
    def run_cli(self, payload):
        return subprocess.run(
            [sys.executable, str(RESOLVER_PATH)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_returns_zero_for_a_resolved_issue_type_and_parent_projection(self):
        completed = self.run_cli(self.scenario("issue-type-and-parent-projection-is-idempotent"))
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["action"], "none")
        self.assertEqual(payload["projection"]["items"][0]["parent"], "example-org/api#4")

    def test_cli_returns_two_for_an_out_of_range_parent(self):
        completed = self.run_cli(self.scenario("draft-parent-item-index-out-of-range-blocks"))
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["code"], "parent_out_of_range")

    def test_cli_returns_two_for_a_required_issue_type(self):
        completed = self.run_cli(self.scenario("required-issue-type-unavailable-blocks"))
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["mapping"], "issue_type")


if __name__ == "__main__":
    unittest.main()
