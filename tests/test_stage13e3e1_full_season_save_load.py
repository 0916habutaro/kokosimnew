from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from phase2_engine import (
    DEPENDENCY_WAITING,
    DataRepository,
    LiveSeasonGraphPlan,
    LiveSeasonGraphPlanner,
    LiveSeasonSaveCompatibilityError,
    LiveSeasonSaveSchemaError,
    LiveSeasonSaveStateError,
    MatchResolution,
    TournamentEngine,
    create_live_season_save,
    read_live_season_save,
    restore_live_season_save,
    write_live_season_save,
)
import phase2_engine.live_season_save as save_module


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class _StaticPlanner:
    def __init__(self, plan):
        self.plan = plan
        self.year = plan.year
        self.rng_seed = plan.rng_seed

    def build_plan(self):
        return self.plan


class _DeterministicScoreResolver:
    def __call__(
        self,
        *,
        match_id,
        competition_id,
        reference_year,
        generation_seed,
        team1,
        team2,
    ):
        return MatchResolution(
            winner_id=team1,
            loser_id=team2,
            team1_score=4,
            team2_score=2,
            score_source="save_test_v1",
            detail={
                "save_test_marker": (
                    f"{competition_id}:{match_id}"
                ),
                "generation_seed": (
                    generation_seed
                ),
            },
        )


class _DivergentResolver:
    def __init__(self, saved_results):
        self.saved_results = saved_results

    def __call__(
        self,
        *,
        match_id,
        competition_id,
        reference_year,
        generation_seed,
        team1,
        team2,
    ):
        key = (
            f"{competition_id}:{match_id}"
        )
        saved = self.saved_results.get(
            key,
            {},
        )
        saved_winner = saved.get(
            "winner_id",
            "",
        )
        if saved_winner == team1:
            winner = team2
        elif saved_winner == team2:
            winner = team1
        else:
            winner = team2
        loser = (
            team2
            if winner == team1
            else team1
        )
        return MatchResolution(
            winner_id=winner,
            loser_id=loser,
            team1_score=(
                5 if winner == team1 else 1
            ),
            team2_score=(
                1 if winner == team1 else 5
            ),
            score_source="divergent_save_test",
            detail={
                "divergent": True,
            },
        )


class Stage13E3E1FullSeasonSaveLoadTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.seed = 2026100823
        cls.full_planner = (
            LiveSeasonGraphPlanner(
                cls.repo,
                DATA_ROOT,
                cls.seed,
                year=2026,
            )
        )
        full_plan = (
            cls.full_planner.build_plan()
        )

        keep = [
            "CMP000029",
            "CMP000077",
        ]
        cls.mini_plan = LiveSeasonGraphPlan(
            repo=full_plan.repo,
            data_dir=full_plan.data_dir,
            year=full_plan.year,
            rng_seed=full_plan.rng_seed,
            entries={
                cid: full_plan.entries[cid]
                for cid in keep
            },
            annual_templates={
                cid: full_plan
                .annual_templates[cid]
                for cid in keep
            },
            annual_build_strategies={
                cid: full_plan
                .annual_build_strategies[cid]
                for cid in keep
            },
            calendar_rows=[
                row
                for row
                in full_plan.calendar_rows
                if row[
                    "competition_id"
                ] in keep
            ],
            stage_calendar_rows=list(
                full_plan.stage_calendar_rows
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
        cls.planner = _StaticPlanner(
            cls.mini_plan
        )

    def _engine(self, resolver=None):
        return TournamentEngine(
            self.repo,
            main_match_resolver=resolver,
            pre_main_match_resolver=resolver,
        )

    def _state_before_release(
        self,
        resolver=None,
    ):
        state = self.mini_plan.build_runtime(
            engine=self._engine(resolver),
            start_date="2026-07-01",
        )
        state.advance_to(
            "2026-07-28"
        )
        return state

    def test_save_restore_unprocessed_current_date_and_continue(
        self,
    ):
        resolver = _DeterministicScoreResolver()
        original = self._state_before_release(
            resolver
        )
        self.assertEqual(
            "2026-07-28",
            original.current_date.isoformat(),
        )
        self.assertEqual(
            DEPENDENCY_WAITING,
            original.dependency_state(
                "CMP000077"
            )["status"],
        )
        self.assertNotIn(
            "CMP000077",
            original.competitions,
        )

        payload = create_live_season_save(
            self.mini_plan,
            original,
            resolver_contract=(
                "deterministic_score_v1"
            ),
        )
        self.assertEqual(
            "2026-07-27",
            payload["processed_dates"][-1],
        )
        self.assertGreater(
            payload["completed_match_count"],
            0,
        )

        restored_plan, restored = (
            restore_live_season_save(
                self.planner,
                payload,
                engine=self._engine(
                    _DeterministicScoreResolver()
                ),
                resolver_contract=(
                    "deterministic_score_v1"
                ),
            )
        )
        self.assertEqual(
            self.mini_plan.public_snapshot(),
            restored_plan.public_snapshot(),
        )
        self.assertEqual(
            original.public_snapshot(),
            restored.public_snapshot(),
        )
        self.assertEqual(
            original.history,
            restored.history,
        )
        self.assertEqual(
            "2026-07-28",
            restored.current_date.isoformat(),
        )
        # 試合の詳細も保存した状態から戻る（やり直していない）
        self.assertTrue(any(
            (match.ability_detail or {}).get(
                "save_test_marker"
            )
            for scheduled in restored.competitions.values()
            for match in scheduled.matches.values()
        ))

        original.play_today()
        restored.play_today()
        self.assertEqual(
            original.public_snapshot(),
            restored.public_snapshot(),
        )
        self.assertIn(
            "CMP000077",
            restored.competitions,
        )
        source = restored.completed_runs()[
            "CMP000029"
        ]
        champion = (
            source.outcome
            .champion_school_id
        )
        self.assertIn(
            champion,
            restored.competitions[
                "CMP000077"
            ].runtime.annual
            .direct_main_entry_school_ids,
        )

    def test_atomic_json_file_roundtrip_after_dependency_activation(
        self,
    ):
        original = (
            self._state_before_release()
        )
        original.play_today()
        self.assertIn(
            "CMP000077",
            original.competitions,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = (
                Path(tmp)
                / "season_save.json"
            )
            written = write_live_season_save(
                path,
                self.mini_plan,
                original,
            )
            self.assertTrue(path.exists())
            self.assertFalse(
                Path(
                    str(path) + ".tmp"
                ).exists()
            )

            loaded_plan, restored = (
                read_live_season_save(
                    path,
                    self.planner,
                )
            )
            resaved = create_live_season_save(
                loaded_plan,
                restored,
            )
            for key in (
                "plan_fingerprint",
                "current_date",
                "processed_dates",
                "completed_match_count",
                "runtime_summary",
            ):
                self.assertEqual(
                    written[key],
                    resaved[key],
                )
            self.assertEqual(
                original.public_snapshot(),
                restored.public_snapshot(),
            )
            self.assertEqual(
                original.history,
                restored.history,
            )

            original.advance_to(
                "2026-08-02"
            )
            restored.advance_to(
                "2026-08-02"
            )
            self.assertEqual(
                original.public_snapshot(),
                restored.public_snapshot(),
            )

    def test_checksum_and_plan_change_are_rejected(
        self,
    ):
        original = (
            self._state_before_release()
        )
        payload = create_live_season_save(
            self.mini_plan,
            original,
        )

        tampered = deepcopy(payload)
        tampered["current_date"] = (
            "2026-07-29"
        )
        with self.assertRaises(
            LiveSeasonSaveSchemaError
        ):
            restore_live_season_save(
                self.planner,
                tampered,
            )

        changed_plan = deepcopy(
            self.mini_plan
        )
        changed_plan.warnings.append(
            "simulated master change"
        )
        changed_planner = _StaticPlanner(
            changed_plan
        )
        with self.assertRaises(
            LiveSeasonSaveCompatibilityError
        ):
            restore_live_season_save(
                changed_planner,
                payload,
            )

    def test_resolver_contract_mismatch_is_rejected_and_load_does_not_replay(
        self,
    ):
        original = self._state_before_release(
            _DeterministicScoreResolver()
        )
        payload = create_live_season_save(
            self.mini_plan,
            original,
            resolver_contract=(
                "deterministic_score_v1"
            ),
        )

        with self.assertRaises(
            LiveSeasonSaveCompatibilityError
        ):
            restore_live_season_save(
                self.planner,
                payload,
                engine=self._engine(
                    _DeterministicScoreResolver()
                ),
                resolver_contract=(
                    "different_model_v2"
                ),
            )

        # 読込で試合をやり直さないので、試合の決め方が違っても
        # 終わった試合の結果は保存したとおりに戻る。
        divergent = _DivergentResolver(
            original.completed_results()
        )
        _, restored = restore_live_season_save(
            self.planner,
            payload,
            engine=self._engine(
                divergent
            ),
            resolver_contract=(
                "deterministic_score_v1"
            ),
        )
        self.assertEqual(
            original.completed_results(),
            restored.completed_results(),
        )

    def test_rehashed_tamper_of_state_or_summary_is_rejected(
        self,
    ):
        original = (
            self._state_before_release()
        )
        payload = create_live_season_save(
            self.mini_plan,
            original,
        )

        def rehash(data):
            body = dict(data)
            body.pop("payload_checksum", None)
            data["payload_checksum"] = (
                save_module._fingerprint(body)
            )
            return data

        summary = deepcopy(payload)
        summary["runtime_summary"]["current_date"] = "2026-07-01"
        with self.assertRaises(
            LiveSeasonSaveStateError
        ):
            restore_live_season_save(
                self.planner,
                rehash(summary),
            )

        broken = deepcopy(payload)
        broken["runtime_state"] = "AAAA"
        with self.assertRaises(
            LiveSeasonSaveStateError
        ):
            restore_live_season_save(
                self.planner,
                rehash(broken),
            )



class NationalSaveLoadTests(unittest.TestCase):
    def test_service_load_restores_state_without_replaying(self):
        from phase2_engine import LiveGameService

        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                repo, DATA_ROOT, save_root=tmp,
                autosave_after_action=False,
            )
            session = service.new_game("national", rng_seed=20261021)
            session.state.advance_through("2026-04-12")
            service.save_game(session)
            loaded = service.load_game("national")
            self.assertEqual(
                session.state.completed_results(),
                loaded.state.completed_results(),
            )
            self.assertEqual(
                session.state.current_date,
                loaded.state.current_date,
            )
            session.state.advance_through("2026-04-19")
            loaded.state.advance_through("2026-04-19")
            self.assertEqual(
                session.state.completed_results(),
                loaded.state.completed_results(),
            )


if __name__ == "__main__":
    unittest.main()
