from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from phase2_engine.hiroshima_fmt025_input_preflight import load_preflight_payload_json
from phase2_engine.hiroshima_fmt025_incremental_preview import (
    CHECKPOINT_VERSION, MATCH_WAITING, MATCH_READY, MATCH_COMPLETED,
    IncrementalPreviewError, export_read_only_checkpoint,
    inspect_read_only_preview, record_preapproved_match_result,
    restore_read_only_checkpoint, start_read_only_preview,
)
from phase2_engine.hiroshima_stage13e3g32 import EXAMPLE_SANDBOX_FILE, EXAMPLE_OBSERVED_FILE
from phase2_engine.hiroshima_stage13e3g33 import (
    EXPECTED_EVENTS_FILE, audit_2026_hiroshima_stage13e3g33,
)
from phase2_engine.hiroshima_stage13e3g25 import EDGES_FILE

DATA = Path(__file__).resolve().parents[1] / "data"


def sample():
    return load_preflight_payload_json((DATA / EXAMPLE_SANDBOX_FILE).read_text(encoding="utf-8"))


def observed():
    return load_preflight_payload_json((DATA / EXAMPLE_OBSERVED_FILE).read_text(encoding="utf-8"))


def started():
    return start_read_only_preview(sample())


def after_p1():
    initial = started()
    return record_preapproved_match_result(
        sample(), initial.checkpoint, match_id="P1", recorded_winner_id="A",
    )


class Stage13E3G33IncrementalStateTests(unittest.TestCase):
    def test_initial_results_pending_with_two_ready_one_waiting(self):
        result=started()
        self.assertEqual(result.checkpoint.checkpoint_version,CHECKPOINT_VERSION)
        self.assertEqual(result.ready_match_ids,("P1","P2"))
        self.assertEqual(result.waiting_match_ids,("R1",))
        self.assertEqual(result.played_match_ids,())
        self.assertEqual(result.confirmed_qualifier_ids,())
        self.assertEqual(result.remaining_qualifier_slots,3)
        self.assertFalse(result.replay_completed)
        self.assertEqual([r.status for r in result.match_statuses],
                         [MATCH_READY,MATCH_READY,MATCH_WAITING])
        self.assertIsNone(result.match_statuses[2].left_team_id)
        self.assertIsNone(result.match_statuses[2].right_team_id)
        self.assertIsNone(result.match_statuses[0].winner_team_id)

    def test_first_match_awards_berth_without_revealing_future_entrant(self):
        result=after_p1()
        self.assertEqual(result.played_match_ids,("P1",))
        self.assertEqual(result.confirmed_qualifier_ids,("A",))
        self.assertEqual(result.remaining_qualifier_slots,2)
        self.assertEqual(result.ready_match_ids,("P2",))
        self.assertEqual(result.waiting_match_ids,("R1",))
        self.assertEqual(result.match_statuses[0].winner_team_id,"A")
        self.assertEqual(result.match_statuses[0].loser_team_id,"B")
        self.assertIsNone(result.match_statuses[2].left_team_id)

    def test_two_initial_matches_unlock_repechage_and_then_finish(self):
        first=after_p1()
        second=record_preapproved_match_result(
            sample(),first.checkpoint,match_id="P2",recorded_winner_id="C",
        )
        self.assertEqual(second.ready_match_ids,("R1",))
        self.assertEqual(second.waiting_match_ids,())
        self.assertEqual(second.confirmed_qualifier_ids,("A","C"))
        self.assertEqual((second.match_statuses[2].left_team_id,
                          second.match_statuses[2].right_team_id),("B","D"))
        self.assertIsNone(second.match_statuses[2].winner_team_id)
        final=record_preapproved_match_result(
            sample(),second.checkpoint,match_id="R1",recorded_winner_id="B",
        )
        self.assertTrue(final.replay_completed)
        self.assertEqual(final.ready_match_ids,())
        self.assertEqual(final.waiting_match_ids,())
        self.assertEqual(final.played_match_ids,("P1","P2","R1"))
        self.assertEqual(final.confirmed_qualifier_ids,("A","C","B"))
        self.assertEqual(final.remaining_qualifier_slots,0)
        self.assertFalse(final.live_fmt025_runtime_enabled)
        self.assertFalse(final.official_draw_verified)

    def test_parallel_initial_matches_can_be_revealed_in_reverse_order(self):
        one=started()
        two=record_preapproved_match_result(sample(),one.checkpoint,
                                            match_id="P2",recorded_winner_id="C")
        self.assertEqual(two.ready_match_ids,("P1",))
        self.assertEqual(two.waiting_match_ids,("R1",))
        third=record_preapproved_match_result(sample(),two.checkpoint,
                                              match_id="P1",recorded_winner_id="A")
        self.assertEqual(third.ready_match_ids,("R1",))
        self.assertEqual(third.played_match_ids,("P1","P2"))
        self.assertEqual(third.checkpoint.applied_results,(("P2","C"),("P1","A")))

    def test_cannot_skip_unplayed_upstream_or_replay_completed_match(self):
        with self.assertRaises(IncrementalPreviewError):
            record_preapproved_match_result(
                sample(),started().checkpoint,match_id="R1",recorded_winner_id="B")
        with self.assertRaises(IncrementalPreviewError):
            record_preapproved_match_result(
                sample(),after_p1().checkpoint,match_id="P1",recorded_winner_id="A")

    def test_unknown_or_wrong_result_rejected(self):
        for match_id,winner in (("BAD","A"),("P1","B"),("P1","OTHER")):
            with self.subTest(match_id=match_id,winner=winner):
                with self.assertRaises(IncrementalPreviewError):
                    record_preapproved_match_result(
                        sample(),started().checkpoint,match_id=match_id,
                        recorded_winner_id=winner,
                    )

    def test_checkpoint_exact_json_roundtrip(self):
        for view in (started(),after_p1()):
            raw=export_read_only_checkpoint(view.checkpoint)
            restored=restore_read_only_checkpoint(sample(),raw)
            self.assertEqual(restored,view)
            self.assertEqual(restored.checkpoint.payload_sha256,view.checkpoint.payload_sha256)
            self.assertEqual(len(restored.checkpoint.topology_sha256),64)

    def test_checkpoint_recovery_then_incrementally_advance(self):
        snapshot=after_p1()
        recover=restore_read_only_checkpoint(
            sample(),export_read_only_checkpoint(snapshot.checkpoint),
        )
        next_step=record_preapproved_match_result(
            sample(),recover.checkpoint,match_id="P2",recorded_winner_id="C",
        )
        self.assertEqual(next_step.ready_match_ids,("R1",))

    def test_duplicate_checkpoint_event_rejected(self):
        view=after_p1()
        cheated=replace(view.checkpoint,
                        applied_results=(("P1","A"),("P1","A")))
        with self.assertRaises(IncrementalPreviewError):
            inspect_read_only_preview(sample(),cheated)

    def test_out_of_order_checkpoint_event_rejected(self):
        cheated=replace(started().checkpoint,
                        applied_results=(("R1","B"),("P1","A"),("P2","C")))
        with self.assertRaises(IncrementalPreviewError):
            inspect_read_only_preview(sample(),cheated)

    def test_checkpoint_bogus_winner_event_rejected(self):
        cheated=replace(started().checkpoint,applied_results=(("P1","B"),))
        with self.assertRaises(IncrementalPreviewError):
            inspect_read_only_preview(sample(),cheated)

    def test_checkpoint_unknown_event_rejected(self):
        cheated=replace(started().checkpoint,applied_results=(("UNKNOWN","A"),))
        with self.assertRaises(IncrementalPreviewError):
            inspect_read_only_preview(sample(),cheated)

    def test_checkpoint_tampered_hash_or_source_rejected(self):
        base=started().checkpoint
        for kwargs in (
            {"payload_sha256":"0"*64},
            {"topology_sha256":"0"*64},
            {"source_kind":"stage25_2026_west_secondary"},
            {"checkpoint_version":"fmt025-read-only-checkpoint-v2"},
            {"official_draw_verified":True},
            {"live_fmt025_runtime_enabled":True},
            {"optional_ranking_enabled":True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(IncrementalPreviewError):
                    inspect_read_only_preview(sample(),replace(base,**kwargs))

    def test_checkpoint_does_not_apply_to_changed_input_fixture(self):
        base=started().checkpoint
        candidate=sample()
        candidate["winners_by_match"]["R1"]="D"
        with self.assertRaises(IncrementalPreviewError):
            inspect_read_only_preview(candidate,base)

    def test_checkpoint_strict_json_restore_blocks_duplicates_unknown_and_flags(self):
        baseline=json.loads(export_read_only_checkpoint(started().checkpoint))
        cases=[
            {**baseline,"extra":"release"},
            {**baseline,"official_draw_verified":True},
            {**baseline,"live_fmt025_runtime_enabled":1},
            {**baseline,"optional_ranking_enabled":"false"},
            {**baseline,"applied_results":[["R1","B"]]},
            {**baseline,"applied_results":[["P1","A"],["P1","A"]]},
            {**baseline,"applied_results":[["P1","OTHER"]]},
            {**baseline,"applied_results":"P1=A"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(IncrementalPreviewError):
                    restore_read_only_checkpoint(sample(),json.dumps(payload))
        with self.assertRaises(IncrementalPreviewError):
            restore_read_only_checkpoint(sample(),'{"a":1,"a":2}')

    def test_read_only_history_starts_ready_without_claiming_official_pdf(self):
        view=start_read_only_preview(observed(),data_dir=DATA)
        self.assertEqual(len(view.match_statuses),25)
        self.assertGreaterEqual(len(view.ready_match_ids),2)
        self.assertEqual(view.confirmed_qualifier_ids,())
        self.assertEqual(view.remaining_qualifier_slots,7)
        self.assertEqual(view.evidence_grade,"observed_secondary_results_not_official_drawing")
        self.assertFalse(view.live_fmt025_runtime_enabled)
        self.assertFalse(view.official_draw_verified)

    def test_historical_resume_requires_data_dir(self):
        history=start_read_only_preview(observed(),data_dir=DATA)
        raw=export_read_only_checkpoint(history.checkpoint)
        with self.assertRaises(IncrementalPreviewError):
            restore_read_only_checkpoint(observed(),raw)
        self.assertEqual(
            restore_read_only_checkpoint(observed(),raw,data_dir=DATA),history,
        )

    def test_history_tamper_changes_content_address_even_with_matching_payload_sha(self):
        original=start_read_only_preview(observed(),data_dir=DATA)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"data"
            shutil.copytree(DATA,root)
            target=root/EDGES_FILE
            raw=target.read_text(encoding="utf-8")
            # Swap the two feeders of the same downstream match. The set
            # of observations is unchanged but its ordered provenance
            # topology differs and must invalidate the old checkpoint.
            rows=raw.splitlines()
            rows[2],rows[24]=rows[24],rows[2]
            target.write_text("\n".join(rows)+"\n",encoding="utf-8")
            with self.assertRaises(IncrementalPreviewError):
                inspect_read_only_preview(observed(),original.checkpoint,data_dir=root)

    def test_strict_recording_strings_and_state_type(self):
        baseline=started()
        for match_id,winner in ((1,"A"),("P1",3),(None,"A")):
            with self.subTest(match_id=match_id):
                with self.assertRaises(IncrementalPreviewError):
                    record_preapproved_match_result(
                        sample(),baseline.checkpoint,match_id=match_id,
                        recorded_winner_id=winner,
                    )
        with self.assertRaises(IncrementalPreviewError):
            inspect_read_only_preview(sample(),{"events":[]})
        with self.assertRaises(IncrementalPreviewError):
            export_read_only_checkpoint({"applied_results":[]})

    def test_full_stage33_audit_binds_four_expected_steps_and_historical_25(self):
        result=audit_2026_hiroshima_stage13e3g33(DATA)
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual(result["fictional_expected_progress_states"],4)
        self.assertEqual(result["historical_incremental_replay"]["historical_matches_revealed"],25)
        self.assertEqual(result["historical_incremental_replay"]["historical_berths_revealed"],7)
        self.assertTrue(result["historical_incremental_replay"]["replay_completed"])
        self.assertEqual(result["official_2026_verified_individual_arrows"],0)
        self.assertEqual(result["unverified_2026_season_district_route_rules"],48)
        self.assertFalse(result["production_fmt025_runtime_connected"])
        self.assertFalse(result["optional_ranking_unlocked"])

    def test_expected_progress_manifest_tamper_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"data"
            shutil.copytree(DATA,root)
            target=root/EXPECTED_EVENTS_FILE
            data=json.loads(target.read_text(encoding="utf-8"))
            data["events"][1]["confirmed_qualifier_ids"]=["A","C"]
            target.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
            result=audit_2026_hiroshima_stage13e3g33(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("recorded fictional step 1 not reproduced" in x
                                for x in result["errors"]),result["errors"])


if __name__ == "__main__":
    unittest.main()
