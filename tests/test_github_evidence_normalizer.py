import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NORMALIZER_PATH = ROOT / "skills/gh-delivery-reconciliation/scripts/normalize_github_evidence.py"
FIXTURE_PATH = ROOT / "skills/gh-delivery-reconciliation/fixtures/github-evidence-scenarios.json"
SPEC = importlib.util.spec_from_file_location("github_evidence_normalizer", NORMALIZER_PATH)
normalizer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(normalizer)


class GitHubEvidenceNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def normalize(self, payload=None):
        result = normalizer.resolve(self.payload if payload is None else payload)
        self.assertEqual(result["status"], "normalized")
        return result

    def criterion(self, result, criterion_id):
        return next(entry for entry in result["criterion_evidence"] if entry["id"] == criterion_id)

    def classifications(self, result, criterion_id):
        return [entry["classification"] for entry in self.criterion(result, criterion_id)["evidence"]]

    def test_merged_pr_passing_unit_and_failing_integration_fixture(self):
        result = self.normalize()
        self.assertIn("supporting", self.classifications(result, "integration"))
        self.assertEqual(self.classifications(result, "unit"), ["supporting"])
        self.assertEqual(
            self.classifications(result, "integration-tests"),
            ["contradicting", "contradicting"],
        )

    def test_closed_issue_and_done_project_cannot_prove_completion(self):
        result = self.normalize()
        classifications = self.classifications(result, "completion")
        self.assertEqual(classifications.count("projection_only"), 4)
        self.assertEqual(classifications[-1], "missing")
        self.assertNotIn("supporting", classifications)

    def test_successful_check_cannot_prove_outside_declared_coverage(self):
        result = self.normalize()
        self.assertEqual(self.classifications(result, "unit"), ["supporting"])
        self.assertEqual(self.classifications(result, "docs"), ["missing"])
        docs_gap = next(gap for gap in result["gaps"] if gap["criterion_id"] == "docs")
        self.assertIn("docs-e2e", docs_gap["detail"])

    def test_failed_skipped_cancelled_stale_and_missing_are_distinct(self):
        result = self.normalize()
        self.assertTrue(all(value == "contradicting" for value in self.classifications(result, "integration-tests")))
        self.assertEqual(self.classifications(result, "skipped-suite"), ["missing"])
        self.assertEqual(self.classifications(result, "cancelled-suite"), ["contradicting"])
        self.assertEqual(self.classifications(result, "current-head"), ["missing"])
        stale = self.criterion(result, "current-head")["evidence"][0]
        self.assertIn("stale", stale["claim"])
        self.assertEqual(self.classifications(result, "docs"), ["missing"])

    def test_review_approval_is_bounded_review_evidence(self):
        result = self.normalize()
        review = self.criterion(result, "review")["evidence"][0]
        self.assertEqual(review["classification"], "supporting")
        self.assertEqual(review["references"]["review_id"], 301)
        completion_sources = self.criterion(result, "completion")["evidence"]
        review_for_completion = next(entry for entry in completion_sources if entry["source_kind"] == "review")
        self.assertEqual(review_for_completion["classification"], "projection_only")

    def test_all_exact_github_references_are_preserved(self):
        result = self.normalize()
        repository_records = result["provenance"]["repository_evidence"]
        references = [record["references"] for record in repository_records]
        self.assertTrue(any(ref.get("issue_ref") == "example/widgets#42" for ref in references))
        self.assertTrue(any(ref.get("pull_request_ref") == "example/widgets#87" for ref in references))
        self.assertTrue(any(ref.get("merge_commit_sha") == "dddddddddddddddddddddddddddddddddddddddd" for ref in references))
        self.assertTrue(any(ref.get("commit_sha") == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" for ref in references))
        self.assertTrue(any(ref.get("review_id") == 301 for ref in references))
        self.assertTrue(any(ref.get("check_run_id") == 501 for ref in references))
        self.assertTrue(any(ref.get("check_name") == "unit" for ref in references))
        self.assertTrue(any(ref.get("workflow_run_id") == 601 for ref in references))
        self.assertTrue(any(ref.get("job_id") == 701 for ref in references))
        self.assertTrue(any(ref.get("artifact_id") == 801 for ref in references))

    def test_cross_repository_project_metadata_is_separate(self):
        result = self.normalize()
        project_metadata = result["provenance"]["project_metadata"]
        self.assertEqual(len(project_metadata), 1)
        self.assertEqual(project_metadata[0]["references"]["projected_repository"], "partner/docs")
        self.assertEqual(
            project_metadata[0]["references"]["project_ref"],
            {"owner": "example", "number": 7, "node_id": "PVT_example7"},
        )
        self.assertTrue(
            all(record["observation"]["kind"] != "project_item" for record in result["provenance"]["repository_evidence"])
        )

    def test_consumer_can_grant_one_narrow_projection_meaning(self):
        payload = copy.deepcopy(self.payload)
        payload["criteria"].append(
            {"id": "tracking", "text": "The tracking Issue is closed.", "evidence_kind": "planning"}
        )
        payload["observations"][0]["criterion_ids"].append("tracking")
        payload["consumer_policy"]["projection_evidence"] = [
            {
                "kind": "issue",
                "criterion_id": "tracking",
                "field": "state",
                "value": "CLOSED",
                "classification": "supporting",
                "meaning": "Issue closure supports only the tracking criterion.",
            }
        ]
        result = self.normalize(payload)
        self.assertEqual(self.classifications(result, "tracking"), ["supporting"])
        self.assertNotIn("supporting", self.classifications(result, "completion"))

    def test_output_is_reconciliation_input_not_an_assessment(self):
        result = self.normalize()
        self.assertEqual(result["schema_version"], "delivery-reconciliation-evidence/v1")
        self.assertEqual(result["handoff_for"], "delivery-reconciliation")
        self.assertEqual(result["work_item_ref"], "plan://launch/work-items/WX-142")
        self.assertNotIn("assessment", result)
        self.assertEqual(result["canonical_transition"], {"performed": False, "implied": False})
        for criterion in result["criterion_evidence"]:
            self.assertTrue(criterion["evidence"])
            for evidence in criterion["evidence"]:
                self.assertIn(evidence["classification"], normalizer.CLASSIFICATIONS)

    def test_identical_inputs_produce_identical_output(self):
        first = normalizer.resolve(self.payload)
        second = normalizer.resolve(copy.deepcopy(self.payload))
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_required_workflow_without_matching_coverage_is_missing(self):
        payload = copy.deepcopy(self.payload)
        payload["observations"].append(
            {
                "kind": "workflow",
                "repository": "example/widgets",
                "name": "docs-e2e",
                "run_id": 999,
                "url": "https://github.com/example/widgets/actions/runs/999",
                "status": "completed",
                "conclusion": "success",
                "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "criterion_ids": ["unit"],
            }
        )
        result = self.normalize(payload)
        self.assertEqual(self.classifications(result, "docs"), ["missing"])

    def test_invalid_coverage_blocks(self):
        payload = copy.deepcopy(self.payload)
        payload["observations"][0]["criterion_ids"] = ["unknown"]
        result = normalizer.resolve(payload)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["code"], "unknown_criterion")

    def test_cli_returns_two_for_invalid_input(self):
        payload = copy.deepcopy(self.payload)
        payload.pop("work_item_ref")
        completed = subprocess.run(
            [sys.executable, str(NORMALIZER_PATH)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
