"""県大会の出場：チームを出せる学校はすべて出る（乱数で出場校を減らさない）。
予選はその年のチーム数から組み、本大会の校数は変わらない。架空の学校で確かめる。"""
from __future__ import annotations

from pathlib import Path
import unittest

from game_core.joint_teams import JointTeam, UnionPlan, apply_to_annual
from phase2_engine import DataRepository, TournamentEngine
from phase2_engine.models import AnnualCompetitionInput
from phase2_engine.season import StructuralAnnualInputFactory

DATA = Path(__file__).resolve().parents[1] / "data"
PREFECTURAL = ("spring_prefectural", "autumn_prefectural")


class FullEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.factory = StructuralAnnualInputFactory(cls.repo, DATA, 1)

    def fake_schools(self, prefix: str, count: int, prefecture: str) -> list[str]:
        ids = [f"FAKE-{prefix}-{n:03d}" for n in range(count)]
        for school_id in ids:
            self.repo.schools[school_id] = {"school_id": school_id, "prefecture_code": prefecture}
            self.addCleanup(self.repo.schools.pop, school_id)
        return ids

    def run_both(self, annual: AnnualCompetitionInput):
        """一度に進める版と、1試合ずつ進める版（ゲームの本番）が同じ結果になる。"""
        legacy = TournamentEngine(self.repo).run(annual)
        lazy = TournamentEngine(self.repo).prepare_competition_runtime(annual).resolve_all()
        self.assertEqual(legacy.to_dict(), lazy.to_dict())
        return lazy

    def test_every_school_enters_every_prefectural_competition(self):
        for cid, comp in sorted(self.repo.competitions.items()):
            if comp.get("competition_type") not in PREFECTURAL:
                continue
            with self.subTest(cid):
                annual = self.factory.build_prefectural(cid, 2027, rng_seed=5)
                self.assertEqual(sorted(self.factory.prefecture_school_ids(cid)),
                                 annual.entrant_school_ids)

    def test_only_union_partners_and_absent_schools_leave(self):
        cid = "CMP000016"  # 東京の秋：連合を外したあと一次予選の組を組み直す
        annual = self.factory.build_prefectural(cid, 2027, rng_seed=5)
        a, b, c, d = annual.entrant_school_ids[:4]
        plan = UnionPlan((JointTeam(a, (a, b, c)),), (d,))
        after = self.factory.arrange_groups(apply_to_annual(annual, plan))
        self.assertEqual(sorted(set(annual.entrant_school_ids) - {b, c, d}), after.entrant_school_ids)
        grouped = [s for ids in after.group_entrant_school_ids.values() for s in ids]
        self.assertEqual(sorted(after.entrant_school_ids), sorted(grouped))

    def test_tokyo_preliminary_groups_follow_team_count(self):
        for count in (150, 230, 280):
            with self.subTest(count):
                teams = self.fake_schools(f"TK{count}", count + 2, "13")
                direct = teams[-2:]
                annual = self.factory.arrange_groups(AnnualCompetitionInput(
                    "CMP000016", 2027, teams, direct_main_entry_school_ids=direct, rng_seed=3))
                sizes = [len(ids) for ids in annual.group_entrant_school_ids.values()]
                self.assertEqual(62, len(sizes))
                self.assertLessEqual(max(sizes) - min(sizes), 1)
                self.assertEqual(count, sum(sizes))
                run = self.run_both(annual)
                self.assertEqual(64, len(run.main_entrant_school_ids))
                self.assertTrue(set(direct) <= set(run.main_entrant_school_ids))

    def test_kanagawa_pools_follow_district_team_count(self):
        cid = "CMP000096"
        stage = self.repo.stage_by_code(cid, "BRANCH_QUALIFIER")
        groups = self.repo.groups_by_stage[stage["stage_id"]]
        quota = sum(self.repo.param(stage["stage_id"], "output_slots", g["stage_group_id"]) for g in groups)
        for delta in (-7, 0, 9):
            with self.subTest(delta):
                pools, entrants = {}, []
                for group in groups:
                    gid = group["stage_group_id"]
                    slots = self.repo.param(stage["stage_id"], "output_slots", gid)
                    pools[gid] = self.fake_schools(f"KN{delta}{gid}", 2 * slots + delta, "14")
                    entrants += pools[gid]
                direct = self.fake_schools(f"KN{delta}D", 1, "14")
                run = self.run_both(AnnualCompetitionInput(
                    cid, 2027, entrants + direct, direct_main_entry_school_ids=direct,
                    rng_seed=3, group_entrant_school_ids=pools))
                self.assertEqual(quota + 1, len(run.main_entrant_school_ids))
                meta = run.stage_executions[0].metadata["group_metadata"]
                for gid, row in meta.items():
                    self.assertTrue(all(size in (3, 4) for size in row["pool_sizes"]), gid)

    def test_chiba_primary_and_repechage_follow_team_count(self):
        for count in (100, 141, 180):
            with self.subTest(count):
                teams = self.fake_schools(f"CB{count}", count + 1, "12")
                run = self.run_both(AnnualCompetitionInput(
                    "CMP000093", 2027, teams, direct_main_entry_school_ids=teams[-1:], rng_seed=3))
                self.assertEqual(48, len(run.main_entrant_school_ids))

    def test_gifu_first_tournament_keeps_second_stage_size(self):
        cid = "CMP000110"
        stage = self.repo.stage_by_code(cid, "SEED_EVENT")
        for extra in (5, 15):
            with self.subTest(extra):
                groups, entrants = {}, []
                for group in self.repo.groups_by_stage[stage["stage_id"]]:
                    gid = group["stage_group_id"]
                    count = 2 * int(group["seed_slots_generated"]) + extra
                    groups[gid] = self.fake_schools(f"GF{extra}{gid}", count, "21")
                    entrants += groups[gid]
                run = self.run_both(AnnualCompetitionInput(
                    cid, 2027, entrants, rng_seed=3, group_entrant_school_ids=groups))
                # 16シード＋1次トーナメントの21校（少なければ不戦勝、多ければ1回戦から）
                self.assertEqual(37, len(run.main_entrant_school_ids))
                self.assertEqual([], run.warnings)


if __name__ == "__main__":
    unittest.main()
