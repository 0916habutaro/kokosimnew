"""Stage118 real-scale fictional 2027 bracket: 16 teams/15 games, then 32 teams/31 games.

Not discovered by `unittest discover` (no `test_` prefix): the dedicated
Stage118 workflow runs it on Linux and native Windows in parallel with the
existing jobs; `test_stage43g118_contract` fails if that wiring disappears.

One shared fixture (saved 2026 31 games -> accepted 2027 33 schools -> practice
1 -> Stage116 v1 2 -> Stage117 eight 7) is built once. Both real tournaments are
played only by child processes that hard-exit after chosen commits; the parent
then re-verifies every saved game independently. Destructive cases run on a
fresh owned store into which the audited bytes are copied, and each such store
is re-audited in full (all games re-run plus event oracle) before use.
"""
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from time import perf_counter, process_time
import unittest
from unittest.mock import patch

from phase2_engine import competition_evidence_gates as gates
from phase2_engine import fictional_scenario_history as history
from phase2_engine import saved_fictional_bracket as trial
from phase2_engine import saved_fictional_tournament as v1
from phase2_engine import saved_practice_match as practice
from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine.fictional_bracket import Bracket, seed_positions
from phase2_engine.fictional_bracket_oracle import progression
from phase2_engine.manual_save_backup import _compatibility
from phase2_engine.registered_full_a_oracle import event_oracle
from phase2_engine.registered_match_driver import _run
from stage43g115_support import scenario as v1_scenario
from stage43g117_support import scenario as eight_scenario
import stage43g118_support as support

MEASUREMENTS = {}
ROOT = Path(__file__).resolve().parents[1]
STAGE117_MAIN = '2cec50ca7818201f702a2512bfdd007a010b5dc8'
CRASH32 = (1, 16, 24, 28, 30, 31)
CRASH16 = (1, 8, 12, 14, 15)


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_counts(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        return {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in trial.TABLES}


class Stage118ScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timing = {}
        began, cpu = perf_counter(), process_time()
        cls.owners = [tempfile.TemporaryDirectory(prefix='stage118-source-') for _ in range(7)]
        for owner in cls.owners:
            cls.addClassCleanup(owner.cleanup)
        t = perf_counter()
        cls.source = annual.SelfCreated2026(cls.owners[0], opt_in=True)
        for _ in range(31):
            cls.source.store.play_next()
        cls.timing['saved2026_31_games'] = perf_counter() - t
        t = perf_counter()
        cls.lab = annual.AnnualRosterLab(cls.source, cls.owners[1], opt_in=True)
        assert cls.lab.advance()['accepted']
        cls.timing['annual2027_accept33'] = perf_counter() - t
        t = perf_counter()
        cls.practice = practice.PracticeStore(cls.lab, cls.owners[2], opt_in=True)
        cls.practice.play()
        cls.timing['practice2027_1'] = perf_counter() - t
        t = perf_counter()
        cls.old = v1.FictionalTournamentStore(cls.lab, cls.owners[3], v1_scenario(cls.lab), fictional_opt_in=True)
        cls.old.play_next()
        cls.old.play_next()
        cls.timing['stage116_v1_2'] = perf_counter() - t
        t = perf_counter()
        cls.eight = trial.FictionalBracketStore(cls.lab, cls.owners[4], eight_scenario(cls.lab), fictional_opt_in=True)
        for _ in range(7):
            cls.eight.play_next()
        cls.timing['stage117_eight_7'] = perf_counter() - t
        cls.authority = practice.saved_authority(cls.lab)
        cls.request32, cls.request16 = support.scenario32(cls.lab), support.scenario16(cls.lab)
        t = perf_counter()
        cls.store32 = trial.FictionalBracketStore(cls.lab, cls.owners[5], cls.request32,
                                                  scenario_seed=support.SEED32, fictional_opt_in=True)
        cls.timing['create32'] = perf_counter() - t
        cls.created32_bytes = cls.store32.db_path.stat().st_size
        cls.store16 = trial.FictionalBracketStore(cls.lab, cls.owners[6], cls.request16,
                                                  scenario_seed=support.SEED16, fictional_opt_in=True)
        cls.pins = cls.bytes()
        cls.catalog = _compatibility(ROOT)
        cls.master = {str(p.relative_to(ROOT)): pin(p) for p in (ROOT / 'data').rglob('*') if p.is_file()}
        MEASUREMENTS['fixture'] = dict(seconds=round(perf_counter() - began, 3),
            cpu_seconds=round(process_time() - cpu, 3), parts={k: round(v, 3) for k, v in cls.timing.items()},
            saved2026_matches=31, saved2027_schools=33, active_players=660, permanent_ids=924,
            saved2027_practice_matches=1, stage116_v1_matches=2, stage117_eight_matches=7,
            created32_db_bytes=cls.created32_bytes, peak_rss_kib=support.peak_rss_kib())
        # Real tournaments: every game is computed by a child that may be hard-exited.
        caps = cls.release()
        try:
            with tempfile.TemporaryDirectory(prefix='stage118-private-') as temp:
                private = Path(temp)
                cls.runs = {}
                for name, crashes in (('sixteen', CRASH16), ('thirty_two', CRASH32)):
                    t = perf_counter()
                    run_caps = {k: v for k, v in caps.items() if k not in ('store32', 'store16')}
                    run_caps['bracket'] = caps['store32' if name == 'thirty_two' else 'store16']
                    states, prefix = [], {}
                    db = Path(run_caps['bracket'].root) / trial.DATABASE
                    for n in crashes:
                        states.append(support.worker(run_caps, private, action=f'crash_after:{n}'))
                        prefix[n] = db.read_bytes()
                    final = support.worker(run_caps, private)
                    cls.runs[name] = dict(states=states, final=final, prefix=prefix, seconds=perf_counter() - t)
        finally:
            cls.reopen(caps)
        cls.addClassCleanup(cls.close_all)

    @classmethod
    def bytes(cls):
        return (cls.source._evidence(), pin(cls.lab.db_path), pin(cls.practice.db_path), pin(cls.old.db_path),
                pin(cls.eight.db_path))

    @classmethod
    def release(cls):
        caps = dict(source=cls.source.capability, annual=cls.lab.capability, practice=cls.practice.capability,
                    v1=cls.old.capability, eight=cls.eight.capability, store32=cls.store32.capability,
                    store16=cls.store16.capability)
        for store in (cls.store16, cls.store32, cls.eight, cls.old, cls.practice, cls.lab, cls.source):
            store.close()
        return caps

    @classmethod
    def reopen(cls, caps):
        cls.source = annual.SelfCreated2026.resume(caps['source'])
        cls.lab = annual.AnnualRosterLab.resume(caps['annual'], cls.source)
        cls.practice = practice.PracticeStore.resume(caps['practice'], cls.lab)
        cls.old = v1.FictionalTournamentStore.resume(caps['v1'], cls.lab, fictional_opt_in=True)
        cls.eight = trial.FictionalBracketStore.resume(caps['eight'], cls.lab, fictional_opt_in=True)
        cls.store32 = trial.FictionalBracketStore.resume(caps['store32'], cls.lab, fictional_opt_in=True)
        cls.store16 = trial.FictionalBracketStore.resume(caps['store16'], cls.lab, fictional_opt_in=True)

    @classmethod
    def close_all(cls):
        for store in (cls.store16, cls.store32, cls.eight, cls.old, cls.practice, cls.lab, cls.source):
            store.close()

    def tearDown(self):
        self.assertEqual(self.pins, self.bytes())

    def copy_store(self, request, seed, raw):
        """Fresh owned store for destructive cases, holding audited bytes."""
        owner = tempfile.TemporaryDirectory(prefix='stage118-copy-')
        self.addCleanup(owner.cleanup)
        store = trial.FictionalBracketStore(self.lab, owner, request, scenario_seed=seed, fictional_opt_in=True)
        self.addCleanup(store.close)
        store.db_path.write_bytes(raw)  # same inode: identity guard still binds this owned file
        return store

    def check_run(self, name, crashes, games, ranks):
        run = self.runs[name]
        states, final = run['states'], run['final']
        self.assertEqual([0, *crashes[:-1]], [s['matches'] for s in states])
        self.assertEqual(games, final['matches'])
        played = [g for s in states for g in s['games_played']]
        self.assertEqual(list(range(1, games + 1)), [g['sequence'] for g in played])
        self.assertEqual(list(crashes), [g['sequence'] for g in played if g['boundary'] == 'after_commit'])
        for state in states:
            self.assertFalse(state['complete'])
            self.assertIsNone(state['champion'])
            self.assertFalse(state['ranks'])
            self.assertEqual(state['result_sha256'], final['result_sha256'][:state['matches']])
        self.assertTrue(final['complete'])
        self.assertTrue(final['readonly_bytes_unchanged'])
        self.assertIsNone(final['next_pair'])
        self.assertEqual(final['winners'][-1], final['champion'])
        self.assertEqual(ranks, [r[0] for r in final['ranks']])
        self.assertEqual(len(states) + 2, len({s['pid'] for s in states} | {final['pid'], os.getpid()}))
        view = (self.store32 if name == 'thirty_two' else self.store16).snapshot()
        self.assertEqual(final['result_sha256'], [trial._sha(r.to_dict()) for r in view.results])
        self.assertEqual(json.loads(json.dumps(view.ranks)), final['ranks'])
        # Each resumed child's next pair comes only from actual saved winners.
        bracket = Bracket(view.plan.slots)
        for state in states[1:]:
            self.assertEqual(list(bracket.pair(state['matches'] + 1, view.results[:state['matches']])),
                             state['next_pair'])
        # Saved prefix bytes at every hard-exit boundary hold exactly that many games, no ranks.
        for n, raw in run['prefix'].items():
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'copy.sqlite3'
                path.write_bytes(raw)
                counts = table_counts(path)
            self.assertEqual(n, counts['bracket_matches'])
            self.assertEqual(n, counts['bracket_checkpoints'])
            self.assertEqual(0 if n < games else len(ranks), counts['bracket_ranks'])
            self.assertEqual(0 if n < games else 1, counts['bracket_acceptance'])
        return view, played

    def test_01_sixteen_teams_fifteen_games_hard_exit_resume(self):
        view, played = self.check_run('sixteen', CRASH16, 15, [1, 2, 3, 3] + [5] * 4 + [9] * 8)
        self.assertEqual({1: 8, 2: 4, 3: 2, 4: 1}, {r: sum(g.round_no == r for g in view.plan.games) for r in range(1, 5)})
        self.assertEqual(16 * 20, len({p.player_id for t in view.teams for p in t.players}))
        self.assertEqual(17, len({p.origin_school_id for t in view.teams for p in t.players}))
        run = self.runs['sixteen']
        MEASUREMENTS['sixteen'] = dict(seconds=round(run['seconds'], 3), namespace=view.plan.namespace,
            scope=view.plan.scope, scenario_seed=support.SEED16, slots=view.plan.slots,
            hard_exit_after_commit_of_games=list(CRASH16), champion=view.fictional_scenario_champion,
            ranks=view.ranks, scores=[[g.team1_id, g.team2_id, g.team1_score, g.team2_score, g.last_inning]
                                      for g in view.results],
            per_game=played, child_wall_seconds=[s['wall_seconds'] for s in run['states']] + [run['final']['wall_seconds']],
            child_resume_seconds=[s['resume_seconds'] for s in run['states']] + [run['final']['resume_seconds']],
            child_peak_rss_kib=[s['peak_rss_kib'] for s in run['states']] + [run['final']['peak_rss_kib']],
            db_bytes=self.store16.db_path.stat().st_size, table_rows=table_counts(self.store16.db_path))

    def test_02_thirty_two_teams_31_games_hard_exit_resume_boundaries(self):
        view, played = self.check_run('thirty_two', CRASH32, 31, [1, 2, 3, 3] + [5] * 4 + [9] * 8 + [17] * 16)
        run = self.runs['thirty_two']
        streams = run['final']['streams']
        self.assertEqual([(2026, 'fictional_tournament', 31), (2027, practice.KIND, 1), (2027, v1.KIND, 2),
                          (2027, trial.KIND, 31), (2027, trial.KIND, 7)],
                         [(s['year'], s['record_kind'], s['matches']) for s in streams])
        MEASUREMENTS['thirty_two_run'] = dict(seconds=round(run['seconds'], 3),
            hard_exit_after_commit_of_games=list(CRASH32), per_game=played,
            per_game_seconds=[g['seconds'] for g in played],
            db_bytes_after_game=[g['db_bytes'] for g in played],
            child_wall_seconds=[s['wall_seconds'] for s in run['states']] + [run['final']['wall_seconds']],
            child_resume_seconds=[s['resume_seconds'] for s in run['states']] + [run['final']['resume_seconds']],
            child_cpu_seconds=[s['cpu_seconds'] for s in run['states']] + [run['final']['cpu_seconds']],
            child_peak_rss_kib=[s['peak_rss_kib'] for s in run['states']] + [run['final']['peak_rss_kib']],
            child_start_states=[{k: s[k] for k in ('pid', 'matches', 'complete', 'champion', 'next_pair', 'db_bytes')}
                                for s in run['states']], final_streams=streams)

    def test_03_thirty_two_entries_real_sql_full_a_progression_and_scale_costs(self):
        began = perf_counter()
        view = self.store32.snapshot()
        snapshot_seconds = perf_counter() - began
        with closing(sqlite3.connect(self.lab.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            sql_people = {p['player_id']: p for raw, in con.execute(
                'SELECT payload_json FROM career_school_rosters WHERE year=2027') for p in json.loads(raw)['players']}
        old = {p.player_id: p for r in self.authority[0].rosters for p in r.players}
        self.assertEqual(32, len(view.teams))
        self.assertEqual(640, sum(len(t.players) for t in view.teams))
        self.assertEqual(640, len({p.player_id for t in view.teams for p in t.players}))
        self.assertEqual(33, len({p.origin_school_id for t in view.teams for p in t.players}))
        self.assertEqual(660, len(sql_people))
        self.assertEqual((), view.bracket.byes)
        self.assertEqual(32, len(view.plan.slots))
        groups = support.groups(self.lab, 31)
        for team, entry, group in zip(view.teams, self.request32.entries.teams, groups):
            self.assertEqual(entry.player_ids, tuple(p.player_id for p in team.players))
            self.assertEqual(group, tuple(sid for sid, _ in entry.programs))
            self.assertEqual({sid: 20 // len(group) for sid in group},
                             {sid: sum(p.origin_school_id == sid for p in team.players) for sid in group})
            for p in team.players:
                self.assertEqual(sql_people[p.player_id]['school_id'], p.origin_school_id)
                self.assertNotEqual(3, old[p.player_id].academic_year if p.player_id in old else 0)
        # Declared seeds 1..4 occupy the standard positions of a 32 slot draw.
        order = seed_positions(32)
        self.assertEqual([order.index(n) for n in (1, 2, 3, 4)],
                         [view.plan.slots.index(t) for t, _ in self.request32.seeds.seeds])
        prepared = self.store32._prepare()
        rounds, games, rerun = {}, [], 0.0
        for i, game in enumerate(view.results):
            match = trial._input(prepared, view.results[:i])
            t = perf_counter()
            oracle = event_oracle(game, match)
            self.assertEqual(game, _run(match, match.match_seed))
            rerun += perf_counter() - t
            self.assertEqual(trial._sha([r.to_dict() for r in view.results[:i]]), match.previous_results_sha256)
            self.assertEqual(len(game.events), sum(r.plate_appearances for r in game.batter_stats))
            self.assertEqual(game.team1_score + game.team2_score, sum(r.runs for r in game.batter_stats))
            self.assertEqual(oracle['runs'], sum(r.runs_allowed for r in game.pitcher_stats))
            self.assertEqual(oracle['pitching_outs'], sum(r.outs_recorded for r in game.pitcher_stats))
            self.assertTrue(all(r.player_id in sql_people for r in (*game.batter_stats, *game.pitcher_stats)))
            self.assertNotEqual(game.team1_score, game.team2_score)
            rounds.setdefault(match.round_no, []).append(game)
            games.append(dict(sequence=i + 1, round_no=match.round_no, day=match.day, match_id=game.match_id,
                team1_id=game.team1_id, team2_id=game.team2_id, winner_id=game.winner_id, seed=match.match_seed,
                score=[game.team1_score, game.team2_score], innings=game.last_inning, events=len(game.events),
                inning_scores=[asdict(r) for r in game.inning_scores],
                batting=[asdict(r) for r in game.batter_stats], pitching=[asdict(r) for r in game.pitcher_stats],
                oracle=oracle, result_sha256=trial._sha(game.to_dict())))
        self.assertEqual({1: 16, 2: 8, 3: 4, 4: 2, 5: 1}, {k: len(v) for k, v in rounds.items()})
        for r in range(2, 6):
            self.assertEqual(sorted(g.winner_id for g in rounds[r - 1]),
                             sorted(t for g in rounds[r] for t in (g.team1_id, g.team2_id)))
        self.assertEqual(support.DATES32, tuple(sorted({g.day for g in view.plan.games})))
        ledger, ranks = progression(view.plan, self.request32, view.results)
        self.assertEqual([(r, t) for r, t, _, _ in ranks], view.bracket.ranks(view.results))
        self.assertEqual(31, sum(w for *_, w, _ in ranks))
        self.assertEqual(31, sum(l for *_, l in ranks))
        self.assertEqual(5, view.team(view.fictional_scenario_champion)['wins'])
        self.assertEqual(31, len([x for x in ledger if x[2] == 'WINNER']))
        # Every team has returning 2026 players and 2027 newcomers among actual batters.
        for team in view.teams:
            appeared = {r.player_id for g in view.results for r in g.batter_stats
                        if r.team_id == team.team_id and r.plate_appearances}
            self.assertTrue(appeared & old.keys())
            self.assertTrue(appeared - old.keys())
        counts = table_counts(self.store32.db_path)
        self.assertEqual(dict(bracket_contract=1, bracket_matches=31, bracket_advancement=31, bracket_checkpoints=31,
                              bracket_ranks=32, bracket_acceptance=1),
                         {k: v for k, v in counts.items() if k != 'bracket_players'})
        with closing(sqlite3.connect(self.store32.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            indexed = set(con.execute('SELECT player_id, entry_team_id FROM bracket_players'))
            page = con.execute('PRAGMA page_size').fetchone()[0]
            pages = con.execute('PRAGMA page_count').fetchone()[0]
            contract_bytes = len(con.execute('SELECT payload FROM bracket_contract').fetchone()[0].encode())
            stored = con.execute('SELECT sum(length(input_json)), sum(length(result_json)) FROM bracket_matches').fetchone()
        appeared = {(e.batter_id, e.offense_team_id) for g in view.results for e in g.events} | \
                   {(e.pitcher_id, e.defense_team_id) for g in view.results for e in g.events}
        self.assertEqual(appeared, indexed)
        # O(N^2) verification layers measured directly on the saved prefix sizes.
        scaling = []
        for n in (1, 8, 16, 24, 31):
            t = perf_counter()
            trial._rows(prepared, self.request32, view.results[:n])
            rows_seconds = perf_counter() - t
            t = perf_counter()
            for i in range(n):
                trial._input(prepared, view.results[:i])
            scaling.append(dict(games=n, rows_full_reaudit_seconds=round(rows_seconds, 3),
                                input_chain_seconds=round(perf_counter() - t, 3)))
        t = perf_counter()
        self.store32._prepare()
        prepare_seconds = perf_counter() - t
        t = perf_counter()
        practice.saved_authority(self.lab)
        authority_seconds = perf_counter() - t
        self.assertEqual(self.catalog, _compatibility(ROOT))
        self.assertEqual(338, len(self.catalog))
        self.assertEqual(106, sum(p.endswith('.csv') for p in self.master))
        self.assertEqual(self.master, {str(p.relative_to(ROOT)): pin(p) for p in (ROOT / 'data').rglob('*') if p.is_file()})
        MEASUREMENTS['thirty_two'] = dict(namespace=view.plan.namespace, scope=view.plan.scope,
            scenario_seed=support.SEED32, slots=view.plan.slots, seeds=self.request32.seeds.seeds,
            joint_entry=self.request32.entries.teams[-1].entry_team_id, joint_programs=self.request32.entries.teams[-1].programs,
            entries=32, schools=33, registered_players=640, games=games,
            champion=view.fictional_scenario_champion, ranks=view.ranks, db_bytes=self.store32.db_path.stat().st_size,
            created_db_bytes=self.created32_bytes, page_size=page, page_count=pages, contract_bytes=contract_bytes,
            stored_input_json_bytes=stored[0], stored_result_json_bytes=stored[1], table_rows=counts,
            indexed_player_rows=counts['bracket_players'], full_snapshot_seconds=round(snapshot_seconds, 3),
            all31_rerun_and_oracle_seconds=round(rerun, 3), prepare_seconds=round(prepare_seconds, 3),
            saved_authority_seconds=round(authority_seconds, 3), scaling=scaling,
            source_bytes_unchanged=self.pins == self.bytes())

    def test_04_cross_scenario_history_joint_separation_and_permanent_ids(self):
        t = perf_counter()
        hist = history.scenario_history((self.store32, self.eight, self.store16), practice_store=self.practice,
                                        v1_store=self.old)
        seconds = perf_counter() - t
        summary = hist.stream_summary()
        self.assertEqual([(2026, 'fictional_tournament', 31), (2027, practice.KIND, 1), (2027, v1.KIND, 2),
                          (2027, trial.KIND, 31), (2027, trial.KIND, 7), (2027, trial.KIND, 15)],
                         [(s['year'], s['record_kind'], s['matches']) for s in summary])
        self.assertEqual(6, len({(s['year'], s['record_kind'], s['namespace']) for s in summary}))
        ids = [g.match_id for *_, games in hist.streams for g in games]
        self.assertEqual(87, len(ids))
        self.assertEqual(87, len(set(ids)))
        v32, v8 = hist.scenarios[support.NAMESPACE32], hist.scenarios['fictional:stage117-owned-eight']
        joint32 = v32.teams[-1].team_id
        joint8 = v8.teams[-1].team_id
        for sid in support.JOINT:
            school = hist.school(sid)
            for namespace, record in school['scenarios'].items():
                self.assertEqual((0, 0), (record['standalone_wins'], record['standalone_losses']), namespace)
                self.assertFalse(record['standalone_records'])
            self.assertEqual([joint32], [r['entry_team_id'] for r in school['scenarios'][support.NAMESPACE32]['joint_records']])
            self.assertEqual([joint8], [r['entry_team_id'] for r in school['scenarios'][v8.plan.namespace]['joint_records']])
            self.assertEqual((0, 0), (school['standalone_wins_all_scenarios'], school['standalone_losses_all_scenarios']))
            self.assertIsNone(school['official_2027_outcomes'])
            self.assertIsNone(school['official_2027_joint_continuation'])
            stream32 = next(h for h in school['history'] if h['namespace'] == support.NAMESPACE32)
            self.assertEqual([joint32], stream32['entry_team_ids'])
            self.assertEqual(len([g for g in v32.results if joint32 in (g.team1_id, g.team2_id)]), len(stream32['matches']))
        # A school entered alone in both 32 and 8 scenarios keeps the two records apart.
        both = v8.request.entries.teams[0].programs[0][0]
        school = hist.school(both)
        r32 = school['scenarios'][support.NAMESPACE32]['standalone_records']
        r8 = school['scenarios'][v8.plan.namespace]['standalone_records']
        self.assertEqual(1, len(r32))
        self.assertEqual(1, len(r8))
        self.assertNotEqual(r32[0]['entry_team_id'], r8[0]['entry_team_id'])
        self.assertEqual(r32[0]['wins'] + r8[0]['wins'] + school['scenarios'][support.NAMESPACE16]['standalone_wins'],
                         school['standalone_wins_all_scenarios'])
        for h in school['history']:
            entry_ids = set(h['entry_team_ids'])
            self.assertTrue(all(entry_ids & {m['result']['team1_id'], m['result']['team2_id']} for m in h['matches']))
        # Permanent IDs: returning players, newcomers and graduates across all streams.
        old = {p.player_id for r in self.authority[0].rosters for p in r.players}
        new = {p.player_id for r in self.authority[1] for p in r.players}
        returning = [pid for pid in sorted(old & new)
                     if hist.player(pid)['history'][0]['appearances'] and hist.player(pid)['history'][3]['appearances']]
        self.assertTrue(returning)
        record = hist.player(returning[0])
        self.assertEqual(6, len(record['history']))
        self.assertEqual(record['history'][0]['profile']['academic_year'] + 1, record['history'][3]['profile']['academic_year'])
        rows = [r for g in v32.results for r in g.batter_stats if r.player_id == returning[0]]
        self.assertEqual(sum(r.plate_appearances for r in rows),
                         record['scenario_totals'][support.NAMESPACE32]['batting']['plate_appearances'])
        newcomer = next(pid for pid in sorted(new - old) if hist.player(pid)['history'][3]['appearances'])
        self.assertEqual('not_yet_enrolled', hist.player(newcomer)['history'][0]['state'])
        graduate = next(pid for pid in sorted(old - new))
        self.assertEqual(['graduated'] * 5, [h['state'] for h in hist.player(graduate)['history'][1:]])
        self.assertFalse(any(h['appearances'] for h in hist.player(graduate)['history'][1:]))
        joint_player = hist.player(v32.teams[-1].players[0].player_id)
        self.assertIn(joint_player['origin_school_id'], support.JOINT)
        self.assertTrue(all(a['entry_team_id'] == joint32 for a in joint_player['history'][3]['appearances']))
        self.assertFalse(hist.official_year_verified)
        self.assertFalse(hist.product_season_start_authorized)
        for bad in (lambda: history.scenario_history(()), lambda: history.scenario_history((self.store32, self.store32)),
                    lambda: history.scenario_history((self.store32, self.practice)),
                    lambda: hist.team('fictional:unknown', joint32), lambda: hist.school('unknown'),
                    lambda: hist.player('unknown')):
            with self.assertRaises(ValueError):
                bad()
        MEASUREMENTS['history'] = dict(seconds=round(seconds, 3), streams=summary, match_ids=len(ids),
            joint_schools={sid: dict(standalone_all=[hist.school(sid)['standalone_wins_all_scenarios'],
                                                     hist.school(sid)['standalone_losses_all_scenarios']],
                                     joint_records={ns: [[r['entry_team_id'], r['wins'], r['losses']] for r in s['joint_records']]
                                                    for ns, s in hist.school(sid)['scenarios'].items()})
                           for sid in support.JOINT},
            returning_players_with_2026_and_2027_32_appearances=len(returning))

    def test_05_final_boundary_rollback_lost_ack_precommit_hard_exit_and_hot_journal(self):
        raw30 = self.runs['thirty_two']['prefix'][30]
        store = self.copy_store(self.request32, support.SEED32, raw30)
        mid = store.snapshot()
        self.assertEqual(30, len(mid.results))
        self.assertFalse(mid.ranks)
        self.assertIsNone(mid.fictional_scenario_champion)
        final = store.next_input()
        self.assertEqual(5, final.round_no)
        self.assertEqual(set(mid.next_pair()), {mid.results[28].winner_id, mid.results[29].winner_id})
        result = _run(final, final.match_seed)
        before = pin(store.db_path)

        def fail(at):
            if at == 'before_commit':
                raise RuntimeError('rollback fixture')
        with self.assertRaises(RuntimeError):
            store.append(final, result, fault=fail)
        self.assertEqual(before, pin(store.db_path))
        self.assertEqual(0, table_counts(store.db_path)['bracket_ranks'])

        def lost(at):
            if at == 'after_commit':
                raise RuntimeError('lost ACK fixture')
        with self.assertRaises(RuntimeError):
            store.append(final, result, fault=lost)
        counts = table_counts(store.db_path)
        self.assertEqual((31, 32, 1), (counts['bracket_matches'], counts['bracket_ranks'], counts['bracket_acceptance']))
        after = pin(store.db_path)
        self.assertFalse(store.append(final, result))
        self.assertEqual(after, pin(store.db_path))
        with self.assertRaises(ValueError):
            store.append(final, _run(final, final.match_seed + 1))
        with self.assertRaises(ValueError):
            store.play_next()
        self.assertEqual(self.runs['thirty_two']['final']['result_sha256'],
                         [trial._sha(r.to_dict()) for r in store.snapshot().results])
        # A real precommit hard exit of the final game leaves a hot journal that is refused.
        hot = self.copy_store(self.request32, support.SEED32, raw30)
        cap = hot.capability
        hot.close()
        caps = self.release()
        try:
            with tempfile.TemporaryDirectory(prefix='stage118-private-') as temp:
                state = support.worker(dict(source=caps['source'], annual=caps['annual'], bracket=cap), Path(temp),
                                       action='crash_before_commit')
        finally:
            self.reopen(caps)
        self.assertEqual(30, state['matches'])
        self.assertEqual([31], [g['sequence'] for g in state['games_played']])
        self.assertEqual('before_commit', state['games_played'][0]['boundary'])
        journal = Path(str(hot.db_path) + '-journal')
        self.assertGreater(journal.stat().st_size, 512)
        frozen = {p.name: pin(p) for p in hot.db_path.parent.iterdir()}
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no automatic hot journal recovery')):
            with self.assertRaises(ValueError):
                trial.FictionalBracketStore.resume(cap, self.lab, fictional_opt_in=True)
        self.assertEqual(frozen, {p.name: pin(p) for p in hot.db_path.parent.iterdir()})
        MEASUREMENTS['final_boundary'] = dict(precommit_child=state['games_played'][0],
                                              hot_journal_bytes=journal.stat().st_size)

    def test_06_tampered_31_game_store_rejected_readonly(self):
        raw = self.store32.db_path.read_bytes()
        store = self.copy_store(self.request32, support.SEED32, raw)
        self.assertEqual(31, len(store.snapshot().results))
        with closing(sqlite3.connect(self.eight.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            foreign = con.execute('SELECT * FROM bracket_players LIMIT 1').fetchone()
        cases = (
            ('CREATE TABLE foreign_table(x)',),
            ('INSERT INTO bracket_players SELECT "unknown-player", origin_school_id, entry_team_id, year, '
             'record_kind, namespace, match_id FROM bracket_players LIMIT 1',),
            ('DROP TRIGGER bracket_players_delete',
             'DELETE FROM bracket_players WHERE rowid IN (SELECT rowid FROM bracket_players LIMIT 1)'),
            ('DROP TRIGGER bracket_players_update',
             f'UPDATE bracket_players SET entry_team_id="{support.NAMESPACE32}:team1" '
             f'WHERE entry_team_id="{support.NAMESPACE32}:team32"'),
            ('DROP TRIGGER bracket_matches_update', 'UPDATE bracket_matches SET result_sha256="tampered" WHERE sequence=16'),
            ('DROP TRIGGER bracket_matches_delete', 'PRAGMA foreign_keys=OFF',
             'DROP TRIGGER bracket_checkpoints_delete', 'DELETE FROM bracket_checkpoints WHERE sequence=31',
             'DROP TRIGGER bracket_players_delete',
             'DELETE FROM bracket_players WHERE match_id=(SELECT match_id FROM bracket_matches WHERE sequence=31)',
             'DELETE FROM bracket_matches WHERE sequence=31'),  # final removed, ranks kept
            ('DROP TRIGGER bracket_checkpoints_update',
             'UPDATE bracket_checkpoints SET prefix_results_sha256=previous_results_sha256 WHERE sequence=24'),
            ('DROP TRIGGER bracket_ranks_update', 'UPDATE bracket_ranks SET rank=9 WHERE rank=5'),
            ('DROP TRIGGER bracket_ranks_delete', 'DELETE FROM bracket_ranks WHERE rank=17'),
            ('DROP TRIGGER bracket_acceptance_delete', 'DELETE FROM bracket_acceptance'),
            ('DROP TRIGGER bracket_advancement_update',
             'UPDATE bracket_advancement SET team_id=(SELECT team_id FROM bracket_advancement WHERE step=3) WHERE step=17'),
            ('DROP TRIGGER bracket_contract_update', 'UPDATE bracket_contract SET payload=replace(payload,"2027-07-17","2027-07-18")'),
            ('INSERT INTO bracket_players VALUES ({})'.format(','.join(repr(v) for v in foreign)),),  # Stage117 row
        )
        for statements in cases:
            with self.subTest(statements=statements[-1][:60]):
                with closing(sqlite3.connect(store.db_path)) as con:
                    for statement in statements:
                        con.execute(statement)
                    con.commit()
                    for statement in statements:
                        if statement.startswith('DROP TRIGGER '):
                            name = statement.split()[-1]
                            con.execute(next(sql for sql in trial.DDL if sql.startswith('CREATE TRIGGER ' + name + ' ')))
                    con.commit()
                before = pin(store.db_path)
                with self.assertRaises(ValueError):
                    store.snapshot()
                self.assertEqual(before, pin(store.db_path))
                store.db_path.write_bytes(raw)  # newly-created fault target only
        self.assertEqual(31, len(store.snapshot().results))
        self.assertEqual(raw, self.store32.db_path.read_bytes())

    def test_07_thirty_two_entry_composition_and_source_refusals(self):
        teams = self.request32.entries.teams
        rosters = {r.school_id: r for r in self.authority[1]}
        graduated = next(p.player_id for r in self.authority[0].rosters for p in r.players if p.academic_year == 3)
        joint = teams[-1]
        extra = rosters[support.JOINT[0]].players[10].player_id
        bad_requests = dict(
            graduate=replace(self.request32, entries=replace(self.request32.entries,
                teams=(replace(teams[0], player_ids=(graduated,) + teams[0].player_ids[1:]),) + teams[1:])),
            other_school_player=replace(self.request32, entries=replace(self.request32.entries,
                teams=(replace(teams[0], player_ids=(teams[30].player_ids[0],) + teams[0].player_ids[1:]),) + teams[1:])),
            joint_11_9=replace(self.request32, entries=replace(self.request32.entries,
                teams=teams[:31] + (replace(joint, player_ids=joint.player_ids[:10] + (extra,) + joint.player_ids[10:19]),))),
            duplicate_entry_id=replace(self.request32, entries=replace(self.request32.entries,
                teams=teams[:31] + (replace(joint, entry_team_id=teams[0].entry_team_id),))),
            joint_member_also_single=replace(self.request32, entries=replace(self.request32.entries,
                teams=teams[:30] + (replace(teams[30], programs=((support.JOINT[0], rosters[support.JOINT[0]].program_id),),
                    player_ids=tuple(p.player_id for p in rosters[support.JOINT[0]].players)),) + (joint,))),
            joint_declaration_missing=replace(self.request32, joints=replace(self.request32.joints, teams=())),
            draw_bye=replace(self.request32, draw=replace(self.request32.draw, bye_count=1)),
            draw_size64=replace(self.request32, draw=replace(self.request32.draw, bracket_size=64, bye_count=32)),
            four_dates=replace(self.request32, schedule=replace(self.request32.schedule, round_dates=support.DATES32[:4])),
            year2026=replace(self.request32, year=2026),
            official_namespace=replace(self.request32, namespace='official:2027'),
            official_label=replace(self.request32, entries=replace(self.request32.entries,
                evidence=replace(self.request32.entries.evidence, source='self-created declaration/公式2027'))),
            seed_out_of_range=replace(self.request32, seeds=replace(self.request32.seeds, seeds=((teams[0].entry_team_id, 17),))),
        )
        refused = {}
        for name, bad in bad_requests.items():
            t = perf_counter()
            with self.subTest(name), self.assertRaises(ValueError):
                trial._prepare(self.lab, bad, support.SEED32, True)
            refused[name] = round(perf_counter() - t, 3)
        # The same request on another physical accepted source yields another contract and is refused.
        owner = tempfile.TemporaryDirectory(prefix='stage118-other-')
        self.addCleanup(owner.cleanup)
        other = annual.AnnualRosterLab(self.source, owner, opt_in=True)
        try:
            other.advance()
            self.store32.lab = other
            with self.assertRaises(ValueError):
                self.store32.snapshot()
        finally:
            self.store32.lab = self.lab
            other.close()
        self.assertTrue(gates.dry_run(self.lab, self.request32, fictional_opt_in=True).fictional_scenario_ready)
        with self.assertRaises(ValueError):
            trial.FictionalBracketStore.resume(self.store32.capability, self.lab, fictional_opt_in=False)
        MEASUREMENTS['refusals'] = dict(seconds=refused, cases=len(refused))

    def test_08_stage116_v1_and_stage117_v2_code_and_saved_stores_unchanged(self):
        for name in ('phase2_engine/saved_fictional_tournament.py', 'phase2_engine/fictional_tournament_oracle.py',
                     'phase2_engine/saved_fictional_bracket.py', 'phase2_engine/fictional_bracket.py',
                     'phase2_engine/fictional_bracket_oracle.py', 'phase2_engine/competition_evidence_gates.py',
                     'phase2_engine/saved_practice_match.py', 'phase2_engine/yamanashi_annual_rosters.py',
                     'phase2_engine/registered_match_driver.py', 'phase2_engine/registered_full_a_oracle.py'):
            main = subprocess.run(['git', 'show', f'{STAGE117_MAIN}:{name}'], cwd=ROOT, capture_output=True, check=True).stdout
            self.assertEqual(main, (ROOT / name).read_bytes(), name)
        eight = self.eight.snapshot(practice_store=self.practice, v1_store=self.old)
        self.assertEqual(7, len(eight.results))
        self.assertEqual([1, 2, 3, 3, 5, 5, 5, 5], [r[0] for r in eight.ranks])
        self.assertEqual(2, len(self.old.snapshot().results))
        self.assertEqual(1, len(self.practice.snapshot().results))
        self.assertEqual(trial.VERSION, json.loads(self.store32.capability.contract_json)['version'])
        self.assertNotEqual(self.eight.capability.contract_json, self.store32.capability.contract_json)


if __name__ == '__main__':
    unittest.main()
