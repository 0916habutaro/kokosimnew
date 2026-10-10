from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_qualifier_bridge import (
    prepare_future_fmt001_qualifier_preview,
)
from phase2_engine.future_season_blueprint import build_future_season_blueprint
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]


class Stage43F3FutureQualifierBridgeTests(unittest.TestCase):
    """Real FMT001 Hokkaido autumn branch -> MAIN, 2027 sandbox only."""

    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.seed = 2026100701
        cls.year = 2027
        cls.competition_id = "CMP000013"
        cls.blueprint = build_future_season_blueprint(
            ROOT / "data", year=2027, base_seed=cls.seed,
        )
        cls.stage = next(
            s for s in cls.repo.stages(cls.competition_id)
            if s["stage_code"] == "BRANCH_QUALIFIER"
        )
        cls.groups = cls.repo.groups_by_stage[cls.stage["stage_id"]]
        assert len(cls.groups) == 10
        cls.groups_explicit = {}
        schools = sorted(
            sid for sid in cls.repo.school_to_program
            if cls.repo.schools[sid]["prefecture_code"] == "01"
        )
        pos = 0
        for group in cls.groups:
            gid = group["stage_group_id"]
            slots = cls.repo.param(
                cls.stage["stage_id"], "output_slots", gid,
                int(group["advance_slots_to_next"]),
            )
            cls.groups_explicit[gid] = schools[pos:pos + 2 * slots]
            pos += 2 * slots
        cls.entrants = schools[:pos]
        cls.total_qualifiers = sum(
            cls.repo.param(
                cls.stage["stage_id"], "output_slots", g["stage_group_id"],
                int(g["advance_slots_to_next"]),
            )
            for g in cls.groups
        )
        assert cls.total_qualifiers == 20
        assert len(cls.entrants) == 40
        cls.temp = tempfile.TemporaryDirectory()
        cls.archive = CareerRosterArchive(
            Path(cls.temp.name) / "saved_rosters.sqlite3"
        )
        generator = PlayerRosterGenerator()
        for sid in cls.entrants:
            roster = generator.generate_for_school_id(
                cls.repo, sid, 2026, cls.seed,
            )
            cls.archive.save_initial_roster(roster)
            cls.archive.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=cls.seed,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def prepare(self, *, blueprint=None, entrants=None, groups=None,
                archive=None, career_seed=None, competition_id=None):
        return prepare_future_fmt001_qualifier_preview(
            blueprint=self.blueprint if blueprint is None else blueprint,
            competition_id=self.competition_id if competition_id is None
                           else competition_id,
            entrant_school_ids=self.entrants if entrants is None else entrants,
            group_entrant_school_ids=self.groups_explicit if groups is None else groups,
            roster_archive=self.archive if archive is None else archive,
            repo=self.repo,
            career_seed=self.seed if career_seed is None else career_seed,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def test_all_ten_groups_are_explicit_and_no_2026_memberships_loaded(self):
        p = self.prepare()
        self.assertEqual(2027, p.year)
        self.assertEqual(40, len(p.annual.entrant_school_ids))
        self.assertEqual(10, len(p.annual.group_entrant_school_ids))
        self.assertEqual(
            self.groups_explicit, p.annual.group_entrant_school_ids,
        )
        self.assertFalse(p.scheduled.runtime.main_runtime)
        self.assertEqual(
            "2027-09-15", p.scheduled.next_scheduled_date()
        )
        rows = p.scheduled.matches_for_date("2027-09-15")
        self.assertEqual(20, len(rows))
        self.assertTrue(all(
            row["stage_code"] == "BRANCH_QUALIFIER"
            and row["date_source"] == "game_projection_v1"
            for row in rows
        ))
        self.assertFalse(p.snapshot()["official_competition"])
        self.assertFalse(p.snapshot()["persistent_game_session"])

    def test_qualifier_winners_enter_main_and_complete_real_2027_game(self):
        p = self.prepare()
        first = p.play_next_date()
        self.assertEqual(20, first["played_match_count"])
        self.assertEqual("2027-09-15", first["date"])
        self.assertFalse(first["is_complete"])
        self.assertTrue(p.scheduled.runtime.qualifier_complete)
        self.assertIsNotNone(p.scheduled.runtime.main_runtime)
        self.assertEqual(20, len(p.scheduled.runtime.main_entrant_school_ids))
        self.assertEqual(
            "2027-10-07", p.scheduled.next_scheduled_date(),
        )
        all_qualified = set(p.scheduled.runtime.main_entrant_school_ids)
        for group in p.scheduled.runtime.qualifier_groups:
            self.assertEqual(group.output_slots, len(group.output_school_ids()))
            self.assertTrue(
                set(group.output_school_ids()).issubset(
                    self.groups_explicit[group.group["stage_group_id"]]
                )
            )
        self.assertTrue(all_qualified.issubset(self.entrants))
        self.assertEqual(
            20, len(p.scheduled.completed_results()),
        )
        count = 1
        while not p.scheduled.is_complete and count < 24:
            item = p.play_next_date()
            self.assertEqual("game_projection_v1", item["date_source"])
            count += 1
        self.assertTrue(p.scheduled.is_complete)
        self.assertEqual(39, len(p.scheduled.completed_results()))
        run = p.scheduled.to_competition_run()
        self.assertEqual(2027, run.year)
        self.assertEqual(20, len(run.main_entrant_school_ids))
        self.assertIn(run.outcome.champion_school_id, all_qualified)
        self.assertEqual(2, len(run.stage_executions))
        self.assertEqual(
            39, len([
                x for x in p.scheduled.matches.values()
                if x.status == "completed"
            ])
        )
        ability_rows = [
            m for m in p.scheduled.matches.values() if m.ability_detail
        ]
        self.assertEqual(39, len(ability_rows))
        for rec in ability_rows:
            self.assertEqual("game_projection_v1", rec.date_source)
            self.assertEqual(2027, rec.ability_detail["reference_year"])
            self.assertIsNotNone(rec.ability_detail["inning_scores"])
            roster_ids = {
                p.player_id
                for sid in (rec.team1_id, rec.team2_id)
                for p in self.archive.roster(2027, sid).players
            }
            batter_ids = {
                row["player_id"]
                for row in rec.ability_detail["batter_stats"]
            }
            self.assertTrue(batter_ids <= roster_ids)

    def test_seed_replay_same_group_draw(self):
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first.scheduled.public_snapshot(),
                         second.scheduled.public_snapshot())

    def test_group_coverage_is_explicit_and_complete(self):
        for bad in (
            {k: v for k, v in self.groups_explicit.items() if k != self.groups[0]["stage_group_id"]},
            {**self.groups_explicit, "SGR-UNKNOWN": ["ANY"]},
        ):
            with self.subTest(keys=sorted(bad)), self.assertRaisesRegex(
                FutureCompetitionNotReady, "all qualifier groups"
            ):
                self.prepare(groups=bad)

    def test_duplicate_school_across_groups_and_unassigned_rejected(self):
        group1, group2 = self.groups[:2]
        bad = deepcopy(self.groups_explicit)
        bad[group2["stage_group_id"]][0] = bad[group1["stage_group_id"]][0]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare(groups=bad)
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare(entrants=self.entrants[:-1])

    def test_unknown_or_other_prefecture_school_rejected(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "non-hardball"):
            self.prepare(entrants=self.entrants[:-1] + ["UNKNOWN-SCHOOL"])
        other = next(
            sid for sid in self.repo.school_to_program
            if self.repo.schools[sid]["prefecture_code"] != "01"
        )
        with self.assertRaisesRegex(FutureCompetitionNotReady, "prefecture"):
            self.prepare(entrants=self.entrants[:-1] + [other])

    def test_insufficient_group_members_rejected(self):
        bad = deepcopy(self.groups_explicit)
        group = next(g for g in self.groups if int(g["advance_slots_to_next"]) > 1)
        bad[group["stage_group_id"]] = bad[group["stage_group_id"]][:1]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "insufficient school"):
            self.prepare(groups=bad)

    def test_missing_roster_and_wrong_career_seed_rejected(self):
        separate = CareerRosterArchive(
            Path(self.temp.name) / "other.sqlite3"
        )
        with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters missing"):
            self.prepare(archive=separate)
        with self.assertRaisesRegex(FutureCompetitionNotReady, "rosters missing"):
            self.prepare(career_seed=self.seed + 1)

    def test_premain_calendar_missing_or_wrong_year_fails_closed(self):
        bad = deepcopy(self.blueprint)
        row = next(x for x in bad["stage_calendars"]
                   if x["competition_id"] == self.competition_id)
        row["date_list"] = ""
        with self.assertRaisesRegex(FutureCompetitionNotReady, "qualifier calendar"):
            self.prepare(blueprint=bad)
        bad = deepcopy(self.blueprint)
        row = next(x for x in bad["stage_calendars"]
                   if x["competition_id"] == self.competition_id)
        row["date_list"] = "2026-09-15"
        with self.assertRaisesRegex(FutureCompetitionNotReady, "wrong year"):
            self.prepare(blueprint=bad)

    def test_missing_main_dates_and_undated_gap_rejected(self):
        bad = deepcopy(self.blueprint)
        row = next(x for x in bad["calendars"]
                   if x["competition_id"] == self.competition_id)
        row["game_date_list"] = "2027-10-07;2027-10-08"
        with self.assertRaisesRegex(FutureCompetitionNotReady, "MAIN days"):
            self.prepare(blueprint=bad)
        bad = deepcopy(self.blueprint)
        row = next(x for x in bad["calendars"]
                   if x["competition_id"] == self.competition_id)
        row["game_date_list"] = "2027-09-15;2027-09-16;2027-09-17;2027-09-18;2027-09-19"
        with self.assertRaisesRegex(FutureCompetitionNotReady, "finish before"):
            self.prepare(blueprint=bad)

    def test_unresolved_external_direct_access_stays_blocked(self):
        with self.assertRaisesRegex(FutureCompetitionNotReady, "external access"):
            self.prepare(competition_id="CMP000004")

    def test_do_not_accept_official_calendar_or_selection(self):
        bad = deepcopy(self.blueprint)
        bad["official_calendar"] = True
        with self.assertRaisesRegex(FutureCompetitionNotReady, "provenance"):
            self.prepare(blueprint=bad)
        bad = deepcopy(self.blueprint)
        row = next(x for x in bad["stage_calendars"]
                   if x["competition_id"] == self.competition_id)
        row["real_world_verified"] = True
        with self.assertRaisesRegex(FutureCompetitionNotReady, "not provisional"):
            self.prepare(blueprint=bad)

    def test_missing_school_area_mapping_never_uses_2026_fallback(self):
        # The participant belongs to the competition but has no explicit
        # group mapping. We must reject instead of consulting 2026 affiliation.
        last = self.entrants[-1]
        bad = deepcopy(self.groups_explicit)
        for gid in bad:
            if last in bad[gid]:
                bad[gid].remove(last)
                break
        with self.assertRaisesRegex(FutureCompetitionNotReady, "partition"):
            self.prepare(groups=bad)


if __name__ == "__main__":
    unittest.main()
