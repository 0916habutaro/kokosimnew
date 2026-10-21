"""試合経過の要点（得点が入った打席・本塁打・投手交代）。"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from game_core.highlights import game_highlights, validate_highlights


def event(inning, half, defense, pitcher, batter, event_type, runs=0):
    return SimpleNamespace(
        inning=inning, half=half, defense_school_id=defense,
        pitcher_id=pitcher, batter_id=batter, event_type=event_type,
        runs_scored=runs,
    )


class HighlightsTests(unittest.TestCase):
    def test_scoring_plays_and_pitching_changes_only(self):
        events = [
            event(1, "top", "B", "PB1", "A1", "single"),
            event(1, "top", "B", "PB1", "A2", "home_run", 2),
            event(1, "bottom", "A", "PA1", "B1", "strikeout"),
            event(5, "top", "B", "PB2", "A3", "sacrifice_fly", 1),
            event(5, "bottom", "A", "PA1", "B2", "double", 1),
        ]
        highlights = game_highlights(events)
        self.assertEqual([
            ["S", 1, "t", "A2", "home_run", 2],
            ["P", 5, "t", "B", "PB2"],
            ["S", 5, "t", "A3", "sacrifice_fly", 1],
            ["S", 5, "b", "B2", "double", 1],
        ], highlights)
        validate_highlights(highlights)

    def test_invalid_entries_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_highlights([["S", 1, "t", "A", "single", 0]])
        with self.assertRaises(ValueError):
            validate_highlights([["X", 1, "t"]])


if __name__ == "__main__":
    unittest.main()
