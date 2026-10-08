from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from phase2_engine import DataRepository
from phase2_engine.browse_repository import BrowseRepository
from phase2_engine.competition_schedule_runtime import ScheduledCompetitionRuntime
from phase2_engine.post_qualification_ranking import RankingOnlyEventRuntime
from phase2_engine.post_qualification_schedule import ScheduledRankingSidecar
from phase2_engine.ranking_school_reconciliation_2026 import (
    audit_ranking_school_mapping_2026,
    build_verified_fmt025_2026_daily_sidecar,
    load_ranking_school_mapping_2026,
)


DATA = Path(__file__).resolve().parents[1] / "data"


class CompletedMainRuntime:
    is_complete = True


def historical_west_shizuoka_pair():
    mappings = [
        row for row in load_ranking_school_mapping_2026(DATA)
        if row["competition_id"] == "CMP000111"
        and row["stage_group_id"] == "SGR000105"
        and row["mapping_status"] == "mapped_same_area_ranking_reference"
    ]
    locked = sorted({
        row[key] for row in mappings
        for key in ("team1_school_id", "team2_school_id")
    })
    kwargs = dict(
        data_dir=DATA,
        competition_id="CMP000111",
        stage_group_id="SGR000105",
        locked_school_ids=locked,
        qualification_locked_on="2026-04-03",
    )
    return (
        build_verified_fmt025_2026_daily_sidecar(
            **kwargs, match_date="2026-04-04"
        ),
        build_verified_fmt025_2026_daily_sidecar(
            **kwargs, match_date="2026-04-11"
        ),
    )


def scheduled_competition():
    return ScheduledCompetitionRuntime(
        repo=DataRepository(DATA), runtime=CompletedMainRuntime(),
        competition_id="CMP000111", competition_name="静岡春",
        calendar_dates=[], stage_date_lists={},
        calendar_status="official_schedule",
    )


def winners_on_date(sidecar, target):
    return {row["match_id"]: row["team1_id"]
            for row in sidecar.matches_for_date(target)}


def legacy_event():
    state = RankingOnlyEventRuntime.create(
        competition_id="CMP000111", stage_id="STG000182",
        stage_code="BRANCH_QUALIFIER",
        group_id="SGR000105", format_model_id="FMT025",
        mode="pairwise_deciders", locked_school_ids=["A", "B"],
        pairings=(("A", "B"),),
    )
    return ScheduledRankingSidecar.create(
        state, qualification_locked_on="2026-03-31",
        match_dates=["2026-04-01"],
    )


class Stage13E3G5MultiInstanceRankingTests(unittest.TestCase):
    def test_two_dates_get_different_stable_instance_and_match_ids(self):
        first, second = historical_west_shizuoka_pair()
        self.assertEqual("D20260404", first.event.event_id)
        self.assertEqual("D20260411", second.event.event_id)
        self.assertEqual("SGR000105@D20260404", first.instance_key)
        self.assertEqual("SGR000105@D20260411", second.instance_key)
        ids_a = {row["match_id"] for row in first.matches_for_date("2026-04-04")}
        ids_b = {row["match_id"] for row in second.matches_for_date("2026-04-11")}
        self.assertTrue(ids_a)
        self.assertTrue(ids_b)
        self.assertFalse(ids_a & ids_b)
        self.assertTrue(all("D20260404" in mid for mid in ids_a))
        self.assertTrue(all("D20260411" in mid for mid in ids_b))

    def test_same_group_twice_in_scheduler_with_independent_results(self):
        first, second = historical_west_shizuoka_pair()
        runtime = scheduled_competition()
        runtime.attach_ranking_sidecar(first)
        runtime.attach_ranking_sidecar(second)
        self.assertEqual(2, len(runtime.ranking_sidecars))
        self.assertEqual(len(first.matches_for_date("2026-04-04")),
                         len(runtime.matches_for_date("2026-04-04")))
        self.assertEqual(len(second.matches_for_date("2026-04-11")),
                         len(runtime.matches_for_date("2026-04-11")))
        winners = winners_on_date(first, "2026-04-04")
        runtime.resolve_ranking_date(
            "2026-04-04", winners_by_group={first.instance_key: winners}
        )
        self.assertTrue(first.is_complete)
        self.assertFalse(second.is_complete)
        self.assertTrue(runtime.is_complete)
        runtime.resolve_ranking_date(
            "2026-04-11",
            winners_by_group={second.instance_key: winners_on_date(
                second, "2026-04-11"
            )},
        )
        self.assertTrue(second.is_complete)
        self.assertTrue(runtime.is_complete)

    def test_snapshot_roundtrip_has_both_group_instances(self):
        first, second = historical_west_shizuoka_pair()
        runtime = scheduled_competition()
        runtime.attach_ranking_sidecar(first)
        runtime.attach_ranking_sidecar(second)
        runtime.resolve_ranking_date(
            "2026-04-04", winners_by_group={
                first.instance_key: winners_on_date(first, "2026-04-04")
            }
        )
        payload = json.loads(json.dumps(runtime.ranking_snapshot()))
        restored = scheduled_competition()
        restored.restore_ranking_snapshot(payload)
        self.assertEqual(payload, restored.ranking_snapshot())
        self.assertTrue(restored.ranking_sidecars[first.instance_key].is_complete)
        self.assertFalse(restored.ranking_sidecars[second.instance_key].is_complete)
        restored.resolve_ranking_date(
            "2026-04-11", winners_by_group={
                second.instance_key: winners_on_date(second, "2026-04-11")
            }
        )
        self.assertTrue(restored.is_complete)

    def test_duplicate_instance_and_tampered_key_are_rejected(self):
        first, second = historical_west_shizuoka_pair()
        runtime = scheduled_competition()
        runtime.attach_ranking_sidecar(first)
        with self.assertRaisesRegex(ValueError, "already attached"):
            runtime.attach_ranking_sidecar(first)
        payload = json.loads(json.dumps({second.instance_key: second.snapshot()}))
        payload["SGR000105@WRONG"] = payload.pop(second.instance_key)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            runtime.restore_ranking_snapshot(payload)
        self.assertIn(first.instance_key, runtime.ranking_sidecars)

    def test_invalid_event_ids_cannot_inject_match_id_delimiters(self):
        for bad in ("../2026", "with spaces", "a@b", "あ", "x" * 65):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "event_id"):
                RankingOnlyEventRuntime.create(
                    competition_id="CMP000111", stage_id="STG000182",
                    stage_code="BRANCH_QUALIFIER",
                    group_id="SGR000105", format_model_id="FMT025",
                    mode="pairwise_deciders",
                    locked_school_ids=["A", "B"],
                    pairings=[("A", "B")], event_id=bad,
                )

    def test_legacy_group_only_snapshot_and_match_id_remain_unchanged(self):
        old = legacy_event()
        self.assertEqual("SGR000105", old.instance_key)
        self.assertEqual(
            "STG000182-SGR000105-POST_RANK-R1-01",
            old.matches_for_date("2026-04-01")[0]["match_id"],
        )
        payload = old.snapshot()
        self.assertNotIn("event_id", payload["event"])
        self.assertNotIn("ranking_instance_id", payload["matches"][0])
        restored = ScheduledRankingSidecar.from_snapshot(
            json.loads(json.dumps(payload))
        )
        self.assertEqual(payload, restored.snapshot())
        runtime = scheduled_competition()
        runtime.attach_ranking_sidecar(old)
        newer, _ = historical_west_shizuoka_pair()
        runtime.attach_ranking_sidecar(newer)
        self.assertEqual(2, len(runtime.ranking_sidecars))
        self.assertTrue(runtime.is_complete)

    def test_sqlite_saves_two_days_without_overwriting_other_day(self):
        with tempfile.TemporaryDirectory() as temp:
            db = BrowseRepository(Path(temp) / "ranking.sqlite3")
            first, second = historical_west_shizuoka_pair()
            db.save_ranking_sidecar(2026, first)
            db.save_ranking_sidecar(2026, second)
            initial = db.competition_ranking_matches(2026, "CMP000111")
            self.assertEqual(
                len(first.matches_for_date("2026-04-04")) +
                len(second.matches_for_date("2026-04-11")), len(initial)
            )
            self.assertEqual(
                {"D20260404", "D20260411"},
                {row["ranking_instance_id"] for row in initial},
            )
            first.resolve_date("2026-04-04", winners_on_date(first, "2026-04-04"))
            db.save_ranking_sidecar(2026, first)
            self.assertEqual(
                len(second.matches_for_date("2026-04-11")),
                len(db.ranking_matches_on_date(2026, "2026-04-11")),
            )
            self.assertTrue(all(row["status"] == "pending" for row
                                in db.ranking_matches_on_date(2026, "2026-04-11")))
            self.assertTrue(all(row["status"] == "completed" for row
                                in db.ranking_matches_on_date(2026, "2026-04-04")))
            restored_a = db.load_ranking_sidecar(
                2026, "CMP000111", "SGR000105", "D20260404"
            )
            restored_b = db.load_ranking_sidecar(
                2026, "CMP000111", "SGR000105", "D20260411"
            )
            self.assertEqual(first.snapshot(), restored_a.snapshot())
            self.assertEqual(second.snapshot(), restored_b.snapshot())
            self.assertEqual(
                [first.instance_key, second.instance_key],
                [s.instance_key for s in db.list_ranking_sidecars(
                    2026, "CMP000111", "SGR000105"
                )],
            )
            db.save_ranking_sidecar(2026, second)
            self.assertTrue(all(row["status"] == "completed" for row
                                in db.ranking_matches_on_date(2026, "2026-04-04")))

    def test_migration_of_old_db_keeps_legacy_saved_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.sqlite3"
            old = legacy_event()
            row = old.snapshot()["matches"][0]
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    CREATE TABLE ranking_event_snapshots (
                        year INTEGER NOT NULL, competition_id TEXT NOT NULL,
                        group_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                        PRIMARY KEY(year,competition_id,group_id)
                    );
                    CREATE TABLE ranking_matches (
                        year INTEGER NOT NULL, competition_id TEXT NOT NULL,
                        group_id TEXT NOT NULL, match_id TEXT NOT NULL,
                        match_date TEXT NOT NULL, stage_code TEXT NOT NULL,
                        phase_code TEXT NOT NULL, round_no INTEGER NOT NULL,
                        team1_id TEXT NOT NULL, team2_id TEXT NOT NULL,
                        winner_id TEXT NOT NULL, loser_id TEXT NOT NULL,
                        team1_score INTEGER, team2_score INTEGER,
                        status TEXT NOT NULL,
                        qualifier_effect TEXT NOT NULL CHECK(qualifier_effect='none'),
                        PRIMARY KEY(year,competition_id,match_id)
                    );
                """)
                connection.execute(
                    "INSERT INTO ranking_event_snapshots VALUES(?,?,?,?)",
                    (2026, old.event.competition_id, old.event.group_id,
                     json.dumps(old.snapshot())),
                )
                connection.execute(
                    "INSERT INTO ranking_matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (2026, old.event.competition_id, old.event.group_id,
                     row["match_id"], row["match_date"], row["stage_code"],
                     row["phase_code"], row["round_no"], row["team1_id"],
                     row["team2_id"], row["winner_id"], row["loser_id"],
                     row["team1_score"], row["team2_score"], row["status"],
                     row["qualifier_effect"]),
                )
            db = BrowseRepository(path)
            db.initialize_schema()
            self.assertEqual(old.snapshot(), db.load_ranking_sidecar(
                2026, "CMP000111", "SGR000105"
            ).snapshot())
            legacy = db.ranking_matches_on_date(2026, "2026-04-01")
            self.assertEqual(1, len(legacy))
            self.assertEqual("", legacy[0]["ranking_instance_id"])
            new, _ = historical_west_shizuoka_pair()
            db.save_ranking_sidecar(2026, new)
            self.assertEqual(1, len(db.ranking_matches_on_date(2026, "2026-04-01")))
            self.assertEqual(2, len(db.list_ranking_sidecars(
                2026, "CMP000111", "SGR000105"
            )))
            db.save_ranking_sidecar(2026, old)
            self.assertEqual(len(new.matches_for_date("2026-04-04")),
                             len(db.ranking_matches_on_date(2026, "2026-04-04")))

    def test_verified_cross_area_hold_is_unchanged(self):
        report = audit_ranking_school_mapping_2026(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual("RR20260023", report["cross_area_review"][0]["reference_id"])
        self.assertEqual(
            {"excluded_qualification_decider": 3,
             "review_cross_area_fixture": 1},
            {name: count for name, count in report["classification_counts"].items()
             if name in ("excluded_qualification_decider",
                         "review_cross_area_fixture")},
        )


if __name__ == "__main__":
    unittest.main()
