from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from phase2_engine.models import CompetitionRun, Match, StageExecution
from phase2_engine.repository import DataRepository
from phase2_engine.result_view import (
    build_competition_result_view,
    save_competition_result_view,
)

ROOT = Path(__file__).resolve().parents[1]


class Stage12PResultViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        ids = sorted(cls.repo.schools)[:5]
        cls.a, cls.b, cls.c, cls.d, cls.e = ids

    def _run(self, seed=2026100701):
        matches = [
            Match(
                match_id="T-M1",
                competition_id="CMPTEST",
                stage_id="STGTEST",
                stage_code="MAIN",
                phase_code="R1",
                round_no=1,
                team1=self.a,
                team2=self.b,
                winner=self.a,
                loser=self.b,
                metadata={"round_name": "1回戦"},
            ),
            Match(
                match_id="T-M2",
                competition_id="CMPTEST",
                stage_id="STGTEST",
                stage_code="MAIN",
                phase_code="R1",
                round_no=1,
                team1=self.c,
                team2=self.d,
                winner=self.d,
                loser=self.c,
                metadata={"round_name": "1回戦"},
            ),
            Match(
                match_id="T-BYE",
                competition_id="CMPTEST",
                stage_id="STGTEST",
                stage_code="MAIN",
                phase_code="R1",
                round_no=1,
                team1=self.e,
                team2="",
                winner=self.e,
                loser="",
                is_bye=True,
                metadata={"round_name": "1回戦"},
            ),
        ]
        stage = StageExecution(
            stage_id="STGTEST",
            stage_code="MAIN",
            format_model_id="",
            entrant_school_ids=[self.a, self.b, self.c, self.d, self.e],
            output_school_ids=[self.a, self.d, self.e],
            matches=matches,
        )
        return CompetitionRun(
            competition_id="CMPTEST",
            year=2026,
            rng_seed=seed,
            entrant_school_ids=[self.a, self.b, self.c, self.d, self.e],
            seed_assignments=[],
            stage_executions=[stage],
            main_entrant_school_ids=[self.a, self.b, self.c, self.d, self.e],
        )

    def test_generated_scores_are_deterministic(self):
        run = self._run()
        a = build_competition_result_view(run, self.repo)
        b = build_competition_result_view(run, self.repo)
        self.assertEqual([x.to_dict() for x in a], [x.to_dict() for x in b])

    def test_generated_score_preserves_tournament_winner(self):
        rows = build_competition_result_view(self._run(), self.repo)
        by = {r.match_id: r for r in rows}
        self.assertGreater(by["T-M1"].team1_score, by["T-M1"].team2_score)
        self.assertLess(by["T-M2"].team1_score, by["T-M2"].team2_score)
        self.assertEqual("generated_v1", by["T-M1"].score_source)
        self.assertEqual("generated_v1", by["T-M2"].score_source)

    def test_school_names_are_resolved_for_display(self):
        rows = build_competition_result_view(self._run(), self.repo)
        first = rows[0]
        self.assertEqual(self.repo.team(self.a).display_name, first.team1_name)
        self.assertEqual(self.repo.team(self.b).display_name, first.team2_name)
        self.assertIn(first.team1_name, first.result_text)
        self.assertIn(first.team2_name, first.result_text)

    def test_exact_score_override(self):
        rows = build_competition_result_view(
            self._run(),
            self.repo,
            score_overrides={
                "T-M1": [7, 2],
                "T-M2": {"team1_score": 1, "team2_score": 4},
            },
        )
        by = {r.match_id: r for r in rows}
        self.assertEqual((7, 2, "override"), (
            by["T-M1"].team1_score,
            by["T-M1"].team2_score,
            by["T-M1"].score_source,
        ))
        self.assertEqual((1, 4, "override"), (
            by["T-M2"].team1_score,
            by["T-M2"].team2_score,
            by["T-M2"].score_source,
        ))

    def test_override_cannot_contradict_winner(self):
        with self.assertRaises(ValueError):
            build_competition_result_view(
                self._run(),
                self.repo,
                score_overrides={"T-M1": [1, 2]},
            )

    def test_tie_override_is_rejected(self):
        with self.assertRaises(ValueError):
            build_competition_result_view(
                self._run(),
                self.repo,
                score_overrides={"T-M1": [3, 3]},
            )

    def test_bye_has_no_score(self):
        rows = build_competition_result_view(self._run(), self.repo)
        bye = next(r for r in rows if r.match_id == "T-BYE")
        self.assertIsNone(bye.team1_score)
        self.assertIsNone(bye.team2_score)
        self.assertEqual("bye", bye.score_source)
        self.assertIn("不戦勝", bye.result_text)

    def test_unknown_override_id_is_rejected(self):
        with self.assertRaises(ValueError):
            build_competition_result_view(
                self._run(),
                self.repo,
                score_overrides={"UNKNOWN": [1, 0]},
            )

    def test_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = save_competition_result_view(
                self._run(),
                self.repo,
                td,
                score_overrides={"T-M1": [5, 2]},
            )
            with Path(path).open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(3, len(rows))
        self.assertIn("team1_name", rows[0])
        self.assertIn("team1_score", rows[0])
        self.assertIn("score_source", rows[0])
        self.assertIn("result_text", rows[0])


if __name__ == "__main__":
    unittest.main()
