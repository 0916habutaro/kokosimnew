"""Windows-first real service/process, SQL oracle and read-only acceptance."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import stage43g97_acceptance_support as lab
from phase2_engine.career_history_slot_session import CareerHistorySlotSession
from phase2_engine.career_history_gui_bridge import CareerHistoryGuiBridge
from phase2_engine.career_history_view_projection import project_history_screen
from phase2_engine.career_saved_year_display_labels import CareerSavedYearDisplayLabels
from phase2_engine.career_longitudinal_read import CareerLongitudinalReadModel

METRICS = []


class Stage43G97AcceptanceTests(unittest.TestCase):
    def game(self):
        game = lab.OwnedGame()
        self.addCleanup(game.close)
        return game

    @lab.owned_sqlite_handles()
    def verify_views(self, game, expected):
        before = lab.pin(game.slot)
        session = CareerHistorySlotSession(game.saves, lab.SLOT)
        bridge = session.bridge
        self.assertEqual([2026], [r['year'] for r in bridge.page['data']['years']])
        schools = bridge.open_year(2026)['data']['schools']
        self.assertEqual(8, len(schools))
        labels = CareerSavedYearDisplayLabels(bridge)
        wins = CareerLongitudinalReadModel(game.slot/'historical_matches.sqlite3',
                                         game.slot/'career_rosters.sqlite3')
        visited = set()
        for school in schools:
            sid = school['school_id']
            page = bridge.open_school(2026, sid)['data']
            games = [g for g in expected if sid in (g['team1_id'], g['team2_id'])]
            self.assertEqual(len(games), page['match_total'])
            self.assertEqual({g['match_id'] for g in games}, {g['match_id'] for g in page['match_page']})
            self.assertTrue(labels.school(2026, sid)['historical_name_proven'])
            record = wins.school_results(sid, start_year=2026, end_year=2026)['records'][0]
            self.assertEqual(sum(g['winner_id'] == sid for g in games), record['wins'])
            self.assertEqual(sum(g['loser_id'] == sid for g in games), record['losses'])
            self.assertEqual(len(games), record['games'])
            for link in page['match_detail_targets']:
                expected_game = next(g for g in games if g['match_id'] == link['match_id'])
                detail = bridge.open_link(link['target'])
                raw = detail['data']
                self.assertEqual(2026, raw['selected_year'])
                self.assertEqual('historical_matches_legacy_iso', raw['source'])
                for key in ('team1_id','team2_id','team1_score','team2_score'):
                    self.assertEqual(expected_game[key], raw['match'][key])
                self.assertEqual({k:expected_game[k] for k in lab.DETAILS}, raw['details'])
                for half, team, score in (('top','team1_id','team1_score'), ('bottom','team2_id','team2_score')):
                    innings = [r for r in raw['details']['inning_scores'] if r['half'] == half]
                    self.assertTrue(all(r['batting_team_id'] == expected_game[team] for r in innings))
                    self.assertEqual(expected_game[score], sum(r['runs'] or 0 for r in innings))
                # Every saved detail row must survive presentation.
                projected = project_history_screen(detail, labels=labels)
                self.assertEqual(sum(len(expected_game[k]) for k in lab.DETAILS),
                                 sum(r['kind'] == 'detail' for r in projected['rows']))
                visited.add(expected_game['match_id'])
                bridge.back()
            # One batter and pitcher per school, totals independently summed
            # from pre-save runtime rows, not from the saved stat read model.
            players = {r['player_id'] for g in games for kind in ('batter_stats','pitcher_stats')
                       for r in g[kind] if r['school_id'] == sid}
            chosen = set()
            for kind in ('batter_stats','pitcher_stats'):
                chosen.add(next(r['player_id'] for g in games for r in g[kind] if r['school_id'] == sid))
            self.assertTrue(players)
            for pid in chosen:
                target = next(t['target'] for t in page['player_targets'] if t['player_id'] == pid)
                player = bridge.open_link(target)['data']
                self.assertEqual(2026, player['selected_year'])
                self.assertTrue(labels.player(2026, sid, pid)['exact_year_roster_membership_verified'])
                stat = player['selected_statistics']
                self.assertIsNotNone(stat)
                for kind, label in (('batter_stats','batting'), ('pitcher_stats','pitching')):
                    rows = [r for g in games for r in g[kind] if r['player_id'] == pid and r['school_id'] == sid]
                    self.assertEqual(len(rows), stat[label]['games'])
                    if rows:
                        for field in rows[0]:
                            if type(rows[0][field]) is int and field in stat[label]:
                                self.assertEqual(sum(r[field] for r in rows), stat[label][field], (pid,field))
                bridge.back()
            bridge.back()
        self.assertEqual(7, len(visited))
        self.assertEqual(before, lab.pin(game.slot))

    def test_new_save_process_exit_reopen_finish_seal_register_and_readonly(self):
        for source in ('manual','autosave'):
            with self.subTest(source=source):
                game = self.game()
                expected = game.ready(source)
                self.assertNotEqual(game.initial['pid'], game.finished['pid'])
                self.assertEqual(6, len(game.initial['games']))
                self.assertEqual(7, len(expected))
                self.assertEqual([], CareerHistoryGuiBridge(game.slot).history)
                self.verify_views(game, expected)
                sealed = lab.pin(game.slot)
                again = game.run('reload', source)
                self.assertEqual(expected, again['games'])
                self.assertEqual(sealed, lab.pin(game.slot))
                match_bytes = lab.sql_games(game.slot)
                registered = game.run('register', source)
                self.assertEqual(expected, registered['games'])
                self.assertEqual(match_bytes, lab.sql_games(game.slot))
                self.verify_views(game, expected)
                with closing(sqlite3.connect(game.slot/'historical_matches.sqlite3')) as con:
                    self.assertEqual([(2026,'sealed',7),(2027,'active',None)],
                        con.execute('SELECT year,status,match_count FROM career_years ORDER BY year').fetchall())
                    self.assertEqual(0, con.execute('SELECT COUNT(*) FROM historical_matches WHERE year=2027').fetchone()[0])
                METRICS.append(dict(source=source,initial_matches=6,final_matches=7,
                    separate_process=True,registered_year=2027,next_year_gameplay_started=False,
                    all_match_details_equal=True,school_and_player_oracle_equal=True,read_zero_write=True))

    def test_corrupt_record_rejected_then_original_bytes_retry_readonly(self):
        game = self.game(); expected = game.ready()
        db = game.slot/'historical_matches.sqlite3'; original = db.read_bytes()
        bridge = CareerHistoryGuiBridge(game.slot)
        with closing(sqlite3.connect(db)) as con:
            con.execute("UPDATE historical_matches SET record_sha256='BAD'");con.commit()
        before = lab.pin(game.slot)
        prior = (bridge.route.copy(), bridge.history.copy(), bridge.page)
        with self.assertRaises(ValueError):
            bridge.open_year(2026)
        self.assertEqual(prior, (bridge.route, bridge.history, bridge.page))
        self.assertEqual(before, lab.pin(game.slot))
        # Test-only rollback to bytes captured from this newly owned fixture.
        db.write_bytes(original)
        self.verify_views(game, expected)

    def test_fixture_connections_cleanup_rollback_and_rename(self):
        from phase2_engine.career_roster_archive import CareerRosterArchive
        game = self.game(); expected = game.ready()
        stage96, service, resolver, engine = lab.services(game.root)
        original_connect = sqlite3.connect; handles = []
        def connect(*args, **kwargs):
            con = original_connect(*args, **kwargs); handles.append(con); return con
        try:
            with patch.object(sqlite3, 'connect', connect), lab.owned_sqlite_handles():
                self.verify_views(game, expected)
                resumed = service.load_game(lab.SLOT, source='manual', engine=engine)
                outcomes = stage96.CareerCompetitionOutcomes(game.slot/'historical_matches.sqlite3')
                for run in resumed.state.completed_runs().values():
                    self.assertFalse(outcomes.record_completed(run)['inserted'])
                self.assertTrue(outcomes.previous_results(2026))
                archive = CareerRosterArchive(game.slot/'career_rosters.sqlite3')
                sid = expected[0]['team1_id']
                roster = archive.roster(2026, sid)
                self.assertEqual([2026], archive.school_years(sid))
                archive.save_initial_roster(roster)
                before = lab.pin(game.slot)
                with self.assertRaises(ValueError):
                    archive.advance_and_save(SimpleNamespace(school_id=sid), next_year=2030, career_seed=97)
                self.assertEqual(before, lab.pin(game.slot))
                def fail(con, saved):
                    con.execute('DELETE FROM career_school_rosters')
                    raise OSError('owned fixture interrupted write')
                with patch.object(archive, '_insert', fail):
                    with self.assertRaises(OSError):
                        archive.save_initial_roster(roster)
                self.assertEqual(before, lab.pin(game.slot))
            self.assertTrue(handles)
            for con in handles:
                with self.assertRaises(sqlite3.ProgrammingError):
                    con.execute('SELECT 1')
            moved = game.saves.with_name('終了後 移動');game.saves.rename(moved)
            self.assertEqual(7, len(lab.sql_games(moved/lab.SLOT)))
        finally:
            for con in handles:
                con.close()


if __name__ == '__main__':
    unittest.main()
