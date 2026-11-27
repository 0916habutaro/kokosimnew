"""能力ランキングの画面（phase2_engine/screen/ability_rankings.py）。学校はすべて架空。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from phase2_engine.screen import ability_rankings as ar
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]


def team(overall, batting=50.0, pitching=50.0, defense=50.0, running=50.0):
    return {"overall": overall, "batting": batting, "pitching": pitching,
            "defense": defense, "running": running}


class TeamRowTests(unittest.TestCase):
    def test_overall_order_and_ties_by_school_id(self):
        rows = ar.team_rows({"S3": team(60.0), "S1": team(70.0), "S2": team(60.0)})
        self.assertEqual(["S1", "S2", "S3"], [r["school_id"] for r in rows])
        self.assertEqual([1, 2, 3], [r["place"] for r in rows])

    def test_sort_by_batting(self):
        rows = ar.team_rows({"S1": team(70.0, batting=40.0), "S2": team(60.0, batting=65.0)},
                            sort_key="batting")
        self.assertEqual(["S2", "S1"], [r["school_id"] for r in rows])

    def test_schools_without_abilities_are_left_out(self):
        # 部員が9人に満たない学校は能力が None
        rows = ar.team_rows({"S1": team(70.0), "S2": None})
        self.assertEqual(["S1"], [r["school_id"] for r in rows])


class ReputationGapTests(unittest.TestCase):
    def setUp(self):
        # 300校：評判は S000 が1位…、総合は逆に S299 が1位…
        ids = [f"S{i:03d}" for i in range(300)]
        self.reputation = {sid: 300.0 - i for i, sid in enumerate(ids)}
        self.overall = {sid: float(i) for i, sid in enumerate(ids)}
        # 評判100位（S099）を総合10位に、評判10位（S009）を総合300位にする
        self.overall["S099"], self.overall["S290"] = self.overall["S290"], self.overall["S099"]
        self.overall["S009"], self.overall["S000"] = self.overall["S000"], self.overall["S009"]

    def test_dark_horse_and_underperformer(self):
        gap = ar.reputation_gap(self.reputation, self.overall, min_places=50)
        horse = {r["school_id"]: r for r in gap["dark_horse"]}
        self.assertEqual((100, 10, 90), (horse["S099"]["reputation_place"],
                                         horse["S099"]["overall_place"], horse["S099"]["gap"]))
        under = {r["school_id"]: r for r in gap["underperformer"]}
        self.assertEqual((10, 300), (under["S009"]["reputation_place"], under["S009"]["overall_place"]))
        # 差の大きい順
        gaps = [r["gap"] for r in gap["dark_horse"]]
        self.assertEqual(sorted(gaps, reverse=True), gaps)

    def test_small_gap_is_in_neither(self):
        gap = ar.reputation_gap({"S1": 3.0, "S2": 2.0, "S3": 1.0}, {"S1": 1.0, "S2": 2.0, "S3": 3.0},
                                min_places=3)
        self.assertEqual({"dark_horse": [], "underperformer": []}, gap)


class PrefectureStrengthTests(unittest.TestCase):
    def test_average_of_top_n_and_small_prefectures(self):
        overall = {"A1": 70.0, "A2": 60.0, "A3": 10.0, "B1": 50.0}
        prefecture = {"A1": "90", "A2": "90", "A3": "90", "B1": "91"}
        rows = ar.prefecture_strength(overall, prefecture.get, top_n=2)
        self.assertEqual(["90", "91"], [r["prefecture_code"] for r in rows])
        self.assertEqual((65.0, 2, "A1", 70.0), (rows[0]["average"], rows[0]["count"],
                                                 rows[0]["top_school_id"], rows[0]["top_overall"]))
        # 2校に満たない県はある学校だけの平均
        self.assertEqual((50.0, 1), (rows[1]["average"], rows[1]["count"]))


BANDS = [{"grade": "S", "min": 90}, {"grade": "A", "min": 80}, {"grade": "G", "min": 1}]


def grade_of(value):
    return next(band["grade"] for band in BANDS if value >= band["min"])


def player(pid, position="SS", grade=2, overall=60.0, values=None, reasons=()):
    return {"player_id": pid, "position": position, "grade": grade, "overall": overall,
            "values": values or {}, "reasons": list(reasons)}


class PlayerTests(unittest.TestCase):
    def test_overall_is_weighted_average(self):
        weights = {"contact": 0.25, "power": 0.75}
        self.assertEqual(77.5, ar.player_overall({"contact": 70, "power": 80}, weights))
        self.assertEqual(64.8, ar.player_overall({"contact": 50, "power": 72.2}, {"contact": 1, "power": 2}))

    def test_velocity_is_not_in_pitcher_overall(self):
        config = ar.load_config(ROOT / "config")["player_overall"]
        self.assertNotIn("velocity_kmh", config["pitcher"])
        values = {"velocity_kmh": 150, "control": 60, "stamina": 60, "stuff": 60, "strikeout": 60, "groundball": 60}
        self.assertEqual(60.0, ar.player_overall(values, config["pitcher"]))

    def test_position_uses_its_weights(self):
        config = {"batter": {"contact": 1.0}, "pitcher": {"control": 1.0},
                  "by_position": {"C": {"catching": 1.0}, "P": "pitcher"}}
        players = [player("A", "C", values={"contact": 90, "catching": 50}),
                   player("B", "C", values={"contact": 50, "catching": 80}),
                   player("C", "SS", values={"contact": 99, "catching": 99})]
        rows = ar.player_rows(players, position="C", weights=ar.position_weights(config, "C"))
        self.assertEqual([("B", 80.0), ("A", 50.0)], [(r["player_id"], r["score"]) for r in rows])
        self.assertEqual({"control": 1.0}, ar.position_weights(config, "P"))

    def test_kind_and_grade_filters(self):
        players = [player("A", "P", grade=1, overall=70.0), player("B", "SS", grade=1, overall=65.0),
                   player("C", "SS", grade=3, overall=80.0)]
        self.assertEqual(["B"], [r["player_id"] for r in ar.player_rows(players, kind="batter", grade=1)])
        self.assertEqual(["C", "B"], [r["player_id"] for r in ar.player_rows(players, kind="batter")])
        self.assertEqual(["A"], [r["player_id"] for r in ar.player_rows(players, kind="pitcher")])

    def test_featured(self):
        keys = ["contact", "power"]
        self.assertEqual(["prospect"], ar.featured_reasons({"contact": 70}, True, keys, grade_of, "S"))
        self.assertEqual(["power"], ar.featured_reasons({"contact": 85, "power": 92}, False, keys, grade_of, "S"))
        self.assertEqual([], ar.featured_reasons({"contact": 85, "power": 89}, None, keys, grade_of, "S"))
        players = [player("A", reasons=["prospect"]), player("B", reasons=["power"]), player("C")]
        self.assertEqual(["A", "B"], [r["player_id"] for r in ar.player_rows(players, featured=True)])


class ScreenDataTests(unittest.TestCase):
    """画面のデータ（ability_rankings）：計算中・県内の順位・大会の出場校。"""

    def screen(self, abilities, ready=True, competitions=()):
        data = GameScreenData.__new__(GameScreenData)
        data.config_root = ROOT / "config"
        repo = SimpleNamespace(
            schools={"S1": {"prefecture_code": "90"}, "S2": {"prefecture_code": "91"},
                     "S3": {"prefecture_code": "90"}},
            data_dir=ROOT / "data")
        data.service = SimpleNamespace(repo=repo)
        data._regions = {"90": "R1", "91": "R2"}
        data.prefectures = {"90": "架空県", "91": "仮想県"}
        data.names = lambda sid, day="": sid
        data._today_members = lambda: {sid: [] for sid in repo.schools}
        data._current_year = lambda: 2030
        data.abilities = SimpleNamespace(get=lambda members, year: (abilities, ready))
        data._reputation_ranks = lambda: {"S1": "A", "S2": "B", "S3": "C"}
        data._reputation_labels = lambda: ["S", "A", "B", "C"]
        data._ranking_competitions = lambda: [dict(c) for c in competitions]
        return data

    def test_computing(self):
        out = self.screen({}, ready=False).ability_rankings()
        self.assertEqual(("computing", []), (out["status"], out["rows"]))

    def test_prefecture_place_and_national_place(self):
        data = self.screen({"S1": team(60.0), "S2": team(70.0), "S3": team(65.0)})
        out = data.ability_rankings({"prefecture": "90"})
        self.assertEqual([("S3", 1, 2), ("S1", 2, 3)],
                         [(r["school_id"], r["place"], r["national_place"]) for r in out["rows"]])

    def test_competition_entrants_and_undecided(self):
        abilities = {"S1": team(60.0), "S2": team(70.0), "S3": team(65.0)}
        competitions = [
            {"competition_id": "SUMMER", "name": "夏", "decided": False, "entrants": []},
            {"competition_id": "SPRING", "name": "春", "decided": True, "entrants": ["S1", "S3"]},
        ]
        data = self.screen(abilities, competitions=competitions)
        # 既定は出場校の決まっている大会
        out = data.ability_rankings({"team_view": "competition"})
        self.assertEqual("SPRING", out["filters"]["competition_id"])
        self.assertEqual(["S3", "S1"], [r["school_id"] for r in out["rows"]])
        out = data.ability_rankings({"team_view": "competition", "competition_id": "SUMMER"})
        self.assertEqual((False, []), (out["decided"], out["rows"]))


    def test_competition_without_runtime_is_listed_as_undecided(self):
        # 夏の甲子園は予選の結果待ちで、まだ進行の状態がない（season.competitions に入っていない）
        from phase2_engine.tournament_runtime import MainTournamentRuntimeState
        main = MainTournamentRuntimeState.__new__(MainTournamentRuntimeState)
        main.entrant_school_ids = ["S1", "S3"]
        season = SimpleNamespace(annual_templates={"SUMMER": None, "SPRING": None, "LOCAL": None},
                                 competitions={"SPRING": SimpleNamespace(runtime=main)})
        data = self.screen({})
        del data._ranking_competitions
        data._season_of = lambda year: season
        data.competition_names = lambda cid, name: name
        data.service.repo.competitions = {
            "SUMMER": {"competition_type": "national_championship", "competition_name": "夏"},
            "SPRING": {"competition_type": "national_invitational", "competition_name": "春"},
            "LOCAL": {"competition_type": "summer_local_qualifier", "competition_name": "県"},
        }
        self.assertEqual([("SUMMER", False, []), ("SPRING", True, ["S1", "S3"])],
                         [(c["competition_id"], c["decided"], c["entrants"])
                          for c in data._ranking_competitions()])


    def test_switching_saves_drops_player_cache(self):
        data = self.screen({})
        data.service.forget_closed_seasons = lambda: None
        data.names = SimpleNamespace(edits=None)
        data._load_edits = lambda: None
        data._new_abilities = lambda: None
        data._ranking_players_cache = ("前のセーブ", [player("OLD")])
        data.use_session(SimpleNamespace(slot_id="slot01"))
        self.assertIsNone(data._ranking_players_cache)


class PlayerSnapshotCacheTests(unittest.TestCase):
    def test_recovery_step_changes_the_snapshot(self):
        from phase2_engine.screen.school_views import SchoolAbilities
        calls = []
        source = SimpleNamespace(version=1, today="2030-05-01", step=(None, 0))
        source.recovery = lambda p, day: source.step

        def generate(p, year, seed):
            calls.append(source.step)
            return {"fielding": 80 if source.step == (None, 0) else 74}

        abilities = SchoolAbilities.__new__(SchoolAbilities)
        abilities._abilities = SimpleNamespace(source=source, generate=generate)
        abilities._player_cache, abilities._player_version = {}, None
        one = SimpleNamespace(player_id="P1")
        self.assertEqual(80, abilities.player(one, 2030, 1)["fielding"])
        self.assertEqual(80, abilities.player(one, 2030, 1)["fielding"])
        # 怪我から戻った直後の日は、詳細と同じく下がった能力を読み直す
        source.step = ("怪我", 1)
        self.assertEqual(74, abilities.player(one, 2030, 1)["fielding"])
        self.assertEqual(2, len(calls))


if __name__ == "__main__":
    unittest.main()
