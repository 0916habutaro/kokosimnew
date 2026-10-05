from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

from .models import Match
from .randomness import rng_for, shuffled

WinnerResolver = Callable[[str, str, str], str]


def random_winner_resolver(base_seed: int) -> WinnerResolver:
    def resolve(team1: str, team2: str, namespace: str) -> str:
        r = rng_for(base_seed, namespace)
        return team1 if r.random() < 0.5 else team2
    return resolve


def balanced_partition(
    teams: Iterable[str],
    block_count: int,
    *,
    base_seed: int,
    namespace: str,
) -> List[List[str]]:
    items = shuffled(teams, base_seed, namespace)
    if block_count <= 0:
        raise ValueError("block_count must be positive")
    if block_count > len(items):
        raise ValueError(f"block_count={block_count} exceeds entrants={len(items)}")
    q, r = divmod(len(items), block_count)
    sizes = [q + (1 if i < r else 0) for i in range(block_count)]
    out: List[List[str]] = []
    pos = 0
    for size in sizes:
        out.append(items[pos:pos + size])
        pos += size
    return out


def run_single_elimination_ranking(
    teams: Iterable[str],
    *,
    competition_id: str,
    stage_id: str,
    stage_code: str,
    phase_code: str,
    group_id: str,
    group_name: str,
    base_seed: int,
    winner_resolver: WinnerResolver,
) -> Tuple[List[str], List[Match]]:
    active = shuffled(teams, base_seed, f"{competition_id}:{stage_id}:{group_id}:draw")
    if not active:
        return [], []
    eliminated_by_round: Dict[int, List[str]] = defaultdict(list)
    matches: List[Match] = []
    round_no = 1
    match_seq = 1
    while len(active) > 1:
        next_round: List[str] = []
        i = 0
        while i < len(active):
            t1 = active[i]
            if i + 1 >= len(active):
                matches.append(Match(
                    match_id=f"{stage_id}-{group_id or 'GLOBAL'}-{phase_code}-{match_seq:03d}",
                    competition_id=competition_id,
                    stage_id=stage_id,
                    stage_code=stage_code,
                    phase_code=phase_code,
                    round_no=round_no,
                    group_id=group_id,
                    group_name=group_name,
                    team1=t1,
                    winner=t1,
                    is_bye=True,
                ))
                next_round.append(t1)
                match_seq += 1
                i += 1
                continue
            t2 = active[i + 1]
            namespace = f"{competition_id}:{stage_id}:{group_id}:R{round_no}:M{match_seq}:{t1}:{t2}"
            winner = winner_resolver(t1, t2, namespace)
            if winner not in {t1, t2}:
                raise ValueError("winner_resolver returned a team not in the match")
            loser = t2 if winner == t1 else t1
            matches.append(Match(
                match_id=f"{stage_id}-{group_id or 'GLOBAL'}-{phase_code}-{match_seq:03d}",
                competition_id=competition_id,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code=phase_code,
                round_no=round_no,
                group_id=group_id,
                group_name=group_name,
                team1=t1,
                team2=t2,
                winner=winner,
                loser=loser,
            ))
            eliminated_by_round[round_no].append(loser)
            next_round.append(winner)
            match_seq += 1
            i += 2
        active = next_round
        round_no += 1
    champion = active[0]
    ranking = [champion]
    for rno in sorted(eliminated_by_round, reverse=True):
        cohort = shuffled(
            eliminated_by_round[rno], base_seed,
            f"{competition_id}:{stage_id}:{group_id}:rank_tiebreak:{rno}"
        )
        ranking.extend(cohort)
    return ranking, matches


def run_single_round_gate(
    teams: Iterable[str],
    *,
    competition_id: str,
    stage_id: str,
    stage_code: str,
    phase_code: str,
    base_seed: int,
    winner_resolver: WinnerResolver,
) -> Tuple[List[str], List[Match]]:
    entrants = shuffled(teams, base_seed, f"{competition_id}:{stage_id}:gate_draw")
    winners: List[str] = []
    matches: List[Match] = []
    match_seq = 1
    i = 0
    while i < len(entrants):
        t1 = entrants[i]
        if i + 1 >= len(entrants):
            winners.append(t1)
            matches.append(Match(
                match_id=f"{stage_id}-GLOBAL-{match_seq:03d}",
                competition_id=competition_id,
                stage_id=stage_id,
                stage_code=stage_code,
                phase_code=phase_code,
                round_no=1,
                team1=t1,
                winner=t1,
                is_bye=True,
                metadata={"reason": "odd_entrant_count"},
            ))
            break
        t2 = entrants[i + 1]
        namespace = f"{competition_id}:{stage_id}:GATE:M{match_seq}:{t1}:{t2}"
        winner = winner_resolver(t1, t2, namespace)
        if winner not in {t1, t2}:
            raise ValueError("winner_resolver returned a team not in the match")
        loser = t2 if winner == t1 else t1
        winners.append(winner)
        matches.append(Match(
            match_id=f"{stage_id}-GLOBAL-{match_seq:03d}",
            competition_id=competition_id,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            round_no=1,
            team1=t1,
            team2=t2,
            winner=winner,
            loser=loser,
        ))
        match_seq += 1
        i += 2
    return winners, matches


def run_block_winner_forest(
    teams: Iterable[str],
    *,
    block_count: int,
    competition_id: str,
    stage_id: str,
    stage_code: str,
    phase_code: str,
    group_id: str,
    group_name: str,
    base_seed: int,
    winner_resolver: WinnerResolver,
) -> Tuple[List[str], List[Match], List[List[str]]]:
    blocks = balanced_partition(
        teams, block_count, base_seed=base_seed,
        namespace=f"{competition_id}:{stage_id}:{group_id}:{phase_code}:forest_partition",
    )
    winners: List[str] = []
    matches: List[Match] = []
    for idx, block in enumerate(blocks, start=1):
        pseudo_group = f"{group_id or 'GLOBAL'}-B{idx:02d}"
        ranking, block_matches = run_single_elimination_ranking(
            block,
            competition_id=competition_id,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            group_id=pseudo_group,
            group_name=group_name,
            base_seed=base_seed,
            winner_resolver=winner_resolver,
        )
        winners.append(ranking[0])
        for m in block_matches:
            m.group_id = group_id
            m.group_name = group_name
            m.metadata["block_no"] = idx
        matches.extend(block_matches)
    return winners, matches, blocks


def run_round_robin(
    teams: Sequence[str],
    *,
    competition_id: str,
    stage_id: str,
    stage_code: str,
    phase_code: str,
    group_id: str,
    group_name: str,
    pool_no: int,
    base_seed: int,
    winner_resolver: WinnerResolver,
) -> Tuple[List[str], List[Match], Dict[str, Dict[str, int]]]:
    items = list(teams)
    wins = {t: 0 for t in items}
    losses = {t: 0 for t in items}
    matches: List[Match] = []
    seq = 1
    for t1, t2 in combinations(items, 2):
        namespace = f"{competition_id}:{stage_id}:{group_id}:{phase_code}:P{pool_no}:M{seq}:{t1}:{t2}"
        winner = winner_resolver(t1, t2, namespace)
        loser = t2 if winner == t1 else t1
        wins[winner] += 1
        losses[loser] += 1
        matches.append(Match(
            match_id=f"{stage_id}-{group_id or 'GLOBAL'}-{phase_code}-P{pool_no:02d}-M{seq:03d}",
            competition_id=competition_id,
            stage_id=stage_id,
            stage_code=stage_code,
            phase_code=phase_code,
            round_no=1,
            group_id=group_id,
            group_name=group_name,
            team1=t1,
            team2=t2,
            winner=winner,
            loser=loser,
            metadata={"pool_no": pool_no},
        ))
        seq += 1
    # Ties on wins are resolved by a namespaced deterministic draw. This is a
    # simulation tiebreak, not a claim about any prefecture's official tie rule.
    tie_order = shuffled(items, base_seed, f"{competition_id}:{stage_id}:{group_id}:{phase_code}:P{pool_no}:tiebreak")
    tie_idx = {t: i for i, t in enumerate(tie_order)}
    ranking = sorted(items, key=lambda t: (-wins[t], tie_idx[t]))
    standings = {t: {"wins": wins[t], "losses": losses[t]} for t in items}
    return ranking, matches, standings


def run_head_to_head(
    team1: str,
    team2: str,
    *,
    competition_id: str,
    stage_id: str,
    stage_code: str,
    phase_code: str,
    group_id: str,
    group_name: str,
    match_no: int,
    base_seed: int,
    winner_resolver: WinnerResolver,
) -> Match:
    namespace = f"{competition_id}:{stage_id}:{group_id}:{phase_code}:M{match_no}:{team1}:{team2}"
    winner = winner_resolver(team1, team2, namespace)
    loser = team2 if winner == team1 else team1
    return Match(
        match_id=f"{stage_id}-{group_id or 'GLOBAL'}-{phase_code}-M{match_no:03d}",
        competition_id=competition_id,
        stage_id=stage_id,
        stage_code=stage_code,
        phase_code=phase_code,
        round_no=1,
        group_id=group_id,
        group_name=group_name,
        team1=team1,
        team2=team2,
        winner=winner,
        loser=loser,
    )
