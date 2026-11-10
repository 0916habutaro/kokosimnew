"""秋季・春季の県大会の成績シード：選ぶ元・仮の決まりの校数・予選の成績の順・繰り上げ。

架空の大会と学校（SCHX…）で確かめる。data/ の中身は固定しない。
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from phase2_engine.live_season_dependency import LiveSeasonDependencyRuntimeState
from phase2_engine.models import AnnualCompetitionInput, Match
from phase2_engine.seed_draw import (
    choose_seeds, chooses_after_prelim, game_seed_rules, main_seeds_after_prelim,
    merge_rankings, prelim_order, seed_sources, seed_total,
)

TEAMS = [f"SCHX{i:03d}" for i in range(40)]
FALLBACK = {"large_min_main_entrants": 32, "large_seed_count": 8, "small_seed_count": 4}


def rule(rule_id, low, high, *, selector="finish_rank", kinds="summer_local_qualifier",
         offsets="0", method="random_within_tier", season="autumn"):
    return {
        "seed_rule_id": rule_id, "season_segment": season,
        "source_competition_type": kinds, "source_year_offset": offsets,
        "source_result_selector": selector, "seed_assignment_method": method,
        "source_rank_from": str(low), "source_rank_to": str(high),
        "seed_count": str(high - low + 1),
    }


def fallback_rules(**kw):
    return [rule("F1", 1, 2, method="main_size_fallback", **kw),
            rule("F2", 3, 4, method="main_size_fallback", **kw),
            rule("F3", 5, 8, method="main_size_fallback", **kw)]


def match(winner, loser, n):
    return Match(match_id=f"M{n}", competition_id="CMPX", stage_id="STGX",
                 stage_code="BRANCH_QUALIFIER", phase_code="", round_no=1,
                 team1=winner, team2=loser, winner=winner, loser=loser)


class FallbackCountTests(unittest.TestCase):
    """仮の決まり：本大会の出場校が32校以上なら8校、32校未満なら4校。"""

    def test_count_follows_the_main_entrants(self):
        rules = fallback_rules()
        self.assertEqual(8, seed_total(rules, 32, FALLBACK))
        self.assertEqual(4, seed_total(rules, 31, FALLBACK))
        self.assertIsNone(seed_total([rule("R1", 1, 4)], 10, FALLBACK))
        summer = TEAMS[:20]
        big = choose_seeds(rules, {"summer_local_qualifier": summer}, TEAMS[:32],
                           base_seed=1, namespace="CMPX", fallback=FALLBACK)
        small = choose_seeds(rules, {"summer_local_qualifier": summer}, TEAMS[:31],
                             base_seed=1, namespace="CMPX", fallback=FALLBACK)
        self.assertEqual(set(summer[:8]), set(big))
        self.assertEqual(set(summer[:4]), set(small))
        self.assertEqual(set(summer[:2]), set(small[:2]))  # 階級の順

    def test_spring_uses_the_previous_autumn(self):
        rules = fallback_rules(kinds="autumn_prefectural", offsets="-1", season="spring")
        self.assertEqual([("autumn_prefectural", -1)], seed_sources(rules))
        autumn = TEAMS[5:25]
        seeds = choose_seeds(rules, {"autumn_prefectural": autumn}, TEAMS[:20],
                             base_seed=1, namespace="CMPX", fallback=FALLBACK)
        # 出場校20校（32校未満）で4校。前年秋の上位のうち春の大会に出る学校から
        self.assertEqual(set(autumn[:4]), set(seeds))
        # 前年秋の結果がない最初の年度はシードなし
        self.assertEqual([], choose_seeds(rules, {}, TEAMS, base_seed=1, namespace="CMPX",
                                          fallback=FALLBACK))


class PrelimOrderTests(unittest.TestCase):
    """秋の支部・地区予選の順位：免除の学校が先、次に負けの少ない順、同じなら夏の順位。"""

    def test_exempt_then_fewer_losses_then_summer(self):
        a, b, c, d, e, f, x = TEAMS[:7]
        main = [a, b, c, d, e, f]
        matches = [match(b, x, 1), match(c, x, 2), match(d, b, 3), match(e, c, 4),
                   match(e, f, 5), match(f, x, 6), match(f, c, 7)]
        # a は予選免除、d・e は無敗（e は夏の順位が上）、b・f は1敗（b が上）、c は2敗
        order = prelim_order(main, matches, tiebreak=[e, b, f, d],
                             base_seed=1, namespace="CMPX")
        self.assertEqual([a, e, d, b, f, c], order)

    def test_seeds_are_chosen_from_main_entrants_after_the_prelim(self):
        rules = [rule("P1", 1, 2, selector="stage_rank",
                      kinds="prelim_stage;summer_local_qualifier", offsets="0;0"),
                 rule("P2", 3, 4, selector="stage_rank",
                      kinds="prelim_stage;summer_local_qualifier", offsets="0;0")]
        self.assertEqual([("summer_local_qualifier", 0)], seed_sources(rules))
        repo = SimpleNamespace(seed_rules=lambda cid: rules,
                               stages=lambda cid: [{"stage_code": "BRANCH_QUALIFIER"},
                                                   {"stage_code": "MAIN"}])
        self.assertTrue(chooses_after_prelim(repo, "CMPX"))
        main = TEAMS[:8]
        losers = TEAMS[20:28]
        matches = [match(w, l, n) for n, (w, l) in enumerate(zip(main, losers))]
        matches.append(match(main[0], main[7], 99))   # main[7] は1敗して勝ち上がった
        annual = AnnualCompetitionInput(
            competition_id="CMPX", year=2027, entrant_school_ids=main + losers, rng_seed=3,
            main_seed_after_prelim=True,
            main_seed_rankings={"summer_local_qualifier": [losers[0], main[5], main[6], main[2]]},
        )
        seeds = main_seeds_after_prelim(repo, annual, main, matches)
        # 夏の順位の上の学校（予選で負けた losers[0] は本大会にいない）が無敗の中で上
        self.assertEqual({main[5], main[6]}, set(seeds[:2]))
        self.assertEqual(4, len(seeds))
        self.assertNotIn(main[7], seeds)
        self.assertTrue(set(seeds) <= set(main))


class MixedSourceTests(unittest.TestCase):
    def test_two_sources_skip_schools_taken_by_the_other(self):
        # 岐阜の春の形：前年秋の上位4校＋地区予選の上位4校。同じ学校は繰り上げる
        rules = [rule("A1", 1, 4, kinds="autumn_prefectural", offsets="-1", season="spring"),
                 rule("B1", 1, 4, selector="stage_rank", kinds="prelim_stage;autumn_prefectural",
                      offsets="0;-1", season="spring")]
        autumn = TEAMS[:10]
        stage = [TEAMS[1], TEAMS[20], TEAMS[2], TEAMS[21], TEAMS[22], TEAMS[23]]
        seeds = choose_seeds(rules, {"autumn_prefectural": autumn, "prelim_stage": stage},
                             TEAMS, base_seed=1, namespace="CMPX")
        self.assertEqual(set(autumn[:4]), set(seeds[:4]))
        self.assertEqual(set(TEAMS[20:24]), set(seeds[4:]))


class MergeTests(unittest.TestCase):
    def test_two_summer_tournaments_are_merged_by_finish(self):
        north = ["N1", "N2", "N3", "N4"]
        south = ["S1", "S2", "S3", "S4"]
        merged = merge_rankings([north, south])
        self.assertEqual({"N1", "S1"}, set(merged[:2]))
        self.assertEqual({"N2", "S2"}, set(merged[2:4]))


class LiveFallbackTests(unittest.TestCase):
    """年度の進行：本大会だけの大会は大会を始めるときに、予選のある大会は本大会を組むときに選ぶ。"""

    def state(self, rules, stages, complete=True):
        summer = SimpleNamespace(
            is_complete=complete,
            to_competition_run=lambda: SimpleNamespace(
                outcome=SimpleNamespace(final_ranking_school_ids=TEAMS[:20])),
        )
        competitions = {
            "CMPS": {"competition_type": "summer_local_qualifier", "prefecture_code": "99"},
            "CMPX": {"competition_type": "autumn_prefectural", "prefecture_code": "99"},
        }
        repo = SimpleNamespace(
            competition=lambda cid: competitions[cid],
            seed_rules=lambda cid: rules if cid == "CMPX" else [],
            stages=lambda cid: stages,
        )
        fake = SimpleNamespace(
            repo=repo, annual_templates={"CMPS": None, "CMPX": None},
            competitions={"CMPS": summer}, prior_autumn_rankings={}, seed_pending=set(),
        )
        fake._seed_prefecture = lambda cid: competitions[cid]["prefecture_code"]
        fake._seed_rankings = lambda cid: LiveSeasonDependencyRuntimeState._seed_rankings(fake, cid)
        return fake

    def annual(self, entrants):
        return AnnualCompetitionInput(competition_id="CMPX", year=2027,
                                      entrant_school_ids=list(entrants), rng_seed=9)

    def test_main_only_competition_picks_from_the_summer(self):
        fake = self.state(fallback_rules(), [{"stage_code": "MAIN"}])
        annual = LiveSeasonDependencyRuntimeState._with_result_seeds(fake, "CMPX", self.annual(TEAMS[:30]))
        self.assertEqual(set(TEAMS[:4]), set(annual.main_seed_school_ids))  # 30校なので4校
        # 連合で出なくなった学校の代わりは次の順位
        after = self.annual([s for s in TEAMS[:30] if s != TEAMS[1]])
        refreshed = LiveSeasonDependencyRuntimeState._with_result_seeds(fake, "CMPX", after, refresh=True)
        self.assertEqual(set(TEAMS[:5]) - {TEAMS[1]}, set(refreshed.main_seed_school_ids))

    def test_prelim_competition_waits_for_the_main_draw(self):
        rules = fallback_rules(selector="stage_rank", kinds="prelim_stage;summer_local_qualifier",
                               offsets="0;0")
        stages = [{"stage_code": "BRANCH_QUALIFIER"}, {"stage_code": "MAIN"}]
        fake = self.state(rules, stages, complete=False)
        annual = LiveSeasonDependencyRuntimeState._with_result_seeds(fake, "CMPX", self.annual(TEAMS))
        self.assertTrue(annual.main_seed_after_prelim)
        self.assertEqual([], annual.main_seed_school_ids)
        self.assertEqual({"CMPX"}, fake.seed_pending)   # 夏が終わったら順位を入れる
        fake.competitions["CMPS"].is_complete = True
        annual = LiveSeasonDependencyRuntimeState._with_result_seeds(fake, "CMPX", self.annual(TEAMS))
        self.assertEqual(TEAMS[:20], annual.main_seed_rankings["summer_local_qualifier"])
        self.assertEqual(set(), fake.seed_pending)

    def test_zero_seed_rows_are_ignored(self):
        zero = dict(rule("Z", 1, 1), seed_count="0", source_rank_from="", source_rank_to="")
        repo = SimpleNamespace(seed_rules=lambda cid: [zero])
        self.assertEqual([], game_seed_rules(repo, "CMPX"))


if __name__ == "__main__":
    unittest.main()
