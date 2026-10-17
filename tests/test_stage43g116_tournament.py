"""Real two-game execution; independent full-A/progression/identity and crash audits."""
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from phase2_engine import competition_evidence_gates as gates
from phase2_engine import saved_fictional_tournament as trial
from phase2_engine import saved_practice_match as practice
from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine.fictional_tournament_oracle import progression
from phase2_engine.manual_save_backup import _compatibility
from phase2_engine.registered_full_a_oracle import event_oracle
from phase2_engine.registered_match_driver import _run
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g115_support import scenario
from stage43g116_support import worker

MEASUREMENTS = {}
ROOT = Path(__file__).resolve().parents[1]


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FictionalTournamentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        began = perf_counter()
        cls.owners = [tempfile.TemporaryDirectory(prefix='stage116-source-') for _ in range(3)]
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
        cls.request = scenario(cls.lab)
        cls.authority = practice.saved_authority(cls.lab)
        cls.pins = cls.bytes()
        cls.catalog = _compatibility(ROOT)
        cls.master = {str(p.relative_to(ROOT)): pin(p) for p in (ROOT / 'data').rglob('*') if p.is_file()}
        MEASUREMENTS['fixture'] = dict(seconds=round(perf_counter()-began, 3), saved2026_matches=31,
            saved2027_schools=33, active_players=660, permanent_ids=924, saved2027_practice_matches=1,
            source_database_sha256=cls.pins[0]['database'], annual_database_sha256=cls.pins[1],
            practice_database_sha256=cls.pins[2])

    @classmethod
    def bytes(cls):
        return cls.source._evidence(), pin(cls.lab.db_path), pin(cls.practice.db_path)

    def setUp(self):
        self.owner = tempfile.TemporaryDirectory(prefix='stage116-tournament-')
        self.addCleanup(self.owner.cleanup)
        self.store = trial.FictionalTournamentStore(self.lab, self.owner, self.request, fictional_opt_in=True)
        self.addCleanup(lambda: self.store.close())

    def tearDown(self):
        self.assertEqual(self.pins, self.bytes())

    def complete(self):
        self.store.play_next()
        self.store.play_next()
        return self.store.snapshot(practice_store=self.practice)

    def release(self):
        caps = self.source.capability, self.lab.capability, self.practice.capability, self.store.capability
        self.store.close(); self.practice.close(); self.lab.close(); self.source.close()
        return caps

    def reopen(self, caps, *, tournament=True):
        cls = type(self)
        cls.source = annual.SelfCreated2026.resume(caps[0])
        cls.lab = annual.AnnualRosterLab.resume(caps[1], cls.source)
        cls.practice = practice.PracticeStore.resume(caps[2], cls.lab)
        if tournament:
            self.store = trial.FictionalTournamentStore.resume(caps[3], self.lab, fictional_opt_in=True)

    def test_real_two_games_sql_full_a_identity_and_three_distinct_history_streams(self):
        began = perf_counter()
        with patch.object(self.lab, 'browse', side_effect=AssertionError('direct saved SQL required')):
            first = self.store.next_input()
        with closing(sqlite3.connect(self.lab.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            sql_people = {p['player_id']: p for raw, in con.execute('SELECT payload_json FROM career_school_rosters WHERE year=2027')
                          for p in json.loads(raw)['players']}
        old = {p.player_id: p for r in self.authority[0].rosters for p in r.players}
        self.assertEqual(264, len(set(old) - sql_people.keys()))
        self.assertEqual(396, len(set(old) & sql_people.keys()))
        self.assertEqual(264, len(sql_people.keys() - old.keys()))
        for pid, person in sql_people.items():
            if pid in old:
                self.assertEqual({**old[pid].to_dict(), 'academic_year': old[pid].academic_year + 1}, person)
            else:
                self.assertEqual((2027, 1), (person['entry_year'], person['academic_year']))
                raw = f"430103:player_career_newcomer_v1:2027:{person['school_id']}:{person['roster_no']}"
                expected_id = 'PLY' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()
                self.assertEqual(expected_id, pid)
        view = self.complete()
        self.assertEqual(60, sum(len(t.players) for t in view.teams))
        self.assertEqual(60, len({p.player_id for t in view.teams for p in t.players}))
        for team, entry in zip(view.teams, self.request.entries.teams):
            self.assertEqual(entry.player_ids, tuple(p.player_id for p in team.players))
            self.assertEqual({'P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'}, {pos for _, pos, _ in team.lineup})
            for p in team.players:
                saved = sql_people[p.player_id]
                self.assertEqual(saved['school_id'], p.origin_school_id)
                self.assertEqual((2027, saved['academic_year'], saved['entry_year']),
                    (p.snapshot.reference_year, p.snapshot.academic_year, saved['entry_year']))
        prepared = self.store._prepare()
        measured = []
        for i, game in enumerate(view.results):
            match = trial._input(view.plan, view.teams, prepared[3], view.results[:i])
            oracle = event_oracle(game, match)
            self.assertEqual(game, _run(match, match.match_seed))
            self.assertEqual(len(game.events), sum(r.plate_appearances for r in game.batter_stats))
            self.assertEqual(game.team1_score + game.team2_score, sum(r.runs for r in game.batter_stats))
            self.assertEqual(oracle['runs'], sum(r.runs_allowed for r in game.pitcher_stats))
            self.assertEqual(oracle['pitching_outs'], sum(r.outs_recorded for r in game.pitcher_stats))
            self.assertTrue(all(r.player_id in sql_people for r in (*game.batter_stats, *game.pitcher_stats)))
            measured.append(dict(match_id=game.match_id, year=game.year, record_kind=trial.KIND,
                namespace=view.plan.namespace, team1_id=game.team1_id, team2_id=game.team2_id,
                winner_id=game.winner_id, day=match.day, seed=match.match_seed,
                score=[game.team1_score, game.team2_score], innings=game.last_inning,
                inning_scores=[asdict(r) for r in game.inning_scores], batter_rows=len(game.batter_stats),
                pitcher_rows=len(game.pitcher_stats), batting=[asdict(r) for r in game.batter_stats],
                pitching=[asdict(r) for r in game.pitcher_stats],
                oracle=oracle, result_sha256=trial._sha(game.to_dict())))
        self.assertEqual(self.request.schedule.round_dates, tuple(g.day for g in view.plan.games))
        self.assertEqual(view.results[0].winner_id, view.results[1].team1_id)
        self.assertEqual(view.plan.slots[0], view.results[1].team2_id)
        self.assertTrue(view.complete)
        self.assertEqual(view.results[1].winner_id, view.fictional_scenario_champion)
        self.assertEqual(3, len(view.ranks))
        self.assertEqual(2, sum(view.team(t.team_id)['wins'] for t in view.teams))
        self.assertEqual(2, sum(view.team(t.team_id)['losses'] for t in view.teams))
        joint = view.teams[2]
        self.assertEqual({sid: 10 for sid, _ in self.request.entries.teams[2].programs},
            {sid: sum(p.origin_school_id == sid for p in joint.players) for sid, _ in self.request.entries.teams[2].programs})
        for sid, _ in self.request.entries.teams[2].programs:
            school = view.school(sid)
            self.assertEqual((0, 0), (school['standalone_wins'], school['standalone_losses']))
            self.assertTrue(school['fictional_team_records'][0]['joint'])
            self.assertIsNone(school['official_2027_outcomes'])
        # Every registered team's starting nine includes each member school and
        # returning/newcomer actual PA. BYE is not a played win.
        for team in view.teams:
            appeared = {r.player_id for g in view.results for r in g.batter_stats
                        if r.team_id == team.team_id and r.plate_appearances}
            self.assertTrue(appeared & old.keys())
            self.assertTrue(appeared - old.keys())
            self.assertEqual({p.origin_school_id for p in team.players}, {sql_people[p]['school_id'] for p in appeared})
        returning = [p for p in view._people if p in old and any(h['appearances'] for h in view.player(p)['history'][:1])
                     and view.player(p)['history'][-1]['appearances']]
        self.assertTrue(returning)
        history = view.player(returning[0])['history']
        self.assertEqual([(2026, trial.KIND), (2027, practice.KIND), (2027, trial.KIND)],
                         [(h['year'], h['record_kind']) for h in history])
        self.assertEqual(3, len({h['namespace'] for h in history}))
        self.assertEqual(history[0]['profile']['academic_year'] + 1, history[2]['profile']['academic_year'])
        newcomer = next(pid for pid in sql_people if pid not in old)
        graduate = next(pid for pid in old if pid not in sql_people)
        self.assertEqual('not_yet_enrolled', view.player(newcomer)['history'][0]['state'])
        self.assertEqual('graduated', view.player(graduate)['history'][-1]['state'])
        self.assertFalse(view.player(graduate)['history'][-1]['appearances'])
        self.assertFalse(view.official_year_verified)
        self.assertFalse(view.product_season_start_authorized)
        self.assertEqual(self.catalog, _compatibility(ROOT))
        self.assertEqual(338, len(self.catalog))
        self.assertEqual(106, sum(p.endswith('.csv') for p in self.master))
        self.assertEqual(self.master, {str(p.relative_to(ROOT)): pin(p) for p in (ROOT/'data').rglob('*') if p.is_file()})
        with closing(sqlite3.connect(self.store.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            self.assertEqual(2, con.execute('SELECT count(*) FROM fictional_matches').fetchone()[0])
            self.assertEqual(1, con.execute('SELECT count(*) FROM fictional_acceptance').fetchone()[0])
            self.assertEqual(3, con.execute('SELECT count(*) FROM fictional_ranks').fetchone()[0])
        MEASUREMENTS['tournament'] = dict(seconds=round(perf_counter()-began, 3), scenario_seed=trial.SEED,
            namespace=view.plan.namespace, scope=view.plan.scope, slots=view.plan.slots, games=measured,
            champion=view.fictional_scenario_champion, ranks=view.ranks,
            joint_team={k: v for k, v in view.team(joint.team_id).items() if k != 'matches'},
            joint_school_standalone_records=[dict(school_id=sid,
                wins=view.school(sid)['standalone_wins'], losses=view.school(sid)['standalone_losses'])
                for sid, _ in self.request.entries.teams[2].programs],
            returning_two_year_appearances=len(returning), bytes=self.store.db_path.stat().st_size,
            source_bytes_unchanged=self.pins == self.bytes(), first_input_sha256=trial._sha(first.to_dict()))

    def test_actual_request_gates_opt_in_source_labels_and_saved_authority_fail_closed(self):
        for flag in (False, 1, 'true', None):
            owner = tempfile.TemporaryDirectory(prefix='stage116-unused-')
            with owner as temp:
                with self.assertRaises(ValueError):
                    trial.FictionalTournamentStore(self.lab, owner, self.request, fictional_opt_in=flag)
                self.assertFalse(list(Path(temp).iterdir()))
        for name in ('entries', 'joints', 'qualification', 'districts', 'seeds', 'draw', 'schedule'):
            owner = tempfile.TemporaryDirectory(prefix='stage116-unused-')
            with self.subTest(gate=name), owner as temp:
                with self.assertRaises(ValueError):
                    trial.FictionalTournamentStore(self.lab, owner, replace(self.request, **{name: None}), fictional_opt_in=True)
                self.assertFalse(list(Path(temp).iterdir()))
        for source in ('official verified source', 'https://official.example/2027',
                       'self-created declaration/official', 'self-created declaration/公式'):
            bad = replace(self.request, entries=replace(self.request.entries,
                evidence=replace(self.request.entries.evidence, source=source)))
            with self.assertRaises(ValueError):
                trial._prepare(self.lab, bad, trial.SEED, True)
        for bad in (gates.dry_run(self.lab, self.request, fictional_opt_in=True),
                    replace(self.request, year=2026), replace(self.request, namespace='official:2027')):
            with self.assertRaises(ValueError):
                trial._prepare(self.lab, bad, trial.SEED, True)
        with patch.object(gates, 'dry_run', wraps=gates.dry_run) as checked:
            self.store.next_input()
            self.assertIs(self.request, checked.call_args.args[1])
        from phase2_engine.saved_school_roster_source import SavedSchoolRosterSource
        for source in (object(), self.practice, SavedSchoolRosterSource.__new__(SavedSchoolRosterSource)):
            with self.assertRaises(ValueError):
                trial._prepare(source, self.request, trial.SEED, True)
        for seed in (True, -1, 2**63, '430116'):
            with self.assertRaises(ValueError):
                trial._prepare(self.lab, self.request, seed, True)
        self.store.scenario_seed += 1
        with self.assertRaises(ValueError):
            self.store.next_input()

    def test_missing_partial_foreign_roster_and_2026_registration_cannot_start(self):
        a, b, joint = self.request.entries.teams
        graduated = next(p.player_id for r in self.authority[0].rosters for p in r.players if p.academic_year == 3)
        for ids in ((graduated,) + a.player_ids[1:], (b.player_ids[0],) + a.player_ids[1:],
                    (a.player_ids[0],)*20):
            request = replace(self.request, entries=replace(self.request.entries,
                teams=(replace(a, player_ids=ids), b, joint)))
            with self.assertRaises(ValueError): trial._prepare(self.lab, request, trial.SEED, True)
        for bad in (replace(self.request, qualification=replace(self.request.qualification, prior_year_receipt_sha256='copied2026')),
                    replace(self.request, draw=replace(self.request.draw, participant_slots=32))):
            with self.assertRaises(ValueError): trial._prepare(self.lab, bad, trial.SEED, True)
        owner = tempfile.TemporaryDirectory(prefix='stage116-partial-'); self.addCleanup(owner.cleanup)
        incomplete = annual.AnnualRosterLab(self.source, owner, opt_in=True)
        try:
            with self.assertRaises(ValueError): trial._prepare(incomplete, self.request, trial.SEED, True)
        finally: incomplete.close()
        owner = tempfile.TemporaryDirectory(prefix='stage116-other-'); self.addCleanup(owner.cleanup)
        other = annual.AnnualRosterLab(self.source, owner, opt_in=True)
        try:
            other.advance()
            self.store.lab = other
            with self.assertRaises(ValueError): self.store.snapshot()
        finally:
            self.store.lab = self.lab
            other.close()

    def test_input_seed_origin_date_and_independent_score_inning_batting_pitching_tampering(self):
        match = self.store.next_input()
        game = _run(match, match.match_seed)
        for change in (dict(year=2026), dict(year=True), dict(match_seed=match.match_seed+1),
            dict(scenario_seed=trial.SEED+1), dict(namespace='official:2027'), dict(competition_id='CMP000041'),
            dict(record_kind='official'), dict(day='2027-07-02'), dict(contract_sha256='bad'),
            dict(previous_results_sha256='bad'), dict(sequence=True)):
            with self.assertRaises(ValueError): self.store.append(replace(match, **change), game)
        bad_player = replace(match.team1.players[0], origin_school_id='SCH000001')
        bad_team = replace(match.team1, players=(bad_player,) + match.team1.players[1:])
        with self.assertRaises(ValueError): self.store.append(replace(match, team1=bad_team), game)
        alternate = _run(match, match.match_seed+1)
        self.assertNotEqual(game.events, alternate.events)
        with self.assertRaises(ValueError): self.store.append(match, alternate)
        variants = (replace(game, team1_score=game.team1_score+1),
            replace(game, inning_scores=(replace(game.inning_scores[0], runs=99),) + game.inning_scores[1:]),
            replace(game, batter_stats=(replace(game.batter_stats[0], hits=99),) + game.batter_stats[1:]),
            replace(game, pitcher_stats=(replace(game.pitcher_stats[0], earned_runs=99),) + game.pitcher_stats[1:]),
            replace(game, winner_id=game.loser_id),
            replace(game, events=(replace(game.events[0], batter_origin_school_id='unknown'),) + game.events[1:]))
        for altered in variants:
            with self.assertRaises(ValueError): event_oracle(altered, match)
            with self.assertRaises(ValueError): self.store.append(match, altered)
        self.assertFalse(self.store.snapshot().results)

    def test_bye_winner_dependency_rejects_skips_loser_advancement_and_wrong_prefix(self):
        view = self.store.snapshot()
        self.assertFalse(view.complete)
        self.assertIsNone(view.fictional_scenario_champion)
        self.assertFalse(view.ranks)
        first = self.store.next_input(); game = _run(first, first.match_seed)
        prepared = self.store._prepare()
        final = trial._input(view.plan, view.teams, prepared[3], (game,))
        with self.assertRaises(ValueError): self.store.append(final, _run(final, final.match_seed))
        self.store.append(first, game)
        final = self.store.next_input()
        self.assertEqual(game.winner_id, final.team1.team_id)
        self.assertNotEqual(game.loser_id, final.team1.team_id)
        self.assertEqual(view.plan.slots[0], final.team2.team_id)
        bad = replace(final, team1=first.team1 if first.team1.team_id == game.loser_id else first.team2)
        with self.assertRaises(ValueError): self.store.append(bad, _run(bad, bad.match_seed))
        with self.assertRaises(ValueError): progression(view.plan, self.request, (replace(game, winner_id=game.loser_id),))
        mid = self.store.snapshot()
        self.assertFalse(mid.ranks); self.assertIsNone(mid.fictional_scenario_champion)
        self.store.play_next()
        with self.assertRaises(ValueError): self.store.play_next()
        with self.assertRaises(ValueError): self.store.snapshot().team('unknown')
        with self.assertRaises(ValueError): self.store.snapshot().school('unknown')
        with self.assertRaises(ValueError): self.store.snapshot().player('unknown')
        with self.assertRaises(ValueError): self.store.snapshot(practice_store=object())

    def test_atomic_rollback_lost_ack_each_game_idempotence_and_all_tables_append_only(self):
        for i in (1, 2):
            match = self.store.next_input(); result = _run(match, match.match_seed)
            before = pin(self.store.db_path)
            def fail(at):
                if at == 'before_commit': raise RuntimeError('rollback fixture')
            with self.assertRaises(RuntimeError): self.store.append(match, result, fault=fail)
            self.assertEqual(before, pin(self.store.db_path))
            self.assertEqual(i-1, len(self.store.snapshot().results))
            def lost(at):
                if at == 'after_commit': raise RuntimeError('lost ACK fixture')
            with self.assertRaises(RuntimeError): self.store.append(match, result, fault=lost)
            before = pin(self.store.db_path)
            self.assertFalse(self.store.append(match, result))
            self.assertEqual(before, pin(self.store.db_path))
            with self.assertRaises(ValueError): self.store.append(match, replace(result, run_seed=result.run_seed+1))
        with closing(sqlite3.connect(self.store.db_path)) as con:
            for table in trial.TABLES:
                key = con.execute(f'PRAGMA table_info({table})').fetchone()[1]
                for statement in (f'UPDATE {table} SET {key}={key}', f'DELETE FROM {table}'):
                    with self.assertRaises(sqlite3.IntegrityError): con.execute(statement)
            con.rollback()
        self.assertEqual(before, pin(self.store.db_path))

    def test_process_hard_exit_after_first_commit_incomplete_resume_second_commit_and_read(self):
        began = perf_counter()
        caps = self.release()
        try:
            with tempfile.TemporaryDirectory(prefix='stage116-private-') as temp:
                private = Path(temp)
                worker(self.lab, self.practice, self.store, private, action='crash_after_commit')
                mid = worker(self.lab, self.practice, self.store, private)
                self.assertEqual(1, mid['matches']); self.assertFalse(mid['complete'])
                self.assertIsNone(mid['champion']); self.assertFalse(mid['ranks'])
                done = worker(self.lab, self.practice, self.store, private, action='finish')
                final = worker(self.lab, self.practice, self.store, private)
                self.assertEqual(2, final['matches']); self.assertTrue(final['complete'])
                self.assertEqual(done['result_sha256'], final['result_sha256'])
                self.assertEqual(mid['result_sha256'], final['result_sha256'][:1])
                self.assertNotEqual(os.getpid(), mid['pid'])
                self.assertNotEqual(mid['pid'], final['pid'])
                self.assertEqual((31, 1), (final['source_matches'], final['practice_matches']))
                self.assertTrue(final['readonly_bytes_unchanged'])
                MEASUREMENTS['restart'] = dict(seconds=round(perf_counter()-began, 3),
                    first_committed_then_os_exit=True, incomplete=mid, resumed_complete=final)
        finally: self.reopen(caps)

    def test_hot_journal_after_real_precommit_hard_exit_refused_without_recovery(self):
        caps = self.release()
        try:
            with tempfile.TemporaryDirectory(prefix='stage116-private-') as temp:
                worker(self.lab, self.practice, self.store, Path(temp), action='crash_before_commit')
        finally: self.reopen(caps, tournament=False)
        journal = Path(str(self.store.db_path) + '-journal')
        self.assertGreater(journal.stat().st_size, 512)
        before = {p.name: pin(p) for p in self.store.db_path.parent.iterdir()}
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no automatic hot journal recovery')):
            with self.assertRaises(ValueError):
                trial.FictionalTournamentStore.resume(caps[3], self.lab, fictional_opt_in=True)
        self.assertEqual(before, {p.name: pin(p) for p in self.store.db_path.parent.iterdir()})

    def test_sidecars_hardlinks_junction_file_root_lease_replacement_and_lease_exclusion(self):
        cap = self.store.capability
        for suffix in ('-journal', '-wal', '-shm'):
            side = Path(str(self.store.db_path) + suffix); side.write_bytes(b'foreign sidecar')
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('guard precedes all SQL')):
                    with self.assertRaises(ValueError): self.store.snapshot()
            finally: side.unlink()
        with self.assertRaises(ValueError): trial.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)
        self.store.close()
        with tempfile.TemporaryDirectory(prefix='stage116-alias-') as temp:
            outside = Path(temp)
            alias = outside / 'junction'
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.store.db_path.parent)], check=True, capture_output=True)
            else: alias.symlink_to(self.store.db_path.parent, target_is_directory=True)
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no junction SQL')):
                    with self.assertRaises(ValueError):
                        trial.FictionalTournamentStore.resume(replace(cap, root=str(alias)), self.lab, fictional_opt_in=True)
            finally:
                if os.name == 'nt': alias.rmdir()
                else: alias.unlink()
            link = outside / 'hardlink'; os.link(self.store.db_path, link)
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no hardlink SQL')):
                    with self.assertRaises(ValueError): trial.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)
            finally: link.unlink()
            lease = self.store.db_path.parent / trial.LEASE
            for path in (self.store.db_path, lease):
                retained = outside / path.name
                path.rename(retained); path.write_bytes(retained.read_bytes())
                try:
                    with patch.object(sqlite3, 'connect', side_effect=AssertionError('no replacement SQL')):
                        with self.assertRaises(ValueError): trial.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)
                finally:
                    path.unlink(); retained.rename(path)
            root = self.store.db_path.parent
            moved = root.with_name(root.name + '-retained')
            root.rename(moved); root.mkdir()
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no replaced root SQL')):
                    with self.assertRaises(ValueError): trial.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)
            finally:
                root.rmdir(); moved.rename(root)
        self.store = trial.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)

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
        self.store = trial.FictionalTournamentStore.resume(cap, self.lab, fictional_opt_in=True)
        self.assertEqual(before, pin(self.store.db_path))

    def test_schema_index_result_and_saved_source_tampering_rejected_readonly(self):
        self.complete()
        original = self.store.db_path.read_bytes()
        cases = (
            ('CREATE TABLE foreign_table(x)',),
            ('INSERT INTO fictional_players SELECT "unknown-player", origin_school_id, entry_team_id, year, '
             'record_kind, namespace, match_id FROM fictional_players LIMIT 1',),
            ('DROP TRIGGER fictional_players_delete', 'DELETE FROM fictional_players'),
            ('DROP TRIGGER fictional_matches_update', 'UPDATE fictional_matches SET result_sha256="tampered" WHERE sequence=1'),
            ('DROP TRIGGER fictional_ranks_update', 'UPDATE fictional_ranks SET wins=99'),
            ('DROP TRIGGER fictional_acceptance_delete', 'DELETE FROM fictional_acceptance'),
        )
        for statements in cases:
            with closing(sqlite3.connect(self.store.db_path)) as con, con:
                for statement in statements: con.execute(statement)
                # Restore exactly the original trigger, so malformed row cases
                # reach content/oracle verification with an unchanged schema.
                if statements[0].startswith('DROP TRIGGER '):
                    name = statements[0].split()[-1]
                    con.execute(next(sql for sql in trial.DDL if sql.startswith('CREATE TRIGGER ' + name + ' ')))
            before = pin(self.store.db_path)
            with self.assertRaises(ValueError): self.store.snapshot()
            self.assertEqual(before, pin(self.store.db_path))
            self.store.db_path.write_bytes(original)  # newly-created fault target only
        raw = self.lab.db_path.read_bytes()
        try:
            with closing(sqlite3.connect(self.lab.db_path)) as con, con:
                con.execute('DROP TRIGGER annual_career_school_rosters_no_update')
                con.execute('UPDATE career_school_rosters SET payload_json="{}" WHERE year=2027')
            before = pin(self.lab.db_path)
            with self.assertRaises(ValueError): self.store.snapshot()
            self.assertEqual(before, pin(self.lab.db_path))
        finally: self.lab.db_path.write_bytes(raw)  # self-created destructive fixture only

    def test_independent_scenario_seed_changes_draw_or_events_and_contract(self):
        owner = tempfile.TemporaryDirectory(prefix='stage116-alternate-')
        with owner:
            other = trial.FictionalTournamentStore(self.lab, owner, self.request,
                scenario_seed=trial.SEED+3, fictional_opt_in=True)
            try:
                a, b = self.store.next_input(), other.next_input()
                self.assertNotEqual(a.contract_sha256, b.contract_sha256)
                self.assertNotEqual(_run(a, a.match_seed).events, _run(b, b.match_seed).events)
                with self.assertRaises(ValueError): self.store.append(b, _run(b, b.match_seed))
                # This independent seed actually gives the joint entry a win.
                # Verify both branches (the default trial gives it a loss).
                joint_id = self.request.entries.teams[2].entry_team_id
                other.play_next()
                alternate = other.snapshot()
                self.assertEqual(1, alternate.team(joint_id)['wins'])
                for sid, _ in self.request.entries.teams[2].programs:
                    school = alternate.school(sid)
                    self.assertEqual((0, 0), (school['standalone_wins'], school['standalone_losses']))
                MEASUREMENTS['joint_winning_seed'] = dict(scenario_seed=trial.SEED+3,
                    joint_wins=1, school_standalone_wins=0, school_standalone_losses=0,
                    score=[alternate.results[0].team1_score, alternate.results[0].team2_score])
            finally: other.close()
