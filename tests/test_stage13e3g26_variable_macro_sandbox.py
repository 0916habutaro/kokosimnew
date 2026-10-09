from __future__ import annotations

import unittest
from dataclasses import replace

from phase2_engine.hiroshima_variable_qualification_macro import (
    MacroDraftError, MacroTemplate, WEST_2026_OBSERVED_MACRO_EXAMPLE,
    draft_qualification_macro, evaluate_declared_macro_awards,
    validate_macro_template,
)


class Stage13E3G26VariableMacroTests(unittest.TestCase):
    def test_2026_west_example_seven_qualifier_slots(self):
        template = WEST_2026_OBSERVED_MACRO_EXAMPLE
        self.assertEqual(validate_macro_template(template), 7)
        self.assertEqual(template.zone_codes, ("A", "B", "C", "D"))
        self.assertEqual(template.direct_second_place_zones, ("A", "B"))
        self.assertEqual(template.cross_second_place_pairs, (("C", "D"),))
        self.assertIn("not_2027_regulation", template.source_scope)

    def test_18_entrants_four_seeded_balanced_zones(self):
        ids = tuple(f"fictional-{i:02d}" for i in range(18))
        draft = draft_qualification_macro(
            entrant_ids=ids,
            template=WEST_2026_OBSERVED_MACRO_EXAMPLE,
            seed="stage26-seed-a",
        )
        allocation = draft.allocation.as_dict()
        self.assertEqual(sorted(len(x) for x in allocation.values()), [4, 4, 5, 5])
        self.assertEqual(set(x for xs in allocation.values() for x in xs), set(ids))
        self.assertEqual(draft.qualifier_slots, 7)
        self.assertEqual(draft.total_main_entry_slots, 7)
        self.assertFalse(draft.official_annual_draw_verified)
        self.assertFalse(draft.official_loser_selector_verified)
        self.assertFalse(draft.match_level_pairings_generated)
        self.assertFalse(draft.live_fmt025_runtime_enabled)
        self.assertFalse(draft.optional_ranking_enabled)

    def test_same_seed_same_allocation_and_different_seed_changes_assignment(self):
        ids = tuple(f"T{i:03d}" for i in range(32))
        def create(seed):
            return draft_qualification_macro(
                entrant_ids=ids,
                template=WEST_2026_OBSERVED_MACRO_EXAMPLE,
                seed=seed,
            ).allocation
        self.assertEqual(create("aaa"), create("aaa"))
        self.assertNotEqual(create("aaa"), create("bbb"))

    def test_arbitrary_future_year_size_and_direct_main_exemptions(self):
        ids = tuple(f"future-{i}" for i in range(23))
        direct = ("exempt-one", "exempt-two")
        draft = draft_qualification_macro(
            entrant_ids=ids,
            template=WEST_2026_OBSERVED_MACRO_EXAMPLE,
            seed="2027-sandbox-not-official",
            direct_main_entry_ids=direct,
        )
        self.assertEqual(sorted(len(v) for v in draft.allocation.as_dict().values()),
                         [5, 6, 6, 6])
        self.assertEqual(draft.qualifier_slots, 7)
        self.assertEqual(draft.total_main_entry_slots, 9)
        self.assertEqual(draft.direct_main_entry_ids, direct)

    def test_external_macro_winner_inputs_award_seven_distinct_slots(self):
        draft = draft_qualification_macro(
            entrant_ids=tuple(f"S{i}" for i in range(20)),
            template=WEST_2026_OBSERVED_MACRO_EXAMPLE,
            seed="winners-demo",
        )
        zones = draft.allocation.as_dict()
        primary = {z: xs[0] for z, xs in zones.items()}
        secondary = {z: xs[1] for z, xs in zones.items()}
        result = evaluate_declared_macro_awards(
            draft, primary_winners=primary, second_place_winners=secondary,
            cross_gate_winners={("C", "D"): secondary["C"]},
        )
        self.assertEqual(result.qualifier_ids,
                         (primary["A"], primary["B"], primary["C"], primary["D"],
                          secondary["A"], secondary["B"], secondary["C"]))
        self.assertEqual(len(set(result.all_main_entry_ids)), 7)
        self.assertFalse(result.live_fmt025_runtime_enabled)

    def test_external_macro_results_support_direct_main_entries(self):
        draft = draft_qualification_macro(
            entrant_ids=tuple(f"f{i}" for i in range(18)),
            template=WEST_2026_OBSERVED_MACRO_EXAMPLE,
            seed="direct-test",
            direct_main_entry_ids=("seed-only",),
        )
        zones = draft.allocation.as_dict()
        primary = {z: xs[0] for z, xs in zones.items()}
        secondary = {z: xs[1] for z, xs in zones.items()}
        result = evaluate_declared_macro_awards(
            draft, primary_winners=primary, second_place_winners=secondary,
            cross_gate_winners={("C", "D"): secondary["D"]},
        )
        self.assertEqual(result.all_main_entry_ids[-1], "seed-only")
        self.assertEqual(len(result.all_main_entry_ids), 8)

    def test_five_or_six_zone_hypothetical_templates_are_not_banned(self):
        five = MacroTemplate(
            zone_codes=("A", "B", "C", "D", "E"),
            direct_second_place_zones=("A", "B", "C"),
            cross_second_place_pairs=(("D", "E"),),
        )
        six = MacroTemplate(
            zone_codes=("A", "B", "C", "D", "E", "F"),
            direct_second_place_zones=("A", "B"),
            cross_second_place_pairs=(("C", "D"), ("E", "F")),
        )
        self.assertEqual(validate_macro_template(five), 9)
        self.assertEqual(validate_macro_template(six), 10)
        for template in (five, six):
            draft = draft_qualification_macro(
                entrant_ids=tuple(f"f-{i}" for i in range(4 * len(template.zone_codes))),
                template=template, seed="multi-zone",
            )
            self.assertEqual(draft.qualifier_slots, validate_macro_template(template))
            self.assertFalse(draft.live_fmt025_runtime_enabled)

    def test_missing_or_duplicate_second_place_exit_is_rejected(self):
        bad = [
            MacroTemplate(("A", "B", "C", "D"), ("A", "B"), ()),
            MacroTemplate(("A", "B", "C", "D"), ("A", "B", "C"), (("C", "D"),)),
            MacroTemplate(("A", "B", "C", "D"), ("A", "A"), (("C", "D"),)),
            MacroTemplate(("A", "B", "C", "D"), (), (("A", "B"), ("A", "C"))),
        ]
        for template in bad:
            with self.subTest(template=template):
                with self.assertRaises(MacroDraftError):
                    validate_macro_template(template)

    def test_invalid_zone_letters_and_cross_group_are_rejected(self):
        bad = [
            MacroTemplate(("B", "A"), (), (("A", "B"),)),
            MacroTemplate(("A", "A"), (), (("A", "A"),)),
            MacroTemplate(("A", "B"), (), (("A", "A"),)),
            MacroTemplate(("A", "B"), (), (("B", "A"),)),
            MacroTemplate(("A", "B"), (), (("A", "C"),)),
        ]
        for template in bad:
            with self.subTest(template=template):
                with self.assertRaises(MacroDraftError):
                    validate_macro_template(template)

    def test_future_official_status_cannot_be_asserted_through_prototype(self):
        with self.assertRaises(MacroDraftError):
            validate_macro_template(replace(
                WEST_2026_OBSERVED_MACRO_EXAMPLE,
                source_scope="official_2027_draw_verified",
            ))

    def test_repeated_entrant_unknown_seed_and_exemption_overlap_blocked(self):
        template = WEST_2026_OBSERVED_MACRO_EXAMPLE
        valid = tuple(f"f{i}" for i in range(18))
        for ids, seed, exempt in [
            (valid + ("f0",), "seed", ()),
            (valid, "", ()),
            (valid, "seed", ("f4",)),
            (("only-one",), "seed", ()),
        ]:
            with self.subTest(ids=len(ids), seed=seed, exempt=exempt):
                with self.assertRaises(MacroDraftError):
                    draft_qualification_macro(
                        entrant_ids=ids, template=template, seed=seed,
                        direct_main_entry_ids=exempt,
                    )

    def test_no_zero_runnerup_zone_for_sparse_entrant_pool(self):
        with self.assertRaises(MacroDraftError):
            draft_qualification_macro(
                entrant_ids=tuple(f"f{i}" for i in range(4)),
                template=WEST_2026_OBSERVED_MACRO_EXAMPLE,
                seed="sparse",
            )

    def test_missing_champion_runnerup_or_cross_decider_is_rejected(self):
        draft = draft_qualification_macro(
            entrant_ids=tuple(f"f{i}" for i in range(18)),
            template=WEST_2026_OBSERVED_MACRO_EXAMPLE, seed="macro",
        )
        zones = draft.allocation.as_dict()
        primary = {z: xs[0] for z, xs in zones.items()}
        secondary = {z: xs[1] for z, xs in zones.items()}
        for first, second, cross in [
            ({}, secondary, {("C", "D"): secondary["C"]}),
            (primary, {"A": secondary["A"]}, {("C", "D"): secondary["C"]}),
            (primary, secondary, {}),
            (primary, secondary, {("C", "D"): primary["C"]}),
            (primary, dict(secondary, A=primary["A"]), {("C", "D"): secondary["C"]}),
        ]:
            with self.subTest(first=first, second=second, cross=cross):
                with self.assertRaises(MacroDraftError):
                    evaluate_declared_macro_awards(
                        draft, primary_winners=first, second_place_winners=second,
                        cross_gate_winners=cross,
                    )

    def test_tampered_runtime_and_quota_fields_rejected(self):
        draft = draft_qualification_macro(
            entrant_ids=tuple(f"f{i}" for i in range(18)),
            template=WEST_2026_OBSERVED_MACRO_EXAMPLE, seed="macro",
        )
        zones = draft.allocation.as_dict()
        primary = {z: xs[0] for z, xs in zones.items()}
        second = {z: xs[1] for z, xs in zones.items()}
        for bad in (
            replace(draft, live_fmt025_runtime_enabled=True),
            replace(draft, official_annual_draw_verified=True),
            replace(draft, official_loser_selector_verified=True),
            replace(draft, match_level_pairings_generated=True),
            replace(draft, optional_ranking_enabled=True),
            replace(draft, qualifier_slots=6),
            replace(draft, total_main_entry_slots=8),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(MacroDraftError):
                    evaluate_declared_macro_awards(
                        bad, primary_winners=primary,
                        second_place_winners=second,
                        cross_gate_winners={("C", "D"): second["C"]},
                    )


if __name__ == "__main__":
    unittest.main()
