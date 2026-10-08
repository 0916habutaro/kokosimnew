from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g16 import (
    CALENDAR_FILE, EVENT_FILE, STRUCTURE_FILE,
    EXACT_DATE_DISCREPANCY, audit_2026_hiroshima_stage13e3g16,
)
from phase2_engine.hiroshima_stage13e3g14 import OFFICIAL_PDF_LIST
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
FILES = (CALENDAR_FILE, EVENT_FILE, STRUCTURE_FILE, OFFICIAL_PDF_LIST, TIMELINE_FILE)


def copy_data(root):
    for path in FILES:
        t = root / path
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / path, t)


def edit(root, path, mutation):
    with (root / path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    mutation(rows)
    with (root / path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G16PublisherStructureChecks(unittest.TestCase):
    def test_parent_89_children_and_87_qualifiers_are_separated(self):
        r = audit_2026_hiroshima_stage13e3g16(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(44,r["spring_publisher_child_events"])
        self.assertEqual(45,r["autumn_publisher_child_events"])
        self.assertEqual(87,r["qualifier_child_events"])

    def test_14_explicit_entry_deciders_and_extra_runnerup_zone(self):
        r = audit_2026_hiroshima_stage13e3g16(DATA)
        self.assertEqual(14,r["explicit_entry_decider_child_events"])
        self.assertEqual(15,r["matched_publisher_stage_to_qualified_game_records"])

    def test_five_publisher_date_end_discrepancies_are_not_game_rewrites(self):
        r = audit_2026_hiroshima_stage13e3g16(DATA)
        self.assertEqual(5,r["publisher_event_window_game_date_disagreements"])
        self.assertEqual(sorted(EXACT_DATE_DISCREPANCY),r["publisher_event_window_game_date_disagreement_ids"])

    def test_calendar_reserve_day_april_11_remains_permitted(self):
        r = audit_2026_hiroshima_stage13e3g16(DATA)
        self.assertTrue(r["ok"],r["errors"])
        with (DATA / CALENDAR_FILE).open(encoding="utf-8", newline="") as f:
            rows = {x["season"]:x for x in csv.DictReader(f)}
        self.assertEqual("2026-04-11",rows["spring"]["reserve_day1"])
        self.assertEqual("2026-04-05",rows["spring"]["qualifier_normal_end"])

    def test_no_later_game_is_proven_after_a_prior_date_qualification(self):
        r = audit_2026_hiroshima_stage13e3g16(DATA)
        self.assertEqual([],r["already_qualified_on_prior_date_match_ids"])
        self.assertEqual(0,r["optional_ranking_only_games_proven"])

    def test_fmt025_stays_pending_without_any_pdf_body(self):
        r = audit_2026_hiroshima_stage13e3g16(DATA)
        self.assertFalse(r["fmt025_release_allowed"])
        self.assertFalse(r["official_bracket_pdf_match_census_complete"])
        self.assertEqual(0,r["official_bracket_pdf_bodies_inspected"])

    def test_fabricated_official_pdf_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, STRUCTURE_FILE, lambda rows:rows[0].update(pdf_body_inspected="yes"))
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("provenance mismatch" in x for x in r["errors"]))

    def test_a_missing_stage_window_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, EVENT_FILE, lambda rows:rows.pop())
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("15" in x or "entry-decider count" in x for x in r["errors"]))

    def test_mislabelled_score_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, EVENT_FILE, lambda rows:rows[0].update(winner_score="99"))
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("evidence mismatch" in x for x in r["errors"]))

    def test_wrong_qualifier_child_event_count_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, STRUCTURE_FILE, lambda rows:rows[0].update(second_place_child_events="9"))
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("counts/provenance mismatch" in x for x in r["errors"]))

    def test_publisher_and_game_dates_cannot_be_silently_equated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, EVENT_FILE, lambda rows:rows[1].update(
                actual_date_outside_child_index_window="no"))
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("evidence mismatch" in x for x in r["errors"]))

    def test_2026_federation_calendar_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, CALENDAR_FILE, lambda rows:rows[0].update(
                qualifier_normal_end="2026-04-04"))
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("federation published calendar changed" in x for x in r["errors"]))

    def test_duplicate_match_id_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);copy_data(root)
            edit(root, EVENT_FILE, lambda rows:rows[0].update(
                matched_match_id=rows[1]["matched_match_id"]))
            r=audit_2026_hiroshima_stage13e3g16(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("duplicate or missing" in x for x in r["errors"]))


if __name__ == "__main__":
    unittest.main()
