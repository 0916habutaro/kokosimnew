from __future__ import annotations

from collections import defaultdict
from math import ceil, log2
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import CompetitionOutcome, Match, MatchResolution, SeedAssignment, StageExecution
from .randomness import shuffled


def next_power_of_two(n: int) -> int:
    if n <= 0:
        raise ValueError("entrant count must be positive")
    return 1 if n == 1 else 1 << ceil(log2(n))


def standard_seed_order(bracket_size: int) -> List[int]:
    """Return standard seed numbers by bracket slot for a power-of-two bracket.

    Examples:
      4 -> [1, 4, 3, 2]
      8 -> [1, 8, 5, 4, 3, 6, 7, 2]
    """
    if bracket_size < 1 or bracket_size & (bracket_size - 1):
        raise ValueError("bracket_size must be a positive power of two")
    order = [1]
    size = 1
    while size < bracket_size:
        mirror = size * 2 + 1
        expanded: List[int] = []
        for seed in order:
            expanded.extend([seed, mirror - seed])
        order = expanded
        size *= 2
    return order


def _seed_priority(a: SeedAssignment) -> Tuple[int, int, str, str]:
    tier = (a.seed_tier or "").lower()
    explicit = {
        "seed_rank_1": 1,
        "ordinal_1": 1,
        "seed_rank_2": 2,
        "ordinal_2": 2,
        "seed_rank_3": 3,
        "ordinal_3": 3,
        "seed_rank_4": 4,
        "ordinal_4": 4,
        "best4_seed": 10,
        "best8_seed": 20,
        "best16_seed": 30,
        "protected_seed_pool": 40,
        "other_seed": 50,
    }
    p = explicit.get(tier, 60)
    return (p, int(a.source_rank or 999), a.group_name or "", a.school_id)


def ordered_seed_ids(
    entrants: Sequence[str],
    seed_assignments: Sequence[SeedAssignment],
    annual_seed_order: Sequence[str],
    *,
    base_seed: int,
    namespace: str,
) -> List[str]:
    entrant_set = set(entrants)
    out: List[str] = []
    seen = set()

    for school_id in annual_seed_order:
        if school_id not in entrant_set:
            raise ValueError(f"MAIN seed school is not a MAIN entrant: {school_id}")
        if school_id not in seen:
            seen.add(school_id)
            out.append(school_id)

    remaining = [a for a in seed_assignments if a.school_id in entrant_set and a.school_id not in seen]
    # Stable tier/rank ordering; exact same-tier positions are randomized so simulations
    # do not accidentally encode lexical school_id order as an official seeding rule.
    buckets: Dict[Tuple[int, int, str], List[SeedAssignment]] = defaultdict(list)
    for a in remaining:
        p, rank, group, _ = _seed_priority(a)
        buckets[(p, rank, group)].append(a)
    for key in sorted(buckets):
        bucket = buckets[key]
        ids = [a.school_id for a in bucket]
        ids = shuffled(ids, base_seed, f"{namespace}:seed_bucket:{key}")
        for school_id in ids:
            if school_id not in seen:
                seen.add(school_id)
                out.append(school_id)
    return out


def generate_main_slots(
    entrants: Sequence[str],
    *,
    seed_ids: Sequence[str],
    base_seed: int,
    namespace: str,
    slot_override: Sequence[str] | None = None,
) -> Tuple[List[str], Dict[str, int]]:
    """Build a fixed power-of-two bracket.

    Empty string denotes a first-round bye. When no exact annual slot override is
    provided, seeds are spread using standard seed positions; byes preferentially sit
    opposite seeded teams, and all remaining teams are reproducibly shuffled.
    """
    teams = list(dict.fromkeys(entrants))
    if len(teams) != len(entrants):
        raise ValueError("duplicate MAIN entrant")
    bracket_size = next_power_of_two(len(teams))
    if slot_override is not None and len(slot_override):
        slots = list(slot_override)
        if len(slots) != bracket_size:
            raise ValueError(
                f"main_bracket_slots length={len(slots)}; expected bracket_size={bracket_size}"
            )
        nonempty = [x for x in slots if x]
        if len(nonempty) != len(set(nonempty)):
            raise ValueError("main_bracket_slots contains duplicate teams")
        if set(nonempty) != set(teams):
            missing = sorted(set(teams) - set(nonempty))
            extra = sorted(set(nonempty) - set(teams))
            raise ValueError(f"main_bracket_slots entrant mismatch missing={missing} extra={extra}")
        for i in range(0, bracket_size, 2):
            if not slots[i] and not slots[i + 1]:
                raise ValueError("main_bracket_slots cannot contain an empty first-round pair")
        seed_slots = {sid: slots.index(sid) + 1 for sid in seed_ids if sid in nonempty}
        return slots, seed_slots

    slots = [""] * bracket_size
    seed_ids = [x for x in dict.fromkeys(seed_ids) if x in set(teams)]
    seed_order = standard_seed_order(bracket_size)
    seed_no_to_slot = {seed_no: idx for idx, seed_no in enumerate(seed_order, start=1)}
    seed_slots: Dict[str, int] = {}
    for seed_no, school_id in enumerate(seed_ids, start=1):
        if seed_no > bracket_size:
            break
        slot_no = seed_no_to_slot[seed_no]
        slots[slot_no - 1] = school_id
        seed_slots[school_id] = slot_no

    bye_count = bracket_size - len(teams)
    bye_slots = set()

    # Give byes to the strongest available seeds first, without creating empty-empty pairs.
    for school_id in seed_ids:
        if len(bye_slots) >= bye_count:
            break
        seed_slot_idx = seed_slots[school_id] - 1
        opponent_idx = seed_slot_idx + 1 if seed_slot_idx % 2 == 0 else seed_slot_idx - 1
        if slots[opponent_idx] == "":
            bye_slots.add(opponent_idx)

    # Remaining byes: reserve one slot in an otherwise empty pair. The paired slot will
    # receive a team below, so every first-round pair has at least one participant.
    if len(bye_slots) < bye_count:
        pair_order = list(range(0, bracket_size, 2))
        pair_order = shuffled(pair_order, base_seed, f"{namespace}:bye_pair_order")
        for left in pair_order:
            if len(bye_slots) >= bye_count:
                break
            right = left + 1
            if left in bye_slots or right in bye_slots:
                continue
            if slots[left] or slots[right]:
                # If exactly one side is already occupied, the empty side is safe as a bye.
                if bool(slots[left]) ^ bool(slots[right]):
                    bye_slots.add(right if slots[left] else left)
                continue
            bye_slots.add(left)

    if len(bye_slots) != bye_count:
        raise AssertionError(f"could not allocate all byes: {len(bye_slots)}/{bye_count}")

    remaining_teams = [x for x in teams if x not in set(seed_ids)]
    remaining_teams = shuffled(remaining_teams, base_seed, f"{namespace}:unseeded_draw")
    fill_positions = [i for i in range(bracket_size) if not slots[i] and i not in bye_slots]
    if len(fill_positions) != len(remaining_teams):
        raise AssertionError("slot accounting mismatch")
    for i, school_id in zip(fill_positions, remaining_teams):
        slots[i] = school_id

    for i in range(0, bracket_size, 2):
        if not slots[i] and not slots[i + 1]:
            raise AssertionError("generated an empty first-round pair")
    return slots, seed_slots


def _round_name(round_no: int, total_rounds: int) -> str:
    rounds_left = total_rounds - round_no
    if rounds_left == 0:
        return "決勝"
    if rounds_left == 1:
        return "準決勝"
    if rounds_left == 2:
        return "準々決勝"
    return f"{round_no}回戦"


def run_main_single_elimination(
    entrants: Sequence[str],
    *,
    competition_id: str,
    stage_id: str,
    base_seed: int,
    winner_resolver,
    seed_assignments: Sequence[SeedAssignment] = (),
    annual_seed_order: Sequence[str] = (),
    slot_override: Sequence[str] | None = None,
    winner_overrides: Dict[str, str] | None = None,
    match_resolver=None,
    resolved_match_sink: Dict[str, dict] | None = None,
    reference_year: int | None = None,
) -> Tuple[StageExecution, CompetitionOutcome]:
    entrants = list(dict.fromkeys(entrants))
    if not entrants:
        raise ValueError("MAIN entrants cannot be empty")
    winner_overrides = dict(winner_overrides or {})

    seed_ids = ordered_seed_ids(
        entrants,
        seed_assignments,
        annual_seed_order,
        base_seed=base_seed,
        namespace=f"{competition_id}:{stage_id}:MAIN",
    )
    slots, seed_slots = generate_main_slots(
        entrants,
        seed_ids=seed_ids,
        base_seed=base_seed,
        namespace=f"{competition_id}:{stage_id}:MAIN",
        slot_override=slot_override,
    )
    bracket_size = len(slots)
    total_rounds = 0 if bracket_size == 1 else int(log2(bracket_size))

    if bracket_size == 1:
        champion = entrants[0]
        execution = StageExecution(
            stage_id=stage_id,
            stage_code="MAIN",
            format_model_id="MAIN_SINGLE_ELIMINATION",
            entrant_school_ids=list(entrants),
            output_school_ids=[champion],
            matches=[],
            metadata={
                "bracket_size": 1,
                "bye_count": 0,
                "seed_count": len(seed_ids),
                "seed_slots": seed_slots,
                "draw_source": "annual_override" if slot_override else "deterministic_standard",
                "initial_slots": slots,
            },
        )
        outcome = CompetitionOutcome(
            champion_school_id=champion,
            runner_up_school_id="",
            semifinalist_school_ids=[],
            quarterfinalist_school_ids=[],
            final_ranking_school_ids=[champion],
            eliminated_by_round={},
            match_count=0,
            bye_count=0,
            bracket_size=1,
        )
        return execution, outcome

    matches: List[Match] = []
    eliminated_by_round: Dict[int, List[str]] = defaultdict(list)
    current = list(slots)
    match_ids_by_round: Dict[int, List[str]] = {}

    for round_no in range(1, total_rounds + 1):
        round_matches: List[str] = []
        nxt: List[str] = []
        match_count = len(current) // 2
        for match_no in range(1, match_count + 1):
            t1 = current[(match_no - 1) * 2]
            t2 = current[(match_no - 1) * 2 + 1]
            match_id = f"{stage_id}-MAIN-R{round_no:02d}-M{match_no:03d}"
            next_match_id = (
                f"{stage_id}-MAIN-R{round_no + 1:02d}-M{((match_no - 1) // 2) + 1:03d}"
                if round_no < total_rounds else ""
            )
            next_side = "team1" if match_no % 2 == 1 else "team2"
            round_name = _round_name(round_no, total_rounds)

            if not t1 and not t2:
                raise AssertionError("empty match after round 1")
            if not t1 or not t2:
                winner = t1 or t2
                match = Match(
                    match_id=match_id,
                    competition_id=competition_id,
                    stage_id=stage_id,
                    stage_code="MAIN",
                    phase_code="MAIN_BRACKET",
                    round_no=round_no,
                    team1=t1,
                    team2=t2,
                    winner=winner,
                    is_bye=True,
                    metadata={
                        "round_name": round_name,
                        "bracket_size": bracket_size,
                        "match_no_in_round": match_no,
                        "next_match_id": next_match_id,
                        "next_match_side": next_side,
                    },
                )
                nxt.append(winner)
                matches.append(match)
                round_matches.append(match_id)
                continue

            resolution: MatchResolution | None = None
            if match_id in winner_overrides:
                winner = winner_overrides[match_id]
                if winner not in {t1, t2}:
                    raise ValueError(f"winner override for {match_id} is not a participant")
                loser = t2 if winner == t1 else t1
            elif match_resolver is not None:
                if reference_year is None:
                    raise ValueError("reference_year is required when match_resolver is used")
                resolution = match_resolver(
                    match_id=match_id,
                    competition_id=competition_id,
                    reference_year=reference_year,
                    generation_seed=base_seed,
                    team1=t1,
                    team2=t2,
                )
                if not isinstance(resolution, MatchResolution):
                    raise TypeError("match_resolver must return MatchResolution")
                if resolution.winner_id not in {t1, t2}:
                    raise ValueError("match_resolver winner is not a participant")
                expected_loser = t2 if resolution.winner_id == t1 else t1
                if resolution.loser_id != expected_loser:
                    raise ValueError("match_resolver loser is inconsistent with winner")
                if (resolution.team1_score is None) != (resolution.team2_score is None):
                    raise ValueError("match_resolver scores must be both present or both absent")
                if resolution.team1_score is not None:
                    if (
                        isinstance(resolution.team1_score, bool)
                        or isinstance(resolution.team2_score, bool)
                        or not isinstance(resolution.team1_score, int)
                        or not isinstance(resolution.team2_score, int)
                    ):
                        raise ValueError("match_resolver scores must be integers")
                    if resolution.team1_score < 0 or resolution.team2_score < 0:
                        raise ValueError("match_resolver scores must be non-negative")
                    if resolution.team1_score == resolution.team2_score:
                        raise ValueError("match_resolver cannot return a tied score")
                    expected_winner = (
                        t1
                        if resolution.team1_score > resolution.team2_score
                        else t2
                    )
                    if resolution.winner_id != expected_winner:
                        raise ValueError("match_resolver score winner mismatch")
                winner = resolution.winner_id
                loser = resolution.loser_id
                if resolved_match_sink is not None:
                    if match_id in resolved_match_sink:
                        raise ValueError(f"duplicate resolved match id: {match_id}")
                    resolved_match_sink[match_id] = dict(resolution.detail)
            else:
                namespace = f"{competition_id}:{stage_id}:MAIN:R{round_no}:M{match_no}:{t1}:{t2}"
                winner = winner_resolver(t1, t2, namespace)
                if winner not in {t1, t2}:
                    raise ValueError("winner_resolver returned a team not in the match")
                loser = t2 if winner == t1 else t1
            eliminated_by_round[round_no].append(loser)
            metadata = {
                "round_name": round_name,
                "bracket_size": bracket_size,
                "match_no_in_round": match_no,
                "next_match_id": next_match_id,
                "next_match_side": next_side,
                "winner_source": (
                    "annual_override"
                    if match_id in winner_overrides
                    else (
                        resolution.score_source
                        if resolution is not None and resolution.score_source
                        else "resolver"
                    )
                ),
            }
            if resolution is not None and resolution.team1_score is not None:
                metadata["score_source"] = resolution.score_source
                metadata["team1_score"] = resolution.team1_score
                metadata["team2_score"] = resolution.team2_score
            match = Match(
                match_id=match_id,
                competition_id=competition_id,
                stage_id=stage_id,
                stage_code="MAIN",
                phase_code="MAIN_BRACKET",
                round_no=round_no,
                team1=t1,
                team2=t2,
                winner=winner,
                loser=loser,
                metadata=metadata,
            )
            nxt.append(winner)
            matches.append(match)
            round_matches.append(match_id)
        current = nxt
        match_ids_by_round[round_no] = round_matches

    champion = current[0]
    final_losers = eliminated_by_round.get(total_rounds, [])
    runner_up = final_losers[0] if final_losers else ""
    semifinalists = list(eliminated_by_round.get(total_rounds - 1, [])) if total_rounds >= 2 else []
    quarterfinalists = list(eliminated_by_round.get(total_rounds - 2, [])) if total_rounds >= 3 else []

    final_ranking = [champion]
    for rno in range(total_rounds, 0, -1):
        cohort = list(eliminated_by_round.get(rno, []))
        if rno == total_rounds and runner_up:
            cohort = [runner_up]
        elif len(cohort) > 1:
            cohort = shuffled(cohort, base_seed, f"{competition_id}:{stage_id}:MAIN:ranking:{rno}")
        final_ranking.extend(cohort)

    execution = StageExecution(
        stage_id=stage_id,
        stage_code="MAIN",
        format_model_id="MAIN_SINGLE_ELIMINATION",
        entrant_school_ids=list(entrants),
        output_school_ids=[champion],
        matches=matches,
        metadata={
            "bracket_size": bracket_size,
            "bye_count": bracket_size - len(entrants),
            "seed_count": len(seed_ids),
            "seed_order_school_ids": seed_ids,
            "seed_slots": seed_slots,
            "draw_source": "annual_override" if slot_override else "deterministic_standard",
            "initial_slots": slots,
            "total_rounds": total_rounds,
            "match_ids_by_round": match_ids_by_round,
        },
    )
    outcome = CompetitionOutcome(
        champion_school_id=champion,
        runner_up_school_id=runner_up,
        semifinalist_school_ids=semifinalists,
        quarterfinalist_school_ids=quarterfinalists,
        final_ranking_school_ids=final_ranking,
        eliminated_by_round={str(k): list(v) for k, v in eliminated_by_round.items()},
        match_count=sum(1 for m in matches if not m.is_bye),
        bye_count=sum(1 for m in matches if m.is_bye),
        bracket_size=bracket_size,
    )
    return execution, outcome
