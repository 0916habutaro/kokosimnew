"""走者の責任投手・失策出塁・タイブレーク配置を追跡する内部状態の検証。"""
from __future__ import annotations

import unittest

from game_core.match_simulator import _RunnerResponsibilityTracker


class RunnerResponsibilityTests(unittest.TestCase):
    def play(
        self, ledger, before, after, scored, batter, pitcher, event, pa,
    ):
        return ledger.record_play(
            bases_before=before,
            bases_after=after,
            scored_runner_ids=scored,
            batter_id=batter,
            pitcher_id=pitcher,
            event_type=event,
            plate_appearance_no=pa,
        )

    def test_inherited_runner_retains_pitcher_through_hit_and_score(self):
        ledger = _RunnerResponsibilityTracker()
        self.play(ledger, [None, None, None], ["R1", None, None], [], "R1", "A", "walk", 1)
        self.play(ledger, ["R1", None, None], ["R2", None, "R1"], [], "R2", "B", "single", 2)
        scored = self.play(
            ledger, ["R2", None, "R1"], ["R3", None, None], ["R1"],
            "R3", "C", "single", 3,
        )
        self.assertEqual([("R1", "A", 1)], [
            (row.player_id, row.responsible_pitcher_id, row.plate_appearance_no)
            for row in scored
        ])

    def test_three_pitchers_and_grand_slam_credit_each_runner(self):
        ledger = _RunnerResponsibilityTracker()
        self.play(ledger, [None] * 3, ["R1", None, None], [], "R1", "A", "walk", 1)
        self.play(ledger, ["R1", None, None], ["R2", "R1", None], [], "R2", "B", "walk", 2)
        self.play(ledger, ["R2", "R1", None], ["R3", "R2", "R1"], [], "R3", "C", "walk", 3)
        scored = self.play(
            ledger, ["R3", "R2", "R1"], [None] * 3,
            ["R3", "R2", "R1", "R4"], "R4", "D", "home_run", 4,
        )
        self.assertEqual(["C", "B", "A", "D"], [
            row.responsible_pitcher_id for row in scored
        ])

    def test_bases_loaded_walk_preserves_responsibility(self):
        ledger = _RunnerResponsibilityTracker()
        self.play(ledger, [None] * 3, ["R1", None, None], [], "R1", "A", "single", 1)
        self.play(ledger, ["R1", None, None], ["R2", "R1", None], [], "R2", "B", "walk", 2)
        self.play(ledger, ["R2", "R1", None], ["R3", "R2", "R1"], [], "R3", "C", "walk", 3)
        scored = self.play(
            ledger, ["R3", "R2", "R1"], ["R4", "R3", "R2"], ["R1"],
            "R4", "D", "walk", 4,
        )
        self.assertEqual("A", scored[0].responsible_pitcher_id)

    def test_error_runner_remains_flagged_through_advancement(self):
        ledger = _RunnerResponsibilityTracker()
        self.play(
            ledger, [None] * 3, ["R1", None, None], [],
            "R1", "A", "reached_on_error", 1,
        )
        self.play(ledger, ["R1", None, None], [None, "R2", "R1"], [], "R2", "B", "double", 2)
        scored = self.play(
            ledger, [None, "R2", "R1"], [None, "R2", None], ["R1"],
            "R3", "C", "sacrifice_fly", 3,
        )
        self.assertEqual("A", scored[0].responsible_pitcher_id)
        self.assertTrue(scored[0].reached_on_error)
        self.assertFalse(scored[0].tiebreak_placed)

    def test_tiebreak_runners_keep_special_flag_and_original_pitcher(self):
        ledger = _RunnerResponsibilityTracker()
        ledger.seed_tiebreak(["R1", "R2", None], "A")
        scored = self.play(
            ledger, ["R1", "R2", None], [None, "R3", "R1"], ["R2"],
            "R3", "A", "double", 10,
        )
        self.assertTrue(scored[0].tiebreak_placed)
        self.assertEqual("A", scored[0].responsible_pitcher_id)
        scored = self.play(
            ledger, [None, "R3", "R1"], [None] * 3, ["R1", "R3", "R4"],
            "R4", "B", "home_run", 11,
        )
        self.assertEqual(
            [("R1", "A", True), ("R3", "A", False), ("R4", "B", False)],
            [(r.player_id, r.responsible_pitcher_id, r.tiebreak_placed) for r in scored],
        )
        self.assertIsNone(scored[0].plate_appearance_no)

    def test_fielders_choice_removes_out_runner_but_retains_new_batter(self):
        ledger = _RunnerResponsibilityTracker()
        self.play(ledger, [None] * 3, ["R1", None, None], [], "R1", "A", "single", 1)
        self.play(ledger, ["R1", None, None], ["R2", None, None], [], "R2", "B", "fielder_choice", 2)
        scored = self.play(
            ledger, ["R2", None, None], [None] * 3,
            ["R2", "R3"], "R3", "C", "home_run", 3,
        )
        self.assertEqual(["B", "C"], [r.responsible_pitcher_id for r in scored])

    def test_sacrifice_bunt_preserves_runner_origin(self):
        ledger = _RunnerResponsibilityTracker()
        self.play(ledger, [None] * 3, ["R1", None, None], [], "R1", "A", "single", 1)
        self.play(ledger, ["R1", None, None], [None, "R1", None], [], "R2", "B", "sacrifice_bunt", 2)
        scored = self.play(
            ledger, [None, "R1", None], [None, "R3", None],
            ["R1"], "R3", "C", "double", 3,
        )
        self.assertEqual("A", scored[0].responsible_pitcher_id)

    def test_new_half_inning_has_no_previous_runners(self):
        first = _RunnerResponsibilityTracker()
        self.play(first, [None] * 3, ["R1", None, None], [], "R1", "A", "walk", 1)
        second = _RunnerResponsibilityTracker()
        scored = self.play(
            second, [None] * 3, [None] * 3,
            ["R2"], "R2", "B", "home_run", 2,
        )
        self.assertEqual("B", scored[0].responsible_pitcher_id)

    def test_deterministic_replay_and_rejects_unknown_runner(self):
        def scenario():
            tracker = _RunnerResponsibilityTracker()
            self.play(
                tracker, [None] * 3, ["R1", None, None], [],
                "R1", "A", "reached_on_error", 1,
            )
            return self.play(
                tracker, ["R1", None, None], [None] * 3, ["R1", "R2"],
                "R2", "B", "home_run", 2,
            )
        self.assertEqual(scenario(), scenario())
        with self.assertRaises(ValueError):
            self.play(
                _RunnerResponsibilityTracker(),
                ["UNKNOWN", None, None], [None] * 3, [],
                "R1", "A", "field_out", 1,
            )


if __name__ == "__main__":
    unittest.main()
