"""Stage 12C-1 structural demo for Gifu autumn.

The demo intentionally uses a deterministic 58-team subset of the 67-school area
membership master. It verifies the engine path 16 seed bypass + 42 gate entrants
-> 21 gate winners -> 37 MAIN entrants. It does not claim to reproduce the exact
2026 annual participant school list or official draw positions.
"""
from pathlib import Path

from phase2_engine.cli import _gifu_demo_entrants
from phase2_engine import AnnualCompetitionInput, DataRepository, TournamentEngine

root = Path(__file__).resolve().parents[1]
repo = DataRepository(root / "data")
annual = AnnualCompetitionInput(
    competition_id="CMP000110",
    year=2026,
    entrant_school_ids=_gifu_demo_entrants(repo),
    rng_seed=2026100401,
)
result = TournamentEngine(repo).run(annual)
print({
    "entrants": len(result.entrant_school_ids),
    "seeds": len(result.seed_assignments),
    "gate_matches": len(result.stage_executions[1].matches),
    "gate_winners": len(result.stage_executions[1].output_school_ids),
    "main_entrants": len(result.main_entrant_school_ids),
    "warnings": result.warnings,
})
