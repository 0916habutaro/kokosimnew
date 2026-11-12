"""県大会の3位決定戦（main_tournament_engine_policies.csv の third_place_match）。

準決勝で負けた2校で1試合。勝った方が3位、負けた方が4位。到達（ベスト4）は変えない。"""
from __future__ import annotations

import pickle
import unittest
from pathlib import Path

from phase2_engine import DataRepository, SeasonOrchestrator
from phase2_engine.tournament_runtime import (
    MATCH_COMPLETED, THIRD_PLACE_NAME, MainTournamentRuntimeState, is_third_place,
)

ROOT = Path(__file__).resolve().parents[1]
SCHOOLS = [f"FAKE-{n}" for n in range(1, 7)]


def bracket(third_place=True, entrants=SCHOOLS):
    return MainTournamentRuntimeState.create(
        competition_id="CMP-FAKE", reference_year=2026, generation_seed=7,
        stage_id="STG-FAKE", entrants=entrants, third_place=third_place,
    )


def play_until_final(state):
    while not any(state.matches[m].status == "ready" for m in state.match_ids_by_round[state.total_rounds]):
        state.resolve_ready_round()


class ThirdPlaceRuntimeTests(unittest.TestCase):
    def test_semifinal_losers_play_and_decide_third_and_fourth(self):
        state = bracket()
        state.resolve_all()
        third = state.matches[state.third_place_match_id]
        self.assertEqual(THIRD_PLACE_NAME, third.round_name)
        self.assertEqual(MATCH_COMPLETED, third.status)
        semifinal = state.eliminated_by_round[state.total_rounds - 1]
        self.assertEqual(set(semifinal), {third.team1, third.team2})
        outcome = state.to_competition_run().outcome
        self.assertEqual([third.winner, third.loser], outcome.final_ranking_school_ids[2:4])
        # 到達は変えない：負けた学校もベスト4のまま
        self.assertEqual(sorted(semifinal), sorted(outcome.semifinalist_school_ids))
        self.assertNotIn(third.loser, state.eliminated_by_round[state.total_rounds])
        # 3位決定戦は決勝と同じ回戦（同じ日に組まれる）
        self.assertIn(state.third_place_match_id, state.match_ids_by_round[state.total_rounds])
        self.assertTrue(is_third_place(third.public_dict()))

    def test_no_third_place_match_when_the_competition_has_none(self):
        state = bracket(third_place=False)
        run = state.resolve_all()
        self.assertEqual("", state.third_place_match_id)
        self.assertFalse(any(is_third_place(m) for m in run.stage_executions[0].matches))
        # 3校だけの大会（準決勝に不戦勝がある）でも作らない
        self.assertEqual("", bracket(entrants=SCHOOLS[:3]).third_place_match_id)

    def test_saved_and_reloaded_before_the_final_gives_the_same_result(self):
        state = bracket()
        play_until_final(state)
        copy = pickle.loads(pickle.dumps(state))
        self.assertEqual(
            state.resolve_all().outcome.final_ranking_school_ids,
            copy.resolve_all().outcome.final_ranking_school_ids,
        )
        self.assertEqual(state.matches[state.third_place_match_id].winner,
                         copy.matches[copy.third_place_match_id].winner)


class ThirdPlaceScheduleTests(unittest.TestCase):
    def test_third_place_match_is_played_on_the_day_of_the_final(self):
        from phase2_engine.competition_schedule_runtime import ScheduledCompetitionRuntime

        repo = DataRepository(ROOT / "data")
        cid = sorted(repo.third_place_competitions)[0]
        state = MainTournamentRuntimeState.create(
            competition_id=cid, reference_year=2026, generation_seed=7,
            stage_id="STG-FAKE", entrants=SCHOOLS, third_place=True,
        )
        days = ["2026-09-12", "2026-09-13", "2026-09-19", "2026-09-20"]
        scheduled = ScheduledCompetitionRuntime.from_calendar_row(
            repo, state, {"competition_id": cid, "game_date_list": ";".join(days),
                          "calendar_status": "official_schedule"})
        scheduled.advance_through(days[-1])
        self.assertTrue(scheduled.is_complete)
        final = scheduled.matches[state._match_id(state.total_rounds, 1)]
        third = scheduled.matches[state.third_place_match_id]
        self.assertEqual(days[-1], final.match_date)
        self.assertEqual(final.match_date, third.match_date)
        self.assertEqual(THIRD_PLACE_NAME, third.round_name)

        # 画面：組み合わせの線の外に「3位決定戦」の枠。学校の成績では到達に数えない
        from phase2_engine.screen.competition_views import bracket_layout
        from phase2_engine.screen.school_views import normalized_rows, year_results

        layout = bracket_layout(state, scheduled)
        self.assertEqual(THIRD_PLACE_NAME, layout["third_place"]["round_name"])
        self.assertEqual(state.third_place_match_id, layout["third_place"]["matches"][0]["match_id"])
        self.assertNotIn(state.third_place_match_id, [m["match_id"] for m in layout["matches"]])
        rows = normalized_rows([{**m.public_dict(), "status": "completed"} for m in scheduled.matches.values()])
        loser = next(r for r in year_results(rows, {}, {cid: state.total_rounds}, lambda c, n: n)[third.loser_id]
                     if r["competition_id"] == cid)
        self.assertEqual("ベスト4", loser["finish"])


class ThirdPlaceSeasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / "data")
        cls.season = SeasonOrchestrator(cls.repo, ROOT / "data").run_structural_season(2026, 2026100501)

    @staticmethod
    def third_place(run):
        return next((m for stage in run.stage_executions for m in stage.matches if is_third_place(m)), None)

    def test_winner_of_the_third_place_match_goes_to_the_regional_as_the_third_school(self):
        # 3校が地区大会へ出る県大会（地区大会の行き先は regional_feeder_rules.csv の順位 1〜3）
        source = "CMP000073"
        self.assertIn(source, self.repo.third_place_competitions)
        run = self.season.competition_runs[source]
        third = self.third_place(run)
        self.assertIsNotNone(third)
        self.assertEqual(third.winner, run.outcome.final_ranking_school_ids[2])
        regional = set(self.season.competition_runs["CMP000014"].entrant_school_ids)
        self.assertIn(third.winner, regional)
        self.assertNotIn(third.loser, regional)

    def test_competitions_without_a_third_place_match_keep_the_random_order(self):
        for cid, run in self.season.competition_runs.items():
            if cid in self.repo.third_place_competitions or run.outcome is None:
                continue
            with self.subTest(competition_id=cid):
                self.assertIsNone(self.third_place(run))
