"""Real eight-team seven-game bracket; independent full-A/progression/identity and crash audits."""
from contextlib import closing
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import tempfile
from time import perf_counter, process_time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from phase2_engine import competition_evidence_gates as gates
from phase2_engine import saved_fictional_bracket as trial
from phase2_engine import saved_fictional_tournament as v1
from phase2_engine import saved_practice_match as practice
from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine.fictional_bracket import Bracket, plan_slots, seed_positions
from phase2_engine.fictional_bracket_oracle import progression
from phase2_engine.fictional_tournament_oracle import progression as v1_progression
from phase2_engine.manual_save_backup import _compatibility
from phase2_engine.registered_full_a_oracle import event_oracle
from phase2_engine.registered_match_driver import _run
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g115_support import scenario as v1_scenario
from stage43g117_support import scenario, worker, GROUPS

MEASUREMENTS = {}
ROOT = Path(__file__).resolve().parents[1]

try:
    import resource
except ImportError:  # Windows
    resource = None


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def peak_rss_kib():
    if resource is not None:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL('psapi')
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.PeakWorkingSetSize // 1024


@dataclass(frozen=True)
class Fake:
    year: int
    competition_id: str
    match_id: str
    run_seed: int
    team1_id: str
    team2_id: str
    team1_score: int
    team2_score: int
    winner_id: str
    loser_id: str


def synthetic(n, size, seeds=(), seed=1):
    ids = [f'fictional:pure:team{i}' for i in range(1, n + 1)]
    slots = plan_slots(ids, seeds, random.Random(seed), size)
    bracket = Bracket(slots)
    dates = tuple(f'2027-07-{10 + 2 * r:02d}' for r in range(bracket.rounds))
    games = tuple(trial.GamePlan(g.sequence, g.round_no, g.position, f'S:r{g.round_no}:g{g.position + 1}',
                                 dates[g.round_no - 1], 1000 + g.sequence) for g in bracket.games)
    plan = trial.BracketPlan(trial.VERSION, 'fictional:pure', 'S', seed, slots, games)
    request = SimpleNamespace(entries=SimpleNamespace(teams=tuple(SimpleNamespace(entry_team_id=t) for t in ids)),
        draw=SimpleNamespace(participant_slots=n, bracket_size=size, bye_count=size - n),
        schedule=SimpleNamespace(round_dates=dates), seeds=SimpleNamespace(seeds=tuple(seeds)))
    return ids, bracket, plan, request


def play_fake(bracket, plan, results, rng):
    game = plan.games[len(results)]
    a, b = bracket.pair(game.sequence, results)
    x, y = rng.sample(range(12), 2)
    return Fake(2027, plan.scope, game.match_id, game.seed, a, b, x, y, *((a, b) if x > y else (b, a)))


class GenericBracketStructureTests(unittest.TestCase):
    """Pure graph/oracle checks for 3..32 entries; no DB or match driver."""

    def test_sizes_four_to_thirty_two_byes_seeds_rounds_and_independent_oracle(self):
        self.assertEqual((1, 8, 4, 5, 2, 7, 3, 6), seed_positions(8))
        rng = random.Random(117)
        checked = []
        for n in range(3, 33):
            size = max(4, 1 << (n - 1).bit_length())
            seeds = tuple((f'fictional:pure:team{i}', i) for i in range(1, min(n // 2, 4) + 1))
            ids, bracket, plan, request = synthetic(n, size, seeds, seed=n)
            self.assertEqual(n - 1, len(bracket.games))
            self.assertEqual(size - n, len(bracket.byes))
            self.assertEqual({t for t, k in seeds if k <= size - n}, set(bracket.byes) & {t for t, _ in seeds})
            results = []
            ledger, ranks = progression(plan, request, ())
            self.assertEqual(sorted((0, 1, 'BYE', t) for t in bracket.byes), ledger)
            self.assertFalse(ranks)
            while len(results) < len(plan.games):
                results.append(play_fake(bracket, plan, results, rng))
                ledger, ranks = progression(plan, request, tuple(results))
                if len(results) < len(plan.games):
                    self.assertFalse(ranks)
            self.assertEqual([(r, t) for r, t, _, _ in ranks], bracket.ranks(results))
            self.assertEqual(results[-1].winner_id, ranks[0][1])
            self.assertEqual(n, len(ranks))
            self.assertEqual(n - 1, sum(r[3] for r in ranks))
            self.assertEqual(n - 1, sum(r[2] for r in ranks))
            checked.append(n)
        self.assertEqual(list(range(3, 33)), checked)
        _, bracket, plan, _ = synthetic(8, 8, (('fictional:pure:team1', 1), ('fictional:pure:team2', 2)))
        self.assertEqual([(1, 1), (2, 1), (3, 1), (4, 1), (5, 2), (6, 2), (7, 3)],
                         [(g.sequence, g.round_no) for g in bracket.games])
        self.assertEqual(('fictional:pure:team1', 'fictional:pure:team2'), (bracket.slots[0], bracket.slots[4]))

    def test_three_team_layout_matches_v1_and_invalid_brackets_rejected(self):
        ids = ['a', 'b', 'c']
        slots = plan_slots(ids, (('a', 1),), random.Random(1), 4)
        self.assertEqual(('a', None), slots[:2])
        self.assertEqual({'b', 'c'}, set(slots[2:]))
        bracket = Bracket(slots)
        self.assertEqual(('a',), bracket.byes)
        self.assertEqual(2, len(bracket.games))
        for args in ((ids, (), 8), (ids, (), 3), (['a'] * 4, (), 4), (ids, (('z', 1),), 4),
                     (ids, (('a', 1), ('b', 1)), 4), (list('abcdefghi'), (), 64), (list('ab'), (), 4)):
            with self.assertRaises(ValueError):
                plan_slots(*args[:2], random.Random(1), args[2])
        for slots in ((None, None, 'a', 'b'), ('a', 'a', 'b', 'c'), ('a', None, 'b', None), ('a', 'b', 'c')):
            with self.assertRaises(ValueError):
                Bracket(slots)

    def test_oracle_rejects_loser_advancement_tie_wrong_seed_order_and_declared_winner(self):
        rng = random.Random(5)
        _, bracket, plan, request = synthetic(8, 8, (('fictional:pure:team1', 1), ('fictional:pure:team2', 2)))
        results = []
        for _ in range(4):
            results.append(play_fake(bracket, plan, results, rng))
        semi = plan.games[4]
        a, b = bracket.pair(5, results)
        loser = results[0].loser_id
        good = Fake(2027, 'S', semi.match_id, semi.seed, a, b, 3, 1, a, b)
        progression(plan, request, tuple(results) + (good,))
        for bad in (replace(good, team1_id=loser, winner_id=loser), replace(good, team2_score=3),
                    replace(good, run_seed=1), replace(good, match_id='S:r1:g1'), replace(good, winner_id=b, loser_id=a),
                    replace(good, year=2026), replace(good, competition_id='other')):
            with self.assertRaises(ValueError):
                progression(plan, request, tuple(results) + (bad,))
        with self.assertRaises(ValueError):
            progression(plan, request, (results[1], results[0]))
        swapped = replace(plan, slots=(plan.slots[4],) + plan.slots[1:4] + (plan.slots[0],) + plan.slots[5:])
        progression(swapped, request, ())
        crowded = replace(plan, slots=(plan.slots[0], plan.slots[4]) + plan.slots[2:4] + (plan.slots[1],) + plan.slots[5:])
        with self.assertRaises(ValueError):
            progression(crowded, request, ())
        with self.assertRaises(ValueError):
            progression(replace(plan, games=plan.games[:6]), request, ())
        with self.assertRaises(ValueError):
            progression(plan, SimpleNamespace(**{**vars(request), 'schedule': SimpleNamespace(round_dates=('2027-07-10', '2027-07-12'))}), ())


class FictionalBracketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        began, cpu = perf_counter(), process_time()
        cls.owners = [tempfile.TemporaryDirectory(prefix='stage117-source-') for _ in range(4)]
        for owner in cls.owners:
            cls.addClassCleanup(owner.cleanup)
        cls.source = annual.SelfCreated2026(cls.owners[0], opt_in=True)
        cls.addClassCleanup(lambda: cls.source.close())
        for _ in range(31):
            cls.source.store.play_next()
        cls.lab = annual.AnnualRosterLab(cls.source, cls.owners[1], opt_in=True)
        cls.addClassCleanup(lambda: cls.lab.close())
        assert cls.lab.advance()['accepted']
        cls.practice = practice.PracticeStore(cls.lab, cls.owners[2], opt_in=True)
        cls.addClassCleanup(lambda: cls.practice.close())
        cls.practice.play()
        cls.old = v1.FictionalTournamentStore(cls.lab, cls.owners[3], v1_scenario(cls.lab), fictional_opt_in=True)
        cls.addClassCleanup(lambda: cls.old.close())
        cls.old.play_next()
        cls.old.play_next()
        cls.request = scenario(cls.lab)
        cls.authority = practice.saved_authority(cls.lab)
        cls.pins = cls.bytes()
        cls.catalog = _compatibility(ROOT)
        cls.master = {str(p.relative_to(ROOT)): pin(p) for p in (ROOT / 'data').rglob('*') if p.is_file()}
        MEASUREMENTS['fixture'] = dict(seconds=round(perf_counter() - began, 3),
            cpu_seconds=round(process_time() - cpu, 3), saved2026_matches=31,
            saved2027_schools=33, active_players=660, permanent_ids=924, saved2027_practice_matches=1,
            stage116_v1_matches=2, source_database_sha256=cls.pins[0]['database'], annual_database_sha256=cls.pins[1],
            practice_database_sha256=cls.pins[2], stage116_v1_database_sha256=cls.pins[3])

    @classmethod
    def bytes(cls):
        return cls.source._evidence(), pin(cls.lab.db_path), pin(cls.practice.db_path), pin(cls.old.db_path)

    def setUp(self):
        self.owner = tempfile.TemporaryDirectory(prefix='stage117-bracket-')
        self.addCleanup(self.owner.cleanup)
        self.store = trial.FictionalBracketStore(self.lab, self.owner, self.request, fictional_opt_in=True)
        self.addCleanup(lambda: self.store.close())
        self._began = perf_counter()

    def tearDown(self):
        self.assertEqual(self.pins, self.bytes())

    def release(self):
        caps = dict(source=self.source.capability, annual=self.lab.capability, practice=self.practice.capability,
                    v1=self.old.capability, bracket=self.store.capability)
        self.store.close(); self.old.close(); self.practice.close(); self.lab.close(); self.source.close()
        return caps

    def reopen(self, caps, *, bracket=True):
        cls = type(self)
        cls.source = annual.SelfCreated2026.resume(caps['source'])
        cls.lab = annual.AnnualRosterLab.resume(caps['annual'], cls.source)
        cls.practice = practice.PracticeStore.resume(caps['practice'], cls.lab)
        cls.old = v1.FictionalTournamentStore.resume(caps['v1'], cls.lab, fictional_opt_in=True)
        if bracket:
            self.store = trial.FictionalBracketStore.resume(caps['bracket'], self.lab, fictional_opt_in=True)

    def test_real_seven_games_sql_full_a_identity_and_four_history_streams(self):
        began, cpu = perf_counter(), process_time()
        with patch.object(self.lab, 'browse', side_effect=AssertionError('direct saved SQL required')):
            first = self.store.next_input()
        with closing(sqlite3.connect(self.lab.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            sql_people = {p['player_id']: p for raw, in con.execute('SELECT payload_json FROM career_school_rosters WHERE year=2027')
                          for p in json.loads(raw)['players']}
        old = {p.player_id: p for r in self.authority[0].rosters for p in r.players}
        played, per_game = [], []
        for _ in range(7):
            t = perf_counter()
            played.append(self.store.play_next())
            per_game.append(round(perf_counter() - t, 3))
        view = self.store.snapshot(practice_store=self.practice, v1_store=self.old)
        run_seconds, run_cpu = perf_counter() - began, process_time() - cpu
        self.assertEqual(tuple(played), view.results)
        self.assertEqual(160, sum(len(t.players) for t in view.teams))
        self.assertEqual(160, len({p.player_id for t in view.teams for p in t.players}))
        self.assertEqual(9, len({p.origin_school_id for t in view.teams for p in t.players}))
        for team, entry, group in zip(view.teams, self.request.entries.teams, GROUPS):
            self.assertEqual(entry.player_ids, tuple(p.player_id for p in team.players))
            self.assertEqual(group, tuple(sid for sid, _ in entry.programs))
            self.assertEqual({'P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'}, {pos for _, pos, _ in team.lineup})
            self.assertTrue(team.pitching_order)
            self.assertEqual({sid: 20 // len(group) for sid in group},
                             {sid: sum(p.origin_school_id == sid for p in team.players) for sid in group})
            for p in team.players:
                saved = sql_people[p.player_id]
                self.assertEqual(saved['school_id'], p.origin_school_id)
                self.assertEqual((2027, saved['academic_year']), (p.snapshot.reference_year, p.snapshot.academic_year))
        prepared = self.store._prepare()
        measured, rounds = [], {}
        for i, game in enumerate(view.results):
            match = trial._input(prepared, view.results[:i])
            if i == 0:
                self.assertEqual(trial._sha(first.to_dict()), trial._sha(match.to_dict()))
            oracle = event_oracle(game, match)
            self.assertEqual(game, _run(match, match.match_seed))
            self.assertEqual(len(game.events), sum(r.plate_appearances for r in game.batter_stats))
            self.assertEqual(game.team1_score + game.team2_score, sum(r.runs for r in game.batter_stats))
            self.assertEqual(oracle['runs'], sum(r.runs_allowed for r in game.pitcher_stats))
            self.assertEqual(oracle['pitching_outs'], sum(r.outs_recorded for r in game.pitcher_stats))
            self.assertTrue(all(r.player_id in sql_people for r in (*game.batter_stats, *game.pitcher_stats)))
            self.assertEqual(trial._sha([r.to_dict() for r in view.results[:i]]), match.previous_results_sha256)
            rounds.setdefault(match.round_no, []).append(game)
            measured.append(dict(sequence=i + 1, round_no=match.round_no, match_id=game.match_id, year=game.year,
                record_kind=trial.KIND, namespace=view.plan.namespace, team1_id=game.team1_id, team2_id=game.team2_id,
                winner_id=game.winner_id, day=match.day, seed=match.match_seed,
                score=[game.team1_score, game.team2_score], innings=game.last_inning, events=len(game.events),
                inning_scores=[asdict(r) for r in game.inning_scores], batter_rows=len(game.batter_stats),
                pitcher_rows=len(game.pitcher_stats), batting=[asdict(r) for r in game.batter_stats],
                pitching=[asdict(r) for r in game.pitcher_stats],
                oracle=oracle, result_sha256=trial._sha(game.to_dict()), play_seconds=per_game[i]))
        self.assertEqual({1: 4, 2: 2, 3: 1}, {k: len(v) for k, v in rounds.items()})
        self.assertEqual(self.request.schedule.round_dates, tuple(sorted({g.day for g in view.plan.games})))
        # Only actual winners advance; every round's participants are the previous round's winners.
        for r in (2, 3):
            self.assertEqual(sorted(g.winner_id for g in rounds[r - 1]),
                             sorted(t for g in rounds[r] for t in (g.team1_id, g.team2_id)))
        self.assertTrue(view.complete)
        self.assertEqual(rounds[3][0].winner_id, view.fictional_scenario_champion)
        self.assertEqual([1, 2, 3, 3, 5, 5, 5, 5], [r[0] for r in view.ranks])
        self.assertEqual(7, sum(view.team(t.team_id)['wins'] for t in view.teams))
        self.assertEqual(7, sum(view.team(t.team_id)['losses'] for t in view.teams))
        self.assertEqual(3, view.team(view.fictional_scenario_champion)['wins'])
        self.assertIsNone(view.next_pair())
        self.assertEqual((), view.bracket.byes)
        seeds = dict(self.request.seeds.seeds)
        self.assertEqual({0, 4}, {view.plan.slots.index(t) for t in seeds})
        joint = view.teams[7]
        joint_record = view.team(joint.team_id)
        self.assertTrue(joint_record['joint'])
        for sid, _ in self.request.entries.teams[7].programs:
            school = view.school(sid)
            self.assertEqual((0, 0), (school['standalone_wins'], school['standalone_losses']))
            self.assertEqual((0, 0), (school['v1_standalone_wins'], school['v1_standalone_losses']))
            self.assertEqual(joint.team_id, school['fictional_team_records'][0]['entry_team_id'])
            self.assertIsNone(school['official_2027_outcomes'])
            self.assertIsNone(school['official_2027_ranking'])
            self.assertEqual(4, len(school['history']))
        for entry in self.request.entries.teams[:7]:
            sid = entry.programs[0][0]
            record = view.team(entry.entry_team_id)
            school = view.school(sid)
            self.assertEqual((record['wins'], record['losses']), (school['standalone_wins'], school['standalone_losses']))
        # Each entry's actual batters include returning 2026 players and 2027 newcomers.
        for team in view.teams:
            appeared = {r.player_id for g in view.results for r in g.batter_stats
                        if r.team_id == team.team_id and r.plate_appearances}
            self.assertTrue(appeared & old.keys())
            self.assertTrue(appeared - old.keys())
            self.assertEqual({p.origin_school_id for p in team.players}, {sql_people[p]['school_id'] for p in appeared})
        streams = [(2026, v1.KIND), (2027, practice.KIND), (2027, v1.KIND), (2027, trial.KIND)]
        returning = [p for p in view._people if p in old and view.player(p)['history'][0]['appearances']
                     and view.player(p)['history'][3]['appearances']]
        self.assertTrue(returning)
        history = view.player(returning[0])['history']
        self.assertEqual(streams, [(h['year'], h['record_kind']) for h in history])
        self.assertEqual(4, len({h['namespace'] for h in history}))
        self.assertEqual(history[0]['profile']['academic_year'] + 1, history[3]['profile']['academic_year'])
        for pid in returning[:3]:
            record = view.player(pid)
            rows = [r for g in view.results for r in g.batter_stats if r.player_id == pid]
            self.assertEqual(sum(r.plate_appearances for r in rows), record['scenario_batting_totals']['plate_appearances'])
            self.assertEqual(sum(r.hits for r in rows), record['scenario_batting_totals']['hits'])
        pitcher = view.results[-1].pitcher_stats[0].player_id
        rows = [r for g in view.results for r in g.pitcher_stats if r.player_id == pitcher]
        self.assertEqual(sum(r.outs_recorded for r in rows), view.player(pitcher)['scenario_pitching_totals']['outs_recorded'])
        joint_player = view.player(joint.players[0].player_id)
        self.assertIn(joint_player['origin_school_id'], {'SCH000202', 'SCH000220'})
        self.assertTrue(all(a['entry_team_id'] == joint.team_id for a in joint_player['history'][3]['appearances']))
        newcomer = next(pid for pid in sql_people if pid not in old)
        graduate = next(pid for pid in old if pid not in sql_people)
        self.assertEqual('not_yet_enrolled', view.player(newcomer)['history'][0]['state'])
        self.assertEqual(['graduated'] * 3, [h['state'] for h in view.player(graduate)['history'][1:]])
        self.assertFalse(any(h['appearances'] for h in view.player(graduate)['history'][1:]))
        self.assertFalse(view.official_year_verified)
        self.assertFalse(view.product_season_start_authorized)
        self.assertEqual(self.catalog, _compatibility(ROOT))
        self.assertEqual(338, len(self.catalog))
        self.assertEqual(106, sum(p.endswith('.csv') for p in self.master))
        self.assertEqual(self.master, {str(p.relative_to(ROOT)): pin(p) for p in (ROOT / 'data').rglob('*') if p.is_file()})
        with closing(sqlite3.connect(self.store.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            counts = {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in trial.TABLES}
        self.assertEqual(dict(bracket_contract=1, bracket_matches=7, bracket_checkpoints=7, bracket_ranks=8,
                              bracket_acceptance=1, bracket_advancement=7), {k: v for k, v in counts.items() if k != 'bracket_players'})
        audit = perf_counter()
        self.store.snapshot()
        audit_seconds = perf_counter() - audit
        audit = perf_counter()
        for i, game in enumerate(view.results):
            trial._validate(game, trial._input(prepared, view.results[:i]))
        replay_seconds = perf_counter() - audit
        MEASUREMENTS['tournament'] = dict(seconds=round(run_seconds, 3), cpu_seconds=round(run_cpu, 3),
            play_next_seconds=per_game, scenario_seed=trial.SEED,
            namespace=view.plan.namespace, scope=view.plan.scope, slots=view.plan.slots, games=measured,
            champion=view.fictional_scenario_champion, ranks=view.ranks,
            joint_team={k: v for k, v in joint_record.items() if k != 'matches'},
            joint_school_standalone_records=[dict(school_id=sid,
                wins=view.school(sid)['standalone_wins'], losses=view.school(sid)['standalone_losses'])
                for sid, _ in self.request.entries.teams[7].programs],
            returning_two_year_appearances=len(returning), bytes=self.store.db_path.stat().st_size,
            table_rows=counts, full_reaudit_seconds=round(audit_seconds, 3),
            all7_rerun_and_oracle_seconds=round(replay_seconds, 3), peak_rss_kib=peak_rss_kib(),
            source_bytes_unchanged=self.pins == self.bytes(), first_input_sha256=trial._sha(first.to_dict()))

    def test_actual_request_gates_opt_in_labels_qualification_and_composition_fail_closed(self):
        for flag in (False, 1, 'true', None):
            owner = tempfile.TemporaryDirectory(prefix='stage117-unused-')
            with owner as temp:
                with self.assertRaises(ValueError):
                    trial.FictionalBracketStore(self.lab, owner, self.request, fictional_opt_in=flag)
                self.assertFalse(list(Path(temp).iterdir()))
        for name in trial.GATES:
            with self.subTest(gate=name), self.assertRaises(ValueError):
                trial._prepare(self.lab, replace(self.request, **{name: None}), trial.SEED, True)
        for source in ('official verified source', 'https://official.example/2027',
                       'self-created declaration/official', 'self-created declaration/公式'):
            bad = replace(self.request, draw=replace(self.request.draw,
                evidence=replace(self.request.draw.evidence, source=source)))
            with self.assertRaises(ValueError):
                trial._prepare(self.lab, bad, trial.SEED, True)
        teams = self.request.entries.teams
        graduated = next(p.player_id for r in self.authority[0].rosters for p in r.players if p.academic_year == 3)
        prior = replace(self.request, qualification=replace(self.request.qualification,
            decisions=tuple(replace(d, basis='saved_prior_year') for d in self.request.qualification.decisions),
            prior_year_receipt_sha256=dict(gates.dry_run(self.lab, self.request, fictional_opt_in=True)
                                           .evidence_digests)['prior_sealed_year']))
        self.assertTrue(gates.dry_run(self.lab, prior, fictional_opt_in=True).fictional_scenario_ready)
        extra = next(r for r in self.authority[1] if r.school_id == 'SCH000202').players[10].player_id
        lopsided = teams[7].player_ids[:10] + (extra,) + teams[7].player_ids[10:19]  # 11+9
        bad_requests = (
            prior,  # a saved 2026 history is not a 2027 qualification here
            replace(self.request, year=2026), replace(self.request, namespace='official:2027'),
            replace(self.request, entries=replace(self.request.entries,
                teams=(replace(teams[0], player_ids=(graduated,) + teams[0].player_ids[1:]),) + teams[1:])),
            replace(self.request, entries=replace(self.request.entries,
                teams=(replace(teams[0], player_ids=(teams[1].player_ids[0],) + teams[0].player_ids[1:]),) + teams[1:])),
            replace(self.request, entries=replace(self.request.entries, teams=teams[:7] + (replace(teams[7], player_ids=lopsided),))),
            replace(self.request, entries=replace(self.request.entries, teams=teams[:7] + (replace(teams[7], entry_team_id=teams[0].entry_team_id),))),
            replace(self.request, draw=replace(self.request.draw, bracket_size=16, bye_count=8)),
            replace(self.request, draw=replace(self.request.draw, participant_slots=32)),
            replace(self.request, schedule=replace(self.request.schedule, round_dates=('2027-07-10', '2027-07-12'))),
            replace(self.request, schedule=replace(self.request.schedule, round_dates=('2026-07-10', '2026-07-12', '2026-07-14'))),
            replace(self.request, joints=replace(self.request.joints, teams=())),
            replace(self.request, seeds=replace(self.request.seeds, seeds=((teams[0].entry_team_id, 9),))),
        )
        for bad in bad_requests:
            with self.assertRaises(ValueError):
                trial._prepare(self.lab, bad, trial.SEED, True)
        with patch.object(gates, 'dry_run', wraps=gates.dry_run) as checked:
            self.store.next_input()
            self.assertIs(self.request, checked.call_args.args[1])
        with patch.object(gates, 'dry_run', wraps=gates.dry_run) as checked:
            self.store.play_next()
            self.assertEqual(2, checked.call_count)  # before append and in the post-commit re-audit
        from phase2_engine.saved_school_roster_source import SavedSchoolRosterSource
        for source in (object(), self.practice, self.old, SavedSchoolRosterSource.__new__(SavedSchoolRosterSource)):
            with self.assertRaises(ValueError):
                trial._prepare(source, self.request, trial.SEED, True)
        for seed in (True, -1, 2**63, '430117'):
            with self.assertRaises(ValueError):
                trial._prepare(self.lab, self.request, seed, True)
        self.store.scenario_seed += 1
        with self.assertRaises(ValueError):
            self.store.next_input()
        self.store.scenario_seed -= 1
        self.store.request = replace(self.request, namespace='fictional:other')
        with self.assertRaises(ValueError):
            self.store.next_input()
        self.store.request = self.request

    def test_v1_three_team_regression_and_real_four_team_path(self):
        # Stage116's two saved games, read independently; v1 itself is untouched.
        old_view = self.old.snapshot()
        slots = old_view.plan.slots
        self.assertEqual(slots[:2], plan_slots([t.team_id for t in old_view.teams], old_view.request.seeds.seeds,
                                               random.Random(0), 4)[:2])
        bracket = Bracket(slots)
        self.assertEqual((slots[0],), bracket.byes)
        self.assertEqual(set(slots[2:]), set(bracket.pair(1, old_view.results)))
        self.assertEqual({old_view.results[0].winner_id, slots[0]}, set(bracket.pair(2, old_view.results)))
        self.assertEqual({old_view.results[1].team1_id, old_view.results[1].team2_id},
                         set(bracket.pair(2, old_view.results)))
        self.assertEqual([(r, t) for r, t, _, _ in v1_progression(old_view.plan, old_view.request, old_view.results)[1]],
                         bracket.ranks(old_view.results))
        self.assertEqual(2, len(old_view.results))
        # A real four-team/no-BYE path through the same generic store.
        groups = (('SCH000204',), ('SCH000205',), ('SCH000206',), ('SCH000207', 'SCH000208'))
        request = scenario(self.lab, groups=groups, namespace='fictional:stage117-owned-four', size=4,
                           dates=('2027-07-20', '2027-07-22'), seeds=1)
        owner = tempfile.TemporaryDirectory(prefix='stage117-four-')
        with owner:
            four = trial.FictionalBracketStore(self.lab, owner, request, fictional_opt_in=True)
            try:
                began = perf_counter()
                for _ in range(3):
                    four.play_next()
                view = four.snapshot(v1_store=self.old)
                self.assertEqual([1, 1, 2], [g.round_no for g in view.plan.games])
                self.assertEqual([1, 2, 3, 3], [r[0] for r in view.ranks])
                self.assertEqual({view.results[0].winner_id, view.results[1].winner_id},
                                 {view.results[2].team1_id, view.results[2].team2_id})
                for sid in ('SCH000207', 'SCH000208'):
                    self.assertEqual((0, 0), (view.school(sid)['standalone_wins'], view.school(sid)['standalone_losses']))
                MEASUREMENTS['four_team_path'] = dict(seconds=round(perf_counter() - began, 3),
                    ranks=view.ranks, scores=[[g.team1_score, g.team2_score, g.last_inning] for g in view.results])
            finally:
                four.close()

    def test_input_seed_origin_date_round_and_result_tampering(self):
        match = self.store.next_input()
        game = _run(match, match.match_seed)
        for change in (dict(year=2026), dict(year=True), dict(match_seed=match.match_seed + 1),
                       dict(scenario_seed=trial.SEED + 1), dict(namespace='official:2027'), dict(competition_id='CMP000041'),
                       dict(record_kind='fictional_tournament'), dict(day='2027-07-12'), dict(contract_sha256='bad'),
                       dict(previous_results_sha256='bad'), dict(sequence=True), dict(round_no=2), dict(sequence=8),
                       dict(match_id=match.match_id.replace(':g1', ':g2'))):
            with self.assertRaises(ValueError):
                self.store.append(replace(match, **change), game)
        bad_player = replace(match.team1.players[0], origin_school_id='SCH000001')
        bad_team = replace(match.team1, players=(bad_player,) + match.team1.players[1:])
        with self.assertRaises(ValueError):
            self.store.append(replace(match, team1=bad_team), game)
        with self.assertRaises(ValueError):
            self.store.append(replace(match, team1=match.team2, team2=match.team1), game)
        alternate = _run(match, match.match_seed + 1)
        self.assertNotEqual(game.events, alternate.events)
        with self.assertRaises(ValueError):
            self.store.append(match, alternate)
        variants = (replace(game, team1_score=game.team1_score + 1),
            replace(game, inning_scores=(replace(game.inning_scores[0], runs=99),) + game.inning_scores[1:]),
            replace(game, batter_stats=(replace(game.batter_stats[0], hits=99),) + game.batter_stats[1:]),
            replace(game, pitcher_stats=(replace(game.pitcher_stats[0], earned_runs=99),) + game.pitcher_stats[1:]),
            replace(game, winner_id=game.loser_id, loser_id=game.winner_id),
            replace(game, events=(replace(game.events[0], batter_origin_school_id='unknown'),) + game.events[1:]))
        for altered in variants:
            with self.assertRaises(ValueError):
                event_oracle(altered, match)
            with self.assertRaises(ValueError):
                self.store.append(match, altered)
        self.assertFalse(self.store.snapshot().results)

    def test_winner_dependency_skip_reorder_duplicate_and_foreign_physical_source(self):
        view = self.store.snapshot()
        self.assertFalse(view.complete)
        self.assertIsNone(view.fictional_scenario_champion)
        self.assertFalse(view.ranks)
        prepared = self.store._prepare()
        m1 = self.store.next_input(); r1 = _run(m1, m1.match_seed)
        m2 = trial._input(prepared, (r1,)); r2 = _run(m2, m2.match_seed)
        m3 = trial._input(prepared, (r1, r2)); r3 = _run(m3, m3.match_seed)
        for match, result in ((m2, r2), (m3, r3)):  # skipped/reordered saves
            with self.assertRaises(ValueError):
                self.store.append(match, result)
        self.assertTrue(self.store.append(m1, r1))
        with self.assertRaises(ValueError):
            self.store.append(m3, r3)
        with self.assertRaises(ValueError):  # same ID, different content
            self.store.append(m1, _run(m1, m1.match_seed + 1))
        before = pin(self.store.db_path)
        self.assertFalse(self.store.append(m1, r1))
        self.assertEqual(before, pin(self.store.db_path))
        self.assertTrue(self.store.append(m2, r2))
        self.assertTrue(self.store.append(m3, r3))
        self.store.play_next()
        mid = self.store.snapshot()
        self.assertEqual(4, len(mid.results))
        self.assertFalse(mid.ranks)
        self.assertIsNone(mid.fictional_scenario_champion)
        semi = self.store.next_input()
        self.assertEqual((mid.results[0].winner_id, mid.results[1].winner_id), (semi.team1.team_id, semi.team2.team_id))
        losers = {r.loser_id for r in mid.results}
        self.assertFalse(losers & {semi.team1.team_id, semi.team2.team_id})
        teams = {t.team_id: t for t in mid.teams}
        bad = replace(semi, team1=teams[mid.results[0].loser_id])
        with self.assertRaises(ValueError):
            self.store.append(bad, _run(bad, bad.match_seed))
        with self.assertRaises(ValueError):
            progression(mid.plan, self.request, mid.results[:3] + (replace(mid.results[3], winner_id=mid.results[3].loser_id,
                        loser_id=mid.results[3].winner_id),))
        # Same request and seed on a different physical saved source.
        owner = tempfile.TemporaryDirectory(prefix='stage117-other-'); self.addCleanup(owner.cleanup)
        other = annual.AnnualRosterLab(self.source, owner, opt_in=True)
        try:
            other.advance()
            other_owner = tempfile.TemporaryDirectory(prefix='stage117-other-bracket-'); self.addCleanup(other_owner.cleanup)
            foreign = trial.FictionalBracketStore(other, other_owner, self.request, fictional_opt_in=True)
            try:
                f1 = foreign.next_input()
                self.assertNotEqual(m1.contract_sha256, f1.contract_sha256)
                with self.assertRaises(ValueError):
                    self.store.append(f1, _run(f1, f1.match_seed))
            finally:
                foreign.close()
            self.store.lab = other
            with self.assertRaises(ValueError):
                self.store.snapshot()
        finally:
            self.store.lab = self.lab
            other.close()
        with self.assertRaises(ValueError): self.store.snapshot().team('unknown')
        with self.assertRaises(ValueError): self.store.snapshot().school('unknown')
        with self.assertRaises(ValueError): self.store.snapshot().player('unknown')
        with self.assertRaises(ValueError): self.store.snapshot(practice_store=object())
        with self.assertRaises(ValueError): self.store.snapshot(v1_store=self.practice)

    def test_atomic_rollback_lost_ack_idempotence_round_boundaries_and_append_only(self):
        for i in range(1, 8):
            if i not in (1, 4, 7):
                self.store.play_next()
                continue
            match = self.store.next_input(); result = _run(match, match.match_seed)
            before = pin(self.store.db_path)

            def fail(at):
                if at == 'before_commit': raise RuntimeError('rollback fixture')
            with self.assertRaises(RuntimeError): self.store.append(match, result, fault=fail)
            self.assertEqual(before, pin(self.store.db_path))
            rolled = self.store.snapshot()
            self.assertEqual(i - 1, len(rolled.results))
            self.assertFalse(rolled.ranks)
            self.assertIsNone(rolled.fictional_scenario_champion)

            def lost(at):
                if at == 'after_commit': raise RuntimeError('lost ACK fixture')
            with self.assertRaises(RuntimeError): self.store.append(match, result, fault=lost)
            before = pin(self.store.db_path)
            self.assertFalse(self.store.append(match, result))
            self.assertEqual(before, pin(self.store.db_path))
            with self.assertRaises(ValueError): self.store.append(match, replace(result, run_seed=result.run_seed + 1))
        done = self.store.snapshot()
        self.assertTrue(done.complete)
        with self.assertRaises(ValueError): self.store.play_next()
        with closing(sqlite3.connect(self.store.db_path)) as con:
            for table in trial.TABLES:
                key = con.execute(f'PRAGMA table_info({table})').fetchone()[1]
                for statement in (f'UPDATE {table} SET {key}={key}', f'DELETE FROM {table}'):
                    with self.assertRaises(sqlite3.IntegrityError): con.execute(statement)
            con.rollback()
        self.assertEqual(7, len(self.store.snapshot().results))

    def test_process_hard_exit_after_games_1_4_6_7_resume_from_actual_winners(self):
        began = perf_counter()
        caps = self.release()
        try:
            with tempfile.TemporaryDirectory(prefix='stage117-private-') as temp:
                private = Path(temp)
                states = []
                for n in (1, 4, 6, 7):
                    states.append(worker(caps, private, action=f'crash_after:{n}'))
                final = worker(caps, private)
                observed = [s['matches'] for s in states] + [final['matches']]
                self.assertEqual([0, 1, 4, 6, 7], observed)
                for state in states:
                    self.assertFalse(state['complete'])
                    self.assertIsNone(state['champion'])
                    self.assertFalse(state['ranks'])
                after4, after6 = states[2], states[3]
                self.assertEqual([after4['winners'][0], after4['winners'][1]], after4['next_pair'])
                self.assertEqual([after6['winners'][4], after6['winners'][5]], after6['next_pair'])
                self.assertTrue(final['complete'])
                self.assertIsNotNone(final['champion'])
                self.assertEqual(8, len(final['ranks']))
                self.assertIsNone(final['next_pair'])
                for state in states[1:]:
                    self.assertEqual(state['result_sha256'], final['result_sha256'][:state['matches']])
                self.assertEqual(final['winners'][6], final['champion'])
                pids = {s['pid'] for s in states} | {final['pid'], os.getpid()}
                self.assertEqual(6, len(pids))
                self.assertEqual((31, 1, 2), (final['source_matches'], final['practice_matches'], final['v1_matches']))
                self.assertTrue(final['readonly_bytes_unchanged'])
                MEASUREMENTS['restart'] = dict(seconds=round(perf_counter() - began, 3),
                    hard_exit_after_commit_of_games=[1, 4, 6, 7], child_states=states, resumed_complete=final)
        finally:
            self.reopen(caps)
        view = self.store.snapshot()
        self.assertEqual(final['result_sha256'], [trial._sha(r.to_dict()) for r in view.results])
        self.assertEqual(json.loads(json.dumps(view.ranks)), final['ranks'])

    def test_hot_journal_after_real_precommit_hard_exit_refused_without_recovery(self):
        caps = self.release()
        try:
            with tempfile.TemporaryDirectory(prefix='stage117-private-') as temp:
                worker(caps, Path(temp), action='crash_before_commit')
        finally:
            self.reopen(caps, bracket=False)
        journal = Path(str(self.store.db_path) + '-journal')
        self.assertGreater(journal.stat().st_size, 512)
        before = {p.name: pin(p) for p in self.store.db_path.parent.iterdir()}
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no automatic hot journal recovery')):
            with self.assertRaises(ValueError):
                trial.FictionalBracketStore.resume(caps['bracket'], self.lab, fictional_opt_in=True)
        self.assertEqual(before, {p.name: pin(p) for p in self.store.db_path.parent.iterdir()})

    def test_sidecars_hardlinks_junction_file_root_lease_replacement_and_lease_exclusion(self):
        cap = self.store.capability
        for suffix in ('-journal', '-wal', '-shm'):
            side = Path(str(self.store.db_path) + suffix); side.write_bytes(b'foreign sidecar')
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('guard precedes all SQL')):
                    with self.assertRaises(ValueError): self.store.snapshot()
            finally: side.unlink()
        with self.assertRaises(ValueError): trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
        with self.assertRaises(ValueError): trial.FictionalBracketStore.resume(self.old.capability, self.lab, fictional_opt_in=True)
        with self.assertRaises(ValueError): v1.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)
        self.store.close()
        with self.assertRaises(ValueError): self.store.snapshot()
        with tempfile.TemporaryDirectory(prefix='stage117-alias-') as temp:
            outside = Path(temp)
            alias = outside / 'junction'
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.store.db_path.parent)], check=True, capture_output=True)
            else: alias.symlink_to(self.store.db_path.parent, target_is_directory=True)
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no junction SQL')):
                    with self.assertRaises(ValueError):
                        trial.FictionalBracketStore.resume(replace(cap, root=str(alias)), self.lab, fictional_opt_in=True)
            finally:
                if os.name == 'nt': alias.rmdir()
                else: alias.unlink()
            link = outside / 'hardlink'; os.link(self.store.db_path, link)
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no hardlink SQL')):
                    with self.assertRaises(ValueError): trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
            finally: link.unlink()
            lease = self.store.db_path.parent / trial.LEASE
            for path in (self.store.db_path, lease):
                retained = outside / path.name
                path.rename(retained); path.write_bytes(retained.read_bytes())
                try:
                    with patch.object(sqlite3, 'connect', side_effect=AssertionError('no replacement SQL')):
                        with self.assertRaises(ValueError): trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
                finally:
                    path.unlink(); retained.rename(path)
            root = self.store.db_path.parent
            moved = root.with_name(root.name + '-retained')
            root.rename(moved); root.mkdir()
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no replaced root SQL')):
                    with self.assertRaises(ValueError): trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
            finally:
                root.rmdir(); moved.rename(root)
        self.store = trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
        with self.assertRaises(Exception):
            trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)  # exclusive lease

    def test_native_connections_close_rename_reopen_readonly_sha_and_sql_lock(self):
        with retained_handles() as handles:
            self.store.play_next(); self.store.snapshot()
            assert_closed(self, handles)
        before = pin(self.store.db_path)
        self.store.snapshot()
        self.assertEqual(before, pin(self.store.db_path))
        with closing(sqlite3.connect(self.store.db_path)) as con:
            con.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError): self.store.snapshot()
            con.rollback()
        cap = self.store.capability; self.store.close()
        moved = self.store.db_path.with_suffix('.released')
        self.store.db_path.rename(moved); moved.rename(self.store.db_path)
        self.store = trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
        self.assertEqual(before, pin(self.store.db_path))

    def test_schema_checkpoint_rank_acceptance_order_and_saved_source_tampering_rejected_readonly(self):
        for _ in range(7):
            self.store.play_next()
        original = self.store.db_path.read_bytes()
        cases = (
            ('CREATE TABLE foreign_table(x)',),
            ('INSERT INTO bracket_players SELECT "unknown-player", origin_school_id, entry_team_id, year, '
             'record_kind, namespace, match_id FROM bracket_players LIMIT 1',),
            ('DROP TRIGGER bracket_players_delete', 'DELETE FROM bracket_players WHERE rowid IN (SELECT rowid FROM bracket_players LIMIT 1)'),
            ('DROP TRIGGER bracket_matches_update', 'UPDATE bracket_matches SET result_sha256="tampered" WHERE sequence=7'),
            ('DROP TRIGGER bracket_matches_update', 'UPDATE bracket_matches SET sequence=sequence+100'),
            ('DROP TRIGGER bracket_checkpoints_update', 'UPDATE bracket_checkpoints SET source_receipt_sha256="copied" WHERE sequence=4'),
            ('DROP TRIGGER bracket_ranks_update', 'UPDATE bracket_ranks SET rank=1'),
            ('DROP TRIGGER bracket_ranks_delete', 'DELETE FROM bracket_ranks'),
            ('DROP TRIGGER bracket_acceptance_delete', 'DELETE FROM bracket_acceptance'),
            ('DROP TRIGGER bracket_advancement_update', 'UPDATE bracket_advancement SET team_id="x" WHERE step=7'),
            ('DROP TRIGGER bracket_contract_update', 'UPDATE bracket_contract SET payload=payload||" "'),
        )
        for statements in cases:
            with closing(sqlite3.connect(self.store.db_path)) as con, con:
                for statement in statements: con.execute(statement)
                if statements[0].startswith('DROP TRIGGER '):
                    name = statements[0].split()[-1]
                    con.execute(next(sql for sql in trial.DDL if sql.startswith('CREATE TRIGGER ' + name + ' ')))
            before = pin(self.store.db_path)
            with self.assertRaises(ValueError): self.store.snapshot()
            self.assertEqual(before, pin(self.store.db_path))
            self.store.db_path.write_bytes(original)  # newly-created fault target only
        self.store.snapshot()
        raw = self.lab.db_path.read_bytes()
        try:
            with closing(sqlite3.connect(self.lab.db_path)) as con, con:
                con.execute('DROP TRIGGER annual_career_school_rosters_no_update')
                con.execute('UPDATE career_school_rosters SET payload_json="{}" WHERE year=2027')
            before = pin(self.lab.db_path)
            with self.assertRaises(ValueError): self.store.snapshot()
            self.assertEqual(before, pin(self.lab.db_path))
        finally: self.lab.db_path.write_bytes(raw)  # self-created destructive fixture only

    def test_independent_scenario_seed_changes_draw_events_and_contract(self):
        owner = tempfile.TemporaryDirectory(prefix='stage117-alternate-')
        with owner:
            other = trial.FictionalBracketStore(self.lab, owner, self.request,
                scenario_seed=trial.SEED + 1, fictional_opt_in=True)
            try:
                a, b = self.store.next_input(), other.next_input()
                self.assertNotEqual(a.contract_sha256, b.contract_sha256)
                self.assertNotEqual(a.match_seed, b.match_seed)
                self.assertNotEqual(self.store.snapshot().plan.slots, other.snapshot().plan.slots)
                self.assertEqual(self.store.snapshot().plan.slots[0], other.snapshot().plan.slots[0])  # seed1 fixed
                self.assertNotEqual(_run(a, a.match_seed).events, _run(b, b.match_seed).events)
                with self.assertRaises(ValueError): self.store.append(b, _run(b, b.match_seed))
            finally:
                other.close()
        # The same seed on the same physical source reproduces the exact contract.
        owner = tempfile.TemporaryDirectory(prefix='stage117-twin-')
        with owner:
            twin = trial.FictionalBracketStore(self.lab, owner, self.request, fictional_opt_in=True)
            try:
                self.assertEqual(self.store.capability.contract_json, twin.capability.contract_json)
                a, b = self.store.next_input(), twin.next_input()
                self.assertEqual(trial._sha(_run(a, a.match_seed).to_dict()), trial._sha(_run(b, b.match_seed).to_dict()))
            finally:
                twin.close()

    @classmethod
    def tearDownClass(cls):
        MEASUREMENTS['peak_rss_kib'] = peak_rss_kib()
