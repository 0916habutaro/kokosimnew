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
            for base in (BASE,'86dee10e90b9224fa53ed43110945a11a6af5546'):
                self.assertEqual(subprocess.check_output(['git','show',base+':'+path],cwd=ROOT),
                                 (ROOT/path).read_bytes(),path)

    def test_only_new_files_are_changed_from_main(self):
        diff=subprocess.check_output(['git','diff','--name-status',BASE],cwd=ROOT,text=True)
        self.assertTrue(all(line.startswith('A\t') for line in diff.splitlines()),diff)

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

    def test_all_public_exceptions_revoke_and_explicit_audit_is_required(self):
        import threading
        from unittest.mock import patch
        obj = v3.FictionalBracketStore.__new__(v3.FictionalBracketStore)
        obj._mutex, obj.closed, obj.state = threading.RLock(), False, 'TRUSTED'
        @v3._public
        def reject(store):
            raise ValueError('bad input')
        with self.assertRaises(ValueError):
            reject(obj)
        self.assertEqual('REVOKED', obj.state)
        with patch.object(obj, '_check_pid'):
            with self.assertRaises(ValueError):
                obj._check_trust()
        obj.invalidate()
        self.assertEqual('REVOKED', obj.state)
        from unittest.mock import Mock
        obj._lease=Mock();obj._lease.close.side_effect=OSError('close fault');obj._pins=None
        with self.assertRaises(OSError):obj.close()
        self.assertEqual('REVOKED',obj.state)
        obj._lease=None;obj.close();self.assertEqual('CLOSED',obj.state)

    def test_manifest_detects_config_master_additions_missing_and_external_reads(self):
        from types import SimpleNamespace
        from phase2_engine import fictional_v3_dependencies as deps
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            lab = SimpleNamespace(capability=SimpleNamespace(root=a),
                                  source=SimpleNamespace(capability=SimpleNamespace(root=b)))
            path = Path(a) / 'source'
            path.write_bytes(b'original')
            manifest = deps.capture(lab)
            import os
            if os.name == 'nt':
                import ctypes
                short = ctypes.create_unicode_buffer(32768)
                get_short_path = ctypes.windll.kernel32.GetShortPathNameW
                get_short_path.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
                get_short_path.restype = ctypes.c_uint32
                self.assertTrue(get_short_path(str(path), short, len(short)))
                # Exercise the native spelling used by subprocess TEMP paths.
                with deps.read_boundary(manifest):
                    self.assertEqual(b'original', Path(short.value).read_bytes())
            paths = {Path(row.path) for row in manifest}
            self.assertTrue(any(p.is_relative_to(ROOT / 'config/match') for p in paths))
            self.assertTrue(any(p.is_relative_to(ROOT / 'data') and p.suffix == '.csv' for p in paths))
            with deps.read_boundary(manifest):
                self.assertEqual(b'original', path.read_bytes())
                with self.assertRaises(ValueError):path.write_bytes(b'forbidden')
                with self.assertRaises(ValueError):sqlite3.connect(path)
                self.assertEqual(b'original',path.read_bytes())
                with self.assertRaises(ValueError):
                    (ROOT / 'README.md').read_bytes()
            import threading
            from unittest.mock import Mock,patch
            obj=v3.FictionalBracketStore.__new__(v3.FictionalBracketStore)
            obj._mutex,obj.closed,obj.state=threading.RLock(),False,'TRUSTED'
            obj.lab,obj._manifest=lab,manifest
            obj._check_trust=Mock()
            obj._prepared=(None,SimpleNamespace(slots=('a','b','c','d')),None,(),'{}')
            obj.request,obj._results,obj._heads=None,(),('0'*64,)
            obj._request_json='{}'
            def unexpected(*args):return (ROOT/'README.md').read_bytes()
            obj._view_class=unexpected
            with patch.object(v3.v1,'decode_request',return_value=None):
                with self.assertRaisesRegex(ValueError,'missing from v3 manifest'):obj.snapshot()
            self.assertEqual('REVOKED',obj.state)
            obj.state='TRUSTED'
            with patch.object(v3,'_input',unexpected):
                with self.assertRaises(ValueError):obj.next_input()
            self.assertEqual('REVOKED',obj.state)
            path.write_bytes(b'changed!')
            with self.assertRaises(ValueError):
                deps.check(lab, manifest)
            path.write_bytes(b'original')
            deps.check(lab, manifest)
            unknown = Path(b) / 'new-reference'
            unknown.write_bytes(b'x')
            with self.assertRaises(ValueError):
                deps.check(lab, manifest)
            unknown.unlink()
            with deps.read_boundary(manifest[:-1]):
                with self.assertRaises(ValueError):
                    Path(manifest[-1].path).read_bytes()

            # Model Windows' locked lease: hashing must use the already owned descriptor.
            with tempfile.TemporaryDirectory() as c:
                lease_path=Path(c)/'session.lease';lease_path.write_bytes(b'0')
                with lease_path.open('r+b',buffering=0) as stream:
                    owned=SimpleNamespace(capability=SimpleNamespace(root=c),source=lab.source,
                        _lease=SimpleNamespace(file=stream),_mutex=threading.RLock(),closed=False)
                    original_sha=deps.annual._sha
                    def no_reopen(p):
                        if p==lease_path:raise AssertionError('locked lease reopened')
                        return original_sha(p)
                    with patch.object(deps.annual,'_sha',no_reopen):
                        captured=deps.capture(owned)
                    self.assertTrue(any(row.path==str(lease_path) for row in captured))
                    self.assertEqual(b'0',deps.lease_bytes(owned))
                    stream.seek(0);stream.write(b'1');stream.seek(0)
                    with self.assertRaises(ValueError):deps.lease_bytes(owned)
                    self.assertEqual(b'1',deps.lease_bytes(owned,require_valid=False))

    def test_anchor_requires_latest_ack_and_chain(self):
        heads = ('0' * 64, '1' * 64, '2' * 64)
        latest = v3.AppendReceipt(2, heads[2], 'f' * 64)
        v3._validate_anchor(latest, (object(), object()), heads)
        with self.assertRaises(ValueError):
            v3._validate_anchor(latest, (object(),), heads[:2])
        # A stale/no anchor cannot reject a valid older prefix.
        v3._validate_anchor(v3.AppendReceipt(1, heads[1], 'e' * 64), (object(),), heads[:2])
        v3._validate_anchor(None, (), heads[:1])
        with self.assertRaises(ValueError):
            v3._validate_anchor(v3.AppendReceipt(True, heads[1], 'e' * 64), (object(),), heads[:2])
        with self.assertRaises(ValueError):
            v3._validate_anchor(v3.AppendReceipt(1, 'a' * 64, 'e' * 64), (object(),), heads[:2])

    def test_dedicated_workflow_and_heavy_cases_are_outside_auto_discovery(self):
        workflow=(ROOT/'.github/workflows/stage119c-fictional-bracket-v3.yml').read_text(encoding='utf-8')
        for needle in ('ubuntu-latest','windows-latest','fail-fast: false','tests/stage43g119c_audit.py',
                       '--require-windows','--old-versions','pull_request','branches: [main]','if: always()'):
            self.assertIn(needle,workflow)
        self.assertFalse(Path('stage43g119c_cases.py').match('test*.py'))
        audit=(ROOT/'tests/stage43g119c_audit.py').read_text(encoding='utf-8')
        self.assertIn('loader.loadTestsFromModule(cases)',audit)
        self.assertEqual(20,len(list((ROOT/'tests').glob('test_stage43g*_compatibility.py'))))

    def test_manifest_binds_directories_even_if_original_file_inodes_are_preserved(self):
        from types import SimpleNamespace
        from phase2_engine import fictional_v3_dependencies as deps
        with tempfile.TemporaryDirectory() as temp:
            parent=Path(temp);a=parent/'a';b=parent/'b';a.mkdir();b.mkdir()
            path=a/'source';path.write_bytes(b'fixed')
            identity=tuple(guards._identity(path))
            lab=SimpleNamespace(capability=SimpleNamespace(root=str(a)),
                                source=SimpleNamespace(capability=SimpleNamespace(root=str(b))))
            manifest=deps.capture(lab)
            a.rename(parent/'old');a.mkdir();(parent/'old/source').rename(path)
            self.assertEqual(identity,tuple(guards._identity(path)))
            with self.assertRaises(ValueError):deps.check(lab,manifest)
