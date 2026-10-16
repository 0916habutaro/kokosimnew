"""Owned, byte-pinned SQLite roster source. No games or competition authority.

Creation alone uses the generator. Every snapshot decodes the saved SQL rows;
resumption never regenerates the initial cohort. No arbitrary path adoption.
"""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3

from .career_roster_archive import CareerRosterArchive, _SCHEMA, _decode, _digest, _identity, _json
from .school_roster_contract import accept_roster_source, RECIPE
from .school_roster_trial import MasterRosterSandbox, SchoolRosterTrial, DATABASE, LEASE
from .yamanashi_annual_rosters import AnnualRosterLab, _owner, _sha, _schema
from . import yamanashi_demo_store as guards

SOURCE_DDL = ('CREATE TABLE saved_roster_source (payload TEXT PRIMARY KEY) STRICT',) + tuple(
    f"CREATE TRIGGER source_{table}_{action.lower()} BEFORE {action} ON {table} "
    "BEGIN SELECT RAISE(ABORT, 'immutable roster source'); END"
    for table in ('career_school_rosters', 'career_player_identities', 'saved_roster_source')
    for action in ('UPDATE', 'DELETE'))


@dataclass(frozen=True)
class SavedRosterCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str
    database_sha256: str


class SavedSchoolRosterSource(AnnualRosterLab):
    """Source owner must stay alive across exited worker processes."""
    def __init__(self, repo, school_ids, owner, *, year, career_seed, opt_in=False):
        if opt_in is not True:
            raise ValueError('explicit saved roster-only opt-in required')
        initial = MasterRosterSandbox(repo, school_ids, year=year, career_seed=career_seed)
        rosters, receipt = initial.snapshot()
        root = _owner(owner)
        self.owner, self.repo, self.owned_root = owner, repo, root
        self.db_path = root / DATABASE
        self.db_path.touch(exist_ok=False)
        (root / LEASE).write_bytes(b'0')
        raw = _json(dict(version='stage43g113_saved_source_v1', recipe=RECIPE, source=receipt.to_dict()))
        self.capability = SavedRosterCapability(str(root), tuple(guards._identity(root)),
            tuple(guards._identity(self.db_path)), tuple(guards._identity(root / LEASE)), raw, '')
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                con.executescript(_SCHEMA)
                for sql in SOURCE_DDL:
                    con.execute(sql)
                with con:
                    con.execute('INSERT INTO saved_roster_source VALUES (?)', (raw,))
            archive = CareerRosterArchive(self.db_path)
            for roster in rosters:
                archive.save_initial_roster(roster)
            from dataclasses import replace
            self.capability = replace(self.capability, database_sha256=_sha(self.db_path))
            self.snapshot()
        except BaseException:
            self.close()
            raise

    @classmethod
    def resume(cls, capability, repo):
        if type(capability) is not SavedRosterCapability:
            raise ValueError('owned saved-source capability required')
        obj = cls.__new__(cls)
        obj.capability, obj.repo, obj.owner = capability, repo, None
        obj.owned_root = Path(capability.root)
        obj.db_path = obj.owned_root / DATABASE
        obj._guard()
        obj._setup_handles()
        try:
            obj.snapshot()
        except BaseException:
            obj.close()
            raise
        return obj

    def snapshot(self):
        with self._mutex:
            self._guard()
            if _sha(self.db_path) != self.capability.database_sha256:
                raise ValueError('saved source bytes changed')
            contract = json.loads(self.capability.contract_json)
            with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)) as con:
                con.execute('PRAGMA query_only=ON')
                con.execute('BEGIN')
                with closing(sqlite3.connect(':memory:')) as reference:
                    reference.executescript(_SCHEMA)
                    for sql in SOURCE_DDL:
                        reference.execute(sql)
                    schema = _schema(reference)
                if (_schema(con) != schema or con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                        or con.execute('SELECT * FROM saved_roster_source').fetchall() != [(self.capability.contract_json,)]):
                    raise ValueError('saved source schema or contract differs')
                rows = con.execute('SELECT * FROM career_school_rosters ORDER BY school_id').fetchall()
                rosters, identities = [], {}
                for year, sid, sha, raw in rows:
                    roster = _decode(raw)
                    if (year != roster.reference_year or sid != roster.school_id
                            or sha != _digest(raw) or raw != _json(roster.to_dict())):
                        raise ValueError('saved source row differs')
                    rosters.append(roster)
                    for p in roster.players:
                        identity = _identity(p)
                        identities[p.player_id] = (p.player_id, p.school_id, p.entry_year, _digest(identity), identity)
                if sorted(con.execute('SELECT * FROM career_player_identities')) != sorted(identities.values()):
                    raise ValueError('saved permanent profiles differ')
            declared = contract['source']
            receipt = accept_roster_source(rosters, self.repo, year=declared['year'],
                career_seed=declared['career_seed'], evidence=declared['evidence'])
            if _json(receipt.to_dict()) != _json(declared):
                raise ValueError('saved master/seed/school set differs')
            self._guard()
            if _sha(self.db_path) != self.capability.database_sha256:
                raise ValueError('source changed during read')
            # Bind both bytes and the owned physical authority. A separately
            # created SQLite file with identical content is a different source.
            authority=_digest(_json(dict(root=self.capability.root_identity,
                file=self.capability.file_identity,lease=self.capability.lease_identity)))
            saved_receipt = accept_roster_source(rosters, self.repo, year=receipt.year,
                career_seed=receipt.career_seed, evidence='saved roster-only SQLite sha256:' + self.capability.database_sha256
                    + '/owned-authority-sha256:' + authority)
            return tuple(rosters), saved_receipt


class SavedSchoolRosterTrial(SchoolRosterTrial):
    """Stage113 entry point only accepts the owned saved SQLite authority."""
    def __init__(self, source, owner, **kwargs):
        if type(source) is not SavedSchoolRosterSource:
            raise ValueError('saved SQLite source required')
        super().__init__(source, owner, **kwargs)

    @classmethod
    def resume(cls, capability, source):
        if type(source) is not SavedSchoolRosterSource:
            raise ValueError('saved SQLite source required')
        return super().resume(capability, source)

    def school(self, school_id, *, year):
        view = self.browse()  # incomplete years cannot be published
        rows = [r for r in view['rosters'] if r['school_id'] == school_id and r['reference_year'] == year]
        if len(rows) != 1:
            raise ValueError('unknown school/year')
        return dict(roster=rows[0], **competition_start_gate(dict(accepted=True)))

    def player(self, player_id):
        view = self.browse()
        history = [dict(year=r['reference_year'], **p)
                   for r in view['rosters'] for p in r['players'] if p['player_id'] == player_id]
        if not history:
            raise ValueError('unknown permanent ID')
        return dict(player_id=player_id, history=history, **competition_start_gate(dict(accepted=True)))


def competition_start_gate(roster_state):
    """A complete school year supplies none of the required tournament inputs.

    No caller flag can turn a roster-only receipt into a qualification token.
    Future competition-specific gates require a separate evidence contract.
    """
    return dict(rosters_accepted=bool(roster_state.get('accepted', False)),
                season_start_authorized=False, tournament_status='not_scheduled_not_played',
                missing_evidence=('competition_entries', 'qualification', 'joint_team_continuity',
                                  'seed_rules', 'schedule'))
