from __future__ import annotations

import csv
import unittest
from pathlib import Path

from phase2_engine import AnnualCompetitionInput, DataRepository, TournamentEngine
from phase2_engine.direct_access_quota import effective_qualifier_group_output_slots

DATA = Path(__file__).resolve().parents[1] / "data"
MISSING = "competitions/2026/hiroshima_qualification_missing_award_queue_2026.csv"


def _read(relative):
    with (DATA / relative).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Stage13E3G11HiroshimaAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.groups = {
            g["stage_group_id"]: g
            for g in cls.repo.groups_by_stage["STG000192"]
        }
        cls.west = cls.groups["SGR000140"]
        cls.entrants = sorted(set().union(*(
            cls.repo.group_school_ids(g, 2026)
            for g in cls.groups.values()
        )))
        cls.west_members = sorted(cls.repo.group_school_ids(cls.west, 2026))
        assert cls.entrants and cls.west_members
        cls.direct = cls.west_members[0]

    def annual(self, direct=()):
        return AnnualCompetitionInput(
            competition_id="CMP000135", year=2026,
            entrant_school_ids=list(self.entrants),
            rng_seed=2026100911,
            direct_main_entry_school_ids=list(direct),
        )

    def test_access_rule_uses_dynamically_derived_senbatsu_participants(self):
        rows = self.repo.access_rules("CMP000135")
        self.assertEqual(1, len(rows))
        self.assertEqual("ACR000023", rows[0]["access_rule_id"])
        self.assertEqual("national_invitational", rows[0]["source_event_kind"])
        self.assertEqual("all_matches", rows[0]["quota_mode"])
        self.assertEqual("excluded_from_bypassed_stage", rows[0]["bypassed_stage_participation_policy"])

    def test_west_7_slots_include_direct_and_are_not_8(self):
        group = self.west
        self.assertEqual(7, self.repo.param("STG000192", "output_slots", "SGR000140"))
        self.assertTrue(self.repo.param("STG000192", "group_quota_includes_direct_access", "SGR000140"))
        self.assertEqual(6, effective_qualifier_group_output_slots(
            self.repo, self.annual([self.direct]), group, 7, [self.direct]
        ))
        self.assertEqual(7, effective_qualifier_group_output_slots(
            self.repo, self.annual(), group, 7, []
        ))
        self.assertEqual(6, effective_qualifier_group_output_slots(
            self.repo, self.annual([self.direct]), group, 7, [self.direct, self.direct]
        ))
        pair = self.west_members[:2]
        self.assertEqual(5, effective_qualifier_group_output_slots(
            self.repo, self.annual(pair), group, 7, pair
        ))

    def test_other_districts_do_not_subtract_west_direct(self):
        for gid, expected in (("SGR000141", 7), ("SGR000142", 9), ("SGR000143", 9)):
            with self.subTest(group=gid):
                self.assertEqual(expected, effective_qualifier_group_output_slots(
                    self.repo, self.annual([self.direct]),
                    self.groups[gid], expected, [self.direct]
                ))

    def test_lazy_prepared_qualifier_excludes_direct_and_has_31_outputs(self):
        runtime = TournamentEngine(self.repo).prepare_qualifier_main_runtime(
            self.annual([self.direct])
        )
        group = next(g for g in runtime.qualifier_groups
                     if g.group["stage_group_id"] == "SGR000140")
        self.assertEqual(6, group.output_slots)
        self.assertNotIn(self.direct, runtime.qualifier_entrant_school_ids)
        self.assertEqual(31, sum(g.output_slots for g in runtime.qualifier_groups))

    def test_no_direct_still_has_32_qualifier_outputs(self):
        runtime = TournamentEngine(self.repo).prepare_qualifier_main_runtime(self.annual())
        group = next(g for g in runtime.qualifier_groups
                     if g.group["stage_group_id"] == "SGR000140")
        self.assertEqual(7, group.output_slots)
        self.assertEqual(32, sum(g.output_slots for g in runtime.qualifier_groups))

    def test_legacy_and_lazy_execute_with_exactly_32_distinct_teams(self):
        annual = self.annual([self.direct])
        legacy = TournamentEngine(self.repo).run(annual)
        lazy = TournamentEngine(self.repo).prepare_qualifier_main_runtime(annual).resolve_all()
        for run in (legacy, lazy):
            self.assertEqual(32, len(run.main_entrant_school_ids))
            self.assertEqual(32, len(set(run.main_entrant_school_ids)))
            self.assertEqual(1, run.main_entrant_school_ids.count(self.direct))
            self.assertNotIn(self.direct, run.stage_executions[0].entrant_school_ids)
            self.assertEqual(31, len(run.stage_executions[0].output_school_ids))
            self.assertEqual(6, len(run.stage_executions[0].metadata["group_outputs"]["SGR000140"]))

    def test_46_unproven_qualification_games_are_not_fabricated(self):
        queue = _read(MISSING)
        self.assertEqual(46, len(queue))
        self.assertEqual(46, len({(x["season"],x["district_code"],x["school_name"]) for x in queue}))
        self.assertTrue(all(x["status"] == "award_match_not_yet_documented" for x in queue))


if __name__ == "__main__":
    unittest.main()
