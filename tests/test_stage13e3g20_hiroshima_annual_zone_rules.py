from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_annual_zone_draft import (
    ZoneDraftError, make_balanced_zone_draft,
)
from phase2_engine.hiroshima_stage13e3g20 import (
    ZONE_CONTRACT_FILE, ROUTE_REQUIREMENTS_FILE,
    audit_2026_hiroshima_stage13e3g20,
)
from phase2_engine.hiroshima_stage13e3g17 import (
    GROUP_CONTRACT_FILE, CROSSWALK_FILE,
)
from phase2_engine.hiroshima_stage13e3g19 import GATE_POLICY_FILE

DATA = Path(__file__).resolve().parents[1] / "data"
INPUTS = (
    ZONE_CONTRACT_FILE, ROUTE_REQUIREMENTS_FILE,
    GROUP_CONTRACT_FILE, CROSSWALK_FILE, GATE_POLICY_FILE,
)


def materialize(root):
    for rel in INPUTS:
        target = root / rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(DATA / rel,target)


def change(root,rel,fn):
    target = root / rel
    with target.open(encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        fields,rows=reader.fieldnames,list(reader)
    fn(rows)
    with target.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Stage13E3G20ZonePolicyAuditTests(unittest.TestCase):
    def test_all_87_child_routes_and_8_group_contracts_are_audited(self):
        r=audit_2026_hiroshima_stage13e3g20(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(8,r["season_district_contracts"])
        self.assertEqual(87,r["published_child_route_requirements"])
        self.assertEqual(38,r["published_primary_zone_count"])
        self.assertEqual(3,r["combined_secondary_zone_events"])
        self.assertEqual({
            "PRIMARY":38,"REPECHAGE_ZONE":35,"REPECHAGE_CROSS_ZONE_GATE":14,
        },r["stage_role_counts"])

    def test_63_qualifier_slots_and_senbatsu_exemption_are_preserved(self):
        r=audit_2026_hiroshima_stage13e3g20(DATA)
        self.assertEqual(63,r["qualifying_slots"])
        self.assertEqual(1,r["direct_main_exempt_slots"])
        self.assertEqual(14,r["published_cross_zone_decider_events"])

    def test_all_8_seasonal_zone_names(self):
        with (DATA/ZONE_CONTRACT_FILE).open(encoding="utf-8",newline="") as stream:
            rows={(x["season"],x["district_code"]):x for x in csv.DictReader(stream)}
        self.assertEqual(("A;B;C;D", "A;B;C;D;E;F"),
                         (rows["spring","west"]["primary_zone_codes"],
                          rows["spring","south"]["primary_zone_codes"]))
        self.assertEqual(("A;B;C;D;E","A;B;C;D;E;F"),
                         (rows["autumn","east"]["primary_zone_codes"],
                          rows["autumn","south"]["primary_zone_codes"]))

    def test_unread_official_pdf_never_authorizes_draw_or_ranking(self):
        r=audit_2026_hiroshima_stage13e3g20(DATA)
        self.assertTrue(r["fmt025_design_pending"])
        self.assertEqual(0,r["official_bracket_pdf_bodies_inspected"])
        self.assertEqual(0,r["individual_primary_loser_route_edges_verified"])
        self.assertEqual(0,r["individual_secondary_candidate_route_edges_verified"])
        self.assertFalse(r["draw_accurate_match_runtime_enabled"])
        self.assertFalse(r["optional_ranking_enabled"])

    def test_three_merged_runner_up_event_names_are_not_assumed_gates(self):
        with (DATA/ROUTE_REQUIREMENTS_FILE).open(encoding="utf-8",newline="") as stream:
            rows=list(csv.DictReader(stream))
        merged=[x for x in rows if x["zone_scope_class"]=="merged_named_secondary_zones"]
        self.assertEqual({
            ("spring","east","C;D"),
            ("autumn","east","B;C"),
            ("autumn","east","D;E"),
        },{(x["season"],x["district_code"],x["named_zone_hint"]) for x in merged})
        self.assertTrue(all(x["annual_draw_selector_present"]=="no" for x in merged))

    def test_tampering_primary_zone_names_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,ZONE_CONTRACT_FILE,lambda rows:rows[0].update(
                primary_zone_codes="A;B;C"))
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("annual zone contract mismatch" in e for e in r["errors"]))

    def test_deleting_a_route_requirement_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,ROUTE_REQUIREMENTS_FILE,lambda rows:rows.pop())
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("87" in e for e in r["errors"]))

    def test_primary_annual_edge_verified_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,ROUTE_REQUIREMENTS_FILE,lambda rows:rows[0].update(
                annual_draw_selector_present="yes"))
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("child route requirement mismatch" in e for e in r["errors"]))

    def test_enabling_runtime_or_ranking_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,ZONE_CONTRACT_FILE,lambda rows:rows[2].update(
                allow_live_runtime_integration="yes",allow_optional_ranking="yes"))
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("annual zone contract mismatch" in e for e in r["errors"]))

    def test_renaming_secondary_route_in_source_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,CROSSWALK_FILE,lambda rows:next(
                x for x in rows if x["phase_execution_role"]=="REPECHAGE_ZONE"
            ).update(published_event_name="X二位校"))
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unrecognized publisher second-place" in e for e in r["errors"]))

    def test_misreporting_published_cross_zone_slots_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,ZONE_CONTRACT_FILE,lambda rows:rows[0].update(
                cross_zone_decider_child_event_count="9"))
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("annual zone contract mismatch" in e for e in r["errors"]))

    def test_2026_upstream_retry_gate_must_not_be_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);materialize(root)
            change(root,GATE_POLICY_FILE,lambda rows:rows[0].update(
                game_runtime_enabled="yes"))
            r=audit_2026_hiroshima_stage13e3g20(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("unverified upstream gate policy" in e for e in r["errors"]))


class Stage13E3G20ZoneDraftTests(unittest.TestCase):
    def _draft(self, seed="seed-2026", entrants=None, **kw):
        if entrants is None:
            entrants=tuple(f"draft-team-{i:02}" for i in range(17))
        return make_balanced_zone_draft(
            entrant_ids=entrants,
            zone_codes=("A","B","C","D"),
            seed=seed,
            **kw,
        )

    def test_seed_replay_and_input_order_independence(self):
        entrants=tuple(f"candidate-{i:02}" for i in range(17))
        self.assertEqual(
            self._draft(entrants=entrants),
            self._draft(entrants=tuple(reversed(entrants))),
        )
        self.assertEqual(self._draft(),self._draft())

    def test_no_school_is_created_or_duplicated(self):
        candidates=tuple(f"school-{i}" for i in range(17))
        zones=self._draft(entrants=candidates).as_dict()
        flattened=[team for group in zones.values() for team in group]
        self.assertCountEqual(candidates,flattened)
        self.assertEqual(len(flattened),len(set(flattened)))
        self.assertEqual((5,4,4,4),tuple(sorted(
            (len(x) for x in zones.values()),reverse=True
        )))

    def test_seed_changes_sandbox_buckets_without_claiming_official_draw(self):
        first=self._draft(seed="alpha")
        second=self._draft(seed="beta")
        self.assertNotEqual(first.zone_school_ids,second.zone_school_ids)
        self.assertEqual("seeded_draft_not_official_bracket",first.proof_scope)
        self.assertFalse(first.annual_draw_verified)
        self.assertFalse(first.runtime_enabled)

    def test_six_zones_for_an_unrelated_large_draft(self):
        x=make_balanced_zone_draft(
            entrant_ids=tuple(f"entrant-{i}" for i in range(121)),
            zone_codes=tuple("ABCDEF"),seed="sample",
        )
        sizes=[len(v) for v in x.as_dict().values()]
        self.assertEqual(121,sum(sizes))
        self.assertEqual(1,max(sizes)-min(sizes))

    def test_joint_school_id_is_one_indivisible_entrant(self):
        candidates=("連合:庄原実・向原・三次青陵","学校-2","学校-3","学校-4")
        x=make_balanced_zone_draft(
            entrant_ids=candidates,
            zone_codes=("A","B"),seed="test",
        )
        allocated=[s for group in x.as_dict().values() for s in group]
        self.assertCountEqual(candidates,allocated)

    def test_direct_main_exempt_is_never_added_to_zone_draft(self):
        x=self._draft(direct_main_school_ids=("senbatsu-exempt",))
        self.assertNotIn("senbatsu-exempt",str(x.zone_school_ids))
        self.assertEqual(17,sum(len(v) for v in x.as_dict().values()))

    def test_direct_main_exemption_cannot_also_enter_qualifier(self):
        with self.assertRaisesRegex(ZoneDraftError,"distinct"):
            self._draft(direct_main_school_ids=("draft-team-01",))

    def test_duplicate_or_insufficient_entrant_ids_fail(self):
        with self.assertRaises(ZoneDraftError):
            self._draft(entrants=("A","B","B","C"))
        with self.assertRaises(ZoneDraftError):
            self._draft(entrants=("A","B","C"))

    def test_unstable_or_unpublished_zone_codes_fail(self):
        for zones in [("A","A"),("B","A"),("A","Z"),()]:
            with self.subTest(zones=zones):
                with self.assertRaises(ZoneDraftError):
                    make_balanced_zone_draft(
                        entrant_ids=("1","2","3","4"),zone_codes=zones,seed="fixed"
                    )

    def test_empty_or_nontext_seed_fails(self):
        for seed in ("",1,None):
            with self.subTest(seed=seed):
                with self.assertRaises(ZoneDraftError):
                    self._draft(seed=seed)

    def test_duplicate_direct_main_exempt_fails(self):
        with self.assertRaises(ZoneDraftError):
            self._draft(direct_main_school_ids=("exempt","exempt"))


if __name__=="__main__":
    unittest.main()
