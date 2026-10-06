from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from phase2_engine.browse_views import (
    build_season_browse_views,
    load_season_calendar,
    save_season_browse_views,
)
from phase2_engine.models import (
    CompetitionOutcome,
    CompetitionRun,
    Match,
    StageExecution,
)
from phase2_engine.repository import DataRepository
from phase2_engine.season import SeasonExecution

ROOT = Path(__file__).resolve().parents[1]


class Stage12QBrowseViewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.calendar = load_season_calendar(ROOT / "data")
        ids = sorted(cls.repo.schools)[:6]
        cls.a, cls.b, cls.c, cls.d, cls.e, cls.f = ids

    def _run(self, competition_id, matches, champion, runner_up, seed):
        stage = StageExecution(
            stage_id=f"STG-{competition_id}",
            stage_code="MAIN",
            format_model_id="",
            entrant_school_ids=sorted({
                x for m in matches for x in (m.team1, m.team2) if x
            }),
            output_school_ids=[champion],
            matches=matches,
        )
        outcome = CompetitionOutcome(
            champion_school_id=champion,
            runner_up_school_id=runner_up,
            semifinalist_school_ids=[],
            quarterfinalist_school_ids=[],
            final_ranking_school_ids=[champion, runner_up],
            eliminated_by_round={},
            match_count=sum(not m.is_bye for m in matches),
            bye_count=sum(m.is_bye for m in matches),
            bracket_size=4,
        )
        entrants=sorted({x for m in matches for x in (m.team1,m.team2) if x})
        return CompetitionRun(
            competition_id=competition_id,
            year=2026,
            rng_seed=seed,
            entrant_school_ids=entrants,
            seed_assignments=[],
            stage_executions=[stage],
            main_entrant_school_ids=entrants,
            outcome=outcome,
        )

    def _season(self):
        run1 = self._run(
            "CMP000064",
            [
                Match(
                    match_id="Q-M1", competition_id="CMP000064",
                    stage_id="S1", stage_code="MAIN", phase_code="R1", round_no=1,
                    team1=self.a, team2=self.b, winner=self.a, loser=self.b,
                    metadata={"round_name": "1回戦"},
                ),
                Match(
                    match_id="Q-BYE", competition_id="CMP000064",
                    stage_id="S1", stage_code="MAIN", phase_code="R1", round_no=1,
                    team1=self.c, team2="", winner=self.c, loser="", is_bye=True,
                    metadata={"round_name": "1回戦"},
                ),
                Match(
                    match_id="Q-M2", competition_id="CMP000064",
                    stage_id="S1", stage_code="MAIN", phase_code="SF", round_no=2,
                    team1=self.a, team2=self.c, winner=self.a, loser=self.c,
                    metadata={"round_name": "準決勝"},
                ),
                Match(
                    match_id="Q-M3", competition_id="CMP000064",
                    stage_id="S1", stage_code="MAIN", phase_code="F", round_no=3,
                    team1=self.a, team2=self.d, winner=self.a, loser=self.d,
                    metadata={"round_name": "決勝"},
                ),
            ],
            self.a,
            self.d,
            2026100701,
        )
        run2 = self._run(
            "CMP000003",
            [
                Match(
                    match_id="Q-J1", competition_id="CMP000003",
                    stage_id="S2", stage_code="MAIN", phase_code="F", round_no=1,
                    team1=self.e, team2=self.f, winner=self.f, loser=self.e,
                    metadata={"round_name": "決勝"},
                ),
            ],
            self.f,
            self.e,
            2026100702,
        )
        return SeasonExecution(
            year=2026,
            rng_seed=2026100799,
            competition_runs={
                "CMP000064": run1,
                "CMP000003": run2,
            },
        )

    def test_three_view_types_are_built(self):
        views = build_season_browse_views(
            self._season(), self.repo, self.calendar
        )
        self.assertEqual(5, len(views.matches_by_date))
        self.assertEqual(2, len(views.competition_results))
        self.assertGreaterEqual(len(views.school_records), 6)

    def test_projected_dates_stay_inside_calendar(self):
        views = build_season_browse_views(
            self._season(), self.repo, self.calendar
        )
        fukuoka = [
            row for row in views.matches_by_date
            if row.competition_id == "CMP000064" and not row.is_bye
        ]
        calendar_row = next(
            row for row in self.calendar if row["competition_id"] == "CMP000064"
        )
        allowed = set(calendar_row["game_date_list"].split(";"))
        self.assertTrue(all(row.match_date in allowed for row in fukuoka))
        self.assertTrue(all(row.date_source == "projected_v1" for row in fukuoka))
        self.assertEqual(
            sorted(row.match_date for row in fukuoka),
            [row.match_date for row in fukuoka],
        )

    def test_undated_competition_is_preserved(self):
        views = build_season_browse_views(
            self._season(), self.repo, self.calendar
        )
        jingu = next(
            row for row in views.matches_by_date
            if row.competition_id == "CMP000003"
        )
        self.assertEqual("", jingu.match_date)
        self.assertEqual("undated", jingu.date_source)

    def test_bye_has_no_date_and_does_not_count_as_game(self):
        views = build_season_browse_views(
            self._season(), self.repo, self.calendar
        )
        bye = next(row for row in views.matches_by_date if row.match_id == "Q-BYE")
        self.assertEqual("", bye.match_date)
        self.assertEqual("bye", bye.date_source)
        record = next(row for row in views.school_records if row.school_id == self.c)
        self.assertEqual(1, record.games)
        self.assertEqual(0, record.wins)
        self.assertEqual(1, record.losses)

    def test_date_override_replaces_projection(self):
        calendar_row = next(
            row for row in self.calendar if row["competition_id"] == "CMP000064"
        )
        target = calendar_row["game_date_list"].split(";")[3]
        views = build_season_browse_views(
            self._season(),
            self.repo,
            self.calendar,
            match_date_overrides_by_competition={
                "CMP000064": {"Q-M1": target}
            },
        )
        row = next(x for x in views.matches_by_date if x.match_id == "Q-M1")
        self.assertEqual(target, row.match_date)
        self.assertEqual("override", row.date_source)

    def test_date_override_outside_calendar_is_rejected(self):
        with self.assertRaises(ValueError):
            build_season_browse_views(
                self._season(),
                self.repo,
                self.calendar,
                match_date_overrides_by_competition={
                    "CMP000064": {"Q-M1": "2099-01-01"}
                },
            )

    def test_invalid_iso_date_override_is_rejected(self):
        with self.assertRaises(ValueError):
            build_season_browse_views(
                self._season(),
                self.repo,
                self.calendar,
                match_date_overrides_by_competition={
                    "CMP000003": {"Q-J1": "2026-99-99"}
                },
            )

    def test_undated_calendar_override_must_stay_in_period(self):
        with self.assertRaises(ValueError):
            build_season_browse_views(
                self._season(),
                self.repo,
                self.calendar,
                match_date_overrides_by_competition={
                    "CMP000003": {"Q-J1": "2026-12-01"}
                },
            )

    def test_competition_summary_has_champion_and_counts(self):
        views = build_season_browse_views(
            self._season(), self.repo, self.calendar
        )
        row = next(
            x for x in views.competition_results
            if x.competition_id == "CMP000064"
        )
        self.assertEqual(self.a, row.champion_id)
        self.assertEqual(self.repo.team(self.a).display_name, row.champion_name)
        self.assertEqual(4, row.match_count)
        self.assertEqual(3, row.played_match_count)
        self.assertEqual(1, row.bye_count)
        self.assertGreater(row.total_runs, 0)

    def test_school_record_aggregates_wins_runs_and_titles(self):
        views = build_season_browse_views(
            self._season(), self.repo, self.calendar
        )
        row = next(x for x in views.school_records if x.school_id == self.a)
        self.assertEqual(3, row.games)
        self.assertEqual(3, row.wins)
        self.assertEqual(0, row.losses)
        self.assertEqual(1.0, row.win_pct)
        self.assertEqual(1, row.titles)
        self.assertGreater(row.runs_for, row.runs_against)
        self.assertEqual(1, row.competition_count)

    def test_saved_csvs_have_expected_contracts(self):
        season = self._season()
        with tempfile.TemporaryDirectory() as td:
            paths = save_season_browse_views(
                season, self.repo, ROOT / "data", td
            )
            with Path(paths["matches_by_date_csv"]).open(
                encoding="utf-8-sig", newline=""
            ) as f:
                matches = list(csv.DictReader(f))
            with Path(paths["competition_results_csv"]).open(
                encoding="utf-8-sig", newline=""
            ) as f:
                competitions = list(csv.DictReader(f))
            with Path(paths["school_records_csv"]).open(
                encoding="utf-8-sig", newline=""
            ) as f:
                schools = list(csv.DictReader(f))
        self.assertEqual(5, len(matches))
        self.assertEqual(2, len(competitions))
        self.assertGreaterEqual(len(schools), 6)
        self.assertIn("match_date", matches[0])
        self.assertIn("champion_name", competitions[0])
        self.assertIn("win_pct", schools[0])


if __name__ == "__main__":
    unittest.main()
