"""Stage116 progression oracle: no RNG, input builder, driver or SQL writes."""


def progression(plan, request, results):
    entries = tuple(t.entry_team_id for t in request.entries.teams)
    slots = plan.slots
    if (len(entries) != 3 or len(set(entries)) != 3 or len(slots) != 4
            or slots[1] is not None or set(slots) != {*entries, None}
            or len(results) > 2 or tuple(g.day for g in plan.games) != request.schedule.round_dates
            or tuple(g.sequence for g in plan.games) != (1, 2)
            or len({g.match_id for g in plan.games}) != 2):
        raise ValueError('fictional three-team bracket/date contract differs')
    if request.seeds.seeds and slots[0] != request.seeds.seeds[0][0]:
        raise ValueError('declared seed must receive this scenario BYE')
    ledger = [(0, plan.games[1].match_id, 'BYE', slots[0])]
    wins, losses = dict.fromkeys(entries, 0), dict.fromkeys(entries, 0)
    pair = slots[2:]
    for i, result in enumerate(results):
        game = plan.games[i]
        if ((result.year, result.competition_id, result.match_id, result.run_seed)
                != (2027, plan.scope, game.match_id, game.seed)
                or (result.team1_id, result.team2_id) != pair
                or result.team1_score == result.team2_score):
            raise ValueError('fictional match sequence/participants/seed differs')
        winner, loser = pair if result.team1_score > result.team2_score else pair[::-1]
        if (result.winner_id, result.loser_id) != (winner, loser) or losses[winner] or losses[loser]:
            raise ValueError('only actual winner may advance')
        wins[winner] += 1
        losses[loser] += 1
        ledger.append((i + 1, game.match_id, 'WINNER', winner))
        pair = (winner, slots[0])
    ranks = []
    if len(results) == 2:
        order = (results[1].winner_id, results[1].loser_id, results[0].loser_id)
        if len(set(order)) != 3 or sum(wins.values()) != 2 or sum(losses.values()) != 2:
            raise ValueError('fictional final standings differ')
        ranks = [(n, tid, wins[tid], losses[tid]) for n, tid in enumerate(order, 1)]
    return ledger, ranks
