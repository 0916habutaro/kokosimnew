"""年度の重なり（game_definition.md §8）。

秋の大会の後に翌年度の大会表をつくり、3月は前の年度の選抜と新しい年度の
春季県大会を同じ日付で進める。年度末（3月31日）を進めたら前の年度を閉じる。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.career_state import CareerState, autumn_end
from phase2_engine.prior_season import invitational_entrants


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def _school_days(seasons):
    days = defaultdict(set)
    for year, state in seasons.items():
        for row in state.completed_results().values():
            for team in (row["team1_id"], row["team2_id"]):
                days[(team, row["match_date"])].add(
                    (year, row["competition_id"], row["match_id"])
                )
    return days


class CareerOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = cls.repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name,
            autosave_after_action=False,
        )
        cls.session = cls.service.new_game("career", rng_seed=20261021)
        cls.state = cls.session.state
        cls.autumn_end_2026 = autumn_end(cls.state.seasons[2026])
        cls.service.advance_through(cls.session, "2027-03-25")
        cls.overlap_seasons = dict(cls.state.seasons)
        cls.overlap_plans = dict(cls.state.plans)
        cls.service.save_game(cls.session)
        cls.loaded = cls.service.load_game("career")
        cls.service.advance_through(cls.session, "2027-04-02")
        cls.service.advance_through(cls.loaded, "2027-04-02")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_next_season_opens_after_autumn(self):
        self.assertIsInstance(self.state, CareerState)
        self.assertEqual([2026, 2027], sorted(self.overlap_seasons))
        opened = self.overlap_seasons[2027].start_date
        self.assertEqual(
            self.autumn_end_2026.toordinal() + 1, opened.toordinal()
        )
        self.assertLess(opened, date(2027, 4, 1))

    def test_march_games_of_both_seasons_share_the_calendar(self):
        march = [
            row for row in self.overlap_seasons[2027].completed_results().values()
            if row["match_date"] < "2027-04-01"
        ]
        self.assertTrue(march)
        senbatsu = [
            row for row in self.overlap_seasons[2026].completed_results().values()
            if row["competition_id"] == "CMP000001"
        ]
        self.assertTrue(senbatsu)
        self.assertTrue(all(r["match_date"].startswith("2027-03") for r in senbatsu))

    def test_senbatsu_is_selected_from_autumn_regionals(self):
        state = self.overlap_seasons[2026]
        entrants = state.competitions[
            "CMP000001"
        ].to_competition_run().entrant_school_ids
        # 地区ごとの枠＋関東・東京の比較枠＋神宮枠＋21世紀枠
        self.assertEqual(32, len(entrants))
        # 21世紀枠（最後の2校）は公立校で、秋の県大会でベスト8以上
        top8 = {
            sid
            for cid, scheduled in state.competitions.items()
            if self.repo.competitions[cid]["competition_type"]
            in ("autumn_prefectural", "autumn_regional")
            for sid in scheduled.to_competition_run()
            .outcome.final_ranking_school_ids[:8]
        }
        for school_id in entrants[-2:]:
            self.assertIn(
                self.repo.schools[school_id]["ownership_type"],
                ("prefectural", "municipal"),
            )
            self.assertIn(school_id, top8)
        self.assertEqual(32, len(set(entrants)))
        kinki = state.competitions[
            "CMP000019"
        ].to_competition_run().outcome.final_ranking_school_ids
        self.assertTrue(set(kinki[:6]) <= set(entrants))
        # 神宮枠はその年の神宮大会の優勝校の地区に付く
        jingu = state.competitions[
            "CMP000003"
        ].to_competition_run().outcome.final_ranking_school_ids
        selection = next(
            item for item in state.history
            if item["action"] == "select_invitational"
        )
        self.assertEqual(jingu[0], selection["jingu_champion_school_id"])
        self.assertIn(jingu[0], entrants)

    def test_next_spring_uses_previous_season_results(self):
        previous = self.overlap_seasons[2026]
        senbatsu = set(invitational_entrants(previous))
        plan = self.overlap_plans[2027]
        prior = plan.prior_results
        autumn_rankings = {
            tuple(
                scheduled.to_competition_run()
                .outcome.final_ranking_school_ids
            )
            for cid, scheduled in previous.competitions.items()
            if self.repo.competitions[cid]["competition_type"]
            in ("autumn_prefectural", "autumn_regional")
        }
        for pcode, ranking in prior.autumn_prefectural_rankings.items():
            self.assertIn(ranking, autumn_rankings)
            self.assertEqual(
                pcode, self.repo.schools[ranking[0]]["prefecture_code"]
            )
        rows = [
            row for row in plan.external_bootstrap_resolutions
            if row.source_event_kind in (
                "national_invitational",
                "autumn_prefectural",
                "autumn_regional",
            )
        ]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual("PASS", row.status, row.access_rule_id)
            self.assertEqual(
                "previous_season_result", row.resolution_source
            )
            if row.source_event_kind == "national_invitational":
                self.assertTrue(set(row.resolved_school_ids) <= senbatsu)
            if row.source_event_kind == "autumn_prefectural":
                pcode = self.repo.competitions[
                    row.destination_competition_id
                ]["prefecture_code"]
                ranking = prior.autumn_prefectural_rankings[pcode]
                self.assertEqual(
                    list(ranking[:len(row.resolved_school_ids)]),
                    list(row.resolved_school_ids),
                )
        self.assertEqual(
            sorted(senbatsu),
            sorted(plan.prior_invitational_entrant_ids),
        )

    def test_no_school_plays_two_competitions_on_one_day(self):
        days = _school_days(self.overlap_seasons)
        doubles = {key: games for key, games in days.items() if len(games) > 1}
        across = [
            games for games in doubles.values()
            if len({(year, cid) for year, cid, _ in games}) > 1
        ]
        self.assertEqual([], across)
        # 日程が地区ごとの日をまとめたものしかない大会だけ、わずかに残る
        self.assertLess(len(doubles), 30)

    def test_previous_season_closes_on_april_first(self):
        self.assertEqual([2027], sorted(self.state.seasons))
        self.assertEqual(2027, self.session.plan.year)
        years = {
            row["year"]: row for row in self.service.career_history_years("career")
        }
        self.assertEqual("sealed", years[2026]["status"])
        self.assertEqual("active", years[2027]["status"])

    def test_save_during_overlap_restores_both_seasons(self):
        self.assertEqual([2027], sorted(self.loaded.state.seasons))
        self.assertEqual(
            self.state.seasons[2027].completed_results(),
            self.loaded.state.seasons[2027].completed_results(),
        )

    def test_save_after_previous_season_closed(self):
        # 前の年度を閉じた後も、セーブに残した前の年度の結果から
        # 同じ大会表をつくり直せる
        self.service.save_game(self.loaded)
        again = self.service.load_game("career")
        self.assertEqual([2027], sorted(again.state.seasons))
        self.assertIsNotNone(again.plan.prior_results)
        self.assertEqual(
            self.loaded.state.completed_results(),
            again.state.completed_results(),
        )


if __name__ == "__main__":
    unittest.main()
