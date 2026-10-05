from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
sys.path.insert(0, str(ROOT))

from phase2_engine import AnnualCompetitionInput, DataRepository, TournamentEngine
from phase2_engine.main_tournament import next_power_of_two
from phase2_engine.results import save_competition_run


class Stage12C4MainEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA_ROOT)
        cls.engine = TournamentEngine(cls.repo)

    def _prefecture_schools(self, competition_id: str):
        pcode = self.repo.competition(competition_id).get("prefecture_code")
        if not pcode:
            with (DATA_ROOT / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row["competition_id"] == competition_id:
                        pcode = row["prefecture_code"]
                        break
        return sorted(
            sid for sid, row in self.repo.schools.items()
            if row.get("prefecture_code") == pcode
        )

    def _annual_for(self, competition_id: str, seed: int = 2026100501):
        stages = self.repo.stages(competition_id)
        assigned_stages = [s for s in stages if s["stage_id"] in self.repo.assignments_by_stage]
        groups = []
        entrants = set()
        for stage in assigned_stages:
            for group in self.repo.groups_by_stage.get(stage["stage_id"], []):
                groups.append(group)
                entrants |= self.repo.group_school_ids(group, 2026)

        group_override = {}
        if not entrants:
            candidates = self._prefecture_schools(competition_id)
            entrants = set(candidates)
            if groups:
                for i, sid in enumerate(candidates):
                    gid = groups[i % len(groups)]["stage_group_id"]
                    group_override.setdefault(gid, []).append(sid)
        elif "MAIN" in {s["stage_code"] for s in stages} and not assigned_stages:
            entrants = set(self._prefecture_schools(competition_id))

        # Kanagawa's 3/4-team-pool mechanism requires the annual participating subset,
        # not every affiliated school. Reuse the Stage12C-2 structural contract.
        if competition_id in {"CMP000095", "CMP000096"}:
            qstage = self.repo.stage_by_code(competition_id, "BRANCH_QUALIFIER")
            reduced = []
            chosen_direct = None
            for idx, group in enumerate(self.repo.groups_by_stage[qstage["stage_id"]]):
                ids = sorted(self.repo.group_school_ids(group, 2026))
                slots = self.repo.param(qstage["stage_id"], "output_slots", group["stage_group_id"])
                target = 2 * slots
                if idx == 0:
                    chosen_direct = ids[-1]
                    ids = [x for x in ids if x != chosen_direct]
                reduced.extend(ids[:target])
            entrants = set(reduced + ([chosen_direct] if chosen_direct else []))

        # Direct MAIN access is an annual result, not a hardcoded school. For the
        # structural harness choose reproducible members of the entrant set according
        # to the observed 2026 quota, but ignore non-MAIN bypass rules (e.g. Mie seed event).
        direct_count = sum(
            int(r.get("observed_2026_count") or 0)
            for r in self.repo.access_rules(competition_id)
            if r.get("grants_main_entry") == "yes"
        )
        if competition_id in {"CMP000095", "CMP000096"} and direct_count:
            qstage = self.repo.stage_by_code(competition_id, "BRANCH_QUALIFIER")
            first_group = self.repo.groups_by_stage[qstage["stage_id"]][0]
            candidates = sorted(self.repo.group_school_ids(first_group, 2026))
            direct = [candidates[-1]]
        else:
            direct = sorted(entrants)[:direct_count]
        if direct and group_override:
            direct_set = set(direct)
            group_override = {gid: [x for x in ids if x not in direct_set] for gid, ids in group_override.items()}
        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=2026,
            entrant_school_ids=sorted(entrants),
            direct_main_entry_school_ids=direct,
            rng_seed=seed,
            group_entrant_school_ids=group_override,
        )

    def test_gifu_37_main_uses_fixed_64_slot_bracket(self):
        annual = self._annual_for("CMP000110", seed=111)
        # Match Stage12C-1's known 58-team structural slice for Gifu autumn.
        seed_stage = self.repo.stage_by_code("CMP000110", "SEED_EVENT")
        chosen = []
        target_counts = [20, 10, 18, 10]
        overrides = {}
        for group, n in zip(self.repo.groups_by_stage[seed_stage["stage_id"]], target_counts):
            ids = sorted(self.repo.group_school_ids(group, 2026))[:n]
            chosen.extend(ids)
            overrides[group["stage_group_id"]] = ids
        annual.entrant_school_ids = chosen
        annual.group_entrant_school_ids = overrides
        run = self.engine.run(annual)
        main = run.stage_executions[-1]
        self.assertEqual(37, len(run.main_entrant_school_ids))
        self.assertEqual(64, main.metadata["bracket_size"])
        self.assertEqual(27, main.metadata["bye_count"])
        self.assertEqual(36, run.outcome.match_count)
        self.assertEqual(27, run.outcome.bye_count)
        self.assertEqual(37, len(run.outcome.final_ranking_school_ids))

    def test_main_outcome_has_champion_runnerup_and_cohorts(self):
        run = self.engine.run(self._annual_for("CMP000013", seed=222))
        self.assertTrue(run.outcome.champion_school_id)
        self.assertTrue(run.outcome.runner_up_school_id)
        self.assertNotEqual(run.outcome.champion_school_id, run.outcome.runner_up_school_id)
        self.assertEqual(2, len(run.outcome.semifinalist_school_ids))
        self.assertEqual(4, len(run.outcome.quarterfinalist_school_ids))
        self.assertEqual(len(run.main_entrant_school_ids), len(run.outcome.final_ranking_school_ids))

    def test_seed_event_seeds_are_spread_and_recorded(self):
        run = self.engine.run(self._annual_for("CMP000073", seed=333))
        main = run.stage_executions[-1]
        self.assertEqual(len(run.seed_assignments), main.metadata["seed_count"])
        self.assertEqual(len(run.seed_assignments), len(main.metadata["seed_slots"]))
        first_round = [m for m in main.matches if m.round_no == 1 and not m.is_bye]
        seeded = set(main.metadata["seed_slots"])
        # Standard simulation draw should not pair two seeds in round 1 when the
        # seed count is <= half the bracket capacity.
        if len(seeded) <= main.metadata["bracket_size"] // 2:
            self.assertFalse(any(m.team1 in seeded and m.team2 in seeded for m in first_round))

    def test_exact_annual_main_draw_override(self):
        annual = self._annual_for("CMP000013", seed=444)
        # Hokkaido autumn resolves to 20 MAIN teams, hence a 32-slot bracket.
        pre = self.engine.run(annual)
        entrants = pre.main_entrant_school_ids
        size = next_power_of_two(len(entrants))
        slots = [""] * size
        # Deterministic exact slot override with 12 byes; never leave empty-empty pairs.
        pos = 0
        for pair in range(size // 2):
            if pos >= len(entrants):
                break
            slots[pair * 2] = entrants[pos]
            pos += 1
            if pos < len(entrants) and (len(entrants) - pos) > (size // 2 - pair - 1):
                slots[pair * 2 + 1] = entrants[pos]
                pos += 1
        self.assertEqual(set(entrants), {x for x in slots if x})
        annual.main_bracket_slots = slots
        run = self.engine.run(annual)
        self.assertEqual("annual_override", run.stage_executions[-1].metadata["draw_source"])
        self.assertEqual(slots, run.stage_executions[-1].metadata["initial_slots"])

    def test_main_match_winner_override(self):
        annual = self._annual_for("CMP000013", seed=555)
        first = self.engine.run(annual)
        main = first.stage_executions[-1]
        target = next(m for m in main.matches if not m.is_bye)
        forced = target.team1 if target.winner != target.team1 else target.team2
        annual.main_match_winner_overrides = {target.match_id: forced}
        second = self.engine.run(annual)
        new = next(m for m in second.stage_executions[-1].matches if m.match_id == target.match_id)
        self.assertEqual(forced, new.winner)
        self.assertEqual("annual_override", new.metadata["winner_source"])

    def test_result_writer_outputs_summary_matches_and_placements(self):
        run = self.engine.run(self._annual_for("CMP000013", seed=666))
        with tempfile.TemporaryDirectory() as td:
            paths = save_competition_run(run, td)
            for path in paths.values():
                self.assertTrue(Path(path).exists())
            payload = json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual(run.outcome.champion_school_id, payload["outcome"]["champion_school_id"])
            with Path(paths["matches_csv"]).open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertTrue(any(r["stage_code"] == "MAIN" for r in rows))

    def test_all_94_prefectural_spring_autumn_mains_complete(self):
        with (DATA_ROOT / "competitions" / "prefectural_competition_index_2026.csv").open(encoding="utf-8-sig", newline="") as f:
            ids = [r["competition_id"] for r in csv.DictReader(f)]
        self.assertEqual(94, len(ids))
        for cid in ids:
            with self.subTest(competition_id=cid):
                run = self.engine.run(self._annual_for(cid, seed=777))
                self.assertIsNotNone(run.outcome)
                self.assertIn(run.outcome.champion_school_id, run.main_entrant_school_ids)
                self.assertEqual(len(run.main_entrant_school_ids) - 1, run.outcome.match_count)
                self.assertEqual(
                    len(run.main_entrant_school_ids),
                    len(run.outcome.final_ranking_school_ids),
                )
                self.assertEqual("MAIN", run.stage_executions[-1].stage_code)

    def test_main_seed_and_draw_reproducible(self):
        a = self.engine.run(self._annual_for("CMP000073", seed=888)).to_dict()
        b = self.engine.run(self._annual_for("CMP000073", seed=888)).to_dict()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
