from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from phase2_engine.hiroshima_explicit_match_dag_sandbox import (
    ExplicitMatch, ExplicitMatchReplayError, replay_explicit_match_dag,
)
from phase2_engine.hiroshima_stage13e3g31 import (
    SANDBOX_EXAMPLES_FILE, audit_2026_hiroshima_stage13e3g31,
    replay_stage25_historical_observations,
)
from phase2_engine.hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from phase2_engine.hiroshima_match_level_2026 import _read

DATA = Path(__file__).resolve().parents[1] / "data"


def simple():
    return (
        ExplicitMatch("P1","entrant:A","entrant:B","PRIMARY",
                      loser_to_match="R1", winner_awards_berth=True),
        ExplicitMatch("P2","entrant:C","entrant:D","PRIMARY",
                      loser_to_match="R1", winner_awards_berth=True),
        ExplicitMatch("R1","loser:P1","loser:P2","REPECHAGE_ZONE",
                      winner_awards_berth=True),
    )


def simple_replay(**changes):
    kwargs = {
        "entrant_ids": ("A","B","C","D"),
        "matches": simple(),
        "winners_by_match": {"P1":"A","P2":"C","R1":"B"},
        "qualifier_slots": 3,
    }
    kwargs.update(changes)
    return replay_explicit_match_dag(**kwargs)


def retry_example():
    return (
        ExplicitMatch("P1","entrant:A","entrant:B","PRIMARY",
                      loser_to_match="R1", winner_awards_berth=True),
        ExplicitMatch("P2","entrant:C","entrant:D","PRIMARY",
                      loser_to_match="R1", winner_awards_berth=True),
        ExplicitMatch("P3","entrant:E","entrant:F","PRIMARY",
                      loser_to_match="R2", winner_awards_berth=True),
        ExplicitMatch("R1","loser:P1","loser:P2","REPECHAGE_ZONE",
                      winner_to_match="R2", loser_to_match="R3",
                      loser_retry_authorized=True),
        ExplicitMatch("R2","winner:R1","loser:P3","REPECHAGE_ZONE",
                      loser_to_match="R3", loser_retry_authorized=True,
                      winner_awards_berth=True),
        ExplicitMatch("R3","loser:R1","loser:R2","CONDITIONAL_RETRY",
                      winner_awards_berth=True),
    )


def retry_replay(**changes):
    kwargs = {
        "entrant_ids": ("A","B","C","D","E","F"),
        "matches": retry_example(),
        "winners_by_match": {"P1":"A","P2":"C","P3":"E","R1":"B","R2":"B","R3":"D"},
        "qualifier_slots": 5,
    }
    kwargs.update(changes)
    return replay_explicit_match_dag(**kwargs)


def modify_csv(path, update):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        cols, records = reader.fieldnames, list(reader)
    update(records)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(records)


class Stage13E3G31ExplicitOutcomeDagTests(unittest.TestCase):
    def test_four_school_explicit_first_loss_repechage(self):
        actual = simple_replay()
        self.assertEqual(actual.qualifier_ids, ("A","C","B"))
        self.assertEqual(len(actual.match_traces), 3)
        self.assertEqual(actual.consumed_declared_outcome_transfers, 2)
        self.assertEqual(actual.consumed_initial_entrant_ids, ("A","B","C","D"))
        self.assertEqual(actual.retried_loser_ids, ())
        self.assertFalse(actual.official_draw_verified)
        self.assertFalse(actual.generated_bracket)
        self.assertFalse(actual.live_fmt025_runtime_enabled)
        self.assertFalse(actual.optional_ranking_enabled)

    def test_conditional_retry_is_possible_only_on_named_gate(self):
        replay = retry_replay()
        self.assertEqual(replay.qualifier_ids, ("A","C","E","B","D"))
        self.assertEqual(replay.retried_loser_ids, ("D","F"))
        self.assertEqual(replay.consumed_declared_outcome_transfers, 6)
        self.assertEqual(len(replay.match_traces), 6)
        self.assertFalse(replay.official_draw_verified)

    def test_exempt_direct_main_entrant_kept_separate(self):
        replay = simple_replay(direct_main_entry_ids=("EXEMPT",))
        self.assertEqual(replay.all_main_entry_ids, ("A","C","B","EXEMPT"))
        self.assertEqual(replay.direct_main_entry_ids, ("EXEMPT",))
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(direct_main_entry_ids=("A",))
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(direct_main_entry_ids=("X","X"))

    def test_initial_entrants_must_be_unique_and_all_used(self):
        for entrants in (("A","B","C","C"), ("A","B","C","D","E"), (), ("A","B","C","")):
            with self.subTest(entrants=entrants):
                with self.assertRaises(ExplicitMatchReplayError):
                    simple_replay(entrant_ids=entrants)

    def test_no_automatic_missing_result_inference(self):
        for results in (
            {"P1":"A","P2":"C"},
            {"P1":"A","P2":"C","R1":"B","extra":"B"},
            {"P1":"A","P2":"C","R1":"Z"},
        ):
            with self.subTest(results=results):
                with self.assertRaises(ExplicitMatchReplayError):
                    simple_replay(winners_by_match=results)

    def test_no_duplicate_match_or_invalid_phase(self):
        for altered in (
            simple() + (simple()[0],),
            (replace(simple()[0], match_id=""),) + simple()[1:],
            (replace(simple()[0], phase="OPTIONAL_RANKING"),) + simple()[1:],
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(ExplicitMatchReplayError):
                    simple_replay(matches=altered)

    def test_same_initial_school_cannot_be_entered_again(self):
        altered = list(simple())
        altered[1] = replace(altered[1], right_source="entrant:B")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_outcome_token_must_be_explicitly_forwarded(self):
        altered = list(simple())
        altered[0] = replace(altered[0], loser_to_match=None)
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_disconnected_upstream_transfer_is_rejected(self):
        altered = list(simple())
        altered[2] = replace(altered[2], left_source="entrant:B")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_future_source_and_cyclic_graph_rejected(self):
        altered = list(simple())
        altered[0] = replace(altered[0], left_source="winner:P2")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_no_qualified_winner_reentry_or_forwarding(self):
        altered = list(simple())
        altered[0] = replace(altered[0], winner_to_match="R1")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_primary_winner_does_not_transfer_to_repechage(self):
        altered = list(simple())
        altered[0] = replace(altered[0], winner_awards_berth=False,
                             winner_to_match="R1")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_primary_loser_cannot_jump_to_cross_zone_without_named_repechage(self):
        altered = list(simple())
        altered[2] = replace(altered[2], phase="REPECHAGE_CROSS_ZONE_GATE")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))
        altered[2] = replace(altered[2], phase="CONDITIONAL_RETRY")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_repeated_secondary_loser_is_forbidden_without_opt_in(self):
        altered = list(retry_example())
        altered[3] = replace(altered[3], loser_retry_authorized=False)
        with self.assertRaises(ExplicitMatchReplayError):
            retry_replay(matches=tuple(altered))

    def test_secondary_loser_cannot_go_to_primary_or_regular_repechage(self):
        altered = list(retry_example())
        altered[5] = replace(altered[5], phase="REPECHAGE_ZONE")
        with self.assertRaises(ExplicitMatchReplayError):
            retry_replay(matches=tuple(altered))
        altered = list(retry_example())
        altered[5] = replace(altered[5], phase="PRIMARY")
        with self.assertRaises(ExplicitMatchReplayError):
            retry_replay(matches=tuple(altered))

    def test_secondary_winner_cannot_return_to_primary(self):
        altered = list(retry_example())
        altered[3] = replace(altered[3], winner_awards_berth=False,
                             winner_to_match="P3")
        with self.assertRaises(ExplicitMatchReplayError):
            retry_replay(matches=tuple(altered))

    def test_self_play_and_duplicate_same_token_rejected(self):
        altered = list(simple())
        altered[2] = replace(altered[2], right_source="loser:P1")
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(matches=tuple(altered))

    def test_berth_quota_checked_and_no_optional_ranking(self):
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(qualifier_slots=2)
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(qualifier_slots=0)
        with self.assertRaises(ExplicitMatchReplayError):
            simple_replay(qualifier_slots=True)

    def test_stage31_historical_fixture_graph_only_is_a_sandbox(self):
        report = audit_2026_hiroshima_stage13e3g31(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["fictional_sandbox_scenarios"], {
            "simple_four_entrants": {"matches": 3, "qualifiers": 3,
                                      "conditional_retries": 0},
            "conditional_six_entrants": {"matches": 6, "qualifiers": 5,
                                         "conditional_retries": 2},
        })
        self.assertEqual(report["observed_2026_west_replay_matches"], 25)
        self.assertEqual(report["observed_2026_west_replay_initial_entrants"], 18)
        self.assertEqual(report["observed_2026_west_replay_transfers"], 32)
        self.assertEqual(report["observed_2026_west_replay_berths"], 7)
        self.assertEqual(report["remaining_unverified_season_district_rules"], 48)
        self.assertEqual(report["official_2026_independently_verified_match_arrows"], 0)
        self.assertFalse(report["year_independent_loser_rule_verified"])
        self.assertFalse(report["automatic_match_pairings_generated"])
        self.assertFalse(report["live_fmt025_runtime_enabled"])
        self.assertFalse(report["optional_ranking_enabled"])

    def test_in_memory_replay_from_2026_dated_results_is_not_official_proof(self):
        historical_nodes = _read(DATA, NODES_FILE)
        historical_edges = _read(DATA, EDGES_FILE)
        observed = replay_stage25_historical_observations(historical_nodes, historical_edges)
        self.assertEqual(len(observed.match_traces), 25)
        self.assertEqual(observed.consumed_declared_outcome_transfers, 32)
        self.assertEqual(len(observed.qualifier_ids), 7)
        self.assertFalse(observed.official_draw_verified)
        self.assertFalse(observed.live_fmt025_runtime_enabled)

    def assert_corrupt_rejected(self, path, fn, fragment):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            shutil.copytree(DATA, root)
            modify_csv(root / path, fn)
            result = audit_2026_hiroshima_stage13e3g31(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any(fragment in s for s in result["errors"]), result["errors"])

    def test_2026_historical_outcome_mismatch_rejected(self):
        self.assert_corrupt_rejected(
            NODES_FILE,
            lambda rows: next(x for x in rows if x["match_id"] == "HT20260072").update(
                observed_winner="広島城北"),
            "Stage25 observed match graph",
        )

    def test_historical_school_outcome_connection_changed_rejected(self):
        self.assert_corrupt_rejected(
            EDGES_FILE,
            lambda rows: rows[0].update(to_match_id="HT20260072"),
            "Stage25 observed match graph",
        )

    def test_sandbox_cannot_be_upgraded_to_verified_draw(self):
        self.assert_corrupt_rejected(
            SANDBOX_EXAMPLES_FILE,
            lambda rows: rows[0].update(official_2026_bracket_verified="yes"),
            "sandbox proof scope",
        )

    def test_sandbox_cannot_be_connected_to_live_runtime(self):
        self.assert_corrupt_rejected(
            SANDBOX_EXAMPLES_FILE,
            lambda rows: rows[0].update(live_fmt025_enabled="yes"),
            "sandbox proof scope",
        )
        self.assert_corrupt_rejected(
            SANDBOX_EXAMPLES_FILE,
            lambda rows: rows[0].update(optional_ranking_enabled="yes"),
            "sandbox proof scope",
        )

    def test_sandbox_wrong_loser_destination_rejected(self):
        self.assert_corrupt_rejected(
            SANDBOX_EXAMPLES_FILE,
            lambda rows: rows[0].update(loser_to_match="INVALID"),
            "fictional explicit match graph rejected",
        )

    def test_sandbox_duplicate_scenario_fixture_rejected(self):
        self.assert_corrupt_rejected(
            SANDBOX_EXAMPLES_FILE,
            lambda rows: rows.append(dict(rows[0])),
            "two separate fictional DAG examples",
        )


if __name__ == "__main__":
    unittest.main()
