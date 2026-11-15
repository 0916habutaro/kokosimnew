"""トーナメント表のシードの印（bracket の行の ``seed``）。架空の大会で確かめる。"""
from __future__ import annotations

import pickle
import unittest
from types import SimpleNamespace

from phase2_engine.models import SeedAssignment
from phase2_engine.screen.competition_views import bracket_layout
from phase2_engine.tournament_runtime import MainTournamentRuntimeState

SCHOOLS = [f"FAKE-{n:02d}" for n in range(1, 13)]


def seed(school_id: str, tier: str, rank: int) -> SeedAssignment:
    return SeedAssignment(
        school_id=school_id, group_id="G1", group_name="架空", seed_tier=tier,
        source_rank=rank, seed_rule_id="RULE-FAKE", destination_stage="MAIN",
    )


def runtime(seeds=()):
    return MainTournamentRuntimeState.create(
        competition_id="CMP-FAKE", reference_year=2026, generation_seed=11,
        stage_id="STG-FAKE", entrants=SCHOOLS, seed_assignments=list(seeds),
    )


def seeds_of(layout) -> dict:
    return {row["school_id"]: row["seed"] for row in layout["rows"] if row["seed"]}


class BracketSeedTests(unittest.TestCase):
    def test_seed_schools_are_numbered_in_seed_order(self):
        main = runtime([
            seed("FAKE-07", "best8_seed", 1),
            seed("FAKE-03", "best4_seed", 2),
            seed("FAKE-10", "best4_seed", 1),
        ])
        layout = bracket_layout(main, SimpleNamespace(matches={}))
        # 上位の区分・順位から 第1シード＝1
        self.assertEqual({"FAKE-10": 1, "FAKE-03": 2, "FAKE-07": 3}, seeds_of(layout))
        # シードでない学校は None
        others = [row for row in layout["rows"] if row["school_id"] not in seeds_of(layout)]
        self.assertTrue(others)
        self.assertTrue(all(row["seed"] is None for row in others))
        # 保存・読込（状態を写す）のあとも同じ番号
        copy = pickle.loads(pickle.dumps(main))
        self.assertEqual(seeds_of(layout), seeds_of(bracket_layout(copy, SimpleNamespace(matches={}))))

    def test_no_marks_without_seeds(self):
        layout = bracket_layout(runtime(), SimpleNamespace(matches={}))
        self.assertEqual({}, seeds_of(layout))


if __name__ == "__main__":
    unittest.main()
