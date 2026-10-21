"""2027年度以降の大会表を2026年の大会からつくる（game_definition.md §8）。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import unittest

from phase2_engine import DataRepository
from phase2_engine.live_season_planner import LiveSeasonGraphPlanner
from phase2_engine.school_year import in_school_year
from phase2_engine.season_catalog import (
    calendar_shift_days,
    competition_display_name,
    season_competitions,
)


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def _competition(cid, ctype, name="第10回テスト大会"):
    return {
        "competition_id": cid,
        "reference_year": "2026",
        "competition_type": ctype,
        "competition_name": name,
    }


class SeasonCatalogRuleTests(unittest.TestCase):
    def test_shift_keeps_weekday_within_three_days(self):
        anchor = date(2026, 7, 18)
        for offset in range(0, 12):
            with self.subTest(offset=offset):
                days = calendar_shift_days(offset)
                self.assertEqual(0, days % 7)
                moved = anchor + timedelta(days=days)
                same_day = anchor.replace(year=2026 + offset)
                self.assertLessEqual(abs((moved - same_day).days), 3)
                self.assertEqual(anchor.weekday(), moved.weekday())

    def test_display_name_advances_edition_and_era_year(self):
        self.assertEqual(
            "第11回テスト大会",
            competition_display_name("第10回テスト大会", 1),
        )
        self.assertEqual(
            "令和10年度春季テスト大会",
            competition_display_name("令和8年度春季テスト大会", 2),
        )
        # 記念大会の冠はその年だけ
        self.assertEqual(
            "第11回テスト大会",
            competition_display_name("創立記念 第10回テスト大会", 1),
        )
        self.assertEqual(
            "創立記念 第10回テスト大会",
            competition_display_name("創立記念 第10回テスト大会", 0),
        )

    def test_invitational_belongs_to_the_previous_school_year(self):
        rows = [
            _competition("C1", "national_invitational"),
            _competition("C2", "summer_local_qualifier"),
        ]
        calendars = {
            "C1": {"start_date": "2026-03-19", "end_date": "2026-03-31"},
            "C2": {"start_date": "2026-07-04", "end_date": "2026-07-26"},
        }
        season = season_competitions(rows, calendars, 2027)
        self.assertEqual(2, season["C1"].year_offset)
        self.assertEqual(1, season["C2"].year_offset)
        self.assertEqual("第12回テスト大会", season["C1"].display_name)
        self.assertEqual(calendar_shift_days(2), season["C1"].shift_days)
        self.assertEqual(calendar_shift_days(1), season["C2"].shift_days)

        # 2028年度：そのままずらすと2029年4月3日まで延びるので1週早める
        season = season_competitions(rows, calendars, 2028)
        end = date(2026, 3, 31) + timedelta(days=season["C1"].shift_days)
        self.assertLessEqual(end, date(2029, 3, 31))
        self.assertEqual(calendar_shift_days(3) - 7, season["C1"].shift_days)


class GeneratedSeasonPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = DataRepository(DATA_ROOT)
        cls.repo = repo
        cls.base = LiveSeasonGraphPlanner(
            repo, DATA_ROOT, 2026102103, year=2026,
        ).build_plan()
        cls.plan = LiveSeasonGraphPlanner(
            repo, DATA_ROOT, 2026102103, year=2027,
        ).build_plan()

    def test_same_competitions_every_year(self):
        self.assertEqual(set(self.base.entries), set(self.plan.entries))
        self.assertEqual(162, len(self.plan.entries))
        self.assertEqual(
            self.base.summary()["dependency_edge_count"],
            self.plan.summary()["dependency_edge_count"],
        )
        self.assertEqual(0, self.plan.summary()["warning_count"])

    def test_editions_advance(self):
        names = {
            cid: entry.display_name
            for cid, entry in self.plan.entries.items()
        }
        self.assertEqual("第100回選抜高等学校野球大会", names["CMP000001"])
        self.assertEqual("第109回全国高等学校野球選手権大会", names["CMP000002"])
        self.assertIn("令和9年度", names["CMP000004"])
        # 2026年度の選抜は2027年3月の第99回
        self.assertEqual(
            "第99回選抜高等学校野球大会",
            self.base.entries["CMP000001"].display_name,
        )

    def test_dates_keep_weekday_and_stay_in_school_year(self):
        base = {
            row["competition_id"]: row for row in self.base.calendar_rows
        }
        for row in self.plan.calendar_rows:
            cid = row["competition_id"]
            with self.subTest(competition=cid):
                before = [
                    date.fromisoformat(x)
                    for x in base[cid]["game_date_list"].split(";") if x
                ]
                after = [
                    date.fromisoformat(x)
                    for x in row["game_date_list"].split(";") if x
                ]
                self.assertEqual(len(before), len(after))
                self.assertEqual(
                    [d.weekday() for d in before],
                    [d.weekday() for d in after],
                )
                self.assertTrue(all(d.year in (2027, 2028) for d in after))
                # 3月に始まる春季大会は新しい年度の大会として3月に入る
                if after:
                    self.assertGreaterEqual(after[0], date(2027, 3, 1))
                    self.assertLessEqual(after[-1], date(2028, 3, 31))
                if after and cid != "CMP000001" and after[-1].month > 3:
                    self.assertTrue(in_school_year(2027, after[-1]))
        senbatsu = [
            row for row in self.plan.calendar_rows
            if row["competition_id"] == "CMP000001"
        ][0]
        self.assertTrue(senbatsu["start_date"].startswith("2028-03"))
        self.assertLessEqual(senbatsu["end_date"], "2028-03-31")

    def test_draws_change_every_year(self):
        self.assertNotEqual(
            self.base.entries["CMP000002"].rng_seed,
            self.plan.entries["CMP000002"].rng_seed,
        )
        # 岐阜秋の参加校の抽出も年度ごとに変わる
        self.assertNotEqual(
            self.base.annual_templates["CMP000110"].entrant_school_ids,
            self.plan.annual_templates["CMP000110"].entrant_school_ids,
        )
        self.assertEqual(2027, self.plan.annual_templates["CMP000110"].year)

    def test_spring_access_uses_previous_year_invitational(self):
        # 2027年度の春季大会の推薦は前の年度（2028年3月ではなく2027年3月）の選抜
        self.assertNotIn(
            ("CMP000001", "CMP000004"),
            self.plan.dependency_edges,
        )
        rows = {
            row.access_rule_id: row
            for row in self.plan.external_bootstrap_resolutions
        }
        self.assertEqual("PASS", rows["ACR000001"].status)
        self.assertTrue(
            set(rows["ACR000001"].resolved_school_ids)
            <= set(self.plan.prior_invitational_entrant_ids)
        )

    def test_runtime_starts_in_the_generated_school_year(self):
        state = self.plan.build_runtime()
        self.assertEqual(date(2027, 4, 1), state.start_date)
        self.assertEqual(2027, state.year)
        # 2027年度の選抜は2028年3月に行う
        self.assertTrue(
            state.competitions["CMP000001"]
            .next_scheduled_date().startswith("2028-03")
        )
        self.assertGreater(len(state.competitions), 100)


if __name__ == "__main__":
    unittest.main()
