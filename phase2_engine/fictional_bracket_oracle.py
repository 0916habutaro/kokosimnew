"""Stage117 progression oracle: no RNG, bracket graph, input builder or SQL.

Folds the saved slot list pairwise, independently of `fictional_bracket`.
Winners come from scores, never from the declared winner alone.
"""


def progression(plan, request, results):
    entries = tuple(t.entry_team_id for t in request.entries.teams)
    slots = tuple(plan.slots)
    size = len(slots)
    rounds = size.bit_length() - 1
    if (size < 4 or size & (size - 1) or set(slots) - {None} != set(entries)
            or len(entries) != len(set(entries)) or sum(s is None for s in slots) != size - len(entries)
            or (request.draw.participant_slots, request.draw.bracket_size, request.draw.bye_count)
            != (len(entries), size, size - len(entries))
            or tuple(request.schedule.round_dates) != tuple(sorted(set(g.day for g in plan.games)))
            or len(request.schedule.round_dates) != rounds
            or tuple(g.sequence for g in plan.games) != tuple(range(1, len(entries)))
            or len({g.match_id for g in plan.games}) != len(plan.games)
            or len(results) > len(plan.games)):
        raise ValueError('fictional bracket/date contract differs')
    # Seeds 1..2^r occupy distinct blocks of size/2^r; BYEs go to top seeds first.
    where = {team: slots.index(team) for team, _ in request.seeds.seeds}
    for team, number in request.seeds.seeds:
        if number <= size - len(entries) and slots[where[team] ^ 1] is not None:
            raise ValueError('declared top seed must receive a scenario BYE')
        for other, rival in request.seeds.seeds:
            span = 1
            while span < max(number, rival):
                span *= 2
            block = size // span
            if other != team and where[team] // block == where[other] // block:
                raise ValueError('declared seeds share a bracket block')
    ledger, wins, losses = [], dict.fromkeys(entries, 0), dict.fromkeys(entries, 0)
    eliminated = {}
    current = list(slots)
    taken = 0
    for round_no in range(1, rounds + 1):
        following = []
        for i in range(0, len(current), 2):
            a, b = current[i], current[i + 1]
            if round_no == 1 and (a is None) != (b is None):
                team = a if b is None else b
                ledger.append((0, 1, 'BYE', team))
                following.append(team)
                continue
            if round_no == 1 and a is None:
                raise ValueError('double BYE')
            game = plan.games[taken] if taken < len(plan.games) else None
            if game is None or game.round_no != round_no or game.day != request.schedule.round_dates[round_no - 1]:
                raise ValueError('fictional game order/round/date differs')
            if taken >= len(results) or a in ('?', None) or b in ('?', None):
                taken += 1
                following.append('?')
                continue
            result = results[taken]
            if ((result.year, result.competition_id, result.match_id, result.run_seed)
                    != (2027, plan.scope, game.match_id, game.seed)
                    or (result.team1_id, result.team2_id) != (a, b)
                    or type(result.team1_score) is not int or type(result.team2_score) is not int
                    or result.team1_score == result.team2_score):
                raise ValueError('fictional match sequence/participants/seed differs')
            winner, loser = (a, b) if result.team1_score > result.team2_score else (b, a)
            if (result.winner_id, result.loser_id) != (winner, loser) or losses[winner] or losses[loser]:
                raise ValueError('only actual winner may advance')
            wins[winner] += 1
            losses[loser] += 1
            eliminated[loser] = round_no
            taken += 1
            ledger.append((game.sequence, round_no, 'WINNER', winner))
            following.append(winner)
        current = following
    if taken != len(plan.games):
        raise ValueError('fictional game count differs')
    ranks = []
    if len(results) == len(plan.games):
        champion = current[0]
        if (sum(wins.values()) != len(results) or sum(losses.values()) != len(results)
                or len(eliminated) != len(entries) - 1 or champion in eliminated or losses[champion]):
            raise ValueError('fictional final standings differ')
        ranks = [(1, champion, wins[champion], 0)]
        ranks += [(2 ** (rounds - r) + 1, tid, wins[tid], losses[tid]) for tid, r in eliminated.items()]
        ranks.sort(key=lambda r: (r[0], r[1]))
    return sorted(ledger), ranks
