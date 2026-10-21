"""履歴の個人成績などの表を詰めて保存し、読むときは同じ中身に戻す。"""
from __future__ import annotations

import json
import unittest

from phase2_engine.historical_match_archive import (
    compact_payload,
    expand_payload,
)


PAYLOAD = {
    "year": 2026,
    "match_id": "M1",
    "inning_scores": [
        {"inning": 1, "half": "top", "runs": 0, "was_played": True},
        {"inning": 1, "half": "bottom", "runs": 2, "was_played": True},
    ],
    "batter_stats": [
        {"player_id": "P1", "school_id": "S1", "hits": 1},
        {"player_id": "P2", "school_id": "S1", "hits": 0},
    ],
    "pitcher_stats": None,
    "team_stats": [],
    "highlights": [["S", 1, "b", "P1", "double", 2]],
}


class ArchiveCompactTests(unittest.TestCase):
    def test_round_trip_keeps_the_same_content(self):
        compact = compact_payload(PAYLOAD)
        self.assertEqual(
            ["player_id", "school_id", "hits"],
            compact["batter_stats"]["columns"],
        )
        self.assertEqual(PAYLOAD, expand_payload(json.loads(json.dumps(compact))))

    def test_compact_is_smaller(self):
        rows = [
            {"player_id": f"P{i}", "plate_appearances": 4, "at_bats": 3}
            for i in range(20)
        ]
        payload = {"batter_stats": rows}
        self.assertLess(
            len(json.dumps(compact_payload(payload))),
            len(json.dumps(payload)) * 0.6,
        )

    def test_uneven_rows_are_left_as_they_are(self):
        payload = {"batter_stats": [{"a": 1}, {"b": 2}]}
        self.assertEqual(payload, compact_payload(payload))


if __name__ == "__main__":
    unittest.main()
