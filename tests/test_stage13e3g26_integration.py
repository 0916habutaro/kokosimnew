from __future__ import annotations
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_stage13e3g26 import (
    MACRO_TEMPLATE_FILE, audit_2026_hiroshima_stage13e3g26,
)
from phase2_engine.hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from phase2_engine.hiroshima_stage13e3g18 import TRANSITION_FILE
from phase2_engine.hiroshima_stage13e3g22 import PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE
from phase2_engine.hiroshima_stage13e3g24 import GRAPH_FILE, PREVIEW_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
FILES = (
    MACRO_TEMPLATE_FILE, NODES_FILE, EDGES_FILE, TIMELINE_FILE,
    TRANSITION_FILE, PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE,
    GRAPH_FILE, PREVIEW_FILE,
)


def modify(root: Path, path: str, fn):
    target = root / path
    with target.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols, rows = rd.fieldnames, list(rd)
    fn(rows)
    with target.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)


class Stage13E3G26IntegrationTests(unittest.TestCase):
    def test_year_independent_sandbox_and_year_limited_official_example(self):
        report = audit_2026_hiroshima_stage13e3g26(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["historical_2026_west_matches_rechecked"], 25)
        self.assertEqual(report["historical_2026_west_edges_rechecked"], 32)
        self.assertEqual(report["historical_main_qualifiers"], 7)
        self.assertEqual(report["observed_2026_macro_qualifier_slots"], 7)
        self.assertEqual([p["participants"] for p in report["future_sandbox_entrant_sizes"]],
                         [18, 19, 23])
        self.assertFalse(report["official_full_pairings_verified"])
        self.assertFalse(report["official_general_loser_selector_verified"])
        self.assertFalse(report["live_fmt025_runtime_changed"])
        self.assertFalse(report["optional_ranking_unlocked"])

    def assert_bad(self, path: str, fn, error_fragment: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for item in FILES:
                output = root / item
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(DATA / item, output)
            modify(root, path, fn)
            report = audit_2026_hiroshima_stage13e3g26(root)
            self.assertFalse(report["ok"])
            self.assertTrue(any(error_fragment in msg for msg in report["errors"]),
                            report["errors"])

    def test_wrong_annual_policy_or_quota_is_rejected(self):
        self.assert_bad(MACRO_TEMPLATE_FILE,
                        lambda rows: rows[0].update(observed_qualifier_awards="8"),
                        "observed_qualifier_awards")
        self.assert_bad(MACRO_TEMPLATE_FILE,
                        lambda rows: rows[0].update(reference_year="2027"),
                        "reference_year")

    def test_unverified_future_annual_rule_claim_is_rejected(self):
        self.assert_bad(MACRO_TEMPLATE_FILE,
                        lambda rows: rows[0].update(general_future_year_regulation_claimed="yes"),
                        "general_future_year_regulation_claimed")
        self.assert_bad(MACRO_TEMPLATE_FILE,
                        lambda rows: rows[0].update(annual_official_loser_transfer_rule_proven="yes"),
                        "annual_official_loser_transfer_rule_proven")

    def test_false_runtime_or_ranking_unlocked_rejected(self):
        self.assert_bad(MACRO_TEMPLATE_FILE,
                        lambda rows: rows[0].update(live_fmt025_runtime_enabled="yes"),
                        "live_fmt025_runtime_enabled")
        self.assert_bad(MACRO_TEMPLATE_FILE,
                        lambda rows: rows[0].update(optional_ranking_enabled="yes"),
                        "optional_ranking_enabled")
        self.assert_bad(GRAPH_FILE,
                        lambda rows: rows[0].update(fmt025_live_route_approved="yes"),
                        "official match routing incorrectly released")

    def test_missing_macro_record_is_rejected(self):
        self.assert_bad(MACRO_TEMPLATE_FILE, lambda rows: rows.pop(),
                        "single year-limited west macro template")

    def test_stage25_graph_source_drift_is_rejected(self):
        self.assert_bad(NODES_FILE, lambda rows: rows[0].update(observed_winner="架空校"),
                        "Stage25 25-game/32-edge historical ledger")


if __name__ == "__main__":
    unittest.main()
