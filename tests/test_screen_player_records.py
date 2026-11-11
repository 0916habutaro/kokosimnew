"""記録の画面の「個人の記録」：規定・上位の並べ方・達成の記録（架空の試合で）。"""
from fractions import Fraction
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.screen.data import GameScreenData

from phase2_engine.screen import player_records as pr


RULE = {"plate_appearances_per_team_game": 3.1, "innings_per_team_game": 1.0}


def batter(school, player, **values):
    return {"school_id": school, "player_id": player, **values}


def pitcher(school, player, **values):
    return {"school_id": school, "player_id": player, **values}


def game(batters=(), pitchers=(), *, day="2030-07-20", winner="S-A", highlights=(), errors=None,
         innings=9):
    """架空の1試合。先攻 S-A・後攻 S-B。"""
    errors = errors or {}
    return {
        "match_date": day, "team1_school_id": "S-A", "team2_school_id": "S-B",
        "team1_score": 1, "team2_score": 0, "winner_id": winner,
        "batter_stats": list(batters), "pitcher_stats": list(pitchers),
        "team_stats": [{"school_id": s, "runs": 0, "hits": 0, "errors": errors.get(s, 0)}
                       for s in ("S-A", "S-B")],
        "highlights": list(highlights),
        "inning_scores": [{"inning": i, "half": h, "batting_team_id": team, "was_played": True,
                           "runs": 0} for i in range(1, innings + 1)
                          for h, team in (("t", "S-A"), ("b", "S-B"))],
    }


def total(**values):
    base = dict.fromkeys(pr.BATTING, 0) | dict.fromkeys(pr.PITCHING, 0) | {"team_games": 0}
    return base | values


class QualifyTests(unittest.TestCase):
    def test_plate_appearances_and_innings_against_team_games(self):
        # 4試合 × 3.1 = 12.4 打席
        self.assertFalse(pr.qualifies(total(plate_appearances=12, team_games=4), "batting", RULE))
        self.assertTrue(pr.qualifies(total(plate_appearances=13, team_games=4), "batting", RULE))
        # 4試合 × 1.0 = 4回 = 12アウト
        self.assertFalse(pr.qualifies(total(outs_recorded=11, team_games=4), "pitching", RULE))
        self.assertTrue(pr.qualifies(total(outs_recorded=12, team_games=4), "pitching", RULE))
        self.assertFalse(pr.qualifies(total(team_games=0), "batting", RULE))


class LeaderTests(unittest.TestCase):
    def test_ties_share_rank_and_counting_stats_skip_zero(self):
        rows = {("S-A", "p1"): total(home_runs=3), ("S-A", "p2"): total(home_runs=5),
                ("S-B", "p3"): total(home_runs=3), ("S-B", "p4"): total(home_runs=0)}
        out = pr.leaders(rows, "home_runs", lower_first=False, limit=20)
        self.assertEqual([(1, "p2"), (2, "p1"), (2, "p3")], [(r["rank"], r["player_id"]) for r in out])

    def test_limit_cuts_ties_and_reports_rest(self):
        rows = {("S-A", f"p{i}"): total(stolen_bases=2 if i else 9) for i in range(6)}
        out = pr.leaders(rows, "stolen_bases", lower_first=False, limit=3)
        self.assertEqual([1, 2, 2], [r["rank"] for r in out])
        self.assertEqual(3, out[-1]["rest"])  # 同率2位の5人のうち2人を出し、残り3人

    def test_rank_beyond_limit_is_not_shown(self):
        rows = {("S-A", "a"): total(rbi=5), ("S-A", "b"): total(rbi=4), ("S-A", "c"): total(rbi=3)}
        self.assertEqual(["a", "b"], [r["player_id"] for r in pr.leaders(rows, "rbi", lower_first=False, limit=2)])

    def test_average_is_exact_and_ties_break_by_at_bats(self):
        rows = {("S-A", "a"): total(hits=1, at_bats=3), ("S-A", "b"): total(hits=2, at_bats=6),
                ("S-A", "c"): total(hits=333, at_bats=1000)}
        out = pr.leaders(rows, "average", lower_first=False, limit=20)
        self.assertEqual(["b", "a", "c"], [r["player_id"] for r in out])
        self.assertEqual([1, 1, 3], [r["rank"] for r in out])
        self.assertEqual(".333", pr.average_label(out[0]["value"]))

    def test_era_lower_first_with_eligibility(self):
        rows = {("S-A", "a"): total(earned_runs=2, outs_recorded=27, team_games=3),
                ("S-A", "b"): total(earned_runs=0, outs_recorded=6, team_games=3),
                ("S-A", "c"): total(earned_runs=1, outs_recorded=27, team_games=3)}
        out = pr.leaders(rows, "era", lower_first=True, limit=20,
                         eligible=lambda ident, t: pr.qualifies(t, "pitching", RULE))
        self.assertEqual(["c", "a"], [r["player_id"] for r in out])
        self.assertEqual(Fraction(1), out[0]["value"])
        self.assertEqual("1.00", pr.era_label(out[0]["value"]))


class FeatTests(unittest.TestCase):
    def tally(self, *games, grade_of=None):
        tally = pr.PlayerTally(year=2030)
        for i, detail in enumerate(games):
            tally.add("CUP", f"M{i}", detail, grade_of)
        return tally

    def test_no_hitter_perfect_and_relay(self):
        clean = pitcher("S-A", "ace", outs_recorded=27, batters_faced=27, strikeouts=12)
        walked = pitcher("S-A", "ace", outs_recorded=27, batters_faced=28, walks=1, strikeouts=9)
        relay = [pitcher("S-A", "ace", outs_recorded=15, batters_faced=15),
                 pitcher("S-A", "sub", outs_recorded=12, batters_faced=12)]
        hit = pitcher("S-A", "ace", outs_recorded=27, batters_faced=28, hits_allowed=1)
        tally = self.tally(game(pitchers=[clean]), game(pitchers=[walked]), game(pitchers=relay),
                           game(pitchers=[hit]),
                           # 味方の失策で出した走者がいれば完全試合ではない
                           game(pitchers=[clean], errors={"S-A": 1}))
        kinds = sorted((f["match_id"], f["kind"]) for f in tally.feats)
        self.assertEqual([("M0", pr.PERFECT), ("M1", pr.NO_HITTER), ("M4", pr.NO_HITTER)], kinds)

    def test_called_game_no_hitter_keeps_outs(self):
        short = pitcher("S-A", "ace", outs_recorded=21, batters_faced=22, walks=1)
        tally = self.tally(game(pitchers=[short], innings=7))
        self.assertEqual(21, tally.feats[0]["outs"])
        self.assertEqual("0奪三振・7回コールド", pr.feat_detail(tally.feats[0]))
        self.assertEqual("9奪三振・延長10回", pr.feat_detail({"kind": pr.NO_HITTER, "value": 9, "outs": 30}))

    def test_cycle_needs_single_double_triple_home_run(self):
        cycle = batter("S-B", "b1", hits=4, doubles=1, triples=1, home_runs=1, at_bats=5)
        no_single = batter("S-B", "b2", hits=3, doubles=1, triples=1, home_runs=1, at_bats=4)
        tally = self.tally(game(batters=[cycle, no_single], winner="S-B"))
        self.assertEqual(["b1"], [f["player_id"] for f in tally.feats if f["kind"] == pr.CYCLE])

    def test_most_strikeouts_in_a_game_and_home_runs_in_a_competition(self):
        tally = self.tally(
            game(pitchers=[pitcher("S-A", "a", strikeouts=14, outs_recorded=27, batters_faced=30, hits_allowed=3)],
                 batters=[batter("S-A", "x", home_runs=2)]),
            game(pitchers=[pitcher("S-B", "b", strikeouts=14, outs_recorded=27, batters_faced=30, hits_allowed=2)],
                 batters=[batter("S-A", "x", home_runs=1), batter("S-B", "y", home_runs=3)]),
        )
        best = pr.most_strikeouts([tally])
        self.assertEqual(14, best[0]["value"])
        self.assertEqual(["a", "b"], [h["player_id"] for h in best[0]["holders"]])
        homers = pr.most_home_runs([tally])
        self.assertEqual([(3, ["x", "y"])], [(r["value"], [h["player_id"] for h in r["holders"]]) for r in homers])

    def test_win_from_scoring_and_blob_round_trip(self):
        highlights = [("S", 1, "t", "x", "single", 1)]
        detail = game(pitchers=[pitcher("S-A", "ace", outs_recorded=27, batters_faced=30, hits_allowed=3,
                                        strikeouts=5),
                                pitcher("S-B", "loser", outs_recorded=24, batters_faced=30, runs_allowed=1,
                                        earned_runs=1, hits_allowed=6)],
                      batters=[batter("S-A", "x", plate_appearances=4, at_bats=4, hits=1, rbi=1)],
                      highlights=highlights)
        tally = self.tally(detail, grade_of=lambda year, school, player, cid: (school, 2))
        again = pr.PlayerTally.from_blob(tally.to_blob())
        merged = pr.merge([again])
        self.assertEqual(1, merged["pitchers"][("S-A", "ace")]["wins"])
        self.assertEqual(0, merged["pitchers"][("S-B", "loser")]["wins"])
        self.assertEqual(1, merged["batters"][("S-A", "x")]["team_games"])
        self.assertEqual(2, again.grades["2030|x"])
        # 同じ試合は2回足さない
        self.assertFalse(tally.add("CUP", "M0", detail))

    def test_march_games_use_the_grade_from_april(self):
        tally = pr.PlayerTally(year=2031)
        tally.add("SPRING", "M1", game(batters=[batter("S-A", "x", plate_appearances=3)], day="2031-03-25"),
                  lambda year, school, player, cid: (school, {2030: 1, 2031: 2}[year]))
        self.assertEqual(2, tally.grades["2031|x"])

    def test_union_players_count_for_their_own_school(self):
        # 連合チームの記録は代表校（S-A）のIDで残る。構成校（S-C）の選手は S-C に数える
        lookup = pr.RosterLookup(partners=lambda cid, school: ["S-C"] if school == "S-A" else [])
        lookup._cache = {(2030, "S-A"): {"a1": ("架空 一郎", 3)}, (2030, "S-C"): {"c1": ("架空 二郎", 2)},
                         (2030, "S-B"): {}}
        tally = pr.PlayerTally(year=2030)
        tally.add("CUP", "M1", game(batters=[batter("S-A", "a1", plate_appearances=4),
                                             batter("S-A", "c1", plate_appearances=4)],
                                    pitchers=[pitcher("S-A", "c1", outs_recorded=27, batters_faced=27)]),
                  lookup.member)
        merged = pr.merge([tally])
        self.assertEqual({("S-A", "a1"), ("S-C", "c1")}, set(merged["batters"]))
        self.assertEqual(1, merged["batters"][("S-C", "c1")]["team_games"])
        self.assertEqual(2, tally.grades["2030|c1"])
        # 達成の記録も自分の学校。相手は試合の相手（S-B）
        self.assertEqual(("S-C", "S-B"), (tally.feats[0]["school_id"], tally.feats[0]["opponent_id"]))

    def test_merge_filters_years_competition_school_and_grade(self):
        first = pr.PlayerTally(year=2030)
        first.add("CUP", "M1", game(batters=[batter("S-A", "x", plate_appearances=4, hits=2),
                                             batter("S-B", "y", plate_appearances=4, hits=1)]),
                  lambda year, school, player, cid: (school, 2))
        first.add("LEAGUE", "M2", game(batters=[batter("S-A", "x", plate_appearances=4, hits=1)]),
                  lambda year, school, player, cid: (school, 2))
        second = pr.PlayerTally(year=2031)
        second.add("CUP", "M1", game(batters=[batter("S-A", "x", plate_appearances=4, hits=3)],
                                     day="2031-07-20"), lambda year, school, player, cid: (school, 3))
        both = [first, second]
        self.assertEqual(6, pr.merge(both)["batters"][("S-A", "x")]["hits"])
        self.assertEqual(3, pr.merge(both)["batters"][("S-A", "x")]["team_games"])
        self.assertEqual(5, pr.merge(both, competition_id="CUP")["batters"][("S-A", "x")]["hits"])
        self.assertEqual(3, pr.merge(both, years={2030})["batters"][("S-A", "x")]["hits"])
        self.assertEqual(3, pr.merge(both, grade=3)["batters"][("S-A", "x")]["hits"])
        self.assertNotIn(("S-B", "y"), pr.merge(both, school_ok=lambda s: s == "S-A")["batters"])


class FilterTests(unittest.TestCase):
    """達成の記録・最多記録も、学年・地域の絞り込みの中で求める。"""

    def setUp(self):
        grades = {"a": 3, "b": 2, "x": 3, "y": 2}
        self.tally = pr.PlayerTally(year=2030)
        member = lambda year, school, player, cid: (school, grades[player])
        # S-A の a（3年）が20奪三振、S-B の b（2年）が10奪三振。サイクルは S-A の x（3年）
        self.tally.add("CUP", "M1", game(
            pitchers=[pitcher("S-A", "a", strikeouts=20, outs_recorded=27, batters_faced=30, hits_allowed=2),
                      pitcher("S-B", "b", strikeouts=10, outs_recorded=24, batters_faced=30, hits_allowed=5)],
            batters=[batter("S-A", "x", hits=5, doubles=1, triples=1, home_runs=2),
                     batter("S-B", "y", hits=1, home_runs=1)]), member)

    def test_grade_filters_feats_and_bests(self):
        self.assertEqual(["x"], [f["player_id"] for f in pr.feats([self.tally], grade=3)])
        self.assertEqual([], pr.feats([self.tally], grade=2))
        self.assertEqual(["y"], [h["player_id"] for h in pr.most_home_runs([self.tally], grade=2)[0]["holders"]])
        self.assertEqual(["b"], [h["player_id"] for h in pr.most_strikeouts([self.tally], grade=2)[0]["holders"]])

    def test_region_keeps_its_own_best_strikeouts(self):
        best = pr.most_strikeouts([self.tally], school_ok=lambda school: school == "S-B")
        self.assertEqual([(10, "b", "M1")], [(r["value"], r["holders"][0]["player_id"], r["holders"][0]["match_id"])
                                             for r in best])
        overall = pr.most_strikeouts([self.tally])
        self.assertEqual(20, overall[0]["value"])
        self.assertEqual("S-B", overall[0]["holders"][0]["opponent_id"])


class ClosedYearTests(unittest.TestCase):
    def test_tally_kept_while_live_is_replaced_by_the_closed_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            first = game(batters=[batter("S-A", "x", plate_appearances=4, hits=1)])
            later = game(batters=[batter("S-A", "x", plate_appearances=4, hits=2)], day="2030-07-21")
            row = SimpleNamespace(match_id="M1", match_date="2030-07-20", status="completed")
            live = SimpleNamespace(year=2030, competitions={"CUP": SimpleNamespace(matches={"M1": row})},
                                   pending_match_details={"CUP:M1": first})
            data = GameScreenData.__new__(GameScreenData)
            data._tallies, data._live_tallies = {}, set()
            data.session = SimpleNamespace(slot_id="s", state=live)
            data.service = SimpleNamespace(_history_archive=lambda slot: archive,
                                           closed_roster=lambda *args: None)
            data._years = lambda: [2030]
            self.assertEqual(1, pr.merge(data.player_tallies().values())["batters"][("S-A", "x")]["hits"])
            # 年度が閉じた：履歴に残した最終の集計（2試合）を読み直す
            archive.store_player_records(2030, pr.build_tally(
                2030, [("CUP", "M1", first), ("CUP", "M2", later)]).to_blob())
            data.session.state = SimpleNamespace(year=2031, competitions={}, pending_match_details={})
            data._years = lambda: [2030, 2031]
            self.assertEqual(3, pr.merge(data.player_tallies().values())["batters"][("S-A", "x")]["hits"])


class PrefectureFilterTests(unittest.TestCase):
    """個人の記録の都道府県は47都道府県のコード（地図の北北海道などのマスでも北海道全体）。"""

    def screen(self):
        from phase2_engine.screen.data import load_screen_config
        root = Path(__file__).resolve().parents[1]
        data = GameScreenData.__new__(GameScreenData)
        data.config = load_screen_config(root / "config")
        data._records_players_memo = {}
        data.player_tallies = lambda: {2030: pr.PlayerTally(year=2030)}
        data._current_year = lambda: 2030
        data.competition_names = lambda cid, name: name
        data.names = lambda sid, *args: sid
        data.session = SimpleNamespace(state=SimpleNamespace(year=2030, seasons={}, rosters=None), slot_id="s")
        data._roster_lookup = lambda *args, **kwargs: None
        data._regions = {"90": "R1", "91": "R1", "92": "R2"}
        data.prefectures = {"90": "架空道", "91": "架空県", "92": "架空都"}
        data.service = SimpleNamespace(repo=SimpleNamespace(data_dir=root / "data", schools={}, competitions={}))
        return data

    def test_prefectures_are_codes(self):
        out = self.screen().records_players({})
        self.assertEqual([["90", "架空道"], ["91", "架空県"], ["92", "架空都"]], out["prefectures"])
        out = self.screen().records_players({"prefecture": "90"})
        self.assertEqual("90", out["filters"]["prefecture"])
        out = self.screen().records_players({"region": "R1"})
        self.assertEqual(["90", "91"], [code for code, _ in out["prefectures"]])


if __name__ == "__main__":
    unittest.main()
