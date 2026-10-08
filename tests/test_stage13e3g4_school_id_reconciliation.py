from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.ranking_school_reconciliation_2026 import (
    GROUP_MAPPED,
    CROSS_AREA,
    EXCLUDED,
    SEED_MAPPED,
    audit_ranking_school_mapping_2026,
    build_verified_fmt025_2026_daily_sidecar,
    load_ranking_school_mapping_2026,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MAPPING = "competitions/2026/post_qualification_rank_school_mapping.csv"
FILES = (
    MAPPING,
    "competitions/2026/post_qualification_rank_school_aliases.csv",
    "competitions/2026/post_qualification_rank_observations.csv",
    "competitions/2026/post_qualification_cross_block_pairs.csv",
    "competitions/competition_stage_groups.csv",
    "competitions/post_qualification_ranking_profiles.csv",
    "master/schools.csv",
    "master/baseball_programs.csv",
    "areas/school_area_memberships.csv",
)


def fixture(root: Path) -> None:
    for path in FILES:
        out = root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / path, out)


def mutate(path: Path, change) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    change(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G4SchoolMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = audit_ranking_school_mapping_2026(DATA)
        cls.mapping = load_ranking_school_mapping_2026(DATA)
        cls.by_id = {r["reference_id"]: r for r in cls.mapping}

    def test_entire_reconciliation_is_consistent(self):
        self.assertTrue(self.audit["ok"], self.audit["errors"])
        self.assertEqual(3746, self.audit["school_master_count"])
        self.assertEqual(3746, self.audit["baseball_program_count"])
        self.assertEqual(6871, self.audit["area_membership_count"])
        self.assertEqual(34, self.audit["observation_count"])
        self.assertEqual(53, self.audit["unique_observed_school_count"])
        self.assertEqual(11, self.audit["reviewed_alias_count"])
        self.assertEqual({
            SEED_MAPPED: 5,
            GROUP_MAPPED: 25,
            CROSS_AREA: 1,
            EXCLUDED: 3,
        }, self.audit["classification_counts"])

    def test_spring_shizuoka_is_partitioned_into_three_groups(self):
        spring = [
            r for r in self.mapping if r["competition_id"] == "CMP000111"
        ]
        self.assertEqual(13, len(spring))
        self.assertTrue(all(r["mapping_status"] == GROUP_MAPPED for r in spring))
        groups = {name: sum(r["stage_group_id"] == name for r in spring)
                  for name in ("SGR000103", "SGR000104", "SGR000105")}
        self.assertEqual({
            "SGR000103": 4, "SGR000104": 4, "SGR000105": 5,
        }, groups)

    def test_autumn_shizuoka_has_explicit_cross_area_hold(self):
        self.assertEqual([{
            "reference_id": "RR20260023",
            "competition_id": "CMP000112",
            "team1_area_id": "AREA000068",
            "team2_area_id": "AREA000067",
        }], self.audit["cross_area_review"])
        mismatch = self.by_id["RR20260023"]
        self.assertEqual("SCH002522", mismatch["team1_school_id"])
        self.assertEqual("SCH002479", mismatch["team2_school_id"])
        self.assertEqual("", mismatch["stage_group_id"])
        self.assertEqual(CROSS_AREA, mismatch["mapping_status"])

    def test_hiroshima_qualification_is_still_excluded(self):
        for cid in ("CMP000135", "CMP000136"):
            matches = [r for r in self.mapping
                       if r["competition_id"] == cid]
            self.assertTrue(matches)
            self.assertTrue(all(r["mapping_status"] == EXCLUDED for r in matches))
            self.assertTrue(all(r["team1_area_id"] == r["team2_area_id"]
                                for r in matches))

    def test_federation_names_and_reviewed_aliases_have_real_master_ids(self):
        self.assertEqual("SCH002490", self.by_id["RR20260014"]["team2_school_id"])
        self.assertEqual("SCH002509", self.by_id["RR20260021"]["team1_school_id"])
        self.assertEqual("SCH002724", self.by_id["RR20260004"]["team2_school_id"])
        self.assertEqual("SCH001834", self.by_id["RR20260032"]["team2_school_id"])

    def test_fmt025_day_builder_creates_unplayed_same_area_fixtures(self):
        available = [r for r in self.mapping
                     if r["competition_id"] == "CMP000111"
                     and r["stage_group_id"] == "SGR000103"]
        ids = list({r[key] for r in available
                    for key in ("team1_school_id", "team2_school_id")})
        state = build_verified_fmt025_2026_daily_sidecar(
            DATA,
            competition_id="CMP000111",
            stage_group_id="SGR000103",
            match_date="2026-04-04",
            locked_school_ids=sorted(ids),
            qualification_locked_on="2026-04-03",
        )
        matches = state.matches_for_date("2026-04-04")
        self.assertGreaterEqual(len(matches), 1)
        self.assertTrue(all(row["winner_id"] == "" for row in matches))
        self.assertTrue(all(row["ranking_only"] for row in matches))
        self.assertEqual("SGR000103", state.event.group_id)
        self.assertEqual("CMP000111", state.event.competition_id)

    def test_no_automatic_import_of_real_winners_or_scores(self):
        ids = [
            sid for row in self.mapping
            if row["competition_id"] == "CMP000112"
            and row["stage_group_id"] == "SGR000106"
            for sid in (row["team1_school_id"], row["team2_school_id"])
        ]
        state = build_verified_fmt025_2026_daily_sidecar(
            DATA,
            competition_id="CMP000112",
            stage_group_id="SGR000106",
            match_date="2026-08-30",
            locked_school_ids=sorted(set(ids)),
            qualification_locked_on="2026-08-28",
        )
        self.assertEqual({}, state.event.results)
        self.assertTrue(all(r["team1_score"] is None and
                            r["team2_score"] is None
                            for r in state.matches_for_date("2026-08-30")))

    def test_cross_area_or_qualifier_cannot_create_post_cut_event(self):
        for cid, group, date in (
            ("CMP000112", "", "2026-08-30"),
            ("CMP000136", "SGR000146", "2026-09-05"),
        ):
            with self.subTest(cid=cid), self.assertRaises(ValueError):
                build_verified_fmt025_2026_daily_sidecar(
                    DATA,
                    competition_id=cid,
                    stage_group_id=group,
                    match_date=date,
                    locked_school_ids=["FAKE_A", "FAKE_B"],
                    qualification_locked_on="2026-08-25",
                )

    def test_stage_qualified_team_validation_rejects_unknown_school(self):
        with self.assertRaisesRegex(ValueError, "locked qualifiers"):
            build_verified_fmt025_2026_daily_sidecar(
                DATA,
                competition_id="CMP000111",
                stage_group_id="SGR000103",
                match_date="2026-04-04",
                locked_school_ids=["FAKE_A", "FAKE_B"],
                qualification_locked_on="2026-04-03",
            )

    def test_wrong_school_id_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)

            def change(rows):
                rows[0]["team1_school_id"] = "SCH002490"
            mutate(root / MAPPING, change)
            audit = audit_ranking_school_mapping_2026(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any("wrong prefecture" in err
                                or "unverified observed name" in err
                                for err in audit["errors"]))

    def test_wrong_area_or_group_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)

            def change(rows):
                rows[5]["team1_area_id"] = "AREA000067"
                rows[5]["stage_group_id"] = "SGR000104"
            mutate(root / MAPPING, change)
            audit = audit_ranking_school_mapping_2026(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any("wrong 2026 area" in err
                                or "ranking stage group differs" in err
                                for err in audit["errors"]))

    def test_unreviewed_alias_or_duplicate_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            path = root / "competitions/2026/post_qualification_rank_school_aliases.csv"

            def change(rows):
                rows.pop()
            mutate(path, change)
            audit = audit_ranking_school_mapping_2026(root)
            self.assertFalse(audit["ok"])
            self.assertTrue(any("expected 11" in err for err in audit["errors"]))


if __name__ == "__main__":
    unittest.main()
