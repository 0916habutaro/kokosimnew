"""Independent positional replay/statistics oracle, separate from driver updates."""
from collections import defaultdict
from dataclasses import asdict

from .joint_team_registration_lab import validate_registered_match_input, _identical
from .registered_full_a_contract import (
    RegisteredTeamFullAResultV1, RegisteredBatterStatsV1, RegisteredPitcherStatsV1,
    decode_result,
)


def event_oracle(result, match):
    """No random draws, driver advancement or driver stat helpers used here."""
    teams = {t.team_id: t for t in (match.team1, match.team2)}
    ids = tuple(teams)
    origin = {p.player_id: (t.team_id, p.origin_school_id)
              for t in teams.values() for p in t.players}
    lineup = {tid: [pid for _, _, pid in t.lineup] for tid, t in teams.items()}
    turn = dict.fromkeys(ids, 0)
    staff_index = dict.fromkeys(ids, 0)
    bat, pitch = {}, {}
    scope = dict(year=match.year, competition_id=match.competition_id, match_id=match.match_id)

    def activate(target, cls, pid):
        if pid not in target:
            tid, sid = origin[pid]
            target[pid] = asdict(cls(**scope, team_id=tid, player_id=pid, origin_school_id=sid))

    for tid in ids:
        for pid in lineup[tid]:
            activate(bat, RegisteredBatterStatsV1, pid)
        activate(pitch, RegisteredPitcherStatsV1, teams[tid].pitching_order[0])
    runs = dict.fromkeys(ids, 0)
    hits = dict.fromkeys(ids, 0)
    inning_totals = defaultdict(int)
    half_key, outs, occupied, liability = None, 0, {}, {}
    for number, event in enumerate(result.events, 1):
        e = asdict(event)
        if any(e[name] != value for name, value in scope.items()) or e['event_no'] != number:
            raise ValueError('event scope/sequence differs')
        attack = ids[0] if event.half == 'top' else ids[1]
        defend = ids[1] if event.half == 'top' else ids[0]
        if (event.offense_team_id, event.defense_team_id) != (attack, defend):
            raise ValueError('event offense/defense differs')
        key = event.inning, event.half
        if key != half_key:
            if half_key is not None and outs != 3:
                raise ValueError('incomplete previous half inning')
            half_key, outs, occupied, liability = key, 0, {}, {}
        if event.outs_before != outs or event.bases_before != tuple(occupied.get(i) for i in (1, 2, 3)):
            raise ValueError('base/out discontinuity')
        index = staff_index[defend]
        current = teams[defend].pitching_order[index]
        if event.replaced_pitcher_id is not None:
            if event.replaced_pitcher_id != current or index + 1 >= len(teams[defend].pitching_order):
                raise ValueError('illegal pitching substitution')
            index += 1
            staff_index[defend] = index
            successor = teams[defend].pitching_order[index]
            lineup[defend][lineup[defend].index(current)] = successor
            current = successor
            activate(bat, RegisteredBatterStatsV1, current)
            activate(pitch, RegisteredPitcherStatsV1, current)
        if (event.pitcher_id, event.pitcher_staff_order) != (current, index + 1):
            raise ValueError('pitcher order differs')
        batter = lineup[attack][turn[attack] % 9]
        turn[attack] += 1
        if event.batter_id != batter:
            raise ValueError('batting order differs')
        if (origin[batter] != (attack, event.batter_origin_school_id)
                or origin[current] != (defend, event.pitcher_origin_school_id)):
            raise ValueError('permanent identity/origin differs')
        kind = event.event_type
        is_hit = kind in ('single', 'double', 'triple', 'home_run')
        is_out = kind in ('strikeout', 'field_out')
        if kind not in ('single', 'double', 'triple', 'home_run', 'strikeout', 'field_out', 'walk', 'hit_by_pitch'):
            raise ValueError('unsupported model event')
        liability[batter] = current
        destinations = dict(occupied)
        crossing = []
        if is_hit:
            step = ('single', 'double', 'triple', 'home_run').index(kind) + 1
            moving = sorted([(place + step, pid) for place, pid in occupied.items()], reverse=True)
            moving.append((step, batter))
            crossing = [pid for place, pid in moving if place >= 4]
            destinations = {place: pid for place, pid in moving if place < 4}
        elif kind in ('walk', 'hit_by_pitch'):
            position = 1
            carried = batter
            while position in occupied and position <= 3:
                destinations[position], carried = carried, occupied[position]
                position += 1
            if position == 4:
                crossing = [carried]
            else:
                destinations[position] = carried
        if event.half == 'bottom' and event.inning >= 9 and kind != 'home_run':
            crossing = crossing[:max(0, runs[defend] + 1 - runs[attack])]
        if (tuple(crossing) != event.scored_player_ids
                or tuple(destinations.get(i) for i in (1, 2, 3)) != event.bases_after
                or event.outs_on_play != int(is_out) or event.rbi != len(crossing)):
            raise ValueError('event movement/score differs')
        occupied = destinations
        outs += int(is_out)
        if outs > 3:
            raise ValueError('too many outs')
        b, p = bat[batter], pitch[current]
        b['plate_appearances'] += 1
        b['at_bats'] += int(kind not in ('walk', 'hit_by_pitch'))
        b['hits'] += int(is_hit)
        b['rbi'] += len(crossing)
        for name, trigger in (('doubles', 'double'), ('triples', 'triple'), ('home_runs', 'home_run'),
                ('walks', 'walk'), ('strikeouts', 'strikeout'), ('hit_by_pitch', 'hit_by_pitch')):
            b[name] += int(kind == trigger)
        p['batters_faced'] += 1
        p['outs_recorded'] += int(is_out)
        p['hits_allowed'] += int(is_hit)
        for name, trigger in (('home_runs_allowed', 'home_run'), ('walks', 'walk'),
                ('strikeouts', 'strikeout'), ('hit_batters', 'hit_by_pitch')):
            p[name] += int(kind == trigger)
        for runner in crossing:
            bat[runner]['runs'] += 1
            pitch[liability[runner]]['runs_allowed'] += 1
            pitch[liability[runner]]['earned_runs'] += 1
        runs[attack] += len(crossing)
        hits[attack] += int(is_hit)
        inning_totals[key] += len(crossing)
        if event.half == 'bottom' and event.inning >= 9 and runs[attack] > runs[defend] and number != len(result.events):
            raise ValueError('events after walkoff')
    if not result.events:
        raise ValueError('no executed game')
    expected_bat = tuple(RegisteredBatterStatsV1(**bat[pid]) for pid in sorted(bat))
    expected_pitch = tuple(RegisteredPitcherStatsV1(**pitch[pid]) for pid in sorted(pitch))
    if not _identical(result.batter_stats, expected_bat) or not _identical(result.pitcher_stats, expected_pitch):
        raise ValueError('independent event statistics differ')
    if (result.team1_score, result.team2_score) != (runs[ids[0]], runs[ids[1]]):
        raise ValueError('independent event score differs')
    if result.last_inning != half_key[0] or result.last_inning < 9 or runs[ids[0]] == runs[ids[1]]:
        raise ValueError('game not completed')
    for row in result.team_stats:
        if (row.runs, row.hits, row.errors) != (runs[row.team_id], hits[row.team_id], 0):
            raise ValueError('team totals differ')
    for row in result.inning_scores:
        if row.was_played and row.runs != inning_totals[row.inning, row.half]:
            raise ValueError('inning score differs')
    return dict(events=len(result.events), plate_appearances=sum(r['plate_appearances'] for r in bat.values()),
                pitching_outs=sum(r['outs_recorded'] for r in pitch.values()),
                strikeouts=sum(r['strikeouts'] for r in pitch.values()),
                runs=sum(runs.values()), rbi=sum(r['rbi'] for r in bat.values()),
                pitcher_runs=sum(r['runs_allowed'] for r in pitch.values()),
                origins=tuple(sorted({sid for tid, sid in origin.values()})))


def validate_registered_full_a(result, match, registration, repo, rosters, *, expected_seed=None):
    validate_registered_match_input(match, registration, repo, rosters)
    if type(result) is not RegisteredTeamFullAResultV1:
        raise ValueError('new versioned result required; legacy schema refused')
    seed = match.match_seed if expected_seed is None else expected_seed
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('invalid expected seed')
    # Exact scalar/container types, full schema and probability provenance, and
    # deterministic execution are checked separately from the statistics oracle.
    from .registered_match_driver import _run
    expected = _run(match, seed)
    if not _identical(result, expected):
        raise ValueError('result differs from seeded execution/versioned contract')
    return event_oracle(result, match)


def load_result(raw, match, registration, repo, rosters, *, expected_seed=None):
    result = decode_result(raw)
    validate_registered_full_a(result, match, registration, repo, rosters, expected_seed=expected_seed)
    return result


def legacy_writer_payload(*args, **kwargs):
    raise ValueError('registered full-A writer not adopted; no legacy export')
