"""Fast v3 contracts only; real runners/fault matrix use a dedicated workflow."""
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from phase2_engine import saved_fictional_bracket_v3 as v3
from phase2_engine import saved_fictional_bracket as v2
from phase2_engine import yamanashi_demo_store as guards

ROOT = Path(__file__).resolve().parents[1]
BASE = 'e4151e0fcb0dc969ec2f3a859c10ce9fa1db568e'


class Stage119CContractTests(unittest.TestCase):
    def test_legacy_sources_bytes_unchanged(self):
        for name in ('saved_fictional_tournament.py', 'saved_fictional_bracket.py',
                     'fictional_scenario_history.py', 'fictional_bracket.py',
                     'fictional_bracket_oracle.py', 'registered_match_driver.py'):
            path = 'phase2_engine/' + name
            self.assertEqual(subprocess.check_output(['git', 'show', BASE + ':' + path], cwd=ROOT),
                             (ROOT / path).read_bytes(), path)

    def test_ddl_is_strict_append_only_and_indexes_queries(self):
        with closing(sqlite3.connect(':memory:')) as con:
            for sql in v3.DDL:
                con.execute(sql)
            con.execute("INSERT INTO v3_contract VALUES (1,'{}','h')")
            for table in v3.TABLES:
                for verb in ('UPDATE', 'DELETE'):
                    sql = f'{verb} {table}' if verb == 'DELETE' else f'UPDATE {table} SET rowid=rowid'
                    # Empty tables do not fire triggers; inspect exact installed triggers too.
                    self.assertIn((table + '_' + verb.lower(),), con.execute(
                        "SELECT name FROM sqlite_schema WHERE type='trigger'").fetchall())
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE v3_contract SET payload='other'")
            for query, index in (("SELECT * FROM v3_players WHERE match_id='m'", 'v3_players_match'),
                                 ("SELECT * FROM v3_players WHERE player_id='p'", 'sqlite_autoindex'),
                                 ('SELECT * FROM v3_matches WHERE sequence BETWEEN 2 AND 9', 'INTEGER PRIMARY KEY')):
                self.assertIn(index, str(con.execute('EXPLAIN QUERY PLAN ' + query).fetchall()))
            self.assertIn('previous_chain_sha256', v3.BracketMatchInput.__dataclass_fields__)
            self.assertNotIn('previous_results_sha256', v3.BracketMatchInput.__dataclass_fields__)

    def test_header_and_names_reject_cross_version_without_writes(self):
        for cls, db, lease, app, version in ((v3.FictionalBracketStore, v3.DATABASE, v3.LEASE, 0, 0),
                                           (v2.FictionalBracketStore, v3.DATABASE, v3.LEASE, v3.APPLICATION_ID, 3)):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path = root / db
                with closing(sqlite3.connect(path)) as con:
                    con.execute('CREATE TABLE x (a)')
                    con.execute(f'PRAGMA application_id={app}')
                    con.execute(f'PRAGMA user_version={version}')
                (root / lease).write_bytes(b'0')
                obj = cls.__new__(cls)
                obj.db_path = path
                obj.capability = v3.BracketCapability(str(root), tuple(guards._identity(root)),
                    tuple(guards._identity(path)), tuple(guards._identity(root / lease)), '{}')
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    obj._guard()
                self.assertEqual(before, path.read_bytes())
