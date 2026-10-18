"""Fast unit tests for Stage119-A metrics. Never execute the real 2400+ suite."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import stage43g119_ci_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]


class Stage119MetricsTests(unittest.TestCase):
    def test_result_keeps_success_skip_failure_and_normal_unittest_failure(self):
        class Toy(unittest.TestCase):
            def test_ok(self):
                self.assertTrue(True)

            @unittest.skip("intentional")
            def test_skip(self):
                raise RuntimeError("must skip")

            def test_failure(self):
                self.fail("deliberate failure in isolated synthetic case")

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Toy)
        output = io.StringIO()
        with redirect_stderr(output):
            result = unittest.TextTestRunner(
                stream=output, verbosity=0,
                resultclass=metrics.TimedTextResult).run(suite)
        self.assertEqual(3, result.testsRun)
        self.assertFalse(result.wasSuccessful())
        report = metrics.make_report(result, elapsed_seconds=1.25,
                                     process_cpu_seconds=0.50,
                                     env={"python": "synthetic", "sqlite": "synthetic"})
        self.assertEqual((3, 1, 1, 0),
                         (report["tests"], report["skipped"], report["failures"], report["errors"]))
        self.assertEqual({"failure", "skipped", "success"},
                         {row["status"] for row in report["per_test"]})
        self.assertEqual(3, len(report["per_test"]))
        self.assertEqual(3, sum(row["count"] for row in report["per_module"].values()))
        self.assertTrue(all(row["seconds"] >= 0 for row in report["per_test"]))
        self.assertEqual(1.25, report["elapsed_seconds"])

    def test_subtest_failure_is_not_misreported_as_success(self):
        class Subtest(unittest.TestCase):
            def test_subtest(self):
                with self.subTest(i=1):
                    self.assertEqual(1, 2)

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Subtest)
        result = unittest.TextTestRunner(
            stream=io.StringIO(), verbosity=0,
            resultclass=metrics.TimedTextResult).run(suite)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual("failure_or_error_subtest", result.timings[0]["status"])

    def test_compare_reports_accounts_for_ids_differences_and_environment(self):
        def report(items, sha):
            rows = [dict(id=f"module.Case.{name}", module="module",
                         status="success", seconds=t,
                         process_cpu_seconds=t/2) for name, t in items]
            return dict(schema=1, tests=len(rows), elapsed_seconds=sum(t for _, t in items),
                        per_test=rows, per_module=metrics.aggregate(rows),
                        environment={"github": {"GITHUB_SHA": sha}})
        before = report([("same", 5.0), ("removed", 2.0)], "old")
        after = report([("same", 8.5), ("new", 1.0)], "new")
        result = metrics.compare_reports(before, after)
        self.assertEqual((1, ["module.Case.new"], ["module.Case.removed"]),
                         (result["common_tests"], result["added_tests"], result["removed_tests"]))
        self.assertEqual(2.5, result["elapsed_delta_seconds"])
        self.assertEqual(3.5, result["test_deltas"][0]["delta_seconds"])
        self.assertTrue(result["cause_not_inferable_from_single_comparison"])
        with self.assertRaises(ValueError):
            metrics.compare_reports(dict(before, schema=100), after)
        with self.assertRaises(ValueError):
            metrics.compare_reports(dict(before, per_test=before["per_test"] * 2), after)

    def test_environment_is_whitelisted_not_secret_or_host_name(self):
        with patch.dict(metrics.os.environ, {"RUNNER_OS": "Linux",
                                              "GITHUB_SHA": "abc",
                                              "PRIVATE_PASSWORD": "do-not-write"}, clear=True):
            value = metrics.environment()
        dumped = json.dumps(value)
        self.assertEqual("Linux", value["github"]["RUNNER_OS"])
        self.assertNotIn("do-not-write", dumped)
        self.assertNotIn("PRIVATE_PASSWORD", dumped)
        self.assertNotIn("hostname", dumped)

    def test_new_report_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subdir" / "report.json"
            metrics.write_new(path, {"tests": 3})
            self.assertEqual(3, json.loads(path.read_text(encoding="utf-8"))["tests"])
            with self.assertRaises(FileExistsError):
                metrics.write_new(path, {"tests": 4})

    def test_existing_full_suite_wired_once_with_artifact_and_no_timeout_change(self):
        workflow = (ROOT / ".github/workflows/python-tests.yml").read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: 120", workflow)
        self.assertEqual(1, workflow.count("python tests/stage43g119_ci_metrics.py"))
        self.assertIn("unittest-timings.json", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn('KOKOSIM_SKIP_STAGE43G10_E2E: "1"', workflow)
        audit = (ROOT / "tests/stage43g119_ci_metrics.py").read_text(encoding="utf-8")
        self.assertIn('pattern="test*.py"', audit)
        self.assertIn("result.wasSuccessful()", audit)


if __name__ == "__main__":
    unittest.main()
