from __future__ import annotations

import unittest

from phase2_engine.main_tournament import run_main_single_elimination


def _first_listed(team1, team2, namespace):
    return team1


class MainBracketByeTests(unittest.TestCase):
    def test_bye_on_left_slot_puts_team_in_team1(self):
        # 抽選で空き枠が左側（team1側）に来ても、不戦勝は team1 に出場校が入る。
        slots = ["", "T01", "T02", "T03", "T04", "", "T05", "T06"]
        execution, outcome = run_main_single_elimination(
            [x for x in slots if x],
            competition_id="CMPTEST",
            stage_id="STGTEST",
            base_seed=1,
            winner_resolver=_first_listed,
            slot_override=slots,
        )
        byes = [m for m in execution.matches if m.is_bye]
        self.assertEqual(
            [("T01", "", "T01"), ("T04", "", "T04")],
            [(m.team1, m.team2, m.winner) for m in byes],
        )
        self.assertEqual(slots, execution.metadata["initial_slots"])
        self.assertEqual(2, outcome.bye_count)
        self.assertEqual("T01", outcome.champion_school_id)


if __name__ == "__main__":
    unittest.main()
