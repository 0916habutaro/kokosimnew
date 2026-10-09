from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from phase2_engine.hiroshima_conditional_retry_gates import (
    GateContractError, RepechageGateSpec, replay_explicit_gate_graph,
)
from phase2_engine.hiroshima_stage13e3g19 import (
    GATE_OBSERVATIONS_FILE, GATE_POLICY_FILE,
    audit_2026_hiroshima_stage13e3g19,
)
from phase2_engine.hiroshima_stage13e3g18 import (
    SECOND_CHANCE_FILE, TRANSITION_FILE, BLOCK_SOURCES,
)
from phase2_engine.hiroshima_stage13e3g17 import (
    CROSSWALK_FILE, GROUP_CONTRACT_FILE,
)
from phase2_engine.hiroshima_stage13e3g16 import EVENT_FILE
from phase2_engine.hiroshima_qualification_timeline_2026 import TIMELINE_FILE

DATA=Path(__file__).resolve().parents[1]/"data"
INPUTS=(
    GATE_OBSERVATIONS_FILE,GATE_POLICY_FILE,
    SECOND_CHANCE_FILE,TRANSITION_FILE,CROSSWALK_FILE,
    GROUP_CONTRACT_FILE,EVENT_FILE,TIMELINE_FILE,*BLOCK_SOURCES
)


def build_fixture(root):
    for relative in INPUTS:
        target=root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(DATA/relative,target)


def modify_csv(root,relative,mutator):
    target=root/relative
    with target.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        columns,rows=reader.fieldnames,list(reader)
    mutator(rows)
    with target.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class ConditionalRetryGatePrototypeTests(unittest.TestCase):
    def _gates(self, allow_retry=True):
        return (
            RepechageGateSpec(
                "first", "entrant:team-A", "entrant:team-B", True,
                loser_to_gate="extra" if allow_retry else None,
            ),
            RepechageGateSpec(
                "extra", "loser:first", "entrant:team-C", True,
                gate_role="conditional_retry_decider",
            ),
        )

    def _replay(self, gates, winners=None, **kwargs):
        return replay_explicit_gate_graph(
            eligible_ids=("team-A","team-B","team-C"),
            gate_specs=gates,
            winners_by_gate=winners or {"first":"team-A","extra":"team-B"},
            qualifier_slots=kwargs.pop("qualifier_slots",2),
            **kwargs,
        )

    def test_explicit_loser_to_named_gate_makes_two_berths(self):
        out=self._replay(self._gates())
        self.assertEqual(("team-A","team-B"),out.qualifiers)
        self.assertEqual(("team-B",),out.retried_loser_ids)
        self.assertEqual(("first","extra"),out.played_gate_ids)

    def test_second_gate_result_is_external_not_historical_fixed(self):
        out=self._replay(self._gates(),{"first":"team-A","extra":"team-C"})
        self.assertEqual(("team-A","team-C"),out.qualifiers)
        self.assertEqual(("team-B",),out.retried_loser_ids)

    def test_loser_without_explicit_gate_authorization_is_excluded(self):
        with self.assertRaisesRegex(GateContractError,"explicit directed transfer"):
            self._replay(self._gates(False))

    def test_reusing_loser_as_an_initial_entrant_is_blocked(self):
        bad=(
            RepechageGateSpec("first","entrant:team-A","entrant:team-B",True),
            RepechageGateSpec("extra","entrant:team-B","entrant:team-C",True),
        )
        with self.assertRaisesRegex(GateContractError,"reused entrant"):
            self._replay(bad)

    def test_qualified_winner_cannot_be_forwarded(self):
        bad=(
            RepechageGateSpec("first","entrant:team-A","entrant:team-B",True,
                              winner_to_gate="extra"),
            RepechageGateSpec("extra","winner:first","entrant:team-C",True),
        )
        with self.assertRaisesRegex(GateContractError,"qualified winner"):
            self._replay(bad)

    def test_qualified_winner_cannot_reenter_as_unrelated_source(self):
        bad=(
            RepechageGateSpec("first","entrant:team-A","entrant:team-B",True),
            RepechageGateSpec("extra","entrant:team-A","entrant:team-C",True),
        )
        with self.assertRaises(GateContractError):
            self._replay(bad)

    def test_made_up_winner_is_rejected(self):
        with self.assertRaisesRegex(GateContractError,"not a participant"):
            self._replay(self._gates(),{"first":"team-UNKNOWN","extra":"team-B"})

    def test_unresolved_future_gate_reference_is_rejected(self):
        bad=(
            RepechageGateSpec("first","loser:extra","entrant:team-A",True),
            RepechageGateSpec("extra","entrant:team-B","entrant:team-C",True),
        )
        with self.assertRaisesRegex(GateContractError,"future or unknown outcome"):
            self._replay(bad)

    def test_nonexistent_named_loser_target_is_rejected(self):
        bad=(RepechageGateSpec("first","entrant:team-A","entrant:team-B",True,
                               loser_to_gate="unknown"),)
        with self.assertRaisesRegex(GateContractError,"declared gate"):
            self._replay(bad,{"first":"team-A"},qualifier_slots=1)

    def test_unused_declared_loser_transfer_is_rejected(self):
        bad=(
            RepechageGateSpec("first","entrant:team-A","entrant:team-B",True,
                              loser_to_gate="extra"),
            RepechageGateSpec("extra","entrant:team-C","entrant:team-D",True),
        )
        with self.assertRaisesRegex(GateContractError,"not consumed"):
            replay_explicit_gate_graph(
                eligible_ids=("team-A","team-B","team-C","team-D"),
                gate_specs=bad,winners_by_gate={"first":"team-A","extra":"team-C"},
                qualifier_slots=2,
            )

    def test_direct_main_school_must_not_enter_gate(self):
        with self.assertRaisesRegex(GateContractError,"disjoint"):
            self._replay(self._gates(),direct_main_entry_ids=("team-A",))

    def test_duplicate_initial_entrant_ids_are_rejected(self):
        with self.assertRaisesRegex(GateContractError,"unique and disjoint"):
            replay_explicit_gate_graph(
                eligible_ids=("team-A","team-A","team-B"),
                gate_specs=(RepechageGateSpec("first","entrant:team-A","entrant:team-B",True),),
                winners_by_gate={"first":"team-A"},qualifier_slots=1,
            )

    def test_quota_overflow_is_rejected(self):
        with self.assertRaisesRegex(GateContractError,"duplicate/excess"):
            self._replay(self._gates(),qualifier_slots=1)

    def test_underfilled_quota_is_rejected(self):
        with self.assertRaisesRegex(GateContractError,"quota mismatch"):
            self._replay(self._gates(),qualifier_slots=3)

    def test_ranking_only_gate_cannot_be_created(self):
        bad=(RepechageGateSpec("first","entrant:team-A","entrant:team-B",True,
                               gate_role="RANKING"),)
        with self.assertRaisesRegex(GateContractError,"ranking or unknown"):
            self._replay(bad,{"first":"team-A"},qualifier_slots=1)

    def test_duplicate_gate_id_is_rejected(self):
        bad=(RepechageGateSpec("first","entrant:team-A","entrant:team-B",True),
             RepechageGateSpec("first","entrant:team-B","entrant:team-C",True))
        with self.assertRaisesRegex(GateContractError,"uniquely named"):
            self._replay(bad)

    def test_missing_gate_winner_is_rejected(self):
        with self.assertRaisesRegex(GateContractError,"every gate"):
            self._replay(self._gates(),{"first":"team-A"})

    def test_intermediate_winner_and_loser_require_individual_edges(self):
        specs=(
            RepechageGateSpec("zone","entrant:A","entrant:B",False,
                              winner_to_gate="qualifier-1",loser_to_gate="qualifier-2",
                              gate_role="zone_runner_up"),
            RepechageGateSpec("qualifier-1","winner:zone","entrant:C",True),
            RepechageGateSpec("qualifier-2","loser:zone","entrant:D",True,
                              gate_role="conditional_retry_decider"),
        )
        result=replay_explicit_gate_graph(
            eligible_ids=("A","B","C","D"),gate_specs=specs,
            winners_by_gate={"zone":"A","qualifier-1":"A","qualifier-2":"D"},
            qualifier_slots=2,
        )
        self.assertEqual(("A","D"),result.qualifiers)
        self.assertEqual(("B",),result.retried_loser_ids)


class Stage13E3G19ObservedContractAuditTests(unittest.TestCase):
    def test_6_case_5_gate_8_group_contract_and_63_awards(self):
        r=audit_2026_hiroshima_stage13e3g19(DATA)
        self.assertTrue(r["ok"],r["errors"])
        self.assertEqual(6,r["observed_retry_participant_sequences"])
        self.assertEqual(5,r["distinct_observed_retry_target_matches"])
        self.assertEqual(8,r["seasonal_group_policies"])
        self.assertEqual(287,r["historical_match_continuity_covered"])
        self.assertEqual(
            {"qualifiers":63,"primary":38,"nonprimary":25,"publisher_gates":14},
            r["quota"],
        )

    def test_group_distribution_has_zero_without_claiming_no_retries(self):
        r=audit_2026_hiroshima_stage13e3g19(DATA)
        self.assertEqual({
            "spring_east":1,"spring_north":1,"spring_south":0,"spring_west":0,
            "autumn_east":2,"autumn_north":0,"autumn_south":2,"autumn_west":0,
        },r["group_retry_counts"])

    def test_no_pdf_authorization_or_live_fmt025_change(self):
        r=audit_2026_hiroshima_stage13e3g19(DATA)
        self.assertEqual(0,r["inferred_annual_draw_edges_authorized"])
        self.assertEqual(0,r["official_federation_pdf_body_verified"])
        self.assertFalse(r["active_fmt025_runtime_changed"])
        self.assertFalse(r["optional_ranking_game_enabled"])
        self.assertTrue(r["candidate_graph_requires_explicit_loser_target"])

    def test_followup_event_is_shared_by_two_autumn_east_losers(self):
        with (DATA/GATE_OBSERVATIONS_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        east=[r for r in rows if r["season"]=="autumn" and r["district_code"]=="east"]
        self.assertEqual(2,len(east))
        self.assertEqual({"HT20260037"},{r["subsequent_decider_match_id"] for r in east})
        self.assertEqual({"神辺旭","英数学館"},{r["school_display_name"] for r in east})

    def test_fake_annual_independent_retry_proof_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build_fixture(root)
            modify_csv(root,GATE_OBSERVATIONS_FILE,lambda x:x[0].update(
                annual_independent_retry_authorized="yes"))
            r=audit_2026_hiroshima_stage13e3g19(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("observation differs" in e for e in r["errors"]))

    def test_fake_runtime_enablement_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build_fixture(root)
            modify_csv(root,GATE_POLICY_FILE,lambda x:x[0].update(game_runtime_enabled="yes"))
            r=audit_2026_hiroshima_stage13e3g19(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("seasonal retry gate policy mismatch" in e for e in r["errors"]))

    def test_tampered_publisher_route_id_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build_fixture(root)
            modify_csv(root,GATE_OBSERVATIONS_FILE,lambda x:x[0].update(
                subsequent_publisher_route_id="HR20269999"))
            r=audit_2026_hiroshima_stage13e3g19(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("observation differs" in e for e in r["errors"]))

    def test_after_loss_match_id_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build_fixture(root)
            modify_csv(root,GATE_OBSERVATIONS_FILE,lambda x:x[0].update(
                subsequent_decider_match_id="HT20269999"))
            r=audit_2026_hiroshima_stage13e3g19(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("observation differs" in e for e in r["errors"]))

    def test_policy_63_slot_conservation_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build_fixture(root)
            modify_csv(root,GATE_POLICY_FILE,lambda x:x[0].update(
                required_qualifier_awards="99"))
            r=audit_2026_hiroshima_stage13e3g19(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("seasonal retry gate policy mismatch" in e for e in r["errors"]))

    def test_observation_count_must_be_six(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build_fixture(root)
            modify_csv(root,GATE_OBSERVATIONS_FILE,lambda x:x.pop())
            r=audit_2026_hiroshima_stage13e3g19(root)
            self.assertFalse(r["ok"])
            self.assertTrue(any("six observed" in e or "observation differs" in e for e in r["errors"]))

    def test_two_case_shared_event_not_double_counted_in_policy(self):
        with (DATA/GATE_POLICY_FILE).open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        east=next(x for x in rows if x["season"]=="autumn" and x["district_code"]=="east")
        self.assertEqual("2",east["observed_loser_to_new_decider_transition_count"])
        self.assertEqual("HT20260037",east["observed_next_gate_match_ids"])


if __name__=="__main__":
    unittest.main()
