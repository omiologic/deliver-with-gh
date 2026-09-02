import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "skills/deliver-with-gh/scripts/route_delivery.py"
FIXTURE_PATH = ROOT / "skills/deliver-with-gh/fixtures/routing-scenarios.json"
SPEC = importlib.util.spec_from_file_location("delivery_router", ROUTER_PATH)
router = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(router)


class DeliveryRouterTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.by_name = {scenario["name"]: scenario for scenario in self.scenarios}

    def test_all_routing_scenarios(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = router.resolve(scenario["input"])
                for key, value in scenario["expect"].items():
                    self.assertEqual(result.get(key), value)

    def test_planning_project_preserves_three_repositories_without_inference(self):
        scenario = self.by_name["bounded-cross-repository-planning-projection"]
        result = router.resolve(scenario["input"])
        references = result["handoff"]["references"]
        self.assertEqual(
            references["repository_refs"],
            ["example-org/api", "example-org/web", "partner-org/docs"],
        )
        self.assertEqual(references["work_item_refs"], ["WI-API", "WI-WEB", "WI-DOCS", "WI-COMMS"])
        self.assertEqual(references["plan_refs"], ["plan://launch/v3"])
        self.assertEqual(
            references["project_ref"],
            {"owner": "example-org", "number": 17, "node_id": "PVT_example17"},
        )

    def test_project_identity_cannot_fill_missing_issue_repository(self):
        payload = copy.deepcopy(self.by_name["bounded-cross-repository-planning-projection"]["input"])
        payload["child_input"]["work_items"][0].pop("repository")
        result = router.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "missing_repository")

    def test_unreconciled_evidence_precedes_change_prerequisites(self):
        scenario = self.by_name["unreconciled-evidence-precedes-another-change-attempt"]
        self.assertNotIn("owner_state", scenario["input"])
        self.assertNotIn("child_input", scenario["input"])
        result = router.resolve(scenario["input"])
        self.assertEqual(result["destination"], "gh-delivery-reconciliation")
        self.assertEqual(
            result["handoff"]["child_input"],
            scenario["input"]["unreconciled_github_evidence"],
        )

    def test_branching_policy_is_passed_without_interpretation(self):
        scenario = self.by_name["ready-authorized-repository-change"]
        payload = copy.deepcopy(scenario["input"])
        opaque_policy = {
            "branching": {
                "strategy": "not-a-router-concern",
                "custom_consumer_data": {"preserve": [3, 2, 1]},
            }
        }
        payload["child_input"]["consumer_policy"] = opaque_policy
        result = router.resolve(payload)
        self.assertEqual(result["status"], "routed")
        self.assertEqual(result["destination"], "gh-change-delivery")
        self.assertEqual(result["handoff"]["child_input"]["consumer_policy"], opaque_policy)

    def test_child_input_is_preserved_exactly_for_every_lane(self):
        for name in (
            "bounded-cross-repository-planning-projection",
            "ready-authorized-repository-change",
            "explicit-github-evidence-reconciliation",
        ):
            with self.subTest(scenario=name):
                scenario = self.by_name[name]
                original = copy.deepcopy(scenario["input"]["child_input"])
                result = router.resolve(scenario["input"])
                self.assertEqual(result["handoff"]["child_input"], original)
                self.assertEqual(scenario["input"]["child_input"], original)

    def test_change_handoff_identifies_exact_repository_and_work(self):
        result = router.resolve(self.by_name["ready-authorized-repository-change"]["input"])
        self.assertEqual(
            result["handoff"]["references"],
            {
                "repository_ref": "example/widgets",
                "work_item_ref": "plan://launch/work-items/WX-142",
            },
        )

    def test_missing_readiness_and_each_requested_authority_block(self):
        readiness = router.resolve(self.by_name["change-missing-owner-readiness"]["input"])
        authority = router.resolve(self.by_name["change-missing-effect-authority"]["input"])
        self.assertEqual(readiness["code"], "missing_ready")
        self.assertEqual(authority["code"], "missing_authority")
        self.assertIn("push", authority["reason"])

    def test_stage_action_conflict_blocks_without_selecting_child(self):
        payload = copy.deepcopy(self.by_name["ready-authorized-repository-change"]["input"])
        payload["delivery_stage"] = "planning"
        result = router.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "stage_action_conflict")
        self.assertNotIn("destination", result)

    def test_no_result_infers_canonical_state(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = router.resolve(scenario["input"])
                self.assertEqual(result["canonical_state_inferences"], [])
                serialized = json.dumps(result, sort_keys=True)
                self.assertNotIn('"approved": true', serialized)
                self.assertNotIn('"complete": true', serialized)
                self.assertNotIn('"accepted": true', serialized)

    def test_identical_inputs_produce_identical_output(self):
        payload = self.by_name["bounded-cross-repository-planning-projection"]["input"]
        first = router.resolve(payload)
        second = router.resolve(copy.deepcopy(payload))
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_cli_exit_status_distinguishes_blocked_from_returned(self):
        blocked = subprocess.run(
            [sys.executable, str(ROUTER_PATH)],
            input=json.dumps(self.by_name["change-missing-repository"]["input"]),
            text=True,
            capture_output=True,
            check=False,
        )
        returned = subprocess.run(
            [sys.executable, str(ROUTER_PATH)],
            input=json.dumps(self.by_name["no-github-specific-action"]["input"]),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(returned.returncode, 0)


if __name__ == "__main__":
    unittest.main()
