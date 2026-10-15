"""Independent Stage108 bracket/standings oracle: no factory, SQL, RNG or driver."""
from dataclasses import dataclass


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
    reached_round: int


def progression_oracle(plan, registration, results):
    entries, n = plan.entries, len(plan.entries)
    known = {t.team_id for t in registration.teams}
    schools = [s for t in registration.teams for s in t.school_ids]
    if (n not in (8,32) or len(set(entries)) != n or not set(entries) <= known
            or len(set(schools)) != len(schools) or len(plan.games) != n-1
            or len(results) > n-1
            or len({g.match_id for g in plan.games}) != n-1
            or len({g.seed for g in plan.games}) != n-1):
        raise ValueError('unique entrants/membership and complete bracket required')
    wins, losses = dict.fromkeys(entries,0), dict.fromkeys(entries,0)
    reached = dict.fromkeys(entries,1)
    ledger, previous_ids, previous_winners = [], (), ()
    offset = 0
    size = n//2
    round_no = 1
    while size:
        games = plan.games[offset:offset+size]
        participants = entries if round_no == 1 else previous_winners
        round_winners = []
        for slot, game in enumerate(games,1):
            sources = (entries[2*slot-2:2*slot] if round_no == 1 else
                tuple('winner:'+mid for mid in previous_ids[2*slot-2:2*slot]))
            if ((game.sequence,game.round_no,game.slot) != (offset+slot,round_no,slot)
                    or (game.team1_source,game.team2_source) != tuple(sources)
                    or (round_no > 1 and game.day <= plan.games[offset-1].day)):
                raise ValueError('round barrier/source/order differs')
            if offset+slot > len(results):
                continue
            pair = participants[2*slot-2:2*slot]
            result = results[offset+slot-1]
            if (len(pair) != 2 or (result.team1_id,result.team2_id) != tuple(pair)
                    or (result.year,result.competition_id,result.match_id,result.run_seed) !=
                    (plan.year,plan.competition_id,game.match_id,game.seed)
                    or result.team1_score == result.team2_score):
                raise ValueError('nonwinner/round not complete/invalid match')
            winner, loser = pair if result.team1_score > result.team2_score else pair[::-1]
            if (result.winner_id,result.loser_id) != (winner,loser) or losses[winner] or losses[loser]:
                raise ValueError('eliminated team or forged winner')
            wins[winner] += 1; losses[loser] += 1
            reached[winner] = reached[loser] = round_no
            round_winners.append(winner)
            ledger.append(Advancement(offset+slot,game.match_id,'WINNER',winner))
        previous_ids = tuple(g.match_id for g in games)
        previous_winners = tuple(round_winners)
        offset += size; size //= 2; round_no += 1
    ranks = ()
    if len(results) == n-1:
        champion = results[-1].winner_id
        # Losing cohorts share their best possible rank: 3,5,9,17.
        ranks = tuple(sorted((TeamRank(1 if tid == champion else
            2**(round_no-1-reached[tid])+1,tid,wins[tid],losses[tid],reached[tid])
            for tid in entries), key=lambda r:(r.rank,r.team_id)))
        if sum(wins.values()) != n-1 or sum(losses.values()) != n-1:
            raise ValueError('incomplete outcomes')
    return tuple(ledger), ranks
