"""秋季・春季の県大会の成績シード：選ぶ元・仮の決まりの校数・予選の成績の順・繰り上げ。

架空の大会と学校（SCHX…）で確かめる。data/ の中身は固定しない。
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from phase2_engine.initial_state import fill_by_lot, initial_autumn_ranking
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


class InitialAutumnRankingTests(unittest.TestCase):
    """最初の年度の春：実際の前年秋の到達点（架空の結果）から順位をつくり、同じ選び方でシードを選ぶ。"""

    def ranking(self, finishes, seed=1):
        known = initial_autumn_ranking(finishes, base_seed=seed, namespace="X")
        return fill_by_lot(known, TEAMS, base_seed=seed, namespace="X")

    def test_known_finishes_come_first_then_the_rest_by_lot(self):
        finishes = ([(TEAMS[10], "champion"), (TEAMS[11], "runner_up")]
                    + [(TEAMS[i], "best4") for i in (12, 13)]
                    + [(TEAMS[i], "best8") for i in (14, 15, 16, 17)])
        ranking = self.ranking(finishes)
        self.assertEqual(TEAMS[10:12], ranking[:2])
        self.assertEqual(set(TEAMS[12:14]), set(ranking[2:4]))
        self.assertEqual(set(TEAMS[14:18]), set(ranking[4:8]))
        self.assertEqual(set(TEAMS), set(ranking))          # 残りは都道府県のほかの学校
        self.assertEqual(ranking, self.ranking(finishes))   # 同じ種なら同じ
        # 16校シード（優勝・準優勝／ベスト4／ベスト8／ベスト16）：ベスト8までは実際の結果、
        # 残りの8校は抽選で埋める
        rules = [rule("S1", 1, 2, kinds="autumn_prefectural", offsets="-1", season="spring"),
                 rule("S2", 3, 4, kinds="autumn_prefectural", offsets="-1", season="spring"),
                 rule("S3", 5, 8, kinds="autumn_prefectural", offsets="-1", season="spring"),
                 rule("S4", 9, 16, kinds="autumn_prefectural", offsets="-1", season="spring")]
        seeds = choose_seeds(rules, {"autumn_prefectural": ranking}, TEAMS,
                             base_seed=1, namespace="CMPX")
        self.assertEqual(16, len(seeds))
        self.assertEqual(set(TEAMS[10:12]), set(seeds[:2]))
        self.assertEqual(set(TEAMS[14:18]), set(seeds[4:8]))
        self.assertEqual(set(ranking[8:16]), set(seeds[8:]))

    def test_an_incomplete_finish_stops_the_known_order(self):
        # ベスト4が1校しか分からない：その学校までを使い、残り（ベスト8の学校も）は抽選
        finishes = [(TEAMS[0], "champion"), (TEAMS[1], "runner_up"), (TEAMS[2], "best4"),
                    (TEAMS[3], "best8")]
        self.assertEqual(TEAMS[:3], initial_autumn_ranking(finishes, base_seed=1, namespace="X"))
        ranking = self.ranking(finishes)
        self.assertEqual(TEAMS[:3], ranking[:3])
        self.assertEqual(set(TEAMS[3:]), set(ranking[3:]))

    def test_game_results_win_over_the_actual_results(self):
        from phase2_engine.initial_state import PriorResults
        from phase2_engine.live_season_planner import LiveSeasonGraphPlanner

        planner = SimpleNamespace(rng_seed=5, year=2026)
        actual = PriorResults(year=2026, autumn_prefectural_finishes={
            "99": ((TEAMS[3], "champion"), (TEAMS[4], "runner_up"))})
        # 最初の年度：分かっている順位だけ持つ（残りはシードを選ぶときに抽選）
        self.assertEqual({"99": tuple(TEAMS[3:5])},
                         LiveSeasonGraphPlanner._prior_autumn_rankings(planner, actual))
        # 2年目からはゲーム内の秋の結果（実際の結果は使わない）
        game = PriorResults(year=2027, autumn_prefectural_rankings={"99": tuple(TEAMS[:20])},
                            autumn_prefectural_finishes=actual.autumn_prefectural_finishes)
        self.assertEqual({"99": tuple(TEAMS[:20])},
                         LiveSeasonGraphPlanner._prior_autumn_rankings(planner, game))
        self.assertEqual({}, LiveSeasonGraphPlanner._prior_autumn_rankings(planner, None))

    def test_season_fills_the_rest_only_for_the_actual_results(self):
        spring = [rule("S1", 1, 2, kinds="autumn_prefectural", offsets="-1", season="spring"),
                  rule("S2", 3, 4, kinds="autumn_prefectural", offsets="-1", season="spring")]
        repo = SimpleNamespace(
            seed_rules=lambda cid: spring,
            competition=lambda cid: {"competition_type": "spring_prefectural", "prefecture_code": "99"},
            schools={sid: {"prefecture_code": "99"} for sid in TEAMS},
        )

        def fake(fill):
            out = SimpleNamespace(repo=repo, annual_templates={}, competitions={}, rng_seed=5,
                                  year=2026, prior_autumn_rankings={"99": tuple(TEAMS[3:5])},
                                  prior_autumn_fill=fill)
            out._seed_prefecture = lambda cid: "99"
            return out

        filled = LiveSeasonDependencyRuntimeState._seed_rankings(fake(True), "CMPX")["autumn_prefectural"]
        self.assertEqual(TEAMS[3:5], list(filled[:2]))
        self.assertEqual(set(TEAMS), set(filled))
        self.assertEqual(filled, LiveSeasonDependencyRuntimeState._seed_rankings(fake(True), "CMPX")["autumn_prefectural"])
        seeds = choose_seeds(spring, {"autumn_prefectural": filled}, TEAMS, base_seed=1, namespace="CMPX")
        self.assertEqual(set(TEAMS[3:5]), set(seeds[:2]))
        self.assertEqual(4, len(seeds))  # 足りない2校は抽選で埋める
        # ゲーム内の結果（2年目から）は埋めない
        self.assertEqual(TEAMS[3:5], list(LiveSeasonDependencyRuntimeState._seed_rankings(
            fake(False), "CMPX")["autumn_prefectural"]))

    def test_csv_finishes_are_read_by_prefecture(self):
        import csv
        import tempfile
        from pathlib import Path
        from phase2_engine.initial_state import PriorResults, load_prior_results

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "initial_state" / "2030" / "prior_results.csv"
            path.parent.mkdir(parents=True)
            fields = ["record_id", "kind", "rule_id", "prefecture_code", "school_id", "achievement"]
            rows = [
                ("autumn_prefectural", "", "99", TEAMS[0], "champion"),
                ("autumn_prefectural", "R1", "99", TEAMS[1], "best4"),
                ("autumn_prefectural", "", "99", TEAMS[1], "runner_up"),   # 良い方を使う
                ("autumn_prefectural", "", "99", "", "best8"),             # 学校IDがない行は使わない
                ("autumn_regional", "", "99", TEAMS[2], "regional_entrant"),
            ]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fields)
                writer.writeheader()
                for n, (kind, rule_id, pcode, sid, ach) in enumerate(rows):
                    writer.writerow(dict(zip(fields, (f"ISR{n}", kind, rule_id, pcode, sid, ach))))
            prior = load_prior_results(tmp, 2030)
        self.assertEqual({"99": ((TEAMS[0], "champion"), (TEAMS[1], "runner_up"))},
                         prior.autumn_prefectural_finishes)
        self.assertFalse(prior.from_game)  # ゲーム内の結果としては扱わない
        self.assertEqual(prior, PriorResults.from_dict(prior.to_dict()))


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
