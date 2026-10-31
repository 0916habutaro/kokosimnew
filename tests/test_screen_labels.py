"""画面に出す言葉（予選の段階名）。"""
from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace
import unittest

from phase2_engine.screen.data import load_screen_config, stage_names


ROOT = Path(__file__).resolve().parents[1]


class StageNameTests(unittest.TestCase):
    def test_config_names_replace_stage_names(self):
        repo = SimpleNamespace(
            competitions={"C1": {}},
            stages=lambda cid: [
                {"stage_id": "S1", "stage_name": "シード決定イベント"},
                {"stage_id": "S2", "stage_name": "県大会本体"},
            ],
        )
        names = stage_names(repo, {"stage_display_names": {"S1": {"name": "地区大会"}}})
        self.assertEqual({"S1": "地区大会", "S2": "県大会本体"}, names)
        self.assertEqual("県大会本体", stage_names(repo, {})["S2"])

    def test_configured_stages_are_seed_events_with_sources(self):
        def rows(path):
            with (ROOT / path).open(encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        stages = {r["stage_id"]: r for r in rows("data/competitions/competition_stages.csv")}
        sources = {r["source_id"] for r in rows("data/sources/phase2_sources.csv")}
        configured = load_screen_config(ROOT / "config")["stage_display_names"]
        self.assertTrue(configured)
        for stage_id, row in configured.items():
            self.assertEqual("SEED_EVENT", stages[stage_id]["stage_code"])
            self.assertIn(row["source_id"], sources)


if __name__ == "__main__":
    unittest.main()
