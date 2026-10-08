from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.ranking_reference_2026 import (
    build_verified_fmt022_2026_sidecar,
    load_2026_ranking_observations,
    validate_ranking_observations,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REFERENCE = DATA / "competitions/2026/post_qualification_rank_observations.csv"


def copy_reference_fixture(path: Path) -> None:
    for relative in (
        "competitions/post_qualification_ranking_profiles.csv",
        "competitions/2026/post_qualification_rank_observations.csv",
    ):
        dest = path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DATA / relative, dest)


def tamper(path: Path, update) -> None:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    update(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G3HistoricalRankingReferenceTests(unittest.TestCase):
    def test_2026_reference_count_and_scope(self):
        report = validate_ranking_observations(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(34, report["record_count"])
        self.assertEqual(31, report["verified_ranking_match_count"])
        self.assertEqual(3, report["qualification_only_count"])
        self.assertEqual(26, report["unmapped_group_count"])
        self.assertEqual({
            "CMP000111": 13,
            "CMP000112": 13,
            "CMP000140": 2,
            "CMP000162": 3,
        }, report["verified_by_competition"])

    def test_historical_results_and_dates_are_not_speculative(self):
        records = load_2026_ranking_observations(DATA)
        verified = [
            r for r in records
            if r["reference_classification"] == "verified_ranking_only"
        ]
        self.assertEqual(
            {
                "CMP000111": {"2026-04-04", "2026-04-05", "2026-04-11"},
                "CMP000112": {"2026-08-29", "2026-08-30", "2026-09-05"},
                "CMP000140": {"2026-08-24"},
                "CMP000162": {"2026-08-13", "2026-08-14"},
            },
            {
                cid: {r["match_date"] for r in verified
                      if r["competition_id"] == cid}
                for cid in {r["competition_id"] for r in verified}
            },
        )

    def test_hiroshima_qualifying_games_are_never_ranking(self):
        rows = load_2026_ranking_observations(DATA)
        hiroshima = [r for r in rows
                     if r["competition_id"] in ("CMP000135", "CMP000136")]
        self.assertEqual(3, len(hiroshima))
        self.assertTrue(all(
            r["reference_classification"] == "qualification_decider_not_ranking"
            and r["stage_group_id"] == ""
            for r in hiroshima
        ))

    def test_tokushima_can_be_scheduled_without_importing_real_winners(self):
        official = {
            "阿南光": "TOK1", "生光学園": "TOK2",
            "鳴門渦潮": "TOK3", "徳島商業": "TOK4",
        }
        state = build_verified_fmt022_2026_sidecar(
            DATA, competition_id="CMP000140",
            school_id_by_official_name=official,
            locked_school_ids=["TOK1", "TOK2", "TOK3", "TOK4"],
            qualification_locked_on="2026-08-21",
        )
        self.assertEqual(["2026-08-24"], list(state.match_dates))
        rows = state.matches_for_date("2026-08-24")
        self.assertEqual(2, len(rows))
        self.assertTrue(all(row["status"] == "pending" for row in rows))
        self.assertTrue(all(row["winner_id"] == "" for row in rows))
        self.assertEqual({}, state.event.results)
        self.assertEqual(tuple(official.values()), state.event.locked_school_ids)

    def test_okinawa_can_be_scheduled_without_importing_real_scores(self):
        official = {
            "ウェルネス沖縄": "OKI1",
            "コザ": "OKI2",
            "沖縄尚学": "OKI3",
            "KBC": "OKI4",
        }
        state = build_verified_fmt022_2026_sidecar(
            DATA, competition_id="CMP000162",
            school_id_by_official_name=official,
            locked_school_ids=list(official.values()),
            qualification_locked_on="2026-08-11",
        )
        self.assertEqual(
            ["2026-08-13", "2026-08-14"], list(state.match_dates)
        )
        self.assertEqual(2, len(state.matches_for_date("2026-08-13")))
        self.assertEqual([], state.matches_for_date("2026-08-14"))
        self.assertEqual({}, state.event.results)

    def test_wrong_school_map_cannot_replace_locked_seeds(self):
        mapping = {
            "阿南光": "A", "生光学園": "B",
            "鳴門渦潮": "C", "徳島商業": "D",
        }
        kwargs = dict(
            data_dir=DATA, competition_id="CMP000140",
            school_id_by_official_name=mapping,
            qualification_locked_on="2026-08-21",
        )
        with self.assertRaisesRegex(ValueError, "do not match"):
            build_verified_fmt022_2026_sidecar(
                **kwargs, locked_school_ids=["A", "B", "C", "OTHER"],
            )
        mapping.pop("生光学園")
        with self.assertRaisesRegex(ValueError, "mapped exactly"):
            build_verified_fmt022_2026_sidecar(
                **kwargs, locked_school_ids=["A", "B", "C", "D"],
            )

    def test_fmt025_is_not_auto_mapped_without_regional_school_ids(self):
        with self.assertRaisesRegex(ValueError, "only FMT022"):
            build_verified_fmt022_2026_sidecar(
                DATA, competition_id="CMP000112",
                school_id_by_official_name={},
                locked_school_ids=["A", "B", "C", "D"],
                qualification_locked_on="2026-08-28",
            )

    def test_bad_score_and_fake_winner_fail_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            copy_reference_fixture(data)
            ref = data / "competitions/2026/post_qualification_rank_observations.csv"

            def change(rows):
                rows[0]["winner_name"] = "存在しない勝者"
                rows[1]["team1_score"] = "-2"
            tamper(ref, change)
            report = validate_ranking_observations(data)
            self.assertFalse(report["ok"])
            self.assertTrue(any("invalid score" in err for err in report["errors"]))

    def test_duplicate_game_and_bad_classification_fail_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            copy_reference_fixture(data)
            ref = data / "competitions/2026/post_qualification_rank_observations.csv"

            def change(rows):
                rows[1]["team1_name"] = rows[0]["team1_name"]
                rows[1]["team2_name"] = rows[0]["team2_name"]
                rows[-1]["reference_classification"] = "verified_ranking_only"
            tamper(ref, change)
            report = validate_ranking_observations(data)
            self.assertFalse(report["ok"])
            self.assertTrue(any("duplicate dated matchup" in err
                                for err in report["errors"]))

    def test_hiroshima_qualifier_mislabel_is_rejected_even_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            copy_reference_fixture(data)
            ref = data / "competitions/2026/post_qualification_rank_observations.csv"

            def mislabel(rows):
                rows[-1]["reference_classification"] = "verified_ranking_only"
            tamper(ref, mislabel)
            report = validate_ranking_observations(data)
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "Hiroshima placement requires proof" in error
                for error in report["errors"]
            ))

    def test_unverified_name_map_remains_a_hard_gate(self):
        report = validate_ranking_observations(DATA)
        self.assertGreater(report["unmapped_group_count"], 0)
        with tempfile.TemporaryDirectory() as temp:
            copy_reference_fixture(Path(temp))
            with self.assertRaises(ValueError):
                build_verified_fmt022_2026_sidecar(
                    temp, competition_id="CMP000162",
                    school_id_by_official_name={"KBC": "OKI"},
                    locked_school_ids=["OKI", "A", "B", "C"],
                    qualification_locked_on="2026-08-11",
                )


if __name__ == "__main__":
    unittest.main()
