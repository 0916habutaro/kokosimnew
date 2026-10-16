"""Stage111 temporary, self-created 2026 -> 2027 school roster experiment.

No arbitrary source path, product slot, migration, calendar or 2027 match API.
The parent must retain both TemporaryDirectory owners across worker restarts.
Markers/digests establish consistency, never authenticated provenance.
"""
from contextlib import closing
from dataclasses import asdict, dataclass, replace
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading

from game_core.career_rosters import advance_school_roster
from .career_roster_archive import CareerRosterArchive, _SCHEMA, _decode, _identity
from . import yamanashi_demo_store as demo
from . import registered_full_a_lab_store as codec
from .yamanashi_tournament_registration import SCHOOLS, YEAR, ROSTER_SEED
from .yamanashi_tournament_lab import checkpoint
from .joint_tournament_oracle import player_totals

VERSION = 'stage43g111_owned_annual_rosters_v1'
NEXT_YEAR = YEAR + 1
DATABASE = 'annual_rosters.sqlite3'
LEASE = 'annual.lease'
TABLES = ('career_school_rosters', 'career_player_identities',
          'annual_contract', 'annual_lineage', 'annual_acceptance')
EXTRA_DDL = (
    'CREATE TABLE annual_contract (payload_json TEXT PRIMARY KEY, sha256 TEXT NOT NULL) STRICT',
    'CREATE TABLE annual_lineage (player_id TEXT PRIMARY KEY, school_id TEXT NOT NULL, '
    'state TEXT NOT NULL, previous_sha256 TEXT, next_sha256 TEXT) STRICT',
    'CREATE INDEX annual_lineage_school ON annual_lineage(school_id,player_id)',
    'CREATE TABLE annual_acceptance (year INTEGER PRIMARY KEY, payload_json TEXT NOT NULL, sha256 TEXT NOT NULL) STRICT',
) + tuple(f"CREATE TRIGGER annual_{table}_no_{action.lower()} BEFORE {action} ON {table} "
          "BEGIN SELECT RAISE(ABORT, 'append-only annual lab'); END"
          for table in TABLES for action in ('UPDATE', 'DELETE'))


def _sha(path):
    with path.open('rb') as inp:
        return hashlib.file_digest(inp, 'sha256').hexdigest()


def _owner(owner):
    if type(owner) is not tempfile.TemporaryDirectory:
        raise ValueError('自己所有TemporaryDirectoryが必要です。既存保存先は入力できません')
    root = demo._path(owner.name)
    demo._safe(root)
    demo._location(root)
    if any(root.iterdir()):
        raise ValueError('自己所有の空の一時領域が必要です')
    return root


@dataclass(frozen=True)
class _SourceCapability:
    root: str
    root_identity: tuple
    demo_id: str


class SelfCreated2026:
    """Only this factory mints annual source capabilities; never adopts a save."""
    def __init__(self, owner, *, opt_in=False):
        if opt_in is not True:
            raise ValueError('自己生成2026試験への明示opt-inが必要です')
        root = _owner(owner)
        self.owner = owner
        ns = demo.DemoNamespace.create(root / 'fictional2026', opt_in=True)
        self.store = demo.DemoStore.create(ns, opt_in=True)
        self.capability = _SourceCapability(str(root), tuple(demo._identity(root)), self.store.demo_id)

    @classmethod
    def resume(cls, capability):
        if type(capability) is not _SourceCapability:
            raise ValueError('自己生成2026のcapabilityが必要です')
        root = Path(capability.root)
        demo._safe(root)
        if tuple(demo._identity(root)) != capability.root_identity:
            raise ValueError('自己所有領域が差し替わっています')
        value = cls.__new__(cls)
        value.owner, value.capability = None, capability
        value.store = demo.DemoStore.resume(demo.DemoNamespace(root / 'fictional2026'), capability.demo_id)
        return value

    def close(self):
        self.store.close()

    def _evidence(self):
        store = self.store
        store.reader._guard()
        return dict(database=_sha(store.db_path),
                    marker=_sha(store.db_path.parent / demo.MARKER),
                    namespace=_sha(store.capability.namespace.path / demo.ROOT_MARKER))

    def verified(self):
        before = self._evidence()
        snap = self.store.snapshot()  # exact schema, every SQL row, full31 seed/event/bracket replay
        if not snap.complete or len(snap.results) != 31 or len(snap.ranks) != 32:
            raise ValueError('保存された全31試合と最終順位が必要です')
        # Decode the saved school authorities, not the generator's returned objects.
        with closing(sqlite3.connect(self.store.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            rows = con.execute('SELECT school_id,year,payload_json,sha256 FROM school_rosters ORDER BY school_id').fetchall()
        saved = []
        for sid, year, raw, sha in rows:
            roster = _decode(raw)
            if (year != YEAR or sid != roster.school_id or roster.reference_year != YEAR
                    or codec.digest(raw) != sha or codec.canonical(roster.to_dict()) != raw):
                raise ValueError('保存済み学校ロスター正本が違います')
            saved.append(roster)
        if (tuple(r.school_id for r in saved) != SCHOOLS
                or codec.canonical([r.to_dict() for r in saved]) != codec.canonical([r.to_dict() for r in snap.rosters])
                or len({p.player_id for r in saved for p in r.players}) != 660):
            raise ValueError('33校660永久IDの保存正本が必要です')
        if before != self._evidence():
            raise ValueError('2026読取中に保存物が変更されました')
        snap = replace(snap, rosters=tuple(saved))
        contract = dict(version=VERSION, source=self.store.capability.metadata,
                        source_bytes=before, source_checkpoint=checkpoint(snap.results),
                        source_rosters_sha256=codec.digest(codec.canonical([r.to_dict() for r in saved])),
                        next_year=NEXT_YEAR, career_seed=ROSTER_SEED,
                        scope='school_rosters_only_no_2027_tournament')
        return snap, contract


@dataclass(frozen=True)
class _AnnualCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    source: _SourceCapability
    contract_json: str


def _schema(con):
    return tuple(sorted(row[0] for row in con.execute(
        "SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")))


def _expected(snap):
    """At most 33 school transitions; no historical match generation here."""
    transitions = tuple(advance_school_roster(r, snap.repo.team(r.school_id),
                        next_year=NEXT_YEAR, career_seed=ROSTER_SEED) for r in snap.rosters)
    old = {p.player_id: p for r in snap.rosters for p in r.players}
    fresh = [p.player_id for t in transitions for p in t.newcomers]
    if len(fresh) != 264 or len(set(fresh)) != 264 or set(fresh) & old.keys():
        raise ValueError('新入生永久IDの衝突・再利用です')
    lineage = []
    for t in transitions:
        for state, people in (('graduated', t.graduated), ('returning', t.returning), ('newcomer', t.newcomers)):
            for p in people:
                prior = old.get(p.player_id)
                lineage.append((p.player_id, p.school_id, state,
                    codec.digest(codec.canonical(prior.to_dict())) if prior else None,
                    codec.digest(codec.canonical(p.to_dict())) if state != 'graduated' else None))
    return transitions, tuple(sorted(lineage))


class AnnualRosterLab:
    """Separate archive, per-school atomic append, then all33 acceptance.

    An incomplete prefix may be resumed with the same capability and seed.
    Missing schools, inconsistent identities or partial acceptance fail closed.
    """
    def __init__(self, source, owner, *, opt_in=False):
        if type(source) is not SelfCreated2026 or opt_in is not True:
            raise ValueError('自己生成2026と隔離年度試験への明示opt-inが必要です')
        snap, contract = source.verified()  # refuse before creating ANY target
        root = _owner(owner)
        source_root = Path(source.capability.root)
        if root == source_root or root.is_relative_to(source_root) or source_root.is_relative_to(root):
            raise ValueError('2026とは別の自己所有領域が必要です')
        self.owner, self.source = owner, source
        self.db_path = root / DATABASE
        with self.db_path.open('xb'):
            pass
        with (root / LEASE).open('xb') as out:
            out.write(b'0')
        raw = codec.canonical(contract)
        self.capability = _AnnualCapability(str(root), tuple(demo._identity(root)),
            tuple(demo._identity(self.db_path)), tuple(demo._identity(root / LEASE)), source.capability, raw)
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                con.executescript(_SCHEMA)
                for sql in EXTRA_DDL:
                    con.execute(sql)
                with con:
                    con.execute('INSERT INTO annual_contract VALUES (?,?)', (raw, codec.digest(raw)))
            archive = CareerRosterArchive(self.db_path)
            for roster in snap.rosters:
                archive.save_initial_roster(roster)
            self._audit(snap, contract)
            if contract['source_bytes'] != source._evidence():
                raise ValueError('2026のbytesが変更されました')
        except BaseException:
            self.close()
            raise

    def _setup_handles(self):
        self.closed = False
        self._mutex = threading.RLock()
        self._lease = self._pins = None
        root = self.db_path.parent
        try:
            self._pins = demo._WindowsPins((root, self.db_path, root / LEASE))
            self._lease = demo._Lease(root / LEASE)
        except BaseException:
            self.close()
            raise

    @classmethod
    def resume(cls, capability, source):
        if (type(capability) is not _AnnualCapability or type(source) is not SelfCreated2026
                or capability.source != source.capability):
            raise ValueError('同じ自己生成2026の年度capabilityが必要です')
        obj = cls.__new__(cls)
        obj.capability, obj.source, obj.owner = capability, source, None
        obj.db_path = Path(capability.root) / DATABASE
        obj._guard()
        obj._setup_handles()
        try:
            snap, contract = source.verified()
            obj._audit(snap, contract)
        except BaseException:
            obj.close()
            raise
        return obj

    def _guard(self):
        if getattr(self, 'closed', False):
            raise ValueError('年度試験は終了しています')
        root = self.db_path.parent
        demo._safe(root)
        if {p.name for p in root.iterdir()} != {DATABASE, LEASE}:
            raise ValueError('年度試験に未知ファイル・sidecar・未完了保存があります（修復しません）')
        for path, identity in ((root, self.capability.root_identity),
                               (self.db_path, self.capability.file_identity),
                               (root / LEASE, self.capability.lease_identity)):
            demo._safe(path, directory=path == root)
            if tuple(demo._identity(path)) != identity:
                raise ValueError('年度試験の実体が差し替わっています')
        if (root / LEASE).stat().st_size != 1:
            raise ValueError('年度leaseが違います')
        with self.db_path.open('rb') as inp:
            header = inp.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3\0' or header[18:20] != b'\x01\x01':
            raise ValueError('DELETE方式の年度DB以外は接続しません')

    def _audit(self, snap, contract):
        self._guard()
        raw = codec.canonical(contract)
        if raw != self.capability.contract_json:
            raise ValueError('別2026ゲーム・異seed・異正本は拒否します')
        transitions, lineage = _expected(snap)
        before = _sha(self.db_path)
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True, timeout=.1)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            with closing(sqlite3.connect(':memory:')) as schema:
                schema.executescript(_SCHEMA)
                for sql in EXTRA_DDL:
                    schema.execute(sql)
                expected_schema = _schema(schema)
            if (_schema(con) != expected_schema or con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                    or con.execute('PRAGMA foreign_key_check').fetchall()
                    or con.execute('PRAGMA journal_mode').fetchone() != ('delete',)):
                raise ValueError('年度schemaまたは整合性が違います')
            if con.execute('SELECT * FROM annual_contract').fetchall() != [(raw, codec.digest(raw))]:
                raise ValueError('年度出典契約が違います')
            active = con.execute('SELECT school_id FROM career_school_rosters WHERE year=? ORDER BY school_id', (NEXT_YEAR,)).fetchall()
            ids = tuple(s for (s,) in active)
            if ids != SCHOOLS[:len(ids)]:
                raise ValueError('途中年度の学校欠損・競合順序です')
            rosters = (*snap.rosters, *(t.roster for t in transitions[:len(ids)]))
            expected_rosters = sorted((r.reference_year, r.school_id,
                codec.digest(codec.canonical(r.to_dict())), codec.canonical(r.to_dict())) for r in rosters)
            if sorted(con.execute('SELECT * FROM career_school_rosters').fetchall()) != expected_rosters:
                raise ValueError('保存済み年度ロスターが継承正本と違います')
            people = {p.player_id: p for r in rosters for p in r.players}
            identities = sorted((p.player_id, p.school_id, p.entry_year,
                codec.digest(_identity(p)), _identity(p)) for p in people.values())
            if sorted(con.execute('SELECT * FROM career_player_identities').fetchall()) != identities:
                raise ValueError('永久ID・元学校・プロフィールが違います')
            acceptance = con.execute('SELECT * FROM annual_acceptance').fetchall()
            mappings = sorted(con.execute('SELECT * FROM annual_lineage').fetchall())
            summary = dict(year=NEXT_YEAR, schools=33, active=660, graduated=264, returning=396, newcomers=264,
                source_contract_sha256=codec.digest(raw),
                rosters_sha256=codec.digest(codec.canonical(expected_rosters)),
                lineage_sha256=codec.digest(codec.canonical(lineage)))
            accepted_raw = codec.canonical(summary)
            if acceptance:
                if (len(ids) != 33 or acceptance != [(NEXT_YEAR, accepted_raw, codec.digest(accepted_raw))]
                        or mappings != list(lineage)):
                    raise ValueError('年度全33校の確定証跡が違います')
            elif mappings:
                raise ValueError('確定前の部分mappingです')
        self._guard()
        if before != _sha(self.db_path):
            raise ValueError('年度読取中に保存物が変更されました')
        if contract['source_bytes'] != self.source._evidence():
            raise ValueError('2026のbytesが変更されました')
        return dict(accepted=bool(acceptance), generated_schools=len(ids), summary=summary,
                    transitions=transitions, lineage=lineage)

    def status(self):
        with self._mutex:
            snap, contract = self.source.verified()
            state = self._audit(snap, contract)
            return dict(year=NEXT_YEAR, accepted=state['accepted'], generated_schools=state['generated_schools'],
                        state='rosters_accepted_no_tournament' if state['accepted'] else 'incomplete_rosters',
                        tournament_status='not_scheduled_not_played')

    def advance(self, *, career_seed=ROSTER_SEED, limit=33, fault=None):
        if type(career_seed) is not int or career_seed != ROSTER_SEED or type(limit) is not int or not 1 <= limit <= 33:
            raise ValueError('固定career seedと1..33校の限定操作が必要です')
        with self._mutex:
            snap, contract = self.source.verified()
            state = self._audit(snap, contract)
            start = state['generated_schools']
            if state['accepted']:
                return self._public_status(state)
            archive = CareerRosterArchive(self.db_path)
            for sid in SCHOOLS[start:start + limit]:
                self._guard()
                archive.advance_and_save(snap.repo.team(sid), next_year=NEXT_YEAR, career_seed=career_seed)
                if fault:
                    fault('school_committed', sid)
            state = self._audit(snap, contract)
            if state['generated_schools'] == 33:
                if contract['source_bytes'] != self.source._evidence():
                    raise ValueError('2026のbytesが変更されました')
                raw = codec.canonical(state['summary'])
                with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=.1)) as con, con:
                    con.execute('PRAGMA synchronous=FULL')
                    con.execute('BEGIN IMMEDIATE')
                    con.executemany('INSERT INTO annual_lineage VALUES (?,?,?,?,?)', state['lineage'])
                    con.execute('INSERT INTO annual_acceptance VALUES (?,?,?)', (NEXT_YEAR, raw, codec.digest(raw)))
                    if fault:
                        fault('before_acceptance_commit', None)
                if fault:
                    fault('after_acceptance_commit', None)
                state = self._audit(snap, contract)
            if contract['source_bytes'] != self.source._evidence():
                raise ValueError('2026のbytesが変更されました')
            return self._public_status(state)

    @staticmethod
    def _public_status(state):
        return dict(year=NEXT_YEAR, accepted=state['accepted'], generated_schools=state['generated_schools'],
                    tournament_status='not_scheduled_not_played')

    def browse(self):
        """One request-scoped, fully verified RO view; never a persistent cache."""
        with self._mutex:
            snap, contract = self.source.verified()
            state = self._audit(snap, contract)
            if not state['accepted']:
                raise ValueError('33校未確定の2027は閲覧用年度として公開しません')
            return AnnualRosterView(snap, state['transitions'])

    def close(self):
        with self._mutex:
            if self._lease is not None:
                self._lease.close()
                self._lease = None
            if self._pins is not None:
                self._pins.close()
                self._pins = None
            self.closed = True


class AnnualRosterView:
    """Detached read-only snapshot for browsing all33 schools/all924 identities."""
    def __init__(self, source, transitions):
        self._source = source
        self._rosters = {YEAR: {r.school_id: r for r in source.rosters},
                         NEXT_YEAR: {t.school_id: t.roster for t in transitions}}
        self._people = {p.player_id: p for r in source.rosters for p in r.players}
        self._people.update({p.player_id: p for t in transitions for p in t.newcomers})

    @staticmethod
    def _year(year):
        if type(year) is not int or year not in (YEAR, NEXT_YEAR):
            raise ValueError('検証した2026・2027学校年度のみ閲覧できます')

    def school(self, school_id, *, year):
        self._year(year)
        if school_id not in SCHOOLS:
            raise ValueError('未知の学校IDです')
        teams = tuple(t for t in self._source.registration.teams if school_id in t.school_ids) if year == YEAR else ()
        tids = {t.team_id for t in teams}
        games = tuple(r for r in self._source.results if tids.intersection((r.team1_id, r.team2_id))) if year == YEAR else ()
        return dict(year=year, school_id=school_id, roster=self._rosters[year][school_id].to_dict(),
            matches=tuple(r.to_dict() for r in games),
            participating_teams=tuple(dict(team_id=t.team_id, label=t.label, school_ids=t.school_ids,
                joint=len(t.school_ids) > 1) for t in teams),
            team_outcomes=tuple(dict(team_id=r.team_id, rank=r.rank, wins=r.wins, losses=r.losses)
                                for r in self._source.ranks if r.team_id in tids),
            school_standalone_outcomes=None,
            tournament_status='completed_fictional_2026' if year == YEAR else 'not_scheduled_not_played')

    def player(self, player_id, *, year):
        self._year(year)
        person = self._people.get(player_id)
        if person is None:
            raise ValueError('未知の永久選手IDです')
        current = next((p for p in self._rosters[year][person.school_id].players if p.player_id == player_id), None)
        state = 'active' if current else ('not_yet_enrolled' if year < person.entry_year else 'graduated')
        games = self._source.results if year == YEAR and current else ()
        appearances = tuple(dict(match_id=r.match_id, competition_id=r.competition_id,
            batting=tuple(asdict(p) for p in r.batter_stats if p.player_id == player_id),
            pitching=tuple(asdict(p) for p in r.pitcher_stats if p.player_id == player_id))
            for r in games if any(p.player_id == player_id for p in r.batter_stats + r.pitcher_stats))
        return dict(year=year, player_id=player_id, origin_school_id=person.school_id,
            entry_year=person.entry_year, state=state, profile=current.to_dict() if current else None,
            identity=person.to_dict(), appearances=appearances, totals=player_totals(games, player_id),
            tournament_status='completed_fictional_2026' if year == YEAR else 'not_scheduled_not_played')
