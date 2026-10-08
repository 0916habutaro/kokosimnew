from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_district_qualification_2026 import (
    audit_2026_hiroshima_qualification_routes,
    load_2026_hiroshima_qualification_routes,
)
from phase2_engine.ranking_cross_block_2026 import (
    hiroshima_2026_qualification_guard,
)


DATA = Path(__file__).resolve().parents[1] / "data"
REL = (
    "competitions/2026/hiroshima_district_qualification_routes.csv",
    "competitions/2026/hiroshima_qualification_examples.csv",
    "competitions/2026/post_qualification_rank_observations.csv",
    "competitions/2026/post_qualification_rank_school_mapping.csv",
    "competitions/competition_stage_groups.csv",
)


def fixture(path: Path):
    for name in REL:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / name, target)


def change_csv(path: Path, mutation) -> None:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fields = reader.fieldnames
        rows = list(reader)
    mutation(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as dest:
        writer = csv.DictWriter(dest, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G7HiroshimaDistrictQualificationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit_2026_hiroshima_qualification_routes(DATA)

    def test_eight_region_seasons_all_qualification_route_labels_reviewed(self):
        self.assertTrue(self.report["ok"], self.report["errors"])
        self.assertEqual(8, self.report["district_season_count"])
        self.assertEqual(87, self.report["sub_tournament_route_count"])
        self.assertEqual({
            "spring_west": 9, "spring_north": 10,
            "spring_south": 15, "spring_east": 9,
            "autumn_west": 9, "autumn_north": 10,
            "autumn_south": 16, "autumn_east": 9,
        }, self.report["region_route_counts"])

    def test_each_season_has_32_berths_and_autumn_quotas_are_official(self):
        self.assertEqual(
            {"west": 7, "north": 6, "south": 10, "east": 9},
            self.report["berth_slots"]["autumn"]
        )
        self.assertEqual(
            {"west": 7, "north": 7, "south": 9, "east": 9},
            self.report["berth_slots"]["spring"]
        )
        for slots in self.report["berth_slots"].values():
            self.assertEqual(32, sum(slots.values()))

    def test_inventory_is_not_wrongly_presented_as_individual_matches(self):
        self.assertEqual(
            "bracket_level_inventory_plus_named_qualification_examples",
            self.report["matching_scope"],
        )
        self.assertEqual(9, self.report["named_qualification_match_count"])
        self.assertTrue(self.report["full_match_by_match_berth_state_audit_pending"])
        self.assertEqual(0, self.report["optional_ranking_matches_registered"])
        self.assertTrue(all(
            row["verification_scope"] == "bracket_level_only"
            and row["qualification_effect"] == "qualification_sensitive"
            for row in load_2026_hiroshima_qualification_routes(DATA)
        ))

    def test_named_qualification_wins_include_2026_spring_and_autumn(self):
        self.assertTrue(self.report["ok"], self.report["errors"])
        with (DATA / "competitions/2026/hiroshima_qualification_examples.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            rows = {r["example_id"]: r for r in csv.DictReader(stream)}
        self.assertEqual(9, len(rows))
        self.assertEqual("広島城北", rows["HQ20260001"]["winner_name"])
        self.assertEqual("RR20260034", rows["HQ20260001"]["prior_reference_id"])
        self.assertEqual("神辺旭", rows["HQ20260005"]["winner_name"])
        self.assertEqual("瀬戸内", rows["HQ20260008"]["winner_name"])
        self.assertEqual("RR20260033", rows["HQ20260009"]["prior_reference_id"])

    def test_old_hiroshima_guard_uses_full_regional_route_inventory(self):
        guard = hiroshima_2026_qualification_guard(DATA)
        self.assertTrue(guard["ok"], guard["errors"])
        self.assertEqual(87, guard["district_sub_tournament_route_count"])
        self.assertEqual(32, guard["federation_main_berths_per_season"])
        self.assertEqual(0, guard["verified_optional_ranking_count"])
        self.assertEqual([
            "RR20260032", "RR20260033", "RR20260034",
        ], guard["excluded_qualification_reference_ids"])
        self.assertTrue(guard["needs_full_2026_bracket_outcome_review"])

    def test_falsely_marking_qualification_route_as_optional_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            path = root / REL[0]
            change_csv(path, lambda rows: rows[0].update(
                qualification_effect="ranking_metadata_only"
            ))
            audit = audit_2026_hiroshima_qualification_routes(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any(
                "ranking-only route" in error for error in audit["errors"]
            ))
            self.assertFalse(hiroshima_2026_qualification_guard(root)["ok"])

    def test_changing_official_autumn_qualifying_slots_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            path = root / REL[-1]
            def tamper(rows):
                r = next(r for r in rows
                         if r["stage_group_id"] == "SGR000145")
                r["advance_slots_to_next"] = "7"
            change_csv(path, tamper)
            audit = audit_2026_hiroshima_qualification_routes(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any(
                "autumn district berths" in error
                for error in audit["errors"]
            ))

    def test_misleading_individual_match_exhaustive_flag_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            path = root / REL[0]
            change_csv(path, lambda rows: rows[-1].update(
                verification_scope="individual_matches_exhaustive"
            ))
            audit = audit_2026_hiroshima_qualification_routes(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any(
                "no individual-match exhaustive proof" in error
                for error in audit["errors"]
            ))

    def test_qualification_game_winner_or_protected_reference_tamper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            path = root / REL[1]
            change_csv(path, lambda rows: rows[0].update(
                winner_name="山陽"
            ))
            audit = audit_2026_hiroshima_qualification_routes(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any(
                "winner and score disagree" in error
                for error in audit["errors"]
            ))

    def test_bogus_berth_route_name_or_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            path = root / REL[0]
            def tamper(rows):
                rows[0]["route_kind"] = "post_qualification_ranking"
                rows[1]["route_id"] = rows[0]["route_id"]
            change_csv(path, tamper)
            audit = audit_2026_hiroshima_qualification_routes(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any(
                "route title and role inconsistent" in error
                or "duplicated ID" in error
                for error in audit["errors"]
            ))


if __name__ == "__main__":
    unittest.main()
