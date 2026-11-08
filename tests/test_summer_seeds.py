"""夏の地方大会の成績シード：選び方・ブロックへの分け方・不戦勝・途中の抽選・連合の扱い。

架空の大会と学校（SCHX…）で確かめる。data/ の中身は固定しない。
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from phase2_engine.live_season_dependency import LiveSeasonDependencyRuntimeState
from phase2_engine.main_tournament import generate_main_slots
from phase2_engine.models import AnnualCompetitionInput
from phase2_engine.seed_draw import (
    choose_seeds, policy_redraw_rounds, policy_seed_bye_count, seed_sources,
)
from phase2_engine.tournament_runtime import MainTournamentRuntimeState


def rule(rule_id, low, high, selector="finish_rank", kinds="spring_prefectural", offsets="0"):
    return {
        "seed_rule_id": rule_id, "season_segment": "summer",
        "source_competition_type": kinds, "source_year_offset": offsets,
        "source_result_selector": selector,
        "source_rank_from": str(low), "source_rank_to": str(high),
        "seed_count": str(high - low + 1),
    }


TIERS_8 = [rule("R1", 1, 2), rule("R2", 3, 4), rule("R3", 5, 8)]
TEAMS = [f"SCHX{i:03d}" for i in range(40)]


def play_all(runtime) -> None:
    while not runtime.is_complete:
        for row in runtime.ready_matches():
            runtime.resolve_match(row["match_id"])


class ChooseSeedsTests(unittest.TestCase):
    def test_tiers_follow_the_spring_finish_and_shuffle_inside(self):
        spring = TEAMS[:20]
        seeds = choose_seeds(TIERS_8, {"spring_prefectural": spring}, TEAMS,
                             base_seed=1, namespace="CMPX")
        self.assertEqual(set(spring[:2]), set(seeds[:2]))
        self.assertEqual(set(spring[2:4]), set(seeds[2:4]))
        self.assertEqual(set(spring[4:8]), set(seeds[4:8]))
        orders = {tuple(choose_seeds(TIERS_8, {"spring_prefectural": spring}, TEAMS,
                                     base_seed=s, namespace="CMPX")[4:8]) for s in range(10)}
        self.assertGreater(len(orders), 1)  # 同じ階級の中は抽選

    def test_only_schools_in_the_summer_competition_count(self):
        # 東京の東西のように、春の順位から夏の大会に出る学校だけで数える。
        # 連合の代表校でなくなった・出ない学校の代わりは次の順位の学校
        spring = TEAMS[:20]
        eligible = [s for s in TEAMS if s not in (spring[0], spring[5])]
        seeds = choose_seeds(TIERS_8, {"spring_prefectural": spring}, eligible,
                             base_seed=1, namespace="CMPX")
        self.assertEqual(8, len(seeds))
        self.assertNotIn(spring[0], seeds)
        self.assertEqual(set(spring[1:3]), set(seeds[:2]))
        self.assertIn(spring[9], seeds)

    def test_fewer_candidates_than_seeds(self):
        seeds = choose_seeds(TIERS_8, {"spring_prefectural": TEAMS[:5]}, TEAMS,
                             base_seed=1, namespace="CMPX")
        self.assertEqual(set(TEAMS[:5]), set(seeds))
        self.assertEqual([], choose_seeds(TIERS_8, {}, TEAMS, base_seed=1, namespace="CMPX"))

    def test_points_add_autumn_and_spring(self):
        rules = [rule("P1", 1, 2, "points_rank", "autumn_prefectural;spring_prefectural", "-1;0"),
                 rule("P2", 3, 4, "points_rank", "autumn_prefectural;spring_prefectural", "-1;0")]
        self.assertEqual([("autumn_prefectural", -1), ("spring_prefectural", 0)], seed_sources(rules))
        config = {"points_by_best": {"1": 10, "2": 8, "4": 6, "8": 4},
                  "source_weights": {"autumn_prefectural": 1, "spring_prefectural": 1}}
        a, b, c, d, e = TEAMS[:5]
        autumn = [a, c, d, e]      # 秋：a優勝10・c準優勝8・d,eベスト4 6
        spring = [b, d, a, e]      # 春：b優勝10・d準優勝8・a,eベスト4 6
        seeds = choose_seeds(rules, {"autumn_prefectural": autumn, "spring_prefectural": spring},
                             TEAMS, base_seed=1, namespace="CMPX", config=config)
        # a=16, d=14, e=12, b=10, c=8
        self.assertEqual({a, d}, set(seeds[:2]))
        self.assertEqual({e, b}, set(seeds[2:4]))
        # 秋の結果がない年度（最初の年度）は春だけ
        spring_only = choose_seeds(rules, {"spring_prefectural": spring}, TEAMS,
                                   base_seed=1, namespace="CMPX", config=config)
        self.assertEqual({b, d}, set(spring_only[:2]))


class SeedPlacementTests(unittest.TestCase):
    def test_seeds_go_to_separate_blocks(self):
        seeds = TEAMS[:8]
        slots, seed_slots = generate_main_slots(TEAMS, seed_ids=seeds, base_seed=3, namespace="x")
        self.assertEqual(64, len(slots))
        blocks = {(seed_slots[s] - 1) // 8 for s in seeds}
        self.assertEqual(8, len(blocks))  # 8校は準々決勝まで当たらない
        self.assertNotEqual((seed_slots[seeds[0]] - 1) // 32, (seed_slots[seeds[1]] - 1) // 32)

    def test_seed_bye_count_keeps_lower_seeds_in_the_first_round(self):
        seeds = TEAMS[:8]

        def opponents(slots, seed_slots):
            return {s: slots[seed_slots[s] - 1 ^ 1] for s in seeds}

        slots, seed_slots = generate_main_slots(TEAMS, seed_ids=seeds, base_seed=3, namespace="x")
        self.assertTrue(all(v == "" for v in opponents(slots, seed_slots).values()))
        slots, seed_slots = generate_main_slots(TEAMS, seed_ids=seeds, base_seed=3, namespace="x",
                                                seed_bye_count=2)
        found = opponents(slots, seed_slots)
        self.assertEqual("", found[seeds[0]])
        self.assertEqual("", found[seeds[1]])
        self.assertTrue(all(found[s] for s in seeds[2:]))
        slots, seed_slots = generate_main_slots(TEAMS, seed_ids=seeds, base_seed=3, namespace="x",
                                                seed_bye_count=0)
        self.assertTrue(all(opponents(slots, seed_slots).values()))
        self.assertEqual(sorted(TEAMS), sorted(s for s in slots if s))


class RedrawPolicyTests(unittest.TestCase):
    def repo(self, redraw="", bye=""):
        policy = {"redraw_rounds": redraw, "seed_bye_count": bye}
        return SimpleNamespace(bracket_policies={("CMPX", "MAIN"): policy})

    def test_policy_parsing(self):
        self.assertEqual({4: 1}, policy_redraw_rounds(self.repo("QF:1"), "CMPX", 6))
        self.assertEqual({5: 2, 6: 2}, policy_redraw_rounds(self.repo("R5:2;QF:2"), "CMPX", 8))
        self.assertEqual({}, policy_redraw_rounds(self.repo(), "CMPX", 6))
        self.assertEqual({}, policy_redraw_rounds(SimpleNamespace(), "CMPX", 6))
        self.assertIsNone(policy_seed_bye_count(self.repo(), "CMPX"))
        self.assertEqual(0, policy_seed_bye_count(self.repo(bye="0"), "CMPX"))

    def test_rounds_after_the_redraw_are_drawn_from_the_winners(self):
        teams = TEAMS[:32]
        runtime = MainTournamentRuntimeState.create(
            competition_id="CMPX", reference_year=2026, generation_seed=5, stage_id="STGX",
            entrants=teams, annual_seed_order=teams[:8],
            redraw_rounds=policy_redraw_rounds(self.repo("R4:2"), "CMPX", 5),
        )
        while not all(runtime.matches[m].status == "completed" for m in runtime.match_ids_by_round[3]):
            self.assertFalse(runtime.is_drawn(4))
            row = next(r for r in runtime.ready_matches() if r["round_no"] <= 3)
            runtime.resolve_match(row["match_id"])
        third = [runtime.matches[m].winner for m in runtime.match_ids_by_round[3]]
        top = runtime.match_ids_by_round[4][:1]
        # 上下の半分ごとに抽選：上の半分の勝者どうしが上の試合
        self.assertEqual(set(third[:2]), {runtime.matches[top[0]].team1, runtime.matches[top[0]].team2})
        play_all(runtime)
        self.assertTrue(runtime.champion_school_id)


class LiveSeedTests(unittest.TestCase):
    """年度の進行に組み込む部分（春季県大会が終わるまではシードなしでつくり、終わったら選ぶ）。"""

    def state(self, complete: bool):
        spring = SimpleNamespace(
            is_complete=complete,
            to_competition_run=lambda: SimpleNamespace(
                outcome=SimpleNamespace(final_ranking_school_ids=TEAMS[:20])),
        )
        competitions = {
            "CMPS": {"competition_type": "spring_prefectural", "prefecture_code": "99"},
            "CMPX": {"competition_type": "summer_local_qualifier", "prefecture_code": "99"},
        }
        repo = SimpleNamespace(
            competition=lambda cid: competitions[cid],
            seed_rules=lambda cid: TIERS_8 if cid == "CMPX" else [],
        )
        fake = SimpleNamespace(
            repo=repo, annual_templates={"CMPS": None, "CMPX": None},
            competitions={"CMPS": spring}, prior_autumn_rankings={}, seed_pending=set(),
        )
        fake._summer_seed_rankings = lambda cid: LiveSeasonDependencyRuntimeState._summer_seed_rankings(fake, cid)
        return fake

    def annual(self, entrants=TEAMS):
        return AnnualCompetitionInput(competition_id="CMPX", year=2027, entrant_school_ids=list(entrants),
                                      rng_seed=9)

    def test_waits_for_the_spring_result(self):
        fake = self.state(complete=False)
        annual = LiveSeasonDependencyRuntimeState._with_summer_seeds(fake, "CMPX", self.annual())
        self.assertEqual([], annual.main_seed_school_ids)
        self.assertEqual({"CMPX"}, fake.seed_pending)
        fake.competitions["CMPS"].is_complete = True
        annual = LiveSeasonDependencyRuntimeState._with_summer_seeds(fake, "CMPX", self.annual())
        self.assertEqual(set(TEAMS[:8]), set(annual.main_seed_school_ids))
        self.assertEqual(set(), fake.seed_pending)

    def test_seeds_lost_to_unions_are_replaced_by_the_next_rank(self):
        fake = self.state(complete=True)
        seeded = LiveSeasonDependencyRuntimeState._with_summer_seeds(fake, "CMPX", self.annual())
        # 連合の組み直し後（代表校は元の枠のまま。TEAMS[3] は部員がいなくて出ない）
        after_union = self.annual([s for s in TEAMS if s != TEAMS[3]])
        after_union.main_seed_school_ids = [s for s in seeded.main_seed_school_ids if s != TEAMS[3]]
        refreshed = LiveSeasonDependencyRuntimeState._with_summer_seeds(
            fake, "CMPX", after_union, refresh=True)
        self.assertEqual(8, len(refreshed.main_seed_school_ids))
        self.assertNotIn(TEAMS[3], refreshed.main_seed_school_ids)
        self.assertIn(TEAMS[8], refreshed.main_seed_school_ids)
        # シード校が残る大会は同じ並び（抽選の結果が変わらない）
        same = LiveSeasonDependencyRuntimeState._with_summer_seeds(
            fake, "CMPX", seeded, refresh=True)
        self.assertEqual(seeded.main_seed_school_ids, same.main_seed_school_ids)


if __name__ == "__main__":
    unittest.main()
