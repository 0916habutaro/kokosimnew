"""Fixture-only relocation experiment. No external save/candidate inputs.

All paths originate in Fixture's TemporaryDirectory. The private in-memory
anchor is captured before export and is never reconstructed from evidence.
This module is test tooling, not a product restore API.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from time import perf_counter

from phase2_engine import manual_save_backup as product
from phase2_engine.legacy_backup_oracle import facts, live_and_membership
from phase2_engine.legacy_backup_compatibility import CATALOG
from stage43g94_fixture_support import Fixture, owned_sqlite_handles

METRICS = []


def anchor(root):
    # Own hashing implementation; product evidence is not an expected value.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in product._scan(root) if p.is_file()}


def browse(root):
    """Canonical-only read-only list/detail/school views of EVERY stored game.

    Do not instantiate archive readers whose list_years creates schema.
    No derived school index with absolute source bindings is opened.
    """
    def connection(name):
        con = sqlite3.connect((root/name).as_uri()+'?mode=ro&immutable=1', uri=True)
        con.execute('PRAGMA query_only=ON')
        return con
    with closing(connection('historical_matches.sqlite3')) as con:
        years = con.execute('SELECT year,status,match_count,ledger_sha256 FROM career_years ORDER BY year').fetchall()
        keys = con.execute('SELECT year,competition_id,match_id FROM historical_matches ORDER BY 1,2,3').fetchall()
        details = [json.loads(con.execute('SELECT payload_json FROM historical_matches '
            'WHERE year=? AND competition_id=? AND match_id=?', key).fetchone()[0]) for key in keys]
        schools = sorted({p[k] for p in details for k in ('team1_id','team2_id')})
        school_games = {s: con.execute('SELECT year,competition_id,match_id FROM historical_matches '
            'WHERE team1_id=? OR team2_id=? ORDER BY 1,2,3', (s,s)).fetchall() for s in schools}
    with closing(connection('career_rosters.sqlite3')) as con:
        rosters = [json.loads(r[0]) for r in con.execute('SELECT payload_json FROM career_school_rosters ORDER BY year,school_id')]
        identities = con.execute('SELECT player_id,identity_json FROM career_player_identities ORDER BY player_id').fetchall()
    return dict(years=years, details=details, school_games=school_games, rosters=rosters, identities=identities)


def copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open('rb') as inp, dst.open('xb') as out:
        shutil.copyfileobj(inp, out)


class Experiment:
    def __init__(self, phase='active', source='manual', extended=False):
        with owned_sqlite_handles():
            self.fixture = Fixture(phase)
        f = self.fixture
        if extended:
            from phase2_engine.historical_match_archive import HistoricalMatchArchive
            archive = HistoricalMatchArchive(f.slot/'historical_matches.sqlite3')
            archive.seal_year(2027, expected_match_count=0)
            body = json.loads((f.slot/'manual.json').read_text(encoding='utf-8'))
            archive.register_next_year(year=2028,rng_seed=body['rng_seed'],
                resolver_contract=body['resolver_contract'],plan_fingerprint='stage95-registration-only')
        self.source = source
        self.target = f.root/'isolated'
        self.source_pin = anchor(f.slot)
        self.sql = facts(f.slot)
        self.views = browse(f.slot)
        repo = Path(__file__).resolve().parents[1]
        compatibility = {n:hashlib.sha256((repo/n).read_bytes()).hexdigest() for n in CATALOG}
        self.phase = phase
        start = perf_counter()
        self.export = product.export_backup(**f.args(source=source))
        product.verify_candidate(candidate=f.destination)
        payload = f.destination/'payload'/'owned94'
        if facts(payload) != self.sql or browse(payload) != self.views:
            raise product.BackupRefused('untrusted_needs_manual_review')
        copied = anchor(payload)
        wanted = {n:v for n,v in self.source_pin.items() if not product.DERIVED.fullmatch(n)}
        if (set(copied) != set(wanted) or any(copied[n] != wanted[n]
                for n in wanted if n not in product.TABLES)
                or anchor(f.destination/'compatibility') != compatibility):
            raise product.BackupRefused('untrusted_needs_manual_review')
        if anchor(f.slot) != self.source_pin:
            raise product.BackupRefused('source_changed')
        self.pin = anchor(f.destination)
        self.export_seconds = perf_counter()-start

    def close(self):
        self.fixture.close()

    def trusted(self, root):
        if anchor(root) != self.pin:
            raise product.BackupRefused('untrusted_needs_manual_review')
        result = product.verify_candidate(candidate=root)
        payload = root/'payload'/'owned94'
        if facts(payload) != self.sql or browse(payload) != self.views:
            raise product.BackupRefused('untrusted_needs_manual_review')
        live_and_membership(payload, self.source)
        if anchor(root) != self.pin:
            raise product.BackupRefused('untrusted_needs_manual_review')
        return result

    def relocate(self, *, measure=False):
        """Only this experiment's owned candidate and new isolated target."""
        f = self.fixture
        def run():
            start = perf_counter()
            src, dst = product._path(f.destination), product._path(self.target)
            # Constrain even test-internal target overrides to owned temp space.
            if dst.parent != f.root or dst == f.root or dst == f.save_root:
                raise product.BackupRefused('output_not_isolated')
            if any(dst == p or dst.is_relative_to(p) or p.is_relative_to(dst)
                   for p in (src, f.save_root, Path(__file__).resolve().parents[1])):
                raise product.BackupRefused('output_not_isolated')
            if os.path.lexists(dst):
                raise product.BackupRefused('destination_exists')
            self.trusted(src)
            if anchor(f.slot) != self.source_pin:
                raise product.BackupRefused('source_changed')
            dst.mkdir(mode=0o700)  # exclusive reservation; no rename/replace
            try:
                for name in sorted(self.pin):
                    if name != 'COMPLETE':
                        copy_file(src/name, dst/name)
                wanted = {n:v for n,v in self.pin.items() if n != 'COMPLETE'}
                if anchor(dst) != wanted or anchor(src) != self.pin:
                    raise product.BackupRefused('changed_during_copy')
                if facts(dst/'payload'/'owned94') != self.sql or browse(dst/'payload'/'owned94') != self.views:
                    raise product.BackupRefused('untrusted_needs_manual_review')
                # Never propagate an early receipt from the source.
                copy_file(src/'COMPLETE', dst/'COMPLETE')
                self.trusted(dst)
                if anchor(src) != self.pin or anchor(f.slot) != self.source_pin:
                    raise product.BackupRefused('changed_before_completion')
            except BaseException:
                # Revoke only our newly written completion receipt, retain data.
                (dst/'COMPLETE').unlink(missing_ok=True)
                raise
            metric = dict(phase=self.phase, source=self.source, fixture_only=True,
                source_zero_write=True, candidate_zero_write=True, no_clobber=True,
                sql_equal=True, sha_equal=True, read_only_equal=True,
                compatibility_files=338, matches=len(self.views['details']),
                years=len(self.views['years']), rosters=len(self.views['rosters']),
                export_seconds=round(self.export_seconds,6), seconds=round(perf_counter()-start,6),
                source_bytes=self.export['source_slot_bytes'], candidate_bytes=self.export['candidate_total_bytes'],
                isolated_bytes=sum(p.stat().st_size for p in product._scan(dst) if p.is_file()),
                restoration_authorized=False, whole_game_restore_proven=False)
            if measure:
                METRICS.append(metric)
            return metric
        return product._safe_call(run)
