from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    DataRepository,
    LiveGameService,
    LiveSeasonGraphPlan,
    LiveSeasonGraphPlanner,
    SAVE_KIND_AUTOSAVE,
    SAVE_KIND_MANUAL,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class _StaticPlanner:
    def __init__(self, plan):
        self.plan = plan
        self.year = plan.year
        self.rng_seed = plan.rng_seed

    def build_plan(self):
        return self.plan


class Stage13E3E2SaveSlotsGameServiceTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.seed = 2026100824
        full = LiveSeasonGraphPlanner(
            cls.repo,
            DATA_ROOT,
            cls.seed,
            year=2026,
        ).build_plan()

        keep = [
            "CMP000029",
            "CMP000077",
        ]
        cls.mini_plan = LiveSeasonGraphPlan(
            repo=full.repo,
            data_dir=full.data_dir,
            year=full.year,
            rng_seed=full.rng_seed,
            entries={
                cid: full.entries[cid]
                for cid in keep
            },
            annual_templates={
                cid: full.annual_templates[cid]
                for cid in keep
            },
            annual_build_strategies={
                cid: full
                .annual_build_strategies[cid]
                for cid in keep
            },
            calendar_rows=[
                row
                for row in full.calendar_rows
                if row["competition_id"]
                in keep
            ],
            stage_calendar_rows=list(
                full.stage_calendar_rows
            ),
            dependency_edges=[
                (
                    "CMP000029",
                    "CMP000077",
                )
            ],
            topological_order=list(keep),
            external_bootstrap_resolutions=[],
            warnings=[],
        )

    def _planner_factory(
        self,
        repo,
        data_dir,
        rng_seed,
        year,
    ):
        self.assertIs(repo, self.repo)
        self.assertEqual(
            Path(data_dir),
            DATA_ROOT,
        )
        self.assertEqual(
            self.seed,
            rng_seed,
        )
        self.assertEqual(2026, year)
        return _StaticPlanner(
            self.mini_plan
        )

    def _service(
        self,
        root,
        *,
        max_backups=2,
        autosave_after_action=True,
    ):
        return LiveGameService(
            self.repo,
            DATA_ROOT,
            save_root=root,
            year=2026,
            max_backups=max_backups,
            autosave_after_action=(
                autosave_after_action
            ),
            planner_factory=(
                self._planner_factory
            ),
        )

    def test_new_game_next_day_autosave_and_latest_load(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            session = service.new_game(
                "slot01",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )

            first = service.slots.slot_summary(
                "slot01"
            )
            self.assertTrue(
                first.manual.exists
            )
            self.assertFalse(
                first.autosave.exists
            )
            self.assertEqual(
                "2026-07-01",
                first.manual.metadata[
                    "current_date"
                ],
            )

            action = service.next_day(
                session
            )
            self.assertEqual(
                "2026-07-02",
                session.state.current_date
                .isoformat(),
            )
            self.assertIsNotNone(
                action["autosave"]
            )

            summary = service.slots.slot_summary(
                "slot01"
            )
            self.assertTrue(
                summary.autosave.exists
            )
            self.assertEqual(
                SAVE_KIND_AUTOSAVE,
                summary.latest_source,
            )
            self.assertEqual(
                "2026-07-02",
                summary.autosave.metadata[
                    "current_date"
                ],
            )

            loaded = service.load_game(
                "slot01"
            )
            self.assertEqual(
                session.state.public_snapshot(),
                loaded.state.public_snapshot(),
            )
            self.assertEqual(
                session.state.history,
                loaded.state.history,
            )

    def test_manual_rolling_backups_are_bounded_and_recoverable(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(
                tmp,
                max_backups=2,
            )
            session = service.new_game(
                "careerA",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )

            service.next_day(
                session,
                autosave=False,
            )
            service.save_game(
                session,
                kind=SAVE_KIND_MANUAL,
            )
            self.assertEqual(
                "2026-07-01",
                service.slots.inspect(
                    "careerA",
                    source="manual_backup_1",
                )["current_date"],
            )

            service.next_day(
                session,
                autosave=False,
            )
            service.save_game(
                session,
                kind=SAVE_KIND_MANUAL,
            )
            self.assertEqual(
                "2026-07-02",
                service.slots.inspect(
                    "careerA",
                    source="manual_backup_1",
                )["current_date"],
            )
            self.assertEqual(
                "2026-07-01",
                service.slots.inspect(
                    "careerA",
                    source="manual_backup_2",
                )["current_date"],
            )

            service.next_day(
                session,
                autosave=False,
            )
            service.save_game(
                session,
                kind=SAVE_KIND_MANUAL,
            )
            self.assertEqual(
                2,
                len(
                    service.slots.backup_files(
                        "careerA",
                        SAVE_KIND_MANUAL,
                    )
                ),
            )
            self.assertEqual(
                "2026-07-03",
                service.slots.inspect(
                    "careerA",
                    source="manual_backup_1",
                )["current_date"],
            )
            self.assertEqual(
                "2026-07-02",
                service.slots.inspect(
                    "careerA",
                    source="manual_backup_2",
                )["current_date"],
            )

            recovered = service.load_game(
                "careerA",
                source="manual_backup_2",
            )
            self.assertEqual(
                "2026-07-02",
                recovered.state.current_date
                .isoformat(),
            )

    def test_autosave_has_independent_backup_chain(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(
                tmp,
                max_backups=2,
            )
            session = service.new_game(
                "auto01",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )

            service.next_day(session)
            service.next_day(session)
            service.next_day(session)

            self.assertEqual(
                "2026-07-04",
                service.slots.inspect(
                    "auto01",
                    source=SAVE_KIND_AUTOSAVE,
                )["current_date"],
            )
            self.assertEqual(
                "2026-07-03",
                service.slots.inspect(
                    "auto01",
                    source="autosave_backup_1",
                )["current_date"],
            )
            self.assertEqual(
                "2026-07-02",
                service.slots.inspect(
                    "auto01",
                    source="autosave_backup_2",
                )["current_date"],
            )
            self.assertEqual(
                "2026-07-01",
                service.slots.inspect(
                    "auto01",
                    source=SAVE_KIND_MANUAL,
                )["current_date"],
            )

    def test_action_autosave_policy_can_be_disabled_per_call(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            session = service.new_game(
                "policy01",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )

            result = service.advance_to(
                session,
                "2026-07-05",
                autosave=False,
            )
            self.assertIsNone(
                result["autosave"]
            )
            self.assertFalse(
                service.slots.slot_summary(
                    "policy01"
                ).autosave.exists
            )

            result = service.play_today(
                session,
                autosave=True,
            )
            self.assertIsNotNone(
                result["autosave"]
            )
            self.assertEqual(
                "2026-07-05",
                service.slots.inspect(
                    "policy01",
                    source=SAVE_KIND_AUTOSAVE,
                )["current_date"],
            )

    def test_slot_listing_validation_and_delete(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service.new_game(
                "slot_b",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )
            service.new_game(
                "slot_a",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )

            listed = service.list_games()
            self.assertEqual(
                ["slot_a", "slot_b"],
                [
                    row["slot_id"]
                    for row in listed
                ],
            )
            with self.assertRaises(
                ValueError
            ):
                service.new_game(
                    "../escape",
                    rng_seed=self.seed,
                )

            service.delete_game(
                "slot_a"
            )
            self.assertEqual(
                ["slot_b"],
                [
                    row["slot_id"]
                    for row
                    in service.list_games()
                ],
            )

    def test_real_full_season_service_starts_without_manual_templates(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                self.repo,
                DATA_ROOT,
                save_root=tmp,
                year=2026,
                max_backups=1,
            )
            session = service.new_game(
                "full2026",
                rng_seed=2026100825,
                save_initial=True,
            )
            runtime = (
                session.state.summary()
            )
            self.assertEqual(
                162,
                runtime[
                    "template_competition_count"
                ],
            )
            self.assertEqual(
                135,
                runtime[
                    "active_runtime_count"
                ],
            )
            self.assertEqual(
                {
                    "active": 135,
                    "waiting_dependencies": 27,
                },
                runtime[
                    "status_counts"
                ],
            )
            slot = service.slots.slot_summary(
                "full2026"
            )
            self.assertTrue(
                slot.manual.exists
            )
            self.assertEqual(
                "2026-01-01",
                slot.manual.metadata[
                    "current_date"
                ],
            )


if __name__ == "__main__":
    unittest.main()
