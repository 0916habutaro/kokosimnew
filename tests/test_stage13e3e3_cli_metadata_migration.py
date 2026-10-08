from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    DataRepository,
    LiveGameService,
    LiveSeasonGraphPlan,
    LiveSeasonGraphPlanner,
    LiveSeasonSaveCompatibilityError,
    SAVE_KIND_AUTOSAVE,
    SAVE_KIND_MANUAL,
    SAVE_SCHEMA_VERSION,
    SaveMigrationRegistry,
    create_live_season_save,
    rechecksum_live_season_save_payload,
    restore_live_season_save,
)
from phase2_engine.live_game_cli import (
    build_parser,
    run_command,
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


class Stage13E3E3CliMetadataMigrationTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.seed = 2026100826
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
        max_backups=3,
    ):
        return LiveGameService(
            self.repo,
            DATA_ROOT,
            save_root=root,
            year=2026,
            max_backups=max_backups,
            planner_factory=(
                self._planner_factory
            ),
        )

    def test_user_metadata_title_lifecycle_is_separate_from_save_payload(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            session = service.new_game(
                "career01",
                rng_seed=self.seed,
                start_date="2026-07-01",
                title="宮城テスト",
            )
            metadata = (
                service.slots
                .read_user_metadata(
                    "career01"
                )
            )
            self.assertIsNotNone(metadata)
            self.assertEqual(
                "宮城テスト",
                metadata.title,
            )
            self.assertTrue(
                metadata.created_at.endswith(
                    "+00:00"
                )
            )
            first_created = (
                metadata.created_at
            )

            renamed = service.rename_game(
                "career01",
                "2026年シーズン",
            )
            self.assertEqual(
                "2026年シーズン",
                renamed["title"],
            )
            self.assertEqual(
                first_created,
                renamed["created_at"],
            )

            service.next_day(
                session,
            )
            updated = (
                service.slots
                .read_user_metadata(
                    "career01"
                )
            )
            self.assertEqual(
                "2026年シーズン",
                updated.title,
            )
            self.assertEqual(
                "autosave",
                updated.last_source,
            )
            self.assertEqual(
                "2026-07-02",
                updated.current_date,
            )

            save_path = (
                service.slots.save_path(
                    "career01",
                    SAVE_KIND_MANUAL,
                )
            )
            payload = json.loads(
                save_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotIn(
                "title",
                payload,
            )

    def test_recovery_inventory_survives_corrupt_primary_and_metadata(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(
                tmp,
                max_backups=2,
            )
            session = service.new_game(
                "recover01",
                rng_seed=self.seed,
                start_date="2026-07-01",
                title="復旧確認",
            )
            service.next_day(session)
            service.next_day(session)

            auto_path = (
                service.slots.save_path(
                    "recover01",
                    SAVE_KIND_AUTOSAVE,
                )
            )
            auto_path.write_text(
                "{broken",
                encoding="utf-8",
            )
            service.slots.metadata_path(
                "recover01"
            ).write_text(
                "{broken",
                encoding="utf-8",
            )

            summary = (
                service.slots.slot_summary(
                    "recover01"
                )
            )
            self.assertEqual(
                "invalid",
                summary.autosave.status,
            )
            self.assertEqual(
                "valid",
                summary.manual.status,
            )
            self.assertEqual(
                SAVE_KIND_MANUAL,
                summary.latest_source,
            )
            self.assertIsNone(
                summary.user_metadata,
            )

            recoveries = (
                service.recovery_sources(
                    "recover01"
                )
            )
            by_source = {
                row["source"]: row
                for row in recoveries
            }
            self.assertEqual(
                "invalid",
                by_source[
                    SAVE_KIND_AUTOSAVE
                ]["status"],
            )
            self.assertEqual(
                "valid",
                by_source[
                    "autosave_backup_1"
                ]["status"],
            )

            loaded = service.load_game(
                "recover01",
                source="latest",
            )
            self.assertEqual(
                "2026-07-01",
                loaded.state.current_date
                .isoformat(),
            )

    def test_recovery_source_can_be_promoted_to_manual_primary(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(
                tmp,
                max_backups=3,
            )
            session = service.new_game(
                "rollback01",
                rng_seed=self.seed,
                start_date="2026-07-01",
            )
            service.next_day(
                session,
                autosave=False,
            )
            service.save_game(session)
            service.next_day(
                session,
                autosave=False,
            )
            service.save_game(session)

            self.assertEqual(
                "2026-07-01",
                service.slots.inspect(
                    "rollback01",
                    source="manual_backup_2",
                )["current_date"],
            )
            recovered = (
                service.recover_game(
                    "rollback01",
                    source="manual_backup_2",
                    promote_kind=(
                        SAVE_KIND_MANUAL
                    ),
                )
            )
            self.assertEqual(
                "2026-07-01",
                recovered.state.current_date
                .isoformat(),
            )
            self.assertEqual(
                "2026-07-01",
                service.slots.inspect(
                    "rollback01",
                    source=SAVE_KIND_MANUAL,
                )["current_date"],
            )
            self.assertEqual(
                "2026-07-03",
                service.slots.inspect(
                    "rollback01",
                    source="manual_backup_1",
                )["current_date"],
            )

    def test_custom_migration_registry_upgrades_legacy_payload(
        self,
    ):
        state = self.mini_plan.build_runtime(
            start_date="2026-07-01"
        )
        state.advance_to(
            "2026-07-03"
        )
        payload = create_live_season_save(
            self.mini_plan,
            state,
        )

        legacy = deepcopy(payload)
        legacy["schema_version"] = (
            "stage13e3e0.live-season-save.v0"
        )
        legacy = (
            rechecksum_live_season_save_payload(
                legacy
            )
        )

        registry = SaveMigrationRegistry()

        def migrate_v0(data):
            data = deepcopy(data)
            data["schema_version"] = (
                SAVE_SCHEMA_VERSION
            )
            return (
                rechecksum_live_season_save_payload(
                    data
                )
            )

        registry.register(
            "stage13e3e0.live-season-save.v0",
            SAVE_SCHEMA_VERSION,
            migrate_v0,
        )

        plan, restored = (
            restore_live_season_save(
                _StaticPlanner(
                    self.mini_plan
                ),
                legacy,
                migration_registry=registry,
            )
        )
        self.assertEqual(
            self.mini_plan.public_snapshot(),
            plan.public_snapshot(),
        )
        self.assertEqual(
            state.public_snapshot(),
            restored.public_snapshot(),
        )

        unknown = deepcopy(legacy)
        unknown["schema_version"] = (
            "unknown.save.v9"
        )
        unknown = (
            rechecksum_live_season_save_payload(
                unknown
            )
        )
        with self.assertRaises(
            LiveSeasonSaveCompatibilityError
        ):
            restore_live_season_save(
                _StaticPlanner(
                    self.mini_plan
                ),
                unknown,
                migration_registry=registry,
            )

    def test_cli_contract_uses_game_service_for_new_list_status_and_actions(
        self,
    ):
        parser = build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)

            created = run_command(
                parser.parse_args([
                    "new",
                    "cli01",
                    "--seed",
                    str(self.seed),
                    "--start-date",
                    "2026-07-01",
                    "--title",
                    "CLIシーズン",
                ]),
                service,
            )
            self.assertEqual(
                "new",
                created["command"],
            )
            self.assertEqual(
                "CLIシーズン",
                created["slot"][
                    "user_metadata"
                ]["title"],
            )

            listed = run_command(
                parser.parse_args([
                    "list",
                ]),
                service,
            )
            self.assertEqual(
                ["cli01"],
                [
                    row["slot_id"]
                    for row in listed["slots"]
                ],
            )

            next_result = run_command(
                parser.parse_args([
                    "next-day",
                    "cli01",
                ]),
                service,
            )
            self.assertEqual(
                "2026-07-02",
                next_result[
                    "to_date"
                ],
            )

            status = run_command(
                parser.parse_args([
                    "status",
                    "cli01",
                ]),
                service,
            )
            self.assertEqual(
                "2026-07-02",
                status["save"][
                    "current_date"
                ],
            )

            recovery = run_command(
                parser.parse_args([
                    "recoveries",
                    "cli01",
                ]),
                service,
            )
            self.assertTrue(
                any(
                    row["source"]
                    == SAVE_KIND_AUTOSAVE
                    for row in recovery[
                        "sources"
                    ]
                )
            )

            renamed = run_command(
                parser.parse_args([
                    "rename",
                    "cli01",
                    "新しい名前",
                ]),
                service,
            )
            self.assertEqual(
                "新しい名前",
                renamed["metadata"][
                    "title"
                ],
            )

            with self.assertRaises(
                ValueError
            ):
                run_command(
                    parser.parse_args([
                        "delete",
                        "cli01",
                    ]),
                    service,
                )
            deleted = run_command(
                parser.parse_args([
                    "delete",
                    "cli01",
                    "--confirm",
                ]),
                service,
            )
            self.assertTrue(
                deleted["deleted"]
            )

    def test_current_schema_requires_no_migration_step(
        self,
    ):
        registry = SaveMigrationRegistry()
        self.assertEqual(
            [],
            registry.path(
                SAVE_SCHEMA_VERSION,
                SAVE_SCHEMA_VERSION,
            ),
        )
        self.assertEqual(
            [],
            registry.registered_versions(),
        )


if __name__ == "__main__":
    unittest.main()
