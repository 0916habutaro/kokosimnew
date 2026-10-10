from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase2_engine.future_season_blueprint import (
    BASE_YEAR, GAME_PROJECTION, _project_day,
    build_future_season_blueprint,
)

ROOT = Path(__file__).resolve().parents[1]


def prior_result(year=2026, count=8, status="completed", source="game_result"):
    return {
        "year": year, "status": status, "source": source,
        "ranked_school_ids": [f"SCH-FICTIONAL-{i:03d}" for i in range(1, count + 1)],
    }


class Stage43FFutureSeasonBlueprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blueprint = build_future_season_blueprint(
            ROOT / "data", year=2027, base_seed=20261010
        )

    def test_all_competitions_are_projected_without_fake_official_data(self):
        p = self.blueprint
        self.assertEqual(2027, p["year"])
        self.assertEqual(BASE_YEAR, p["source_structure_year"])
        self.assertEqual(GAME_PROJECTION, p["provenance"])
        self.assertFalse(p["official_calendar"])
        self.assertFalse(p["live_runtime_ready"])
        self.assertEqual(162, p["competition_count"])
        self.assertEqual(162, p["calendar_count"])
        self.assertTrue(p["stage_calendar_count"] > 0)
        self.assertEqual(162, len({
            x["competition_id"] for x in p["competitions"]
        }))
        self.assertEqual(
            {x["competition_id"] for x in p["competitions"]},
            {x["competition_id"] for x in p["calendars"]},
        )
        for row in p["competitions"]:
            self.assertEqual(2027, row["reference_year"])
            self.assertEqual("unresolved", row["participant_status"])
            self.assertEqual("unresolved", row["draw_status"])
            self.assertEqual("requires_future_year_validation",
                             row["structure_status"])
            self.assertNotIn("令和8", row["display_name"])
            self.assertNotIn("2026", row["competition_code"])
            self.assertIn("2027", row["competition_code"])

    def test_game_dates_are_not_advertised_as_verified(self):
        p = self.blueprint
        march = next(
            c for c in p["calendars"] if c["competition_id"] == "CMP000001"
        )
        self.assertEqual("2027-03-19", march["start_date"])
        self.assertEqual("2027-03-31", march["end_date"])
        self.assertEqual("2027-03-06", march["draw_date"])
        self.assertEqual(GAME_PROJECTION, march["date_source"])
        self.assertEqual("provisional_game_schedule", march["calendar_status"])
        self.assertFalse(march["real_world_verified"])
        self.assertEqual("", march["primary_source_id"])
        self.assertEqual("", march["verified_at"])
        self.assertEqual("official_schedule", march["source_calendar_status_2026"])
        for row in p["calendars"]:
            self.assertFalse(row["real_world_verified"])
            self.assertEqual("", row["primary_source_id"])
            for key in ("start_date", "end_date", "draw_date"):
                if row[key]:
                    self.assertEqual("2027", row[key][:4])
            for day in row["game_date_list"].split(";"):
                if day:
                    self.assertTrue(day.startswith("2027-"))

    def test_missing_2026_game_days_are_not_invented(self):
        jinguu = next(
            r for r in self.blueprint["calendars"]
            if r["competition_id"] == "CMP000003"
        )
        self.assertEqual("", jinguu["game_date_list"])

    def test_stage_calendars_are_projections_not_2026_verified_results(self):
        for row in self.blueprint["stage_calendars"]:
            self.assertEqual(2027, row["reference_year"])
            self.assertEqual(GAME_PROJECTION, row["date_source"])
            self.assertEqual("provisional_game_schedule", row["date_status"])
            self.assertFalse(row["real_world_verified"])
            self.assertEqual("", row["primary_source_id"])
            self.assertEqual("", row["verified_at"])
            for day in row["date_list"].split(";"):
                if day:
                    self.assertTrue(day.startswith("2027-"))

    def test_blueprint_is_deterministic_and_seed_changes_only_seed_fields(self):
        same = build_future_season_blueprint(
            ROOT / "data", year=2027, base_seed=20261010
        )
        self.assertEqual(self.blueprint, same)
        another = build_future_season_blueprint(
            ROOT / "data", year=2027, base_seed=20261011
        )
        self.assertEqual(
            [r["competition_id"] for r in self.blueprint["competitions"]],
            [r["competition_id"] for r in another["competitions"]],
        )
        self.assertNotEqual(
            self.blueprint["competitions"][0]["rng_seed"],
            another["competitions"][0]["rng_seed"],
        )
        self.assertEqual(
            self.blueprint["calendars"], another["calendars"]
        )

    def test_cross_year_must_use_saved_prior_autumn_result(self):
        p = self.blueprint
        selected = next(
            r for r in p["prior_autumn_access"]
            if r["access_rule_id"] == "ACR000004"
        )
        self.assertEqual("CMP000085", selected["source_competition_id"])
        self.assertEqual(2026, selected["source_year"])
        self.assertEqual("unresolved", selected["status"])
        self.assertEqual([], selected["school_ids"])
        self.assertIn("ACR000004", p["unresolved_prior_rule_ids"])

        with_result = build_future_season_blueprint(
            ROOT / "data", year=2027, base_seed=20261010,
            previous_results={"CMP000085": prior_result(count=4)},
        )
        selected = next(
            r for r in with_result["prior_autumn_access"]
            if r["access_rule_id"] == "ACR000004"
        )
        self.assertEqual("resolved", selected["status"])
        self.assertEqual("previous_year_saved_game_result",
                         selected["provenance"])
        self.assertEqual(
            [f"SCH-FICTIONAL-{i:03d}" for i in range(1, 5)],
            selected["school_ids"],
        )
        self.assertNotIn("ACR000004", with_result["unresolved_prior_rule_ids"])

    def test_mismatched_year_or_unknown_source_is_not_accepted(self):
        for changed in (
            prior_result(year=2025, count=4),
            prior_result(year=2026, count=4, status="pending"),
            prior_result(year=2026, count=4, source="official_2026_fixture"),
        ):
            p = build_future_season_blueprint(
                ROOT / "data", year=2027, base_seed=2,
                previous_results={"CMP000085": changed},
            )
            result = next(r for r in p["prior_autumn_access"]
                          if r["access_rule_id"] == "ACR000004")
            self.assertEqual("unresolved", result["status"])
            self.assertEqual([], result["school_ids"])

    def test_incomplete_or_duplicate_ranks_do_not_qualify(self):
        examples = [
            prior_result(count=2),
            {**prior_result(count=4),
             "ranked_school_ids": ["S1", "S1", "S3", "S4"]},
            {**prior_result(count=4),
             "ranked_school_ids": ["S1", "", "S3", "S4"]},
        ]
        for bad in examples:
            with self.subTest(bad=bad):
                p = build_future_season_blueprint(
                    ROOT / "data", year=2027, base_seed=2,
                    previous_results={"CMP000085": bad},
                )
                result = next(r for r in p["prior_autumn_access"]
                              if r["access_rule_id"] == "ACR000004")
                self.assertEqual("unresolved", result["status"])

    def test_committee_selection_is_never_auto_filled_from_prior_autumn(self):
        committee = self.blueprint["committee_selections"]
        self.assertTrue(any(
            row["competition_id"] == "CMP000001" and
            row["status"] == "committee_selection_pending"
            for row in committee
        ))
        self.assertNotIn(
            "entrant_school_ids",
            self.blueprint["competitions"][0],
        )

    def test_unsupported_regional_autumn_rule_fails_closed(self):
        row = next(
            r for r in self.blueprint["prior_autumn_access"]
            if r["access_rule_id"] == "ACR000015"
        )
        self.assertEqual("unresolved", row["status"])
        self.assertEqual("unsupported_prior_year_selector", row["reason"])

    def test_following_2028_year_uses_2027_results_when_provided(self):
        p = build_future_season_blueprint(
            ROOT / "data", year=2028, base_seed=9,
            previous_results={"CMP000085": prior_result(year=2027, count=4)},
        )
        result = next(r for r in p["prior_autumn_access"]
                      if r["access_rule_id"] == "ACR000004")
        self.assertEqual(2027, result["source_year"])
        self.assertEqual("resolved", result["status"])
        self.assertTrue(all(
            v["start_date"].startswith("2028-") for v in p["calendars"]
            if v["start_date"]
        ))

    def test_future_out_of_supported_datetime_range_is_explicit_error(self):
        for year in (2026, 0, 10000, True):
            with self.subTest(year=year), self.assertRaises(ValueError):
                build_future_season_blueprint(
                    ROOT / "data", year=year, base_seed=12
                )
        with self.assertRaises(ValueError):
            _project_day("2025-03-01", 2027)

    def test_export_is_json_serializable_and_contains_no_actual_results(self):
        text = json.dumps(self.blueprint, ensure_ascii=False, sort_keys=True)
        self.assertNotIn('"match_results"', text)
        self.assertIn('"live_runtime_ready": false', text)
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "projection.json"
            file.write_text(text, encoding="utf-8")
            self.assertEqual(
                self.blueprint,
                json.loads(file.read_text(encoding="utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
