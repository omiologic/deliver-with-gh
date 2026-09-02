import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "skills/gh-change-delivery/scripts/resolve_change_delivery.py"
FIXTURE_PATH = ROOT / "skills/gh-change-delivery/fixtures/change-delivery-scenarios.json"
SPEC = importlib.util.spec_from_file_location("change_delivery_resolver", RESOLVER_PATH)
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolver)


def deep_merge(base, patch):
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class ChangeDeliveryResolverTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.base = fixture["base_input"]
        self.scenarios = fixture["scenarios"]

    def test_fixture_scenarios(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["name"]):
                payload = deep_merge(self.base, scenario["patch"])
                result = resolver.resolve(payload)
                for key, value in scenario["expect"].items():
                    if key == "blocker_codes":
                        actual = [entry["code"] for entry in result["handoff"]["delivery_blockers"]]
                        self.assertEqual(actual, value)
                    else:
                        self.assertEqual(result.get(key), value)

    def test_valid_feature_branch_handoff_preserves_exact_references(self):
        result = resolver.resolve(self.base)
        self.assertEqual(result["repository"], "example/widgets")
        self.assertEqual(result["work_item_ref"], "plan://launch/work-items/WX-142")
        self.assertEqual(result["branch_contract"]["branch_name"], "feature/WX-142-add-organization-delete")
        self.assertEqual(
            result["handoff"]["commits"][0]["sha"],
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        self.assertEqual(result["handoff"]["pull_request"]["number"], 87)
        self.assertEqual(result["handoff"]["canonical_completion"], "not_determined")

    def test_missing_repository_blocks_before_branch_policy(self):
        payload = copy.deepcopy(self.base)
        payload.pop("repository")
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "missing_repository")
        self.assertNotIn("blocker_source", result)

    def test_missing_and_malformed_policy_use_branch_policy_blockers(self):
        for policy, code in ((None, "missing_policy"), ("feature", "malformed_policy")):
            with self.subTest(policy=policy):
                payload = copy.deepcopy(self.base)
                payload["consumer_policy"] = policy
                result = resolver.resolve(payload)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["code"], code)
                self.assertEqual(result["blocker_source"], "branch_policy")

    def test_cross_repository_scope_requires_separate_envelope(self):
        payload = copy.deepcopy(self.base)
        payload["change_envelope"]["immutable_scope"].append(
            {"repository": "example/other", "path": "src/coupled_change.py"}
        )
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "cross_repository_scope")

    def test_each_mutating_effect_requires_its_own_authority(self):
        cases = {}

        branch = copy.deepcopy(self.base)
        branch["requested_effects"] = ["branch_create"]
        branch["observations"]["branch"]["exists"] = False
        cases["branch_create"] = branch

        commit = copy.deepcopy(self.base)
        commit["requested_effects"] = ["commit_create"]
        commit["desired"] = {"commit": {"idempotency_key": "WX-142-followup"}}
        cases["commit_create"] = commit

        push = copy.deepcopy(self.base)
        push["requested_effects"] = ["push"]
        push["desired"] = {"push": {"head_sha": "cccccccccccccccccccccccccccccccccccccccc"}}
        cases["push"] = push

        pr_create = copy.deepcopy(self.base)
        pr_create["requested_effects"] = ["pr_create"]
        pr_create["desired"] = {
            "pull_request": {"title": "New PR", "body": "WorkItem: plan://launch/work-items/WX-142"}
        }
        pr_create["observations"].pop("pull_request")
        cases["pr_create"] = pr_create

        pr_update = copy.deepcopy(self.base)
        pr_update["requested_effects"] = ["pr_update"]
        pr_update["desired"] = {
            "pull_request": {"title": "Updated PR", "body": "WorkItem: plan://launch/work-items/WX-142"}
        }
        cases["pr_update"] = pr_update

        review = copy.deepcopy(self.base)
        review["requested_effects"] = ["review_submit"]
        review["desired"] = {
            "review": {
                "reviewer": "octocat",
                "decision": "APPROVED",
                "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        }
        cases["review_submit"] = review

        checks = copy.deepcopy(self.base)
        checks["requested_effects"] = ["checks_trigger"]
        checks["desired"] = {"checks": {"head_sha": "cccccccccccccccccccccccccccccccccccccccc"}}
        cases["checks_trigger"] = checks

        merge = copy.deepcopy(self.base)
        merge["requested_effects"] = ["merge"]
        cases["merge"] = merge

        for effect, payload in cases.items():
            with self.subTest(effect=effect):
                result = resolver.resolve(payload)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["code"], "unauthorized_effect")
                self.assertEqual(result["effect"], effect)

    def test_exact_existing_pr_create_and_update_are_idempotent(self):
        for effect in ("pr_create", "pr_update"):
            with self.subTest(effect=effect):
                payload = copy.deepcopy(self.base)
                payload["requested_effects"] = [effect]
                payload["desired"] = {
                    "pull_request": {
                        "title": "WX-142: Add organization delete",
                        "body": "WorkItem: plan://launch/work-items/WX-142",
                    }
                }
                result = resolver.resolve(payload)
                self.assertEqual(result["status"], "resolved")
                self.assertEqual(result["effects"], [{"effect": effect, "action": "none"}])

    def test_merge_with_failed_check_is_blocked_even_when_authorized(self):
        payload = deep_merge(self.base, self.scenarios[1]["patch"])
        payload["requested_effects"] = ["merge"]
        payload["authority"] = {"merge": True}
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "merge_prerequisite_blocked")
        self.assertEqual(result["effect"], "merge")

    def test_merged_pr_is_evidence_not_completion(self):
        payload = copy.deepcopy(self.base)
        payload["observations"]["pull_request"]["merged"] = True
        payload["observations"]["pull_request"]["state"] = "MERGED"
        payload["requested_effects"] = ["merge"]
        result = resolver.resolve(payload)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["phase"], "merged_evidence")
        self.assertEqual(result["effects"], [{"effect": "merge", "action": "none"}])
        self.assertTrue(result["handoff"]["merge_observed"])
        self.assertEqual(result["handoff"]["canonical_completion"], "not_determined")

    def test_scope_digest_is_deterministic_and_order_sensitive(self):
        first = resolver.resolve(self.base)
        second = resolver.resolve(copy.deepcopy(self.base))
        self.assertEqual(first["scope_digest"], second["scope_digest"])
        reversed_payload = copy.deepcopy(self.base)
        reversed_payload["change_envelope"]["immutable_scope"].reverse()
        reversed_result = resolver.resolve(reversed_payload)
        self.assertNotEqual(first["scope_digest"], reversed_result["scope_digest"])

    def test_cli_returns_two_for_unauthorized_effect(self):
        payload = copy.deepcopy(self.base)
        payload["requested_effects"] = ["merge"]
        completed = subprocess.run(
            [sys.executable, str(RESOLVER_PATH)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["code"], "unauthorized_effect")


if __name__ == "__main__":
    unittest.main()
