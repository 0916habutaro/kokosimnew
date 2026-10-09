from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from phase2_engine.hiroshima_fmt025_input_preflight import (
    Fmt025PreflightError, ROUTE_LOCK_FILE,
    load_preflight_payload_json, preflight_fmt025_input,
    require_live_fmt025_release,
)
from phase2_engine.hiroshima_stage13e3g32 import (
    EXAMPLE_OBSERVED_FILE, EXAMPLE_SANDBOX_FILE,
    audit_2026_hiroshima_stage13e3g32,
)

DATA = Path(__file__).resolve().parents[1] / "data"


def fixture(relative: str) -> dict:
    return json.loads((DATA / relative).read_text(encoding="utf-8"))


def try_fictional(update=None):
    p = fixture(EXAMPLE_SANDBOX_FILE)
    if update is not None:
        update(p)
    return preflight_fmt025_input(p)


class Stage13E3G32Fmt025VersionedInputContractTests(unittest.TestCase):
    def test_8_release_locks_and_48_official_requirements_stay_blocked(self):
        report = audit_2026_hiroshima_stage13e3g32(DATA)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["season_district_release_locks"], 8)
        self.assertEqual(report["official_unresolved_route_requirements"], 48)
        self.assertEqual(report["production_fmt025_release_paths"], 0)
        self.assertEqual(report["full_official_match_arrows_verified"], 0)
        self.assertFalse(report["optional_ranking_unlocked"])
        self.assertEqual(report["preview_scenarios"], {
            "fictional_inline": {
                "matches": 3, "first_entrants": 4, "outcome_transfers": 2,
                "qualifiers": 3, "read_only": True,
            },
            "observed_secondary": {
                "matches": 25, "first_entrants": 18, "outcome_transfers": 32,
                "qualifiers": 7, "read_only": True,
            },
        })

    def test_fictional_json_input_is_read_only_and_checksum_stable(self):
        one = try_fictional()
        two = try_fictional()
        self.assertEqual(one.payload_sha256, two.payload_sha256)
        self.assertEqual(len(one.payload_sha256), 64)
        self.assertEqual(one.qualifiers, ("A","C","B"))
        self.assertTrue(one.accepted_for_read_only_preview)
        self.assertFalse(one.authorized_for_live_fmt025)
        self.assertFalse(one.full_official_draw_verified)
        self.assertFalse(one.optional_ranking_allowed)
        self.assertEqual(one.source_kind, "fictional_inline")

    def test_json_duplicate_keys_and_invalid_constants_are_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', "{broken"):
            with self.subTest(raw=raw):
                with self.assertRaises(Fmt025PreflightError):
                    load_preflight_payload_json(raw)

    def test_schema_version_and_unknown_keys_do_not_silently_evolve(self):
        for change in (
            lambda p: p.update(contract_version="fmt025-explicit-input-v2"),
            lambda p: p.update(new_feature_auto_pairing=True),
            lambda p: p.pop("format_model_id"),
            lambda p: p.update(format_model_id="FMT024"),
        ):
            with self.subTest(change=repr(change)):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(change)

    def test_live_scheduler_or_ranking_requests_are_rejected(self):
        for change in (
            lambda p: p.update(execution_intent="live"),
            lambda p: p.update(execution_intent="generate_matches"),
            lambda p: p.update(optional_ranking_requested=True),
            lambda p: p.update(release_approved=True),
            lambda p: p.update(official_draw_verified=True),
            lambda p: p.update(official_loser_selector_verified=True),
        ):
            with self.subTest(change=repr(change)):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(change)

    def test_proof_claims_are_rejected_even_with_string_truthy_values(self):
        for value in ("yes","true",1,None):
            with self.subTest(value=value):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(lambda p: p.update(official_draw_verified=value))

    def test_sandbox_cannot_impersonate_official_year_or_stage(self):
        for change in (
            lambda p: p.update(year=2026),
            lambda p: p.update(season="autumn"),
            lambda p: p.update(district_code="west"),
            lambda p: p.update(stage_group_id="SGR000144"),
        ):
            with self.subTest(change=repr(change)):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(change)
        with self.assertRaises(Fmt025PreflightError):
            preflight_fmt025_input(fixture(EXAMPLE_SANDBOX_FILE), data_dir=DATA)

    def test_official_source_kind_can_only_be_fixed_secondary_2026_west(self):
        p = fixture(EXAMPLE_OBSERVED_FILE)
        result = preflight_fmt025_input(p, data_dir=DATA)
        self.assertEqual(result.match_count, 25)
        self.assertEqual(result.qualifier_count, 7)
        self.assertEqual(result.first_entry_count, 18)
        self.assertEqual(result.transfer_count, 32)
        self.assertEqual(result.evidence_grade, "observed_secondary_results_not_official_drawing")
        self.assertFalse(result.full_official_draw_verified)
        with self.assertRaises(Fmt025PreflightError):
            preflight_fmt025_input(p)
        with self.assertRaises(Fmt025PreflightError):
            preflight_fmt025_input(p, data_dir=None)

    def test_restrict_historical_to_exact_stage_and_quota(self):
        base = fixture(EXAMPLE_OBSERVED_FILE)
        for field, value in (
            ("year",2025), ("year",True), ("season","spring"),
            ("district_code","north"), ("stage_group_id","SGR000145"),
            ("qualifier_slots",6),
        ):
            with self.subTest(field=field):
                p = copy.deepcopy(base)
                p[field] = value
                with self.assertRaises(Fmt025PreflightError):
                    preflight_fmt025_input(p, data_dir=DATA)

    def test_caller_cannot_replace_checked_in_historical_games(self):
        base = fixture(EXAMPLE_OBSERVED_FILE)
        for key,value in (
            ("entrant_ids", ["A"]), ("matches", fixture(EXAMPLE_SANDBOX_FILE)["matches"]),
            ("winners_by_match", {"P1":"A"}), ("direct_main_entry_ids", ["EXEMPT"]),
        ):
            with self.subTest(field=key):
                p = copy.deepcopy(base)
                p[key]=value
                with self.assertRaises(Fmt025PreflightError):
                    preflight_fmt025_input(p, data_dir=DATA)

    def test_no_unknown_source_kind_or_fake_official_sourced_draw(self):
        with self.assertRaises(Fmt025PreflightError):
            try_fictional(lambda p: p.update(source_kind="federation_official_pdf"))
        with self.assertRaises(Fmt025PreflightError):
            try_fictional(lambda p: p.update(source_kind="stage25_2026_west_secondary"))

    def test_match_schema_strict_fields_and_boolean_types(self):
        for change in (
            lambda p: p["matches"][0].update(extra="value"),
            lambda p: p["matches"][0].pop("phase"),
            lambda p: p["matches"][0].update(loser_retry_authorized="no"),
            lambda p: p["matches"][0].update(winner_awards_berth=1),
            lambda p: p["matches"][0].update(winner_to_match=""),
            lambda p: p.update(matches="not a list"),
        ):
            with self.subTest(change=repr(change)):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(change)

    def test_invalid_winner_and_unmatched_loser_transfer_are_blocked(self):
        for change in (
            lambda p: p["winners_by_match"].update(R1="Z"),
            lambda p: p["winners_by_match"].pop("P1"),
            lambda p: p["matches"][0].update(loser_to_match=None),
            lambda p: p["matches"][2].update(left_source="loser:P2"),
            lambda p: p["matches"][1].update(left_source="winner:R1"),
            lambda p: p["matches"][2].update(phase="OPTIONAL_RANKING"),
        ):
            with self.subTest(change=repr(change)):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(change)

    def test_entrant_duplicates_and_bad_quotas_are_blocked(self):
        for change in (
            lambda p: p.update(entrant_ids=["A","B","C","C"]),
            lambda p: p.update(qualifier_slots=True),
            lambda p: p.update(qualifier_slots=0),
            lambda p: p.update(qualifier_slots=4),
            lambda p: p.update(direct_main_entry_ids=["A"]),
        ):
            with self.subTest(change=repr(change)):
                with self.assertRaises(Fmt025PreflightError):
                    try_fictional(change)

    def test_digest_changes_with_bound_candidate_data(self):
        original = try_fictional()
        changed = try_fictional(lambda p: p["winners_by_match"].update(R1="D"))
        self.assertNotEqual(original.payload_sha256, changed.payload_sha256)
        self.assertEqual(changed.qualifiers, ("A","C","D"))
        self.assertFalse(changed.authorized_for_live_fmt025)

    def test_release_requires_an_unimplemented_external_verifier(self):
        candidate = try_fictional()
        with self.assertRaises(Fmt025PreflightError):
            require_live_fmt025_release(candidate)
        # Even a dishonest dataclass replacement cannot bypass this boundary.
        cheated = replace(candidate, authorized_for_live_fmt025=True,
                          full_official_draw_verified=True)
        with self.assertRaises(Fmt025PreflightError):
            require_live_fmt025_release(cheated)
        with self.assertRaises(Fmt025PreflightError):
            require_live_fmt025_release({"authorized":True})

    def test_release_lock_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"data"
            shutil.copytree(DATA,root)
            path=root/ROUTE_LOCK_FILE
            raw=path.read_text(encoding="utf-8")
            self.assertIn(",no,no,blocked_pending_verified",raw)
            path.write_text(raw.replace(
                ",no,no,blocked_pending_verified", ",yes,no,blocked_pending_verified",1
            ), encoding="utf-8")
            result=audit_2026_hiroshima_stage13e3g32(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("annual FMT025 preflight release boundary changed" in x
                                for x in result["errors"]),result["errors"])

    def test_full_audit_rejects_unsupported_self_certified_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"data"
            shutil.copytree(DATA,root)
            target=root/EXAMPLE_SANDBOX_FILE
            p=json.loads(target.read_text(encoding="utf-8"))
            p["official_draw_verified"]=True
            target.write_text(json.dumps(p,ensure_ascii=False),encoding="utf-8")
            result=audit_2026_hiroshima_stage13e3g32(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("versioned input preflight rejected" in x
                                for x in result["errors"]),result["errors"])


if __name__ == "__main__":
    unittest.main()
