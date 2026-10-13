"""Native product handles retained across success/rollback/error boundaries."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine.career_roster_archive import CareerRosterArchive, CareerRosterConflictError
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes, CareerOutcomeConflictError
from phase2_engine.career_history_browse_model import CareerHistoryBrowseModel
from phase2_engine.career_longitudinal_read import CareerLongitudinalReadModel, CareerHistoryViewConflict, _iter_school_games
from phase2_engine.career_player_records import CareerPlayerRecordView
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from stage43g94_fixture_support import Fixture, owned_sqlite_handles
from stage43g95_isolated_harness import anchor
from stage43g97_acceptance_support import services, actual_runtime, sql_games
from stage43g99_fixture_support import ROOT, retained_handles, assert_closed, rename_and_read


class Stage43G99LifetimeTests(unittest.TestCase):
    def fixture(self):
        with owned_sqlite_handles():
            f = Fixture('sealed')
        self.addCleanup(f.close)
        return f

    def test_sqlite_with_commits_without_close_and_native_windows_rename_refusal(self):
        with tempfile.TemporaryDirectory(prefix='stage99-native-leak-') as temp:
            path = Path(temp)/'使用中.sqlite3'
            con = sqlite3.connect(path)
            try:
                with con:
                    con.execute('CREATE TABLE proof(value INTEGER)')
                    con.execute('INSERT INTO proof VALUES(1)')
                self.assertEqual([(1,)], con.execute('SELECT value FROM proof').fetchall())
                before = path.read_bytes()
                if sys.platform == 'win32':
                    with self.assertRaises(OSError):
                        path.rename(path.with_suffix('.blocked'))
                    self.assertEqual(before, path.read_bytes())
            finally:
                con.close()
            moved = path.with_suffix('.released')
            path.rename(moved)
            with closing(sqlite3.connect(moved)) as reader:
                self.assertEqual([(1,)], reader.execute('SELECT value FROM proof').fetchall())

    def test_same_process_new_save_load_seal_rosters_outcomes_release_without_gc(self):
        with tempfile.TemporaryDirectory(prefix='stage99-product-game-') as temp:
            root = Path(temp).resolve()
            stage96, service, resolver, engine = services(root)
            sid = 'owned99'
            slot = service.slots.slot_dir(sid)
            # All product operations use real connections; no child exit or
            # fixture close wrapper establishes this test's success.
            with retained_handles() as handles:
                session = service.new_game(sid, rng_seed=stage96.SEED, start_date='2026-07-01', engine=engine)
                service.advance_through(session, '2026-07-12')
                service.save_game(session, kind='manual')
                service.save_game(session, kind='autosave')
                assert_closed(self, handles)
                rename_and_read(self, slot)
                before = anchor(slot)
                for source in ('manual', 'autosave'):
                    session = service.load_game(sid, source=source, engine=engine)
                    self.assertEqual(before, anchor(slot))
                    assert_closed(self, handles)
                    rename_and_read(self, slot)
                service.advance_through(session, '2026-12-31')
                expected = actual_runtime(session)
                service.finalize_season(session)
                rosters = CareerRosterArchive(slot/'career_rosters.sqlite3')
                for roster in resolver._roster_cache.values():
                    self.assertTrue(rosters.save_initial_roster(roster)['inserted'])
                    self.assertFalse(rosters.save_initial_roster(roster)['inserted'])
                outcomes = CareerCompetitionOutcomes(slot/'historical_matches.sqlite3')
                for run in session.state.completed_runs().values():
                    self.assertTrue(outcomes.record_completed(run)['inserted'])
                    self.assertFalse(outcomes.record_completed(run)['inserted'])
                self.assertTrue(outcomes.previous_results(2026))
                service.save_game(session, kind='manual')
                service.save_game(session, kind='autosave')
                assert_closed(self, handles)
                rename_and_read(self, slot)
            stored = sql_games(slot)
            from stage43g97_acceptance_support import KEYS, DETAILS
            self.assertEqual(expected, [{k:r[k] for k in KEYS+DETAILS} for r in stored])
            self.assertEqual(7, len(stored))

    def test_roster_read_advance_idempotency_conflict_and_transaction_rollback(self):
        f = self.fixture()
        path = f.slot/'career_rosters.sqlite3'
        archive = CareerRosterArchive(path)
        with closing(sqlite3.connect(path)) as con:
            sid = con.execute('SELECT school_id FROM career_school_rosters ORDER BY school_id LIMIT 1').fetchone()[0]
        before = anchor(f.slot)
        errors = []
        with retained_handles() as handles:
            roster = archive.roster(2026, sid)
            self.assertEqual([2026], archive.school_years(sid))
            self.assertTrue(archive.player_history(roster.players[0].player_id))
            self.assertFalse(archive.save_initial_roster(roster)['inserted'])
            changed = replace(roster, players=[
                replace(roster.players[0], display_name=roster.players[0].display_name+'変更'),
                *roster.players[1:],
            ])
            try:
                archive.save_initial_roster(changed)
            except CareerRosterConflictError as error:
                errors.append(error)  # Keep the traceback and frame alive.
            else:
                self.fail('roster conflict accepted')
            original = archive._insert
            def interrupted(conn, new_roster):
                original(conn, new_roster)
                raise RuntimeError('injected after roster and identity inserts')
            from test_stage43g92_legacy_replay import Stage43G92LegacyReplayTests, SEED
            team = Stage43G92LegacyReplayTests.repo.team(sid)
            with patch.object(archive, '_insert', interrupted):
                try:
                    archive.advance_and_save(team, next_year=2027, career_seed=SEED)
                except RuntimeError as error:
                    errors.append(error)
            self.assertEqual(2, len(errors))
            self.assertEqual(before, anchor(f.slot))
            assert_closed(self, handles)
            rename_and_read(self, f.slot)
            self.assertTrue(archive.advance_and_save(team, next_year=2027, career_seed=SEED)['inserted'])
            self.assertFalse(archive.advance_and_save(team, next_year=2027, career_seed=SEED)['inserted'])
            self.assertEqual([2026,2027], archive.school_years(sid))
            assert_closed(self, handles)
            rename_and_read(self, f.slot)

    def test_outcome_exception_retains_original_bytes_and_releases_archive_handle(self):
        f = self.fixture()
        before = anchor(f.slot)
        outcomes = CareerCompetitionOutcomes(f.slot/'historical_matches.sqlite3')
        errors = []
        with retained_handles() as handles:
            self.assertTrue(outcomes.previous_results(2026))
            try:
                outcomes.previous_results(2099)
            except CareerOutcomeConflictError as error:
                errors.append(error)
            self.assertEqual(1, len(errors))
            assert_closed(self, handles)
            rename_and_read(self, f.slot)
        self.assertEqual(before, anchor(f.slot))

    def test_native_schema_and_transaction_exit_exceptions_still_close(self):
        f = self.fixture()
        before = anchor(f.slot)
        errors = []
        class SchemaFailure(sqlite3.Connection):
            def executescript(self, sql):
                raise sqlite3.OperationalError('owned schema failure')
        class ExitFailure(sqlite3.Connection):
            def __exit__(self, *args):
                super().__exit__(*args)
                raise sqlite3.OperationalError('owned transaction exit failure')
        with retained_handles() as handles:
            archive = CareerRosterArchive(f.slot/'career_rosters.sqlite3')
            sid = next(iter(sql_games(f.slot)))['team1_id']
            roster = archive.roster(2026,sid)
            for factory in (SchemaFailure,ExitFailure):
                def connect():
                    conn = sqlite3.connect(archive.db_path,factory=factory)
                    conn.row_factory = sqlite3.Row
                    return conn
                with patch.object(archive,'_connect',connect):
                    try:
                        archive.save_initial_roster(roster)
                    except sqlite3.OperationalError as error:
                        errors.append(error)
                assert_closed(self,handles)
                rename_and_read(self,f.slot)
            outcomes = CareerCompetitionOutcomes(f.slot/'historical_matches.sqlite3')
            def connect_outcomes():
                return sqlite3.connect(outcomes.archive.db_path,factory=SchemaFailure)
            with patch.object(outcomes.archive,'_connect',connect_outcomes):
                try:
                    outcomes.previous_results(2026)
                except sqlite3.OperationalError as error:
                    errors.append(error)
            self.assertEqual(3,len(errors))
            assert_closed(self,handles)
            rename_and_read(self,f.slot)
        self.assertEqual(before,anchor(f.slot))

    def test_buffered_history_and_multiple_readers_return_detached_values(self):
        f = self.fixture()
        model = CareerHistoryBrowseModel(ROOT/'data', f.slot)
        first = sql_games(f.slot)[0]
        sid = first['team1_id']
        before = anchor(f.slot)
        with retained_handles() as handles:
            years = model.years()
            page = model.match_page(2026, first['competition_id'], first['match_id'])
            players = model._school_players_at_year(2026, sid, limit=100, offset=0)
            longitudinal = CareerLongitudinalReadModel(model.history, model.rosters)
            summary = longitudinal.school_results(sid, start_year=2026, end_year=2026)
            player_index = longitudinal.school_player_index(sid)
            stats = CareerPlayerRecordView(model.history, model.rosters)
            leaders = stats.school_leaders(sid, start_year=2026, end_year=2026, category='batting_hits')
            assert_closed(self, handles)
            rename_and_read(self, f.slot)
            self.assertTrue(years and page and players and summary and player_index and leaders)
        self.assertEqual(before, anchor(f.slot))

    def test_generator_early_close_and_consumer_exception_release_with_retained_frames(self):
        f = self.fixture()
        first = sql_games(f.slot)[0]
        sid = first['team1_id']
        before = anchor(f.slot)
        with retained_handles() as handles:
            rows = _iter_school_games(f.slot/'historical_matches.sqlite3', sid, 2026, 2026)
            self.assertEqual(2026, next(rows)['year'])
            rows.close()
            assert_closed(self, handles)
            stats = CareerPlayerRecordView(f.slot/'historical_matches.sqlite3', f.slot/'career_rosters.sqlite3')
            errors = []
            with patch.object(stats, '_add', side_effect=RuntimeError('consumer failure')):
                try:
                    stats.school_leaders(sid, start_year=2026, end_year=2026, category='batting_hits')
                except RuntimeError as error:
                    errors.append(error)
            self.assertEqual(1, len(errors))
            assert_closed(self, handles)
            rename_and_read(self, f.slot)
        self.assertEqual(before, anchor(f.slot))

    def test_corrupt_stream_and_roster_errors_close_without_repairing_history(self):
        f = self.fixture()
        first = sql_games(f.slot)[0]
        sid = first['team1_id']
        with closing(sqlite3.connect(f.slot/'historical_matches.sqlite3')) as con, con:
            con.execute("UPDATE historical_matches SET record_sha256='corrupt'")
        with closing(sqlite3.connect(f.slot/'career_rosters.sqlite3')) as con, con:
            con.execute("UPDATE career_school_rosters SET content_sha256='corrupt'")
        broken = anchor(f.slot)
        errors = []
        with retained_handles() as handles:
            model = CareerLongitudinalReadModel(f.slot/'historical_matches.sqlite3', f.slot/'career_rosters.sqlite3')
            actions = [lambda:model.school_results(sid,start_year=2026,end_year=2026),
                       lambda:model.rosters.roster(2026,sid),
                       lambda:CareerPlayerRecordView(model.matches,model.rosters).school_leaders(
                           sid,start_year=2026,end_year=2026,category='batting_hits')]
            for action in actions:
                try:
                    action()
                except (CareerHistoryViewConflict, CareerRosterConflictError) as error:
                    errors.append(error)
                else:
                    self.fail('corrupt history accepted')
                assert_closed(self, handles)
                rename_and_read(self, f.slot)
        self.assertEqual(3,len(errors))
        self.assertEqual(broken, anchor(f.slot))


if __name__ == '__main__':
    unittest.main()
