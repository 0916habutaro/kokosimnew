"""Stage105 separate team driver; only old probability/usage formulas reused.

No legacy MatchSimulationInput/Result, no school reassignment, no file writer.
"""
from dataclasses import asdict
from pathlib import Path
from statistics import fmean

from game_core.match_simulator import MatchSimulator
from .randomness import rng_for
from .joint_team_registration_lab import validate_registered_match_input, _sha
from .registered_full_a_contract import (
    VERSION, MODEL, RegisteredTeamFullAResultV1, RegisteredEventV1,
    RegisteredTeamStatsV1, RegisteredInningScoreV1,
    RegisteredBatterStatsV1, RegisteredPitcherStatsV1,
)

KINDS = ('strikeout', 'walk', 'hit_by_pitch', 'single', 'double', 'triple',
         'home_run', 'field_out')
DISTANCE = {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}
CONFIG = Path(__file__).resolve().parents[1] / 'config/match'


def probability_model():
    return MatchSimulator(CONFIG)


def config_digest(model):
    return _sha(model.params)


def weights(model, batter, pitcher, defense):
    original = model._event_weights(batter, pitcher, defense)
    selected = {kind: original[kind] for kind in KINDS}
    selected['field_out'] += original['reached_on_error'] + original['fielder_choice']
    return selected


def _scope(m):
    return dict(year=m.year, competition_id=m.competition_id, match_id=m.match_id)


def _advance(kind, batter, bases):
    """Driver's mutable three-slot advancement, returning actual scorers."""
    scored = []
    if kind in ('walk', 'hit_by_pitch'):
        if bases[0] is not None:
            if bases[1] is not None:
                if bases[2] is not None:
                    scored.append(bases[2])
                bases[2] = bases[1]
            bases[1] = bases[0]
        bases[0] = batter
    elif kind in DISTANCE:
        distance = DISTANCE[kind]
        new = [None, None, None]
        for index in (2, 1, 0):
            runner = bases[index]
            if runner is not None:
                if index + distance >= 3:
                    scored.append(runner)
                else:
                    new[index + distance] = runner
        if distance == 4:
            scored.append(batter)
        else:
            new[distance - 1] = batter
        bases[:] = new
    return tuple(scored)


def _run(m, seed):
    """Internal calculation. Public entry validates sources before calling."""
    model = probability_model()
    scope = _scope(m)
    teams = {t.team_id: t for t in (m.team1, m.team2)}
    sides = tuple(teams)
    origins = {p.player_id: p.origin_school_id for t in teams.values() for p in t.players}
    abilities = {p.player_id: p.snapshot for t in teams.values() for p in t.players}
    lineups = {tid: [pid for _, _, pid in t.lineup] for tid, t in teams.items()}
    batting_index = dict.fromkeys(sides, 0)
    pitching_index = dict.fromkeys(sides, 0)
    defense = {tid: fmean(abilities[pid].fielding for _, pos, pid in t.lineup if pos != 'P')
               for tid, t in teams.items()}
    runs = dict.fromkeys(sides, 0)
    hits = dict.fromkeys(sides, 0)
    batting, pitching = {}, {}

    def row(cls, tid, pid):
        return asdict(cls(**scope, team_id=tid, player_id=pid, origin_school_id=origins[pid]))

    for tid, lineup in lineups.items():
        for pid in lineup:
            batting[pid] = row(RegisteredBatterStatsV1, tid, pid)
        pid = teams[tid].pitching_order[0]
        pitching[pid] = row(RegisteredPitcherStatsV1, tid, pid)
    events, innings = [], []
    done = False
    ending = 'bottom'
    for inning in range(1, 31):
        for half, attack, defend in (('top', sides[0], sides[1]), ('bottom', sides[1], sides[0])):
            if half == 'bottom' and inning >= 9 and runs[sides[1]] > runs[sides[0]]:
                innings.append(RegisteredInningScoreV1(**scope, inning=inning, half=half,
                               team_id=attack, was_played=False, runs=None))
                done, ending = True, 'top'
                break
            before_runs = runs[attack]
            bases = [None, None, None]
            responsible = {}
            outs = 0
            while outs < 3:
                if len(events) >= 10000:
                    raise RuntimeError('lab plate appearance safety bound; no result')
                staff = teams[defend].pitching_order
                index = pitching_index[defend]
                pitcher = staff[index]
                removed = None
                if model._should_change_pitcher(pitcher=abilities[pitcher], stats=pitching[pitcher],
                        starter=index == 0, has_next=index + 1 < len(staff)):
                    removed = pitcher
                    index += 1
                    pitching_index[defend] = index
                    pitcher = staff[index]
                    slot = lineups[defend].index(removed)
                    lineups[defend][slot] = pitcher
                    batting[pitcher] = row(RegisteredBatterStatsV1, defend, pitcher)
                    pitching[pitcher] = row(RegisteredPitcherStatsV1, defend, pitcher)
                batter = lineups[attack][batting_index[attack] % 9]
                batting_index[attack] += 1
                number = len(events) + 1
                rng = rng_for(seed, f'lab105:{m.match_id}:pa:{number}')
                kind = model._weighted_choice(rng, weights(model, abilities[batter], abilities[pitcher], defense[defend]))
                before = tuple(bases)
                responsible[batter] = pitcher
                scored = _advance(kind, batter, bases)
                # Non-HR walkoff ends when the winning run crosses home.
                if half == 'bottom' and inning >= 9 and kind != 'home_run':
                    needed = runs[defend] - runs[attack] + 1
                    if len(scored) >= needed:
                        scored = scored[:needed]
                out = int(kind in ('strikeout', 'field_out'))
                br, pr = batting[batter], pitching[pitcher]
                br['plate_appearances'] += 1
                pr['batters_faced'] += 1
                br['at_bats'] += int(kind not in ('walk', 'hit_by_pitch'))
                br['rbi'] += len(scored)
                pr['outs_recorded'] += out
                if kind in DISTANCE:
                    br['hits'] += 1
                    hits[attack] += 1
                    pr['hits_allowed'] += 1
                    if kind != 'single':
                        br[{'double': 'doubles', 'triple': 'triples', 'home_run': 'home_runs'}[kind]] += 1
                    if kind == 'home_run':
                        pr['home_runs_allowed'] += 1
                if kind in ('walk', 'strikeout', 'hit_by_pitch'):
                    br[{'walk': 'walks', 'strikeout': 'strikeouts', 'hit_by_pitch': 'hit_by_pitch'}[kind]] += 1
                    pr[{'walk': 'walks', 'strikeout': 'strikeouts', 'hit_by_pitch': 'hit_batters'}[kind]] += 1
                for runner in scored:
                    batting[runner]['runs'] += 1
                    charged = pitching[responsible[runner]]
                    charged['runs_allowed'] += 1
                    charged['earned_runs'] += 1
                events.append(RegisteredEventV1(**scope, event_no=number, inning=inning, half=half,
                    offense_team_id=attack, defense_team_id=defend, batter_id=batter, pitcher_id=pitcher,
                    batter_origin_school_id=origins[batter], pitcher_origin_school_id=origins[pitcher],
                    event_type=kind, bases_before=before, bases_after=tuple(bases), scored_player_ids=scored,
                    outs_before=outs, outs_on_play=out, rbi=len(scored), pitcher_staff_order=index + 1,
                    replaced_pitcher_id=removed))
                outs += out
                runs[attack] += len(scored)
                if half == 'bottom' and inning >= 9 and runs[attack] > runs[defend]:
                    done = True
                    break
            innings.append(RegisteredInningScoreV1(**scope, inning=inning, half=half,
                           team_id=attack, was_played=True, runs=runs[attack] - before_runs))
            ending = half
            if half == 'bottom' and inning >= 9 and runs[attack] != runs[defend]:
                done = True
            if done:
                break
        if done:
            break
    if not done:
        raise RuntimeError('tie after 30 innings; no complete result')
    winner, loser = sorted(sides, key=lambda tid: runs[tid], reverse=True)
    return RegisteredTeamFullAResultV1(**scope, version=VERSION, model=MODEL,
        input_sha256=_sha(m.to_dict()), probability_config_sha256=config_digest(model), run_seed=seed,
        team1_id=sides[0], team2_id=sides[1], team1_score=runs[sides[0]], team2_score=runs[sides[1]],
        winner_id=winner, loser_id=loser, last_inning=inning, ending_half=ending,
        team_stats=tuple(RegisteredTeamStatsV1(**scope, team_id=tid, runs=runs[tid], hits=hits[tid], errors=0) for tid in sides),
        inning_scores=tuple(innings), events=tuple(events),
        batter_stats=tuple(RegisteredBatterStatsV1(**batting[pid]) for pid in sorted(batting)),
        pitcher_stats=tuple(RegisteredPitcherStatsV1(**pitching[pid]) for pid in sorted(pitching)))


def simulate_registered_full_a(m, registration, repo, rosters, *, run_seed=None):
    validate_registered_match_input(m, registration, repo, rosters)
    seed = m.match_seed if run_seed is None else run_seed
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError('explicit nonnegative integer lab seed required')
    result = _run(m, seed)
    from .registered_full_a_oracle import validate_registered_full_a
    validate_registered_full_a(result, m, registration, repo, rosters, expected_seed=seed)
    return result
