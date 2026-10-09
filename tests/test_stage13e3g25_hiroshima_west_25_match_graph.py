from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g25 import (
    NODES_FILE, EDGES_FILE, audit_2026_hiroshima_stage13e3g25,
)
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_stage13e3g18 import TRANSITION_FILE
from phase2_engine.hiroshima_stage13e3g22 import PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE
from phase2_engine.hiroshima_stage13e3g24 import GRAPH_FILE, PREVIEW_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
FILES = (
    NODES_FILE, EDGES_FILE, TIMELINE_FILE, TRANSITION_FILE,
    PUBLISHER_GROUPS_FILE, GRAPH_FILE, PREVIEW_FILE, PRIOR_YEAR_PDF_FILE,
)


def copy_data(root: Path):
    for rel in FILES:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA / rel, dst)


def change(root: Path, rel: str, action):
    file = root / rel
    with file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames, rows = reader.fieldnames, list(reader)
    action(rows)
    with file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G25HiroshimaWest25MatchGraphTests(unittest.TestCase):
    def test_25_played_matches_32_continuations_18_schools(self):
        result = audit_2026_hiroshima_stage13e3g25(DATA)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["historical_played_games"], 25)
        self.assertEqual(result["mapped_phase_nodes"], 25)
        self.assertEqual(result["role_counts"], {
            "PRIMARY": 14, "REPECHAGE_ZONE": 10,
            "REPECHAGE_CROSS_ZONE_GATE": 1,
        })
        self.assertEqual(result["school_continuation_edges"], 32)
        self.assertEqual(result["distinct_first_entry_schools"], 18)
        self.assertEqual(result["historical_berth_awards"], 7)
        self.assertEqual(result["official_numbered_match_arrows_verified"], 0)
        self.assertFalse(result["raw_2026_official_pdf_acquired"])
        self.assertFalse(result["season_independent_loser_selector_verified"])
        self.assertFalse(result["live_fmt025_runtime_changed"])

    def assert_blocked(self, path, update, error):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_data(root)
            change(root, path, update)
            result = audit_2026_hiroshima_stage13e3g25(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any(error in e for e in result["errors"]), result["errors"])

    def test_numbered_match_slot_requires_primary_confirmation(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(official_match_number="1"),
                            "official_match_number")

    def test_false_official_pairing_confirmation_rejected(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(official_pairings_verified="yes"),
                            "official_pairings_verified")

    def test_false_individual_loser_arrow_rejected(self):
        self.assert_blocked(EDGES_FILE,
                            lambda r: r[0].update(official_number_and_arrow_verified="yes"),
                            "official_number_and_arrow_verified")

    def test_2026_team_and_score_tampering_rejected(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(team1_name="架空校"),
                            "team1_name")
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(team1_score="999"),
                            "team1_score")

    def test_wrong_zone_phase_or_publisher_rejected(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(zone_scope="D"),
                            "zone_scope")
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(publisher_route_id="HR00000000"),
                            "publisher_route_id")

    def test_second_place_wrongly_promoted_to_primary_rejected(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: next(n for n in r if n["match_id"] == "HT20260035").update(
                                phase_execution_role="PRIMARY"
                            ),
                            "phase_execution_role")

    def test_c_d_cross_gate_must_exist(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: [x for x in r if x["match_id"] == "HT20260072"][0].update(
                                publisher_event_audit_id="HAW2026003"
                            ),
                            "publisher_event_audit_id")

    def test_no_extra_or_missing_fixtures(self):
        self.assert_blocked(NODES_FILE, lambda r: r.pop(), "25 unique")
        self.assert_blocked(NODES_FILE, lambda r: r.append(dict(r[0])), "25 unique")

    def test_all_32_observed_school_edges_required(self):
        self.assert_blocked(EDGES_FILE, lambda r: r.pop(), "32 unique")
        self.assert_blocked(EDGES_FILE,
                            lambda r: r[0].update(to_match_id="HT20260072"),
                            "to_match_id")
        self.assert_blocked(EDGES_FILE,
                            lambda r: r[0].update(school_display_name="架空校"),
                            "school_display_name")

    def test_edge_result_outcome_must_match_played_result(self):
        self.assert_blocked(EDGES_FILE,
                            lambda r: r[0].update(from_result="loser"),
                            "from_result")

    def test_2025_2026_graph_not_interchangeable(self):
        self.assert_blocked(PRIOR_YEAR_PDF_FILE,
                            lambda r: r[0].update(prior_year_graph_reusable_for_2026="yes"),
                            "prior-year")

    def test_official_preview_macro_limit_immutable(self):
        self.assert_blocked(PREVIEW_FILE,
                            lambda r: r[0].update(all_pairings_and_loser_arrows_reviewed="yes"),
                            "macro-level")
        self.assert_blocked(PREVIEW_FILE,
                            lambda r: r[0].update(source_pdf_bytes_downloaded="yes"),
                            "macro-level")

    def test_changes_to_source_history_are_detected(self):
        self.assert_blocked(TIMELINE_FILE,
                            lambda r: next(x for x in r if x["match_id"] == "HT20260072").update(
                                winner_name="広島城北"
                            ),
                            "observed_winner")
        self.assert_blocked(TRANSITION_FILE,
                            lambda r: next(x for x in r if x["transition_id"] == "HPTR20260072").update(
                                from_result="loser"
                            ),
                            "from_result")

    def test_runtime_activation_is_rejected(self):
        self.assert_blocked(NODES_FILE,
                            lambda r: r[0].update(fmt025_live_allowed="yes"),
                            "fmt025_live_allowed")
        self.assert_blocked(EDGES_FILE,
                            lambda r: r[0].update(fmt025_live_allowed="yes"),
                            "fmt025_live_allowed")
        self.assert_blocked(GRAPH_FILE,
                            lambda r: r[0].update(fmt025_live_route_approved="yes"),
                            "cannot silently unlock")


if __name__ == "__main__":
    unittest.main()
