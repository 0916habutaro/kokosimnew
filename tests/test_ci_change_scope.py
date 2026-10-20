"""Fast, synthetic regression tests for Stage119-CI-1; no real season run."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import ci_change_scope as scope


BASE = "1" * 40
HEAD = "2" * 40
ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ".github/workflows/python-tests.yml",
    ".github/workflows/windows-game-acceptance.yml",
)


class CiChangeScopeTests(unittest.TestCase):
    def test_allowlisted_prose_only(self):
        good = ("docs/research/stage43g119b_v3_save_design_20261018.md",
                "docs/guide/intro.rst", "README.md", "CHANGELOG.md", "CONTRIBUTING.md")
        for name in good:
            with self.subTest(name=name):
                self.assertTrue(scope.is_documentation_path(name))

    def test_no_config_scripts_or_path_tricks_are_docs(self):
        bad = (
            "tests/test_example.py", "phase2_engine/saved_fictional_bracket.py",
            "docs/config.json", "docs/ci-change.py", "docs/fixture.csv",
            ".github/workflows/python-tests.yml", ".github/README.md",
            "docs/research/a.md/../hack.py", "docs/../README.md",
            "other/README.md", "/docs/test.md", "docs\\test.md", "docs/readme",
            "", "docs/a\x00.md",
        )
        for name in bad:
            with self.subTest(name=name):
                self.assertFalse(scope.is_documentation_path(name))

    def test_docs_only_pr_and_main_push_are_fast(self):
        docs = ["docs/design/a.md", "README.md"]
        self.assertTrue(scope.route("pull_request", "refs/pull/1/merge",
                                    BASE, HEAD, paths=docs)[0])
        self.assertTrue(scope.route("push", "refs/heads/main",
                                    BASE, HEAD, paths=docs)[0])

    def test_code_and_mixed_changes_use_full_suite(self):
        for changes in (
            ["phase2_engine/example.py"],
            ["README.md", "tests/test_ci_change_scope.py"],
            ["docs/notes.md", ".github/workflows/python-tests.yml"],
            ["docs/data/master.csv"],
        ):
            with self.subTest(changes=changes):
                self.assertFalse(scope.route("pull_request", "", BASE, HEAD, paths=changes)[0])

    def test_unknown_event_revision_or_diff_is_full(self):
        cases = (
            ("workflow_dispatch", "", BASE, HEAD, ["README.md"]),
            ("schedule", "", BASE, HEAD, ["README.md"]),
            ("push", "refs/heads/feature", BASE, HEAD, ["README.md"]),
            ("push", "refs/heads/main", "0" * 40, HEAD, ["README.md"]),
            ("pull_request", "", "", HEAD, ["README.md"]),
            ("pull_request", "", BASE, "not-a-sha", ["README.md"]),
            ("pull_request", "", BASE, BASE, ["README.md"]),
            ("pull_request", "", BASE, HEAD, []),
        )
        for event, ref, base, head, paths in cases:
            with self.subTest(event=event, paths=paths, base=base):
                self.assertFalse(scope.route(event, ref, base, head, paths=paths)[0])

    def test_git_diff_handles_filename_with_newline_and_renames(self):
        completed = subprocess.CompletedProcess([], 0, b"docs/first.md\x00docs/other\nname.md\x00", b"")
        with patch.object(scope.subprocess, "run", return_value=completed) as runner:
            self.assertEqual(["docs/first.md", "docs/other\nname.md"],
                             scope.changed_paths(BASE, HEAD))
        command = runner.call_args.args[0]
        self.assertIn("-z", command)
        self.assertIn("--no-renames", command)
        self.assertEqual([BASE, HEAD], command[-2:])

    def test_git_errors_fail_closed(self):
        for result in (subprocess.CompletedProcess([], 1, b"", b"failed"),
                       subprocess.CompletedProcess([], 0, b"", b""),
                       subprocess.CompletedProcess([], 0, b"docs/a.md", b""),
                       subprocess.CompletedProcess([], 0, b"docs/a.md\xff\x00", b"")):
            with patch.object(scope.subprocess, "run", return_value=result):
                self.assertFalse(scope.route("pull_request", "", BASE, HEAD)[0])
        with patch.object(scope.subprocess, "run", side_effect=OSError("git missing")):
            self.assertFalse(scope.route("pull_request", "", BASE, HEAD)[0])

    def test_ci_wiring_preserves_core_heavy_commands(self):
        workflows = {name: (ROOT / name).read_text(encoding="utf-8")
                     for name in WORKFLOWS}
        for name, content in workflows.items():
            with self.subTest(workflow=name):
                self.assertIn("python tests/ci_change_scope.py", content)
                self.assertIn("steps.scope.outputs.docs_only != 'true'", content)
                self.assertIn("steps.scope.outputs.docs_only == 'true'", content)
                self.assertIn("pull_request", content)
                self.assertIn("main", content)
        self.assertIn("python tests/stage43g119_ci_metrics.py",
                      workflows[WORKFLOWS[0]])
        self.assertIn("test_stage43g10_full_kanto17_e2e.py",
                      workflows[WORKFLOWS[0]])
        self.assertIn("test_stage13e3e1_full_season_save_load.py",
                      workflows[WORKFLOWS[1]])
        self.assertIn("windows-latest", workflows[WORKFLOWS[1]])

    def test_only_kept_workflows_exist(self):
        # 段階0でCIを2本に整理した。増やす場合はこのテストと方針を見直す
        present = {p.name for p in (ROOT / ".github/workflows").glob("*.yml")}
        self.assertEqual({Path(name).name for name in WORKFLOWS}, present)


if __name__ == "__main__":
    unittest.main()
