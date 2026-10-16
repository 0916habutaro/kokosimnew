"""Real saved full31 seal, annual lineage, read-only independent SQL/JSON oracles."""
from collections import Counter
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from phase2_engine import yamanashi_annual_rosters as annual
from phase2_engine import yamanashi_demo_store as demo
from phase2_engine.career_roster_archive import CareerRosterArchive
from stage43g99_fixture_support import retained_handles, assert_closed
from stage43g111_support import worker_input, run_worker

MEASUREMENTS = {}


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sql(path, statement, args=()):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        return con.execute(statement, args).fetchall()


class AnnualRosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_owner = tempfile.TemporaryDirectory(prefix='stage111-selfcreated2026-')
        cls.addClassCleanup(cls.source_owner.cleanup)
        cls.source = annual.SelfCreated2026(cls.source_owner, opt_in=True)
        cls.addClassCleanup(lambda: cls.source.close())
        began = perf_counter()
        cls.refused = []
        # Real writer reaches 0/1/16/30/31; no complete flag fixture.
        for count in range(32):
            if count in (0, 1, 16, 30):
                with tempfile.TemporaryDirectory(prefix='stage111-refused-target-'):
                    owner = tempfile.TemporaryDirectory(prefix='stage111-empty-target-')
                    try:
                        before = cls.source._evidence()
                        try:
                            annual.AnnualRosterLab(cls.source, owner, opt_in=True)
                        except ValueError:
                            cls.refused.append(count)
                        else:
                            raise AssertionError('incomplete source accepted')
                        assert before == cls.source._evidence() and not list(Path(owner.name).iterdir())
                    finally:
                        owner.cleanup()
            if count < 31:
                cls.source.store.play_next()
        cls.snapshot, cls.contract = cls.source.verified()
        cls.source_pin = cls.source._evidence()
        MEASUREMENTS['source'] = dict(seconds=round(perf_counter() - began, 6), matches=31,
            schools=33, permanent_players=660, tournament_teams=32, registered_slots=640,
            database_bytes=cls.source.store.db_path.stat().st_size, refused_incomplete_counts=cls.refused)

    def setUp(self):
        self.target_owner = tempfile.TemporaryDirectory(prefix='stage111-new-annual-')
        self.addCleanup(self.target_owner.cleanup)
        self.lab = annual.AnnualRosterLab(self.source, self.target_owner, opt_in=True)
        self.addCleanup(lambda: self.lab.close())

    def tearDown(self):
        self.assertEqual(self.source_pin, self.source._evidence())

    def test_full33_saved_source_lineage_sql_json_sha_and_all924_cross_year_reads(self):
        self.assertEqual([0, 1, 16, 30], self.refused)
        began = perf_counter()
        with retained_handles() as handles:
            result = self.lab.advance()
            self.assertTrue(result['accepted'])
            assert_closed(self, handles)
        elapsed = perf_counter() - began
        before = pin(self.lab.db_path)
        with retained_handles() as handles:
            view = self.lab.browse()
            assert_closed(self, handles)
        with closing(sqlite3.connect(self.source.store.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            old = {sid: json.loads(raw) for sid, raw in con.execute('SELECT school_id,payload_json FROM school_rosters')}
        rows = sql(self.lab.db_path, 'SELECT year,school_id,payload_json,content_sha256 FROM career_school_rosters')
        saved = {}
        for year, sid, raw, sha in rows:
            self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), sha)
            saved[year, sid] = json.loads(raw)
        lineage = dict((pid, (sid, state, prev, nxt)) for pid, sid, state, prev, nxt in
                      sql(self.lab.db_path, 'SELECT * FROM annual_lineage'))
        self.assertEqual(Counter(graduated=264, returning=396, newcomer=264), Counter(v[1] for v in lineage.values()))
        registered = {p.player_id for t in self.snapshot.registration.teams for p in t.players}
        old_ids = set()
        new_ids = set()
        for sid, prior in old.items():
            self.assertEqual(prior, saved[2026, sid])
            after = saved[2027, sid]
            pmap = {p['player_id']: p for p in after['players']}
            self.assertEqual(20, len(pmap))
            self.assertEqual(Counter({1: 8, 2: 5, 3: 7}), Counter(p['academic_year'] for p in pmap.values()))
            for p in prior['players']:
                pid = p['player_id']; old_ids.add(pid)
                state = lineage[pid][1]
                self.assertEqual(hashlib.sha256(annual.codec.canonical(p).encode()).hexdigest(), lineage[pid][2])
                if p['academic_year'] == 3:
                    self.assertNotIn(pid, pmap)
                    self.assertEqual('graduated', state)
                    slot = p['roster_no']
                    expected_id = 'PLY' + hashlib.sha256(f'430103:player_career_newcomer_v1:2027:{sid}:{slot}'.encode()).hexdigest()[:20].upper()
                    fresh = pmap[expected_id]; new_ids.add(expected_id)
                    self.assertEqual((sid, 2027, 1, slot, p['primary_position']),
                        (fresh['school_id'], fresh['entry_year'], fresh['academic_year'], fresh['roster_no'], fresh['primary_position']))
                else:
                    self.assertEqual({**p, 'academic_year': p['academic_year'] + 1}, pmap[pid])
                    self.assertEqual('returning', state)
            for year in (2026, 2027):
                school = view.school(sid, year=year)
                self.assertEqual(saved[year, sid], school['roster'])
                self.assertIsNone(school['school_standalone_outcomes'])
                self.assertEqual((), school['matches'] if year == 2027 else ())
                if year == 2026:
                    self.assertTrue(school['matches'])
                    for team in school['participating_teams']:
                        if team['joint']:
                            self.assertEqual(('SCH000202', 'SCH000220'), team['school_ids'])
                            self.assertTrue(all(r['team_id'].endswith(':joint') for r in school['team_outcomes']))
        self.assertEqual((660, 264, 0), (len(old_ids), len(new_ids), len(old_ids & new_ids)))
        self.assertEqual(924, sql(self.lab.db_path, 'SELECT count(*) FROM career_player_identities')[0][0])
        # Independent JSON summation for every permanent identity, including 20 unregistered players.
        for pid in old_ids | new_ids:
            old_view = view.player(pid, year=2026); new_view = view.player(pid, year=2027)
            self.assertEqual((), new_view['appearances'])
            self.assertEqual({'batting': {}, 'pitching': {}}, new_view['totals'])
            self.assertEqual('not_scheduled_not_played', new_view['tournament_status'])
            if pid in new_ids:
                self.assertEqual('not_yet_enrolled', old_view['state'])
                self.assertIsNone(old_view['profile'])
                self.assertFalse(old_view['appearances'])
                continue
            totals = {'batting': {}, 'pitching': {}}
            for game in self.snapshot.results:
                for kind, attr in (('batting', 'batter_stats'), ('pitching', 'pitcher_stats')):
                    for row in getattr(game, attr):
                        if row.player_id == pid:
                            for key, value in asdict(row).items():
                                if type(value) is int and key != 'year':
                                    totals[kind][key] = totals[kind].get(key, 0) + value
            self.assertEqual(totals, old_view['totals'])
            self.assertEqual('graduated' if lineage[pid][1] == 'graduated' else 'active', new_view['state'])
            self.assertEqual(old_view['origin_school_id'], new_view['origin_school_id'])
            if pid not in registered:
                self.assertFalse(old_view['appearances'])
        self.assertEqual(before, pin(self.lab.db_path))
        self.assertEqual(33, sql(self.lab.db_path, '''SELECT count(*) FROM (
            SELECT school_id FROM career_school_rosters WHERE year=2027 AND json_array_length(payload_json,'$.players')=20)''')[0][0])
        self.lab.close()
        moved = self.lab.db_path.with_suffix('.released')
        self.lab.db_path.rename(moved); moved.rename(self.lab.db_path)
        self.lab = annual.AnnualRosterLab.resume(self.lab.capability, self.source)
        self.assertEqual(before, pin(self.lab.db_path))
        self.assertTrue(self.lab.status()['accepted'])
        MEASUREMENTS['rollover'] = dict(seconds=round(elapsed, 6), database_bytes=self.lab.db_path.stat().st_size,
            graduated=264, returning=396, newcomers=264, active=660, browsed_identities=924,
            source_bytes_unchanged=True, readonly_bytes_unchanged=True, native_handles_closed=True)

    def test_partial_process_restart_after_commit_crash_same_ids_idempotence(self):
        self.assertFalse(self.lab.advance(limit=1)['accepted'])
        before = pin(self.lab.db_path)
        with self.assertRaises(ValueError): self.lab.browse()
        self.assertEqual(before, pin(self.lab.db_path))
        payload = worker_input(self.source, self.lab)
        cap = self.source.capability
        self.lab.close(); self.source.close()
        try:
            with tempfile.TemporaryDirectory(prefix='stage111-private-transport-') as private:
                run_worker(payload, Path(private), limit=1, crash='school_committed')
                resumed = run_worker(payload, Path(private))
                self.assertTrue(resumed['accepted']); self.assertEqual(33, resumed['browsed_schools'])
        finally:
            type(self).source = annual.SelfCreated2026.resume(cap)
        self.lab = annual.AnnualRosterLab.resume(self.lab.capability, self.source)
        before = pin(self.lab.db_path)
        self.assertTrue(self.lab.advance()['accepted'])
        self.assertEqual(before, pin(self.lab.db_path))
        self.assertEqual(924, sql(self.lab.db_path, 'SELECT count(*) FROM career_player_identities')[0][0])
        # A real interrupted SQLite acceptance transaction remains dirty and is never recovered.
        with tempfile.TemporaryDirectory(prefix='stage111-crash-target-') as temp:
            owner = tempfile.TemporaryDirectory(prefix='stage111-dirty-target-')
            dirty = annual.AnnualRosterLab(self.source, owner, opt_in=True)
            payload = worker_input(self.source, dirty)
            dirty.close(); self.source.close()
            try:
                run_worker(payload, Path(temp), crash='before_acceptance_commit')
            finally:
                type(self).source = annual.SelfCreated2026.resume(cap)
            try:
                journal = Path(str(dirty.db_path) + '-journal')
                self.assertGreater(journal.stat().st_size, 512)
                unchanged = {p.name: pin(p) for p in dirty.db_path.parent.iterdir()}
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('never recover hot journal')):
                    with self.assertRaises(ValueError): annual.AnnualRosterLab.resume(dirty.capability, self.source)
                self.assertEqual(unchanged, {p.name: pin(p) for p in dirty.db_path.parent.iterdir()})
            finally:
                dirty.close(); owner.cleanup()
        MEASUREMENTS['restart'] = dict(exited_worker_resume=True, crash_after_school_commit=True,
            idempotent_bytes_unchanged=True, hot_journal_refused_without_sqlite_open=True,
            os_login_session_restart_verified=False)

    def test_acceptance_transaction_rollback_and_lost_acknowledgement(self):
        def fail_before(at, sid):
            if at == 'before_acceptance_commit': raise RuntimeError('injected pre-commit fault')
        with self.assertRaises(RuntimeError): self.lab.advance(fault=fail_before)
        self.assertEqual((False, 33), (self.lab.status()['accepted'], self.lab.status()['generated_schools']))
        self.assertEqual([], sql(self.lab.db_path, 'SELECT * FROM annual_lineage'))
        self.assertEqual([], sql(self.lab.db_path, 'SELECT * FROM annual_acceptance'))
        with self.assertRaises(ValueError): self.lab.browse()
        def fail_after(at, sid):
            if at == 'after_acceptance_commit': raise RuntimeError('lost acknowledgement')
        with self.assertRaises(RuntimeError): self.lab.advance(fault=fail_after)
        self.assertTrue(self.lab.status()['accepted'])
        before = pin(self.lab.db_path)
        self.assertTrue(self.lab.advance()['accepted']); self.assertEqual(before, pin(self.lab.db_path))

    def test_source_schema_marker_duplicate_json_seed_corruption_and_other_demo_refused(self):
        source = self.source.store
        db, marker = source.db_path, source.db_path.parent / demo.MARKER
        original, marker_raw = db.read_bytes(), marker.read_bytes()
        def refused():
            before = self.source._evidence(); target = pin(self.lab.db_path)
            with self.assertRaises((ValueError, sqlite3.DatabaseError)): self.lab.advance()
            self.assertEqual(before, self.source._evidence()); self.assertEqual(target, pin(self.lab.db_path))
        try:
            for content in (marker_raw + b' ', b'{"version":1,"version":1}'):
                marker.write_bytes(content)
                with self.assertRaises(ValueError): self.lab.advance()
                self.assertEqual(content, marker.read_bytes())
            marker.write_bytes(marker_raw)
            for alteration in ('extra_schema', 'wrong_seed', 'duplicate_json', 'roster_origin', 'missing_rank'):
                with closing(sqlite3.connect(db)) as con, con:
                    if alteration == 'extra_schema':
                        con.execute('CREATE TABLE unexpected(x)')
                    else:
                        table = 'school_rosters' if alteration == 'roster_origin' else ('team_ranks' if alteration == 'missing_rank' else 'matches')
                        action = 'delete' if alteration == 'missing_rank' else 'update'
                        trigger = con.execute('SELECT sql FROM sqlite_master WHERE name=?', (f'{table}_no_{action}',)).fetchone()[0]
                        con.execute(f'DROP TRIGGER {table}_no_{action}')
                        if alteration == 'missing_rank':
                            con.execute('DELETE FROM team_ranks WHERE rowid=(SELECT min(rowid) FROM team_ranks)')
                        elif alteration == 'roster_origin':
                            raw = con.execute('SELECT payload_json FROM school_rosters LIMIT 1').fetchone()[0]
                            data = json.loads(raw); data['players'][0]['school_id'] = 'SCH000001'
                            raw = annual.codec.canonical(data)
                            con.execute('UPDATE school_rosters SET payload_json=?,sha256=? WHERE rowid=(SELECT min(rowid) FROM school_rosters)', (raw, annual.codec.digest(raw)))
                        else:
                            raw = con.execute('SELECT result_json FROM matches LIMIT 1').fetchone()[0]
                            data = json.loads(raw); data['run_seed'] += 1
                            raw = annual.codec.canonical(data) if alteration == 'wrong_seed' else raw[:-1] + ',"year":2026}'
                            con.execute('UPDATE matches SET result_json=?,result_sha256=? WHERE rowid=(SELECT min(rowid) FROM matches)', (raw, annual.codec.digest(raw)))
                        con.execute(trigger)
                refused()
                db.write_bytes(original)  # reset only the newly self-generated fault fixture, never a user save
        finally:
            marker.write_bytes(marker_raw); db.write_bytes(original)
        other = demo.DemoStore.create(source.capability.namespace, opt_in=True)
        try:
            bad = annual._AnnualCapability(**{**asdict(self.lab.capability), 'source': annual._SourceCapability(
                self.source.capability.root, self.source.capability.root_identity, other.demo_id)})
            with self.assertRaises(ValueError): annual.AnnualRosterLab.resume(bad, self.source)
        finally: other.close()

    def test_target_tampering_gaps_partial_acceptance_and_identity_refuse_without_repair(self):
        self.lab.advance(limit=2)
        original = self.lab.db_path.read_bytes()
        try:
            for table, statement in (
                ('career_school_rosters', 'DELETE FROM career_school_rosters WHERE year=2027 AND school_id="SCH000196"'),
                ('career_player_identities', 'UPDATE career_player_identities SET entry_year=2027 WHERE rowid=1'),
                ('annual_contract', 'UPDATE annual_contract SET sha256="unknown"'),
                ('annual_acceptance', 'INSERT INTO annual_acceptance VALUES (2027,"{}","bad")'),
                ('annual_lineage', 'INSERT INTO annual_lineage VALUES ("fake","SCH000196","newcomer",NULL,"bad")')):
                with closing(sqlite3.connect(self.lab.db_path)) as con, con:
                    action = 'delete' if statement.startswith('DELETE') else 'update'
                    name = f'annual_{table}_no_{action}'
                    trigger = con.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
                    con.execute(f'DROP TRIGGER {name}'); con.execute(statement); con.execute(trigger)
                before = pin(self.lab.db_path)
                with self.assertRaises(ValueError): self.lab.advance()
                self.assertEqual(before, pin(self.lab.db_path))
                self.lab.db_path.write_bytes(original)
        finally: self.lab.db_path.write_bytes(original)

    def test_capability_opt_in_wrong_seed_link_sidecar_lock_conflict_and_scope(self):
        before = pin(self.lab.db_path)
        for seed in (430104, True, '430103'):
            with self.assertRaises(ValueError): self.lab.advance(career_seed=seed)
        for limit in (0, 34, True):
            with self.assertRaises(ValueError): self.lab.advance(limit=limit)
        with patch('game_core.career_rosters._newcomer_id', return_value=self.snapshot.rosters[0].players[0].player_id):
            with self.assertRaises(ValueError): self.lab.advance()
        with self.assertRaises(ValueError): annual.AnnualRosterLab(self.source, self.target_owner)
        with self.assertRaises(ValueError): annual.AnnualRosterLab.resume(self.lab.db_path, self.source)
        with self.assertRaises(ValueError): annual.SelfCreated2026.resume(self.source.store.db_path)
        with self.assertRaises(ValueError): annual.AnnualRosterLab.resume(self.lab.capability, self.source)
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(self.lab.db_path) + suffix); sidecar.write_bytes(b'no recovery')
            try:
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('no SQLite open')):
                    with self.assertRaises(ValueError): self.lab._guard()
                self.assertEqual(b'no recovery', sidecar.read_bytes())
            finally: sidecar.unlink()  # test-created sidecar only
        with tempfile.TemporaryDirectory(prefix='stage111-hardlink-') as temp:
            link = Path(temp) / 'hardlink'
            os.link(self.lab.db_path, link)
            try:
                with self.assertRaises(ValueError): self.lab.status()
            finally: link.unlink()
        with closing(sqlite3.connect(self.lab.db_path)) as con:
            con.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError): self.lab.status()
            con.rollback()
        self.assertEqual(before, pin(self.lab.db_path))
        self.lab.advance()
        view = self.lab.browse()
        for year in (2028, True, '2027'):
            with self.assertRaises(ValueError): view.school('SCH000196', year=year)
        with self.assertRaises(ValueError): view.player('unknown', year=2027)
        with self.assertRaises(ValueError): view.school('unknown', year=2027)
        # Read-only annual and source API never expose a 2027 match/schedule/eligibility constructor.
        self.assertFalse(hasattr(self.lab, 'play_next'))

    def test_roster_only_two_centuries_streamed_active20_permanent_id_continuity(self):
        # Separate single-school roster-only archive: no 2027 game or 2028 career acceptance.
        began = perf_counter()
        with tempfile.TemporaryDirectory(prefix='stage111-roster-only-') as temp:
            db = Path(temp) / 'roster-only.sqlite3'
            archive = CareerRosterArchive(db)
            initial = self.snapshot.rosters[0]
            archive.save_initial_roster(initial)
            team = self.snapshot.repo.team(initial.school_id)
            prior = {p.player_id: p for p in initial.players}
            seen = set(prior)
            for year in range(2027, 2227):
                archive.advance_and_save(team, next_year=year, career_seed=430103)
                roster = archive.roster(year, initial.school_id)
                current = {p.player_id: p for p in roster.players}
                self.assertEqual(20, len(current))
                for pid, p in prior.items():
                    if p.academic_year == 3: self.assertNotIn(pid, current)
                    else: self.assertEqual({**p.to_dict(), 'academic_year': p.academic_year + 1}, current[pid].to_dict())
                self.assertFalse((set(current) - set(prior)) & seen)
                seen.update(current); prior = current
            for p in initial.players:
                history = archive.player_history(p.player_id)
                self.assertLessEqual(len(history), 3)
                self.assertEqual(2026, history[0]['year'])
            size = db.stat().st_size
            self.assertEqual(len(seen), sql(db, 'SELECT count(*) FROM career_player_identities')[0][0])
        MEASUREMENTS['roster_only_200_years'] = dict(school_count=1, snapshots=201, last_year=2226,
            seconds=round(perf_counter() - began, 6), database_bytes=size, permanent_players=len(seen),
            active_players=20, games_generated=0, game_years_accepted=0)
