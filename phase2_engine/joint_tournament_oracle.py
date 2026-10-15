"""Stage107 progression oracle: no input factory, RNG, driver or SQL helpers."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Advancement:
    sequence: int
    match_id: str
    source: str
    team_id: str


@dataclass(frozen=True)
class TeamRank:
    rank: int
    team_id: str
    wins: int
    losses: int


def progression_oracle(plan, registration, results):
    """Independently derive BYE, advancement and final team-only standings."""
    entries = tuple(t.team_id for t in registration.teams)
    schools = [sid for t in registration.teams for sid in t.school_ids]
    if (len(entries) != 3 or len(set(entries)) != 3 or len(schools) != len(set(schools))
            or plan.entries != entries or plan.bye_team_id != entries[2]
            or len(plan.games) != 2 or len(results) > 2):
        raise ValueError('three unique entries and one BYE required')
    first, final = plan.games
    if (first.sequence, final.sequence) != (1, 2) or first.day >= final.day or first.match_id == final.match_id:
        raise ValueError('ordered distinct games required')
    ledger = [Advancement(0, final.match_id, 'BYE', entries[2])]
    wins, losses = dict.fromkeys(entries, 0), dict.fromkeys(entries, 0)
    expected_pair = entries[:2]
    for i, result in enumerate(results):
        game = plan.games[i]
        if ((result.year, result.competition_id, result.match_id) !=
                (plan.year, plan.competition_id, game.match_id)
                or (result.team1_id, result.team2_id) != expected_pair
                or result.team1_id == result.team2_id or result.run_seed != game.seed
                or result.team1_score == result.team2_score):
            raise ValueError('game order/seed/eligible participants differ')
        winner, loser = (expected_pair if result.team1_score > result.team2_score else expected_pair[::-1])
        if (result.winner_id, result.loser_id) != (winner, loser) or losses[winner] or losses[loser]:
            raise ValueError('nonwinner advancement or eliminated team replay')
        wins[winner] += 1
        losses[loser] += 1
        ledger.append(Advancement(i + 1, game.match_id, 'WINNER', winner))
        expected_pair = (winner, entries[2])
    ranks = ()
    if len(results) == 2:
        order = (results[1].winner_id, results[1].loser_id, results[0].loser_id)
        if len(set(order)) != 3 or sum(wins.values()) != 2 or sum(losses.values()) != 2:
            raise ValueError('incomplete tournament outcomes')
        ranks = tuple(TeamRank(i, tid, wins[tid], losses[tid]) for i, tid in enumerate(order, 1))
    return tuple(ledger), ranks


def player_totals(results, player_id):
    """Sum counting stats once per played game; never add rates or team wins."""
    totals = {'batting': {}, 'pitching': {}}
    identities = set()
    for result in results:
        for kind, rows in (('batting', result.batter_stats), ('pitching', result.pitcher_stats)):
            for row in rows:
                if row.player_id != player_id:
                    continue
                identities.add((row.team_id, row.origin_school_id))
                for key, value in asdict(row).items():
                    if key not in ('year', 'competition_id', 'match_id', 'team_id', 'player_id', 'origin_school_id'):
                        totals[kind][key] = totals[kind].get(key, 0) + value
    if len(identities) > 1:
        raise ValueError('permanent player attribution changed')
    return totals
