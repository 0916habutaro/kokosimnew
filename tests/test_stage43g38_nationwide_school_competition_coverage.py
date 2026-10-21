"""Stage43G-38: audit all 47 actual school-master regions against 2026 inputs."""
from __future__ import annotations

from copy import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from phase2_engine.career_national_coverage_audit import (
    audit_national_competition_inputs,
)
from phase2_engine.live_season_planner import LiveSeasonGraphPlanner
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class Stage43G38NationwideCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.plan = LiveSeasonGraphPlanner(
            cls.repo, DATA, 2026100822, year=2026,
        ).build_plan()
        cls.report = audit_national_competition_inputs(
            cls.repo, cls.plan, DATA,
        )

    def test_all_47_prefectures_162_competitions_49_summer_areas(self):
        self.assertTrue(self.report["ok"], self.report["issues"][:20])
        s = self.report["summary"]
        self.assertEqual(47, s["prefecture_count"])
        self.assertEqual(162, s["competition_count"])
        self.assertEqual(162, s["national_plan_entry_count"])
        self.assertEqual(49, s["summer_local_competition_count"])
        self.assertEqual(0, s["issue_count"])
        self.assertEqual(
            len(self.repo.school_to_program),
            s["registered_hardball_school_count"],
        )
        self.assertGreater(s["input_school_references_checked"], 100)
        self.assertFalse(s["match_simulation_executed"])
        self.assertFalse(s["career_year_continuity_verified"])
        self.assertFalse(s["official_real_2026_entrant_results"])

    def test_non_kanto_regions_have_real_master_ids_and_2026_event_routes(self):
        by_code = {
            x["prefecture_code"]: x for x in self.report["prefectures"]
        }
        for code in ("01", "04", "20", "23", "27", "34", "36", "47"):
            with self.subTest(prefecture=code):
                row = by_code[code]
                self.assertGreater(row["registered_hardball_school_count"], 0)
                self.assertEqual(1, len(row["spring_competition_ids"]))
                self.assertEqual(1, len(row["autumn_competition_ids"]))
                self.assertEqual(2 if code == "01" else 1,
                                 len(row["summer_competition_ids"]))
                self.assertGreater(row["summer_input_school_count"], 0)
                self.assertTrue(row["summer_school_ids_unique"])
                for cid in (row["spring_competition_ids"] +
                            row["autumn_competition_ids"] +
                            row["summer_competition_ids"]):
                    self.assertIn(cid, self.repo.competitions)
                    self.assertIn(cid, self.plan.annual_templates)
                    self.assertTrue(self.repo.stages(cid))

    def test_hokkaido_and_tokyo_two_summer_areas_but_single_autumn(self):
        entries = {x["prefecture_code"]: x for x in self.report["prefectures"]}
        self.assertEqual(2, len(entries["01"]["summer_competition_ids"]))
        self.assertEqual(2, len(entries["13"]["summer_competition_ids"]))
        self.assertEqual(["CMP000004"], entries["01"]["spring_competition_ids"])
        self.assertEqual(["CMP000013"], entries["01"]["autumn_competition_ids"])
        self.assertEqual(["CMP000016"], entries["13"]["autumn_competition_ids"])

    def _plan(self, changes: dict | None = None):
        """Clone only the plan's view mappings: never change master or plan."""
        source = self.plan
        templates = dict(source.annual_templates)
        if changes:
            templates.update(changes)
        return SimpleNamespace(
            year=2026, annual_templates=templates,
            entries=source.entries, calendar_rows=source.calendar_rows,
        )

    def test_foreign_prefecture_and_unknown_ids_are_detected(self):
        chosen = next(
            row for row in self.report["prefectures"]
            if row["prefecture_code"] == "02"
        )
        cid = chosen["summer_competition_ids"][0]
        school = next(
            sid for sid in self.repo.school_to_program
            if self.repo.schools[sid]["prefecture_code"] == "14"
        )
        original = self.plan.annual_templates[cid]
        altered = SimpleNamespace(
            entrant_school_ids=list(original.entrant_school_ids) + [school]
        )
        report = audit_national_competition_inputs(
            self.repo, self._plan({cid: altered}), DATA,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "foreign or unknown entrant" in error and cid in error
            for error in report["issues"]
        ))
        self.assertNotIn(school, original.entrant_school_ids)

    def test_duplicate_tournament_entrants_are_detected(self):
        code = "47"
        cid = next(x for x in self.report["prefectures"]
                   if x["prefecture_code"] == code)["summer_competition_ids"][0]
        original = self.plan.annual_templates[cid]
        new_entrants = list(original.entrant_school_ids)
        self.assertTrue(new_entrants)
        new_entrants.append(new_entrants[0])
        report = audit_national_competition_inputs(
            self.repo, self._plan({
                cid: SimpleNamespace(entrant_school_ids=new_entrants),
            }), DATA,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "duplicate entrant" in error
            for error in report["issues"]
        ))

    def test_missing_competition_and_duplicate_calendar_cannot_pass(self):
        source = self._plan()
        absent = next(x for x in self.report["prefectures"]
                      if x["prefecture_code"] == "34")["summer_competition_ids"][0]
        source.annual_templates.pop(absent)
        result = audit_national_competition_inputs(self.repo, source, DATA)
        self.assertFalse(result["ok"])
        self.assertTrue(any(
            "annual templates differ" in x or
            "missing annual tournament input" in x for x in result["issues"]
        ))
        same = self._plan()
        same.calendar_rows = [*same.calendar_rows, same.calendar_rows[0]]
        duplicate = audit_national_competition_inputs(self.repo, same, DATA)
        self.assertFalse(duplicate["ok"])
        self.assertIn("duplicate annual calendar competition ID",
                      duplicate["issues"])

    def test_future_year_must_not_be_claimed_as_2026_audit(self):
        other = self._plan()
        other.year = 2027
        with self.assertRaisesRegex(ValueError, "2026"):
            audit_national_competition_inputs(self.repo, other, DATA)


if __name__ == "__main__":
    unittest.main()
