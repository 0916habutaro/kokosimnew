from __future__ import annotations

import json
import unittest
from pathlib import Path

from phase2_engine import DataRepository, TournamentEngine
from phase2_engine.models import StageExecution
from phase2_engine.post_qualification_ranking import (
    RankingOnlyEventRuntime,
    load_post_qualification_profiles,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def executed_stage(
    competition_id: str,
    stage_id: str,
    stage_code: str,
    group_id: str,
    format_model_id: str,
    locked: list[str],
) -> StageExecution:
    return StageExecution(
        stage_id=stage_id,
        stage_code=stage_code,
        format_model_id=format_model_id,
        entrant_school_ids=locked + ["UNQUALIFIED"],
        output_school_ids=locked[:],
        metadata={
            "group_models": {group_id: format_model_id},
            "group_outputs": {group_id: locked[:]},
        },
    )


class Stage13E3G1NonblockingRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.engine = TournamentEngine(cls.repo)

    def _tokushima(self):
        return self.engine.prepare_post_qualification_ranking(
            stage_execution=executed_stage(
                "CMP000140", "STG000202", "SEED_EVENT",
                "SGR000171", "FMT022", ["A", "B", "C", "D"],
            ),
            group_id="SGR000171",
        )

    def _okinawa(self):
        return self.engine.prepare_post_qualification_ranking(
            stage_execution=executed_stage(
                "CMP000162", "STG000206", "SEED_EVENT",
                "SGR000184", "FMT022", ["A", "B", "C", "D"],
            ),
            group_id="SGR000184",
        )

    def _shizuoka(self):
        return self.engine.prepare_post_qualification_ranking(
            stage_execution=executed_stage(
                "CMP000112", "STG000183", "BRANCH_QUALIFIER",
                "SGR000106", "FMT025", ["A", "B", "C", "D", "E"],
            ),
            group_id="SGR000106",
            pairings=(("B", "C"), ("A", "D")),
        )

    def test_six_real_profiles_are_separately_configured(self):
        profiles = load_post_qualification_profiles(DATA)
        self.assertEqual({
            "CMP000140", "CMP000162", "CMP000111",
            "CMP000112", "CMP000135", "CMP000136",
        }, set(profiles))
        self.assertEqual(
            "two_block_deciders", profiles["CMP000140"]["ranking_event_mode"]
        )
        self.assertEqual(
            "semifinal_final", profiles["CMP000162"]["ranking_event_mode"]
        )
        for cid in ("CMP000111", "CMP000112", "CMP000135", "CMP000136"):
            self.assertEqual(
                "pairwise_deciders", profiles[cid]["ranking_event_mode"]
            )
            self.assertEqual(
                "ranking_metadata_only", profiles[cid]["result_effect"]
            )

    def test_fmt022_tokushima_post_cut_two_block_finals(self):
        event = self._tokushima()
        self.assertEqual(2, len(event.ready_matches()))
        self.assertEqual({}, event.results)
        locked = event.locked_school_ids
        first, second = event.ready_matches()
        event.resolve(first["match_id"], first["team1"])
        self.assertFalse(event.is_complete)
        event.resolve(second["match_id"], second["team2"])
        self.assertTrue(event.is_complete)
        self.assertEqual(locked, event.locked_school_ids)
        self.assertEqual("none", event.ranking_metadata()["qualifier_effect"])
        self.assertEqual(2, len(event.ranking_metadata()["placement_decisions"]))

    def test_fmt022_okinawa_finals_are_lazy(self):
        event = self._okinawa()
        first, second = event.ready_matches()
        self.assertEqual([1, 1], [r["round_no"] for r in event.ready_matches()])
        event.resolve(first["match_id"], first["team1"])
        self.assertEqual(1, len(event.ready_matches()))
        event.resolve(second["match_id"], second["team2"])
        final = event.ready_matches()
        self.assertEqual(1, len(final))
        self.assertEqual(2, final[0]["round_no"])
        self.assertEqual(
            {first["team1"], second["team2"]},
            {final[0]["team1"], final[0]["team2"]},
        )
        self.assertFalse(event.is_complete)
        event.resolve(final[0]["match_id"], final[0]["team1"])
        self.assertTrue(event.is_complete)
        self.assertEqual(
            final[0]["team1"],
            event.ranking_metadata()["event_champion_school_id"],
        )
        self.assertEqual(["A", "B", "C", "D"], event.snapshot()["locked_school_ids"])

    def test_fmt025_only_explicit_pairings_among_qualified(self):
        event = self._shizuoka()
        self.assertEqual(2, len(event.ready_matches()))
        self.assertEqual(["A", "B", "C", "D", "E"],
                         event.snapshot()["locked_school_ids"])
        for ready in event.ready_matches():
            event.resolve(ready["match_id"], ready["team2"])
        self.assertTrue(event.is_complete)
        self.assertEqual(2, len(event.ranking_metadata()["placement_decisions"]))
        self.assertEqual(
            ["A", "B", "C", "D", "E"],
            event.ranking_metadata()["locked_qualifiers"],
        )

    def test_no_implicit_fmt025_draw_is_generated(self):
        stage = executed_stage(
            "CMP000112", "STG000183", "BRANCH_QUALIFIER",
            "SGR000106", "FMT025", ["A", "B", "C", "D"],
        )
        with self.assertRaisesRegex(ValueError, "explicit annual draw"):
            self.engine.prepare_post_qualification_ranking(
                stage_execution=stage, group_id="SGR000106",
            )

    def test_ranking_can_be_serialized_and_replayed(self):
        event = self._okinawa()
        event.resolve(event.ready_matches()[0]["match_id"], "A")
        saved = json.loads(json.dumps(event.snapshot()))
        resumed = RankingOnlyEventRuntime.from_snapshot(saved)
        self.assertEqual(event.snapshot(), resumed.snapshot())
        resumed.resolve(resumed.ready_matches()[0]["match_id"], "B")
        resumed.resolve(resumed.ready_matches()[0]["match_id"], "B")
        self.assertTrue(resumed.is_complete)
        self.assertEqual(["A", "B", "C", "D"],
                         resumed.snapshot()["locked_school_ids"])

    def test_duplicate_winner_or_early_final_is_forbidden(self):
        event = self._okinawa()
        with self.assertRaisesRegex(ValueError, "not ready"):
            event.resolve("STG000206-SGR000184-POST_RANK-FINAL", "A")
        first = event.ready_matches()[0]
        with self.assertRaisesRegex(ValueError, "winner must be"):
            event.resolve(first["match_id"], "UNQUALIFIED")
        event.resolve(first["match_id"], first["team1"])
        with self.assertRaisesRegex(ValueError, "already completed"):
            event.resolve(first["match_id"], first["team1"])

    def test_invalid_and_repeated_draw_participants_rejected(self):
        kwargs = dict(
            competition_id="CMP000112",
            stage_id="STG000183",
            stage_code="BRANCH_QUALIFIER",
            group_id="SGR000106",
            format_model_id="FMT025",
            mode="pairwise_deciders",
            locked_school_ids=["A", "B", "C", "D"],
        )
        for pairings in (
            (("A", "A"),),
            (("A", "Z"),),
            (("A", "B"), ("B", "C")),
            (("A",),),
        ):
            with self.subTest(pairings=pairings), self.assertRaises(ValueError):
                RankingOnlyEventRuntime.create(**kwargs, pairings=pairings)

    def test_source_stage_group_and_locked_qualification_are_validated(self):
        stage = executed_stage(
            "CMP000140", "STG000202", "SEED_EVENT",
            "SGR000171", "FMT022", ["A", "B", "C", "D"],
        )
        with self.assertRaises(ValueError):
            self.engine.prepare_post_qualification_ranking(
                stage_execution=stage, group_id="SGR000184",
            )
        stage.metadata["group_outputs"]["SGR000171"].append("UNQUALIFIED")
        with self.assertRaisesRegex(ValueError, "unqualified"):
            self.engine.prepare_post_qualification_ranking(
                stage_execution=stage, group_id="SGR000171",
            )

    def test_nonqualifier_is_never_added_to_ranking(self):
        event = self._shizuoka()
        self.assertNotIn("UNQUALIFIED", event.locked_school_ids)
        self.assertNotIn("UNQUALIFIED", [
            value
            for fixture in event.ready_matches()
            for value in (fixture["team1"], fixture["team2"])
        ])


if __name__ == "__main__":
    unittest.main()
