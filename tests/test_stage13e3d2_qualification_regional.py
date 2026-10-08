from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import unittest

from phase2_engine import (
    AnnualCompetitionInput,
    CompetitionOutcome,
    CompetitionRun,
    DataRepository,
    LiveSeasonDependencyRuntimeState,
    SeasonExecution,
    SeasonOrchestrator,
    StructuralAnnualInputFactory,
    TournamentEngine,
)
from phase2_engine.browse_views import (
    load_season_calendar,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


@dataclass
class _CompletedScheduledStub:
    run: CompetitionRun

    @property
    def is_complete(self):
        return True

    def to_competition_run(self):
        return self.run


class Stage13E3D2QualificationRegionalTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.year = 2026
        cls.seed = 2026100821
        cls.factory = StructuralAnnualInputFactory(
            cls.repo,
            DATA_ROOT,
            cls.seed,
        )
        cls.calendar_rows = load_season_calendar(
            DATA_ROOT
        )
        cls.calendar_by_comp = {
            row["competition_id"]: row
            for row in cls.calendar_rows
        }

    @staticmethod
    def _date_values(row):
        return [
            value
            for value in (
                row.get("game_date_list")
                or ""
            ).split(";")
            if value
        ]

    def _summer_annual(
        self,
        competition_id: str,
        rng_seed: int,
    ) -> AnnualCompetitionInput:
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=self.year,
            entrant_school_ids=(
                self.factory.summer_area_school_ids(
                    competition_id,
                    self.year,
                )
            ),
            rng_seed=rng_seed,
        )

    def _prefectural_annual(
        self,
        competition_id: str,
        rng_seed: int,
    ) -> AnnualCompetitionInput:
        return self.factory.build_prefectural(
            competition_id,
            self.year,
            rng_seed=rng_seed,
        )

    def _fake_run(
        self,
        competition_id: str,
        ranking: list[str],
    ) -> CompetitionRun:
        champion = ranking[0]
        runner = (
            ranking[1]
            if len(ranking) > 1
            else ranking[0]
        )
        outcome = CompetitionOutcome(
            champion_school_id=champion,
            runner_up_school_id=runner,
            semifinalist_school_ids=ranking[2:4],
            quarterfinalist_school_ids=ranking[4:8],
            final_ranking_school_ids=list(ranking),
            eliminated_by_round={},
            match_count=max(len(ranking) - 1, 0),
            bye_count=0,
            bracket_size=max(len(ranking), 1),
        )
        return CompetitionRun(
            competition_id=competition_id,
            year=self.year,
            rng_seed=self.seed,
            entrant_school_ids=list(ranking),
            seed_assignments=[],
            stage_executions=[],
            main_entrant_school_ids=list(ranking),
            outcome=outcome,
        )

    def _school_ids_for_prefecture(
        self,
        prefecture_code: str,
        count: int = 5,
    ) -> list[str]:
        ids = sorted(
            school_id
            for school_id, row
            in self.repo.schools.items()
            if row.get("prefecture_code")
            == prefecture_code
        )
        self.assertGreaterEqual(len(ids), count)
        return ids[:count]

    def test_49_local_champions_activate_summer_national(
        self,
    ):
        source_ids = [
            f"CMP{number:06d}"
            for number in range(23, 72)
        ]
        templates = [
            self._summer_annual(
                cid,
                self.seed + index,
            )
            for index, cid in enumerate(
                source_ids,
                start=1,
            )
        ]
        national_seed = self.seed + 1000
        templates.append(
            AnnualCompetitionInput(
                competition_id="CMP000002",
                year=self.year,
                entrant_school_ids=[],
                rng_seed=national_seed,
            )
        )
        calendars = [
            self.calendar_by_comp[cid]
            for cid in (
                source_ids + ["CMP000002"]
            )
        ]
        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=templates,
                calendar_rows=calendars,
                rng_seed=self.seed,
                start_date="2026-06-01",
            )
        )

        self.assertNotIn(
            "CMP000002",
            state.competitions,
        )
        self.assertEqual(
            "qualification",
            state.dependency_state(
                "CMP000002"
            )["dependency_family"],
        )
        last_source_date = max(
            max(
                self._date_values(
                    self.calendar_by_comp[cid]
                )
            )
            for cid in source_ids
        )
        before = (
            date.fromisoformat(last_source_date)
            - timedelta(days=1)
        ).isoformat()
        state.advance_through(before)
        self.assertNotIn(
            "CMP000002",
            state.competitions,
        )

        state.advance_through(
            last_source_date
        )
        self.assertIn(
            "CMP000002",
            state.competitions,
        )
        self.assertEqual(
            49,
            len(state.qualification_resolutions),
        )
        self.assertTrue(all(
            row.status == "PASS"
            for row in state.qualification_resolutions
        ))

        ordered_resolutions = sorted(
            state.qualification_resolutions,
            key=lambda row: row.rule_id,
        )
        entrants = [
            row.resolved_school_ids[0]
            for row in ordered_resolutions
        ]
        self.assertEqual(
            49,
            len(set(entrants)),
        )
        self.assertEqual(
            entrants,
            state.competitions[
                "CMP000002"
            ].runtime.entrant_school_ids,
        )

        state.advance_through("2026-08-22")
        live = state.completed_runs()[
            "CMP000002"
        ]
        legacy = TournamentEngine(
            self.repo
        ).run(
            AnnualCompetitionInput(
                competition_id="CMP000002",
                year=self.year,
                entrant_school_ids=entrants,
                rng_seed=national_seed,
            )
        )
        self.assertEqual(
            legacy.to_dict(),
            live.to_dict(),
        )

    def test_shikoku_prefectural_rankings_activate_spring_regional(
        self,
    ):
        source_ids = [
            "CMP000139",
            "CMP000141",
            "CMP000143",
            "CMP000145",
        ]
        templates = [
            self._prefectural_annual(
                cid,
                self.seed + index,
            )
            for index, cid in enumerate(
                source_ids,
                start=200,
            )
        ]
        regional_seed = self.seed + 300
        templates.append(
            AnnualCompetitionInput(
                competition_id="CMP000011",
                year=self.year,
                entrant_school_ids=[],
                rng_seed=regional_seed,
            )
        )
        calendars = [
            self.calendar_by_comp[cid]
            for cid in (
                source_ids + ["CMP000011"]
            )
        ]
        state = (
            LiveSeasonDependencyRuntimeState
            .from_annual_templates(
                engine=TournamentEngine(
                    self.repo
                ),
                repo=self.repo,
                annual_templates=templates,
                calendar_rows=calendars,
                rng_seed=self.seed,
                start_date="2026-03-20",
            )
        )

        last_source_date = max(
            max(
                self._date_values(
                    self.calendar_by_comp[cid]
                )
            )
            for cid in source_ids
        )
        state.advance_through(
            (
                date.fromisoformat(
                    last_source_date
                )
                - timedelta(days=1)
            ).isoformat()
        )
        self.assertNotIn(
            "CMP000011",
            state.competitions,
        )
        state.advance_through(
            last_source_date
        )
        self.assertIn(
            "CMP000011",
            state.competitions,
        )
        self.assertEqual(
            4,
            len(state.regional_feeder_resolutions),
        )
        self.assertTrue(all(
            row.status == "PASS"
            and len(row.resolved_school_ids) == 2
            for row
            in state.regional_feeder_resolutions
        ))

        source_runs = {
            cid: state.completed_runs()[cid]
            for cid in source_ids
        }
        legacy_season = SeasonExecution(
            year=self.year,
            rng_seed=self.seed,
            competition_runs=source_runs,
        )
        legacy_orchestrator = SeasonOrchestrator(
            self.repo,
            DATA_ROOT,
        )
        (
            legacy_entrants,
            _,
            legacy_playoffs,
        ) = (
            legacy_orchestrator
            ._resolve_regional_feeders(
                "CMP000011",
                self.year,
                self.seed,
                legacy_season,
            )
        )
        self.assertEqual([], legacy_playoffs)
        self.assertEqual(
            legacy_entrants,
            state.competitions[
                "CMP000011"
            ].runtime.entrant_school_ids,
        )
        self.assertEqual(
            8,
            len(legacy_entrants),
        )

        state.advance_through("2026-05-02")
        live = state.completed_runs()[
            "CMP000011"
        ]
        legacy = TournamentEngine(
            self.repo
        ).run(
            AnnualCompetitionInput(
                competition_id="CMP000011",
                year=self.year,
                entrant_school_ids=legacy_entrants,
                rng_seed=regional_seed,
            )
        )
        self.assertEqual(
            legacy.to_dict(),
            live.to_dict(),
        )

    def test_kinki_playoff_candidates_match_legacy_resolver(
        self,
    ):
        source_prefectures = {
            "CMP000118": "25",
            "CMP000120": "26",
            "CMP000122": "27",
            "CMP000124": "28",
            "CMP000126": "29",
            "CMP000128": "30",
        }
        runs = {
            cid: self._fake_run(
                cid,
                self._school_ids_for_prefecture(
                    pcode,
                    5,
                ),
            )
            for cid, pcode
            in source_prefectures.items()
        }
        legacy_season = SeasonExecution(
            year=self.year,
            rng_seed=self.seed,
            competition_runs=runs,
        )
        orchestrator = SeasonOrchestrator(
            self.repo,
            DATA_ROOT,
        )
        (
            legacy_entrants,
            legacy_resolutions,
            legacy_playoffs,
        ) = orchestrator._resolve_regional_feeders(
            "CMP000019",
            self.year,
            self.seed,
            legacy_season,
        )

        feeder_rows = (
            LiveSeasonDependencyRuntimeState
            ._read_csv(
                DATA_ROOT,
                "regional_feeder_rules.csv",
            )
        )
        playoff_rows = (
            LiveSeasonDependencyRuntimeState
            ._read_csv(
                DATA_ROOT,
                "regional_qualification_playoffs.csv",
            )
        )
        live = LiveSeasonDependencyRuntimeState(
            engine=TournamentEngine(self.repo),
            repo=self.repo,
            year=self.year,
            rng_seed=self.seed,
            annual_templates={
                "CMP000019": AnnualCompetitionInput(
                    competition_id="CMP000019",
                    year=self.year,
                    entrant_school_ids=[],
                    rng_seed=self.seed + 400,
                )
            },
            regional_feeder_rules={
                "CMP000019": [
                    row
                    for row in feeder_rows
                    if row[
                        "destination_competition_id"
                    ] == "CMP000019"
                ]
            },
            regional_playoffs={
                "CMP000019": [
                    row
                    for row in playoff_rows
                    if row[
                        "destination_competition_id"
                    ] == "CMP000019"
                ]
            },
            competitions={
                cid: _CompletedScheduledStub(run)
                for cid, run in runs.items()
            },
        )
        (
            live_entrants,
            live_resolutions,
            live_playoffs,
        ) = live._resolve_regional_feeder_destination(
            "CMP000019"
        )

        self.assertEqual(
            legacy_entrants,
            live_entrants,
        )
        self.assertEqual(
            [
                row.resolved_school_ids
                for row in legacy_resolutions
            ],
            [
                list(row.resolved_school_ids)
                for row in live_resolutions
            ],
        )
        self.assertEqual(
            [
                row.winner_school_id
                for row in legacy_playoffs
            ],
            [
                row.winner_school_id
                for row in live_playoffs
            ],
        )
        self.assertEqual(
            ["PASS", "PASS"],
            [
                row.status
                for row in live_playoffs
            ],
        )
        self.assertEqual(
            16,
            len(live_entrants),
        )

    def test_jingu_ten_winners_build_national_template(
        self,
    ):
        source_ids = [
            f"CMP{number:06d}"
            for number in range(13, 23)
        ]
        school_ids = sorted(
            self.repo.schools
        )[:10]
        runs = {
            cid: self._fake_run(
                cid,
                [
                    school_ids[index],
                    school_ids[
                        (index + 1) % 10
                    ],
                ],
            )
            for index, cid in enumerate(
                source_ids
            )
        }
        qualification_rows = (
            LiveSeasonDependencyRuntimeState
            ._read_csv(
                DATA_ROOT,
                "qualification_rules.csv",
            )
        )
        live = LiveSeasonDependencyRuntimeState(
            engine=TournamentEngine(self.repo),
            repo=self.repo,
            year=self.year,
            rng_seed=self.seed,
            annual_templates={
                "CMP000003": AnnualCompetitionInput(
                    competition_id="CMP000003",
                    year=self.year,
                    entrant_school_ids=[],
                    rng_seed=self.seed + 500,
                )
            },
            qualification_rules={
                "CMP000003": [
                    row
                    for row in qualification_rows
                    if row[
                        "destination_competition_id"
                    ] == "CMP000003"
                ]
            },
            competitions={
                cid: _CompletedScheduledStub(run)
                for cid, run in runs.items()
            },
        )
        annual, resolutions = (
            live._build_qualification_destination_annual(
                "CMP000003"
            )
        )
        self.assertIsNotNone(annual)
        self.assertEqual(
            10,
            len(resolutions),
        )
        self.assertTrue(all(
            row.status == "PASS"
            for row in resolutions
        ))
        self.assertEqual(
            school_ids,
            annual.entrant_school_ids,
        )


if __name__ == "__main__":
    unittest.main()
