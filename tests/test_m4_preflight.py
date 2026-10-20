import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.m4_preflight import CATEGORIES, main, validate_plan
from repolens.domain import RepoLensError


class M4PreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "plan.json"
        self.plan = {"schema_version": "repolens.m4-input.v1", "annotator": "fixture-reviewer",
                     "repositories": []}
        self.datasets = []
        for number in range(3):
            repo_id = f"fixture-{number}"
            sha = str(number + 1) * 40
            cases = []
            for index in range(15):
                category = CATEGORIES[index % len(CATEGORIES)]
                locators = [{"path": "src/service.py", "line_start": 1,
                             "line_end": 2, "symbol": "handler"}]
                if category == "cross_file":
                    locators.append(locators[0] | {"path": "src/caller.py"})
                if category in ("history", "abstention"):
                    locators = []
                cases.append({
                    "id": f"{repo_id}-{index}", "repo": repo_id, "commit_sha": sha,
                    "category": category, "query": f"fixture question {index}",
                    "expected_behavior": "abstain" if category == "abstention" else "answer",
                    "expected_evidence": locators,
                    "expected_commits": [sha] if category == "history" else [],
                    "review_notes": "Synthetic schema fixture, not real repository gold.",
                })
            self.datasets.append(cases)
            self.plan["repositories"].append({
                "id": repo_id, "local_path": str(self.root / f"unopened-{number}"),
                "commit_sha": sha, "language": "python", "license": "NOASSERTION",
                "authorization_note": "Synthetic metadata only.", "external_blind": True,
                "publish_metadata": False, "dataset": f"cases-{number}.jsonl",
            })
        self.write_inputs()

    def write_inputs(self):
        self.path.write_text(json.dumps(self.plan), encoding="utf-8")
        for number, cases in enumerate(self.datasets):
            (self.root / f"cases-{number}.jsonl").write_text(
                "".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8",
            )

    def test_valid_declarations_do_not_open_git_or_claim_benchmark_readiness(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with patch("subprocess.run", side_effect=AssertionError("must not invoke Git")):
            report = validate_plan(self.path)
        self.assertEqual(report["case_count"], 45)
        self.assertFalse(report["benchmark_ready"])
        self.assertEqual(report["plan_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        for number, summary in enumerate(report["repositories"]):
            raw = (self.root / f"cases-{number}.jsonl").read_bytes()
            self.assertEqual(summary["dataset_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(set(summary["by_category"]), set(CATEGORIES))
            self.assertFalse(summary["publish_metadata"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})

    def test_repository_requirements_reject_incomplete_or_reused_inputs(self):
        original = copy.deepcopy(self.plan)
        mutations = (
            lambda p: p.update(repositories=p["repositories"][:2]),
            lambda p: p.update(repositories=p["repositories"] * 2),
            lambda p: p.update(annotator=""),
            lambda p: p["repositories"][0].update(external_blind=False),
            lambda p: p["repositories"][0].update(language="typescript"),
            lambda p: p["repositories"][0].update(publish_metadata="false"),
            lambda p: p["repositories"][0].update(authorization_note=""),
            lambda p: p["repositories"][0].update(license=""),
            lambda p: p["repositories"][0].update(commit_sha="HEAD"),
            lambda p: p["repositories"][1].update(local_path=p["repositories"][0]["local_path"]),
        )
        for mutate in mutations:
            self.plan = copy.deepcopy(original)
            mutate(self.plan)
            self.write_inputs()
            with self.subTest(plan=self.plan), self.assertRaises(RepoLensError):
                validate_plan(self.path)

    def test_learning_references_and_existing_development_corpora_are_excluded(self):
        for name in ("all-in-rag", "AgentGuide", "pallets/flask", "RepoLens", "taskboard-v0",
                     "Book Manager V1", "book-manager-v1"):
            with self.subTest(name=name):
                self.plan["repositories"][0]["id"] = name
                self.write_inputs()
                with self.assertRaisesRegex(RepoLensError, "excluded"):
                    validate_plan(self.path)

    def test_a_new_id_does_not_hide_the_declared_development_repository_path(self):
        self.plan["repositories"][0]["local_path"] = "D:/sample/repos/Book Manager V1"
        self.write_inputs()
        with self.assertRaisesRegex(RepoLensError, "excluded"):
            validate_plan(self.path)

    def test_a_new_target_may_be_stored_under_the_repolens_data_directory(self):
        self.plan["repositories"][0]["local_path"] = "D:/sample/RepoLens/data/repositories/new-target"
        self.write_inputs()
        self.assertEqual(validate_plan(self.path)["case_count"], 45)
        self.plan["repositories"][0]["local_path"] = "D:\\sample\\AgentGuide\\"
        self.write_inputs()
        with self.assertRaisesRegex(RepoLensError, "excluded"):
            validate_plan(self.path)

    def test_commit_identity_and_global_case_ids_are_enforced(self):
        original = copy.deepcopy(self.datasets)
        for key, value in (("repo", "another-repo"), ("commit_sha", "a" * 40),
                           ("id", self.datasets[1][0]["id"])):
            with self.subTest(key=key):
                self.datasets = copy.deepcopy(original)
                self.datasets[0][0][key] = value
                self.write_inputs()
                with self.assertRaises(RepoLensError):
                    validate_plan(self.path)

    def test_question_count_and_category_coverage_are_enforced(self):
        self.datasets[0] = self.datasets[0][:14]
        self.write_inputs()
        with self.assertRaisesRegex(RepoLensError, "15 cases"):
            validate_plan(self.path)
        self.datasets[0].append(self.datasets[0][0] | {"id": "replacement"})
        for case in self.datasets[0]:
            if case["category"] == "english_natural_language":
                case["category"] = "identifier"
        self.write_inputs()
        with self.assertRaisesRegex(RepoLensError, "six categories"):
            validate_plan(self.path)

    def test_invalid_gold_cannot_pass_as_a_source_case(self):
        original = copy.deepcopy(self.datasets)
        mutations = (
            lambda c: c.update(expected_evidence=[]),
            lambda c: c["expected_evidence"][0].update(path="../secret.py"),
            lambda c: c["expected_evidence"][0].update(line_start=True),
            lambda c: c["expected_evidence"][0].update(line_end=0),
            lambda c: c["expected_evidence"].append(c["expected_evidence"][0].copy()),
            lambda c: c.update(expected_behavior="abstain"),
            lambda c: c.update(review_notes=""),
            lambda c: c.update(category=[]),
        )
        for index, mutate in enumerate(mutations):
            self.datasets = copy.deepcopy(original)
            mutate(self.datasets[0][0])
            self.write_inputs()
            with self.subTest(mutation=index), self.assertRaises(RepoLensError):
                validate_plan(self.path)

    def test_history_and_abstention_have_distinct_gold_contracts(self):
        original = copy.deepcopy(self.datasets)
        mutations = (
            (4, {"expected_commits": []}),
            (4, {"expected_commits": ["HEAD"]}),
            (4, {"expected_commits": ["1" * 40, "1" * 40]}),
            (5, {"expected_commits": ["1" * 40]}),
            (5, {"expected_evidence": self.datasets[0][0]["expected_evidence"]}),
            (3, {"expected_evidence": self.datasets[0][0]["expected_evidence"]}),
        )
        for case_index, values in mutations:
            self.datasets = copy.deepcopy(original)
            self.datasets[0][case_index].update(values)
            self.write_inputs()
            with self.subTest(case_index=case_index, values=values), self.assertRaises(RepoLensError):
                validate_plan(self.path)

    def test_unreadable_and_malformed_inputs_have_controlled_errors(self):
        for payload in ("not json", "[]", '{"schema_version": "unknown"}'):
            self.path.write_text(payload, encoding="utf-8")
            with self.subTest(payload=payload), self.assertRaises(RepoLensError):
                validate_plan(self.path)
        self.write_inputs()
        (self.root / "cases-0.jsonl").unlink()
        with self.assertRaises(RepoLensError):
            validate_plan(self.path)

    def test_cli_reports_json_with_exit_status_and_no_private_local_paths(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--plan", str(self.path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "input_shape_validated")
        self.assertNotIn(str(self.root), output.getvalue())
        self.path.write_text("{}", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--plan", str(self.path)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "input_rejected")


if __name__ == "__main__":
    unittest.main()
