"""今日の画面の「今日の見出し」（phase2_engine/screen/headlines.py）。学校・試合はすべて架空。"""
from __future__ import annotations

from pathlib import Path
import unittest

from phase2_engine.screen import headlines as h


ROOT = Path(__file__).resolve().parents[1]
CONFIG = h.load_config(ROOT / "config")
RANKS = ["S", "A", "B", "C", "D", "E"]
NAMES = {"SCH_A": "青葉台", "SCH_B": "緑ヶ丘", "SCH_C": "白波", "SCH_D": "東雲"}


def match(level="local", round_name="2回戦", winner="SCH_A", score=(3, 2), match_id="M1", **extra):
    return {
        "school_year": 2027, "competition_id": "CMP_X", "match_id": match_id,
        "match_date": "2027-07-20", "stage_code": "MAIN", "round_name": round_name,
        "competition_name": "夏・架空大会", "level": level, "ctype": "summer_local_qualifier",
        "team1_id": "SCH_A", "team2_id": "SCH_B",
        "team1_score": score[0], "team2_score": score[1], "winner_id": winner, **extra,
    }


def halves(top, bottom, away="SCH_A", home="SCH_B"):
    """回ごとの点（表＝away、裏＝home）から inning_scores。裏の点が None ならその回の裏はない。"""
    out = []
    for i, (t, b) in enumerate(zip(top, bottom), start=1):
        out.append({"inning": i, "half": "top", "batting_team_id": away, "was_played": True, "runs": t})
        if b is not None:
            out.append({"inning": i, "half": "bottom", "batting_team_id": home, "was_played": True, "runs": b})
    return out


def pitcher(school, player, **stats):
    base = {"school_id": school, "player_id": player, "outs_recorded": 27, "batters_faced": 30,
            "hits_allowed": 5, "runs_allowed": 2, "earned_runs": 2, "walks": 2, "strikeouts": 6,
            "hit_batters": 0, "errors": 0}
    return {**base, **stats}


def batter(school, player, **stats):
    base = {"school_id": school, "player_id": player, "at_bats": 4, "hits": 1, "doubles": 0,
            "triples": 0, "home_runs": 0, "errors": 0}
    return {**base, **stats}


def player(school_id, player_id):
    return ("佐藤 一郎", 3) if player_id == "P1" else ("鈴木 次郎", 2)


def kinds(items):
    return [item["kind"] for item in items]


class GameHeadlineTests(unittest.TestCase):
    def test_no_hitter_and_cycle(self):
        m = match(score=(5, 0))
        detail = {
            "match_date": "2027-07-20",
            "team1_school_id": "SCH_A", "team2_school_id": "SCH_B",
            "winner_id": "SCH_A",
            "pitcher_stats": [pitcher("SCH_A", "P1", hits_allowed=0, runs_allowed=0, earned_runs=0, walks=1,
                                      strikeouts=11),
                              pitcher("SCH_B", "P2")],
            "batter_stats": [batter("SCH_B", "P3", hits=0),
                             batter("SCH_A", "P4", hits=4, doubles=1, triples=1, home_runs=1)],
            "team_stats": [{"school_id": "SCH_A", "errors": 0}, {"school_id": "SCH_B", "errors": 1}],
            "inning_scores": halves([1, 0, 0, 2, 0, 0, 0, 2, 0], [0] * 8 + [None]),
        }
        items = h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)
        self.assertIn("no_hitter", kinds(items))
        self.assertIn("cycle", kinds(items))
        # 同じ投手の奪三振は重ねて出さない
        detail["pitcher_stats"][0]["strikeouts"] = 16
        self.assertNotIn("strikeouts", kinds(h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)))
        no_hitter = next(i for i in items if i["kind"] == "no_hitter")
        self.assertEqual("ノーヒットノーラン", no_hitter["label"])
        self.assertEqual("青葉台・佐藤（3年）、夏・架空大会 2回戦で達成", no_hitter["text"])
        self.assertEqual({"type": "match", "school_year": 2027, "competition_id": "CMP_X", "match_id": "M1"},
                         no_hitter["target"])

    def test_walk_off_and_extra_innings(self):
        # 後攻の緑ヶ丘が9回裏に2点を取ってサヨナラ（全国大会）
        m = match(level="national", winner="SCH_B", score=(3, 4))
        detail = {"inning_scores": halves([1, 0, 0, 2, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 1, 0, 0, 2])}
        items = h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)
        self.assertEqual(["walk_off"], kinds(items))
        self.assertIn("サヨナラ勝ち（4-3）", items[0]["text"])
        # 延長11回（表で勝ち越し）
        m = match(level="regional", score=(5, 3))
        detail = {"last_inning": 11,
                  "inning_scores": halves([0, 0, 1, 0, 0, 0, 0, 2, 0, 0, 2], [0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0])}
        items = h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)
        self.assertEqual(["extra_innings"], kinds(items))
        self.assertIn("延長11回タイブレーク", items[0]["text"])
        # 県大会の序盤のサヨナラは見出しにしない（多すぎる）
        m = match(level="local", winner="SCH_B", score=(3, 4))
        detail = {"inning_scores": halves([1, 0, 0, 2, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 1, 0, 0, 2])}
        self.assertEqual([], h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player))

    def test_comeback(self):
        # 準々決勝なら5点差から、県大会の序盤は8点差から
        detail = {"inning_scores": halves([3, 3, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 2, 2, 3, 0, None])}
        m = match(level="local", round_name="準々決勝", winner="SCH_B", score=(6, 7))
        items = h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)
        self.assertEqual(["comeback"], kinds(items))
        self.assertIn("6点差をひっくり返し", items[0]["text"])
        m = match(level="local", winner="SCH_B", score=(6, 7))
        self.assertEqual([], h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player))
        detail = {"inning_scores": halves([4, 4, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 2, 2, 5, 0, None])}
        m = match(level="local", winner="SCH_B", score=(8, 9))
        self.assertEqual(["comeback"], kinds(h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)))

    def test_upset_depends_on_level_and_round(self):
        def upset(level, win_rank, lose_rank, round_name="2回戦"):
            ranks = {"SCH_A": win_rank, "SCH_B": lose_rank}
            return kinds(h.match_headlines(CONFIG, match(level=level, round_name=round_name),
                                           None, NAMES, ranks, RANKS, player)) == ["upset"]

        # 県大会：2段以上の差でSかAが負けたとき
        items = h.match_headlines(CONFIG, match(), None, NAMES, {"SCH_A": "C", "SCH_B": "S"}, RANKS, player)
        self.assertEqual(["upset"], kinds(items))
        self.assertEqual("評判Cの青葉台、評判Sの緑ヶ丘を破る ― 夏・架空大会 2回戦", items[0]["text"])
        self.assertFalse(upset("local", "A", "S"))
        self.assertFalse(upset("local", "A", "S", round_name="準々決勝"))
        # 甲子園：差1は出さない。差2はSの負けだけ、差3以上はBまで
        self.assertFalse(upset("national", "A", "S"))
        self.assertTrue(upset("national", "B", "S"))
        self.assertFalse(upset("national", "C", "A"))
        self.assertTrue(upset("national", "D", "A"))
        # 地区大会：差1は出さず、差2なら出す
        self.assertFalse(upset("regional", "A", "S"))
        self.assertTrue(upset("regional", "C", "A"))
        # 強い方が勝てば出さない
        self.assertEqual([], h.match_headlines(
            CONFIG, match(level="national", winner="SCH_B", score=(1, 2)), None, NAMES,
            {"SCH_A": "D", "SCH_B": "S"}, RANKS, player))

    def test_records(self):
        m = match(level="regional", score=(21, 0))
        detail = {"pitcher_stats": [pitcher("SCH_A", "P1", strikeouts=16)],
                  "batter_stats": [batter("SCH_A", "P5", hits=3, home_runs=3)]}
        self.assertEqual({"big_score", "strikeouts", "home_runs"},
                         set(kinds(h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player))))
        # 県大会の序盤の大量得点は見出しにしない（奪三振・本塁打は出す）
        self.assertEqual({"strikeouts", "home_runs"},
                         set(kinds(h.match_headlines(CONFIG, match(score=(21, 0)), detail, NAMES, {}, RANKS, player))))

    def test_no_hitter_in_a_called_game_is_not_a_headline(self):
        m = match(score=(10, 0))
        detail = {"winner_id": "SCH_A", "team1_school_id": "SCH_A", "team2_school_id": "SCH_B",
                  "pitcher_stats": [pitcher("SCH_A", "P1", outs_recorded=15, batters_faced=17, hits_allowed=0,
                                            runs_allowed=0, earned_runs=0)],
                  "inning_scores": halves([2, 3, 0, 5, 0], [0, 0, 0, 0, 0])}
        self.assertNotIn("no_hitter", kinds(h.match_headlines(CONFIG, m, detail, NAMES, {}, RANKS, player)))


class KoshienHeadlineTests(unittest.TestCase):
    def test_first_long_gap_and_streak(self):
        self.assertEqual(("first_appearance", None), h.qualify_kind(CONFIG, 0, set(), 2027))
        self.assertEqual(("long_gap", 25), h.qualify_kind(CONFIG, 3, {1990, 2002}, 2027))
        self.assertEqual(("streak", 6), h.qualify_kind(CONFIG, 9, {2001, 2022, 2023, 2024, 2025, 2026}, 2027))
        self.assertEqual(("qualified", None), h.qualify_kind(CONFIG, 4, {2020, 2024}, 2027))
        # 欠けているかもしれない年に届く連続・ぶりは言わない
        self.assertEqual(("qualified", None), h.qualify_kind(CONFIG, 9, {2000}, 2027, uncertain_until=2010))

    def test_texts(self):
        final = match(round_name="決勝")
        first = h.qualify_headline(CONFIG, final, NAMES, "SCH_A", "first_appearance", None, "初出場")
        self.assertEqual("初出場", first["label"])
        self.assertEqual("青葉台、夏の甲子園へ ― 夏・架空大会を制す", first["text"])
        gap = h.qualify_headline(CONFIG, final, NAMES, "SCH_A", "long_gap", 25, "25年ぶり4回目")
        self.assertEqual("25年ぶり", gap["label"])
        self.assertIn("25年ぶり4回目の夏の甲子園へ", gap["text"])

    def test_streak_broken(self):
        self.assertEqual(8, h.koshien_streak(set(range(2019, 2027)), 2027))
        self.assertEqual(0, h.koshien_streak({2020, 2025}, 2027))
        self.assertIsNone(h.koshien_streak({2024, 2025, 2026}, 2027, uncertain_until=2024))
        m = match(winner="SCH_A", round_name="3回戦")
        item = h.streak_broken_headline(CONFIG, m, NAMES, "SCH_B", 8)
        self.assertEqual("途切れる", item["label"])
        self.assertEqual("緑ヶ丘、夏の甲子園の連続出場が8で止まる ― 夏・架空大会 3回戦で青葉台に敗れる", item["text"])
        self.assertEqual({"type": "school", "school_id": "SCH_B"}, item["target"])


class ArrangeTests(unittest.TestCase):
    def test_order_is_by_importance(self):
        ranks = {"SCH_A": "C", "SCH_B": "S"}
        upset = h.upset_headline(CONFIG, match(match_id="M1"), NAMES, ranks, RANKS)
        walk_off = h.headline(CONFIG, "walk_off", "サヨナラ", match(level="national", match_id="M2"))
        no_hitter = h.headline(CONFIG, "no_hitter", "達成", match(match_id="M3"))
        first = h.qualify_headline(CONFIG, match(round_name="決勝", match_id="M4"), NAMES, "SCH_A",
                                   "first_appearance", None, "初出場")
        champion = h.champion_headline(CONFIG, match(level="national", round_name="決勝", match_id="M5"),
                                       NAMES, national=True, nth="初優勝")
        regional = h.champion_headline(CONFIG, match(level="regional", round_name="決勝", match_id="M6"),
                                       NAMES, national=False)
        out = h.arrange(CONFIG, [walk_off, upset, regional, no_hitter, first, champion])
        # その他の中は大会の格の順（全国大会のサヨナラ → 地区大会の優勝）
        self.assertEqual(["national_champion", "first_appearance", "no_hitter", "upset",
                          "walk_off", "regional_champion"], kinds(out["items"]))
        self.assertEqual(6, out["shown"])
        # 同じ順位の中では大会の格・回戦の重さ
        late = h.headline(CONFIG, "walk_off", "x", match(level="national", round_name="準決勝", match_id="M7"))
        early = h.headline(CONFIG, "walk_off", "x", match(level="national", round_name="1回戦", match_id="M8"))
        local = h.headline(CONFIG, "walk_off", "x", match(level="local", round_name="決勝", match_id="M9"))
        self.assertEqual(["M7", "M8", "M9"], [i["target"]["match_id"] for i in
                                              h.arrange(CONFIG, [local, early, late])["items"]])

    def test_more_than_max_lines(self):
        items = [h.headline(CONFIG, "walk_off", f"x{i}", match(match_id=f"M{i}")) for i in range(11)]
        out = h.arrange(CONFIG, items + items[:2])  # 同じ見出しは1つにする
        self.assertEqual(11, len(out["items"]))
        self.assertEqual(CONFIG["max_lines"], out["shown"])
        self.assertEqual(8, out["shown"])


if __name__ == "__main__":
    unittest.main()


class ArchiveReadTests(unittest.TestCase):
    """見出しのために履歴をまとめて読む（その日の試合の成績・学校の試合の事実）。"""

    def test_day_match_stats_and_school_facts(self):
        import sqlite3
        import tempfile
        from contextlib import closing
        from phase2_engine import historical_match_archive as hma

        with tempfile.TemporaryDirectory() as tmp:
            archive = hma.HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            rows = []
            for mid, day, team1, team2 in (("M1", "2027-07-20", "SCH_A", "SCH_B"),
                                           ("M2", "2027-07-20", "SCH_C", "SCH_D"),
                                           ("M3", "2027-07-21", "SCH_A", "SCH_C")):
                payload = {"year": 2027, "competition_id": "CMP_X", "match_id": mid,
                           "team1_score": 3, "team2_score": 1,
                           "pitcher_stats": [pitcher(team1, "P1"), pitcher(team2, "P2")],
                           "inning_scores": halves([1, 0, 2], [0, 1, None], team1, team2),
                           "highlights": [["S", 1, "t", "P1", "single", 1]]}
                raw = hma._canonical(hma.compact_payload(payload))
                rows.append((2027, "CMP_X", mid, day, "stage_date_list", team1, team2, 3, 1,
                             "ability_model_v1", hma._digest(raw), raw))
            with closing(sqlite3.connect(archive.db_path)) as conn, conn:
                conn.executescript(hma._SCHEMA)
                conn.executemany("INSERT INTO historical_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            out = archive.day_match_stats(2027, "2027-07-20", [("CMP_X", "M1"), ("CMP_X", "M3")])
            self.assertEqual([("CMP_X", "M1")], list(out))
            self.assertEqual("P1", out["CMP_X", "M1"]["pitcher_stats"][0]["player_id"])
            self.assertEqual(5, len(out["CMP_X", "M1"]["inning_scores"]))
            self.assertNotIn("highlights", out["CMP_X", "M1"])
            facts = archive.schools_match_facts(["SCH_A", "SCH_C"], "2027-04-01", "2027-07-31")
            self.assertEqual(["M1", "M2", "M3"], sorted(f["match_id"] for f in facts))


class SessionSwitchTests(unittest.TestCase):
    def test_roster_cache_is_dropped_when_switching_saves(self):
        """見出しの選手の名前を引く名簿は、別のセーブに切り替えたら引き直す。"""
        from types import SimpleNamespace
        from phase2_engine.school_edits import SchoolEdits
        from phase2_engine.screen.data import GameScreenData
        from phase2_engine.screen.player_records import RosterLookup

        def session(name):
            state = SimpleNamespace(year=2027, seasons={})
            return SimpleNamespace(state=state, slot_id=name, name=name)

        data = GameScreenData.__new__(GameScreenData)
        data.service = SimpleNamespace(forget_closed_seasons=lambda: None,
                                       school_edits=lambda s: SchoolEdits())
        data.names = SimpleNamespace(edits=None)
        data.config_root = ROOT / "config"
        data.config = {"school_overall_weights": {}}
        data._headline_lookups = {}
        data._roster_lookup = lambda season: RosterLookup(
            closed_roster=lambda year, school, slot=data.session.slot_id: [
                {"player_id": "P1", "display_name": f"{slot} 太郎", "academic_year": 3}])
        data._new_abilities = lambda: None
        game = match()
        data.session = session("前のセーブ")
        self.assertEqual(("前のセーブ 太郎", 3), data._headline_player(game)("SCH_A", "P1"))
        data.use_session(session("次のセーブ"))
        self.assertEqual(("次のセーブ 太郎", 3), data._headline_player(game)("SCH_A", "P1"))
