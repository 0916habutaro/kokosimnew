from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass(frozen=True)
class Team:
    school_id: str
    program_id: str
    display_name: str
    prefecture_code: str


@dataclass
class Match:
    match_id: str
    competition_id: str
    stage_id: str
    stage_code: str
    phase_code: str
    round_no: int
    group_id: str = ""
    group_name: str = ""
    team1: str = ""
    team2: str = ""
    winner: str = ""
    loser: str = ""
    is_bye: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SeedAssignment:
    school_id: str
    group_id: str
    group_name: str
    seed_tier: str
    source_rank: int
    seed_rule_id: str
    destination_stage: str


@dataclass
class StageExecution:
    stage_id: str
    stage_code: str
    format_model_id: str
    entrant_school_ids: List[str]
    output_school_ids: List[str]
    matches: List[Match] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompetitionOutcome:
    champion_school_id: str
    runner_up_school_id: str
    semifinalist_school_ids: List[str]
    quarterfinalist_school_ids: List[str]
    final_ranking_school_ids: List[str]
    eliminated_by_round: Dict[str, List[str]]
    match_count: int
    bye_count: int
    bracket_size: int


@dataclass
class CompetitionRun:
    competition_id: str
    year: int
    rng_seed: int
    entrant_school_ids: List[str]
    seed_assignments: List[SeedAssignment]
    stage_executions: List[StageExecution]
    main_entrant_school_ids: List[str]
    warnings: List[str] = field(default_factory=list)
    outcome: CompetitionOutcome | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnnualCompetitionInput:
    competition_id: str
    year: int
    entrant_school_ids: List[str]
    rng_seed: int
    # Teams already entitled to MAIN via competition_access_rules. They remain part
    # of the competition entrant set, but are removed from a bypassed qualifier when
    # the rule says excluded_from_bypassed_stage.
    direct_main_entry_school_ids: List[str] = field(default_factory=list)
    # Optional annual official ranking override. Key=stage_group_id, value=ordered ids.
    # Useful for replaying a known year's seed event without hardcoding schools in rules.
    group_rankings: Dict[str, List[str]] = field(default_factory=dict)
    # Optional exact annual pool draw. Key=stage_group_id, value=list of pools.
    # If omitted, the engine creates a namespaced deterministic draw from the format.
    group_pool_assignments: Dict[str, List[List[str]]] = field(default_factory=dict)
    # Optional annual group entrant override. This is intentionally annual input rather
    # than a permanent rule: it covers years where district membership is missing,
    # temporary, or differs from the affiliation master (e.g. reorganization/combined
    # teams). Every listed team must still be in entrant_school_ids.
    group_entrant_school_ids: Dict[str, List[str]] = field(default_factory=dict)
    # Teams that bypass a SEED_EVENT because a cross-competition access rule grants
    # their seed directly (e.g. current summer champion). They remain competition
    # entrants and continue to the next competition stage, but do not consume a
    # seed-event slot; the linked competition_seed_rule supplies their seed metadata.
    seed_event_bypass_school_ids: List[str] = field(default_factory=list)
    # Optional MAIN seeding order. This supplements structured seed-event metadata and
    # is useful when a prefecture has a main-tournament seed rule not yet modeled as a
    # Stage 11 seed event. Order is strongest seed first.
    main_seed_school_ids: List[str] = field(default_factory=list)
    # Optional exact annual MAIN draw. One item per power-of-two bracket slot; use an
    # empty string for a first-round bye. If omitted, a reproducible standard draw is
    # generated with seed spreading.
    main_bracket_slots: List[str] = field(default_factory=list)
    # Optional real-result replay: match_id -> winning school_id for MAIN matches.
    main_match_winner_overrides: Dict[str, str] = field(default_factory=dict)
