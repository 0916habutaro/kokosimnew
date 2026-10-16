"""Owned TemporaryDirectory roster-only trial; never a product save writer.

Reuse Stage111's Windows pins, lease, strict location/sidecar guard and explicit
close. Reuse CareerRosterArchive transactions, not a new roster generator.
"""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from game_core.players import PlayerRosterGenerator
from .career_roster_archive import CareerRosterArchive, _SCHEMA, _decode, _identity, _json, _digest
from .school_roster_contract import accept_roster_source, stream_school_transitions, RECIPE
from .yamanashi_annual_rosters import AnnualRosterLab, _owner, _sha, _schema

DATABASE = 'annual_rosters.sqlite3'
LEASE = 'annual.lease'
DDL = (
    'CREATE TABLE roster_trial_contract (payload TEXT PRIMARY KEY) STRICT',
    'CREATE TABLE roster_trial_acceptance (year INTEGER PRIMARY KEY, payload TEXT NOT NULL) STRICT',
) + tuple(f"CREATE TRIGGER trial_{table}_{action.lower()} BEFORE {action} ON {table} "
          "BEGIN SELECT RAISE(ABORT, 'append-only roster trial'); END"
          for table in ('career_school_rosters', 'career_player_identities',
                        'roster_trial_contract', 'roster_trial_acceptance')
          for action in ('UPDATE', 'DELETE'))


class MasterRosterSandbox:
    """Initial synthetic school rosters from explicit real master IDs, no games."""
    def __init__(self, repo, school_ids, *, year, career_seed):
        self.repo = repo
        self._rosters = tuple(PlayerRosterGenerator().generate_for_school_id(repo, sid, year, career_seed)
                              for sid in sorted(school_ids))
        self._receipt = accept_roster_source(self._rosters, repo, year=year,
            career_seed=career_seed, evidence='self-created master roster sandbox')

    def snapshot(self):
        # Recheck mutable roster payloads before every operation.
        check = accept_roster_source(self._rosters, self.repo, year=self._receipt.year,
            career_seed=self._receipt.career_seed, evidence=self._receipt.evidence)
        if check != self._receipt:
            raise ValueError('sandbox source changed')
        return self._rosters, check


class VerifiedSavedSchoolSource:
    """Adapter: Stage111 alone verifies its own real saved31 completion gate."""
    def __init__(self, source):
        from .yamanashi_annual_rosters import SelfCreated2026
        if type(source) is not SelfCreated2026:
            raise ValueError('Stage111 self-created source required')
        self.source = source
        self.owned_root = Path(source.capability.root)

    def snapshot(self):
        snap, contract = self.source.verified()
        self.repo = snap.repo
        receipt = accept_roster_source(snap.rosters, snap.repo,
            year=snap.rosters[0].reference_year, career_seed=contract['career_seed'],
            evidence=_digest(_json(contract)), source_kind='verified_saved_school_source')
        return snap.rosters, receipt


@dataclass(frozen=True)
class TrialCapability:
    root: str
    root_identity: tuple
    file_identity: tuple
    lease_identity: tuple
    contract_json: str


class SchoolRosterTrial(AnnualRosterLab):
    """Per-school commits followed by separate complete-set roster acceptance.

    The inherited guard operates only on the same DATABASE/LEASE filenames.
    No AnnualRosterView, tournament, CompetitionRun or future outcomes exist.
    """
    def __init__(self, source, owner, *, next_year, career_seed, recipe=RECIPE, opt_in=False):
        if opt_in is not True:
            raise ValueError('explicit roster-only trial opt-in required')
        rosters, receipt = source.snapshot()
        # Validate the entire input/recipe before creating a target file.
        for _ in stream_school_transitions(rosters, source.repo, receipt,
                  next_year=next_year, career_seed=career_seed, recipe=recipe):
            pass
        root = _owner(owner)
        source_root = getattr(source, 'owned_root', None)
        if source_root is not None and (root == source_root or root.is_relative_to(source_root)
                                        or source_root.is_relative_to(root)):
            raise ValueError('source and target must be separate owned roots')
        self.owner, self.source, self.db_path = owner, source, root / DATABASE
        self.db_path.touch(exist_ok=False)
        (root / LEASE).write_bytes(b'0')
        from . import yamanashi_demo_store as guards
        contract = _json(dict(version='stage43g112_roster_only_v1', source=receipt.to_dict(),
                              next_year=next_year, recipe=recipe))
        self.capability = TrialCapability(str(root), tuple(guards._identity(root)),
            tuple(guards._identity(self.db_path)), tuple(guards._identity(root / LEASE)), contract)
        self._setup_handles()
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                con.executescript(_SCHEMA)
                for sql in DDL:
                    con.execute(sql)
                with con:
                    con.execute('INSERT INTO roster_trial_contract VALUES (?)', (contract,))
            archive = CareerRosterArchive(self.db_path)
            for r in rosters:
                archive.save_initial_roster(r)
            self._verify()
        except BaseException:
            self.close()
            raise

    @classmethod
    def resume(cls, capability, source):
        if type(capability) is not TrialCapability:
            raise ValueError('owned trial capability required')
        obj = cls.__new__(cls)
        obj.capability, obj.source, obj.owner = capability, source, None
        obj.db_path = Path(capability.root) / DATABASE
        obj._guard()  # before opening SQLite, including hot journals
        obj._setup_handles()
        try:
            obj._verify()
        except BaseException:
            obj.close()
            raise
        return obj

    def _verify(self):
        self._guard()
        rosters, receipt = self.source.snapshot()
        raw = _json(dict(version='stage43g112_roster_only_v1', source=receipt.to_dict(),
                        next_year=receipt.year + 1, recipe=receipt.recipe))
        if raw != self.capability.contract_json:
            raise ValueError('different source/seed/year/recipe')
        before = _sha(self.db_path)
        expected_ids = tuple(s[0] for s in receipt.schools)
        # Source acceptance has already verified all school identities. The target
        # is read by indexed school/year; no historical match is regenerated.
        with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            with closing(sqlite3.connect(':memory:')) as reference:
                reference.executescript(_SCHEMA)
                for sql in DDL:
                    reference.execute(sql)
                expected_schema = _schema(reference)
            if (_schema(con) != expected_schema or con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                    or con.execute('PRAGMA journal_mode').fetchone() != ('delete',)
                    or con.execute('SELECT * FROM roster_trial_contract').fetchall() != [(raw,)]):
                raise ValueError('trial schema/integrity/source contract differs')
            ids = tuple(s for (s,) in con.execute('SELECT school_id FROM career_school_rosters WHERE year=? ORDER BY school_id',
                                                (receipt.year + 1,)))
            if ids != expected_ids[:len(ids)]:
                raise ValueError('partial school set is not a resumable prefix')
            expected_rows, people = [], {}
            totals = dict(graduated=0, returning=0, newcomers=0)
            for old, t in zip(rosters, stream_school_transitions(rosters, self.source.repo, receipt,
                       next_year=receipt.year + 1, career_seed=receipt.career_seed), strict=True):
                for r in (old, t.roster) if t.school_id in ids else (old,):
                    payload = _json(r.to_dict())
                    expected_rows.append((r.reference_year, r.school_id, _digest(payload), payload))
                    for p in r.players:
                        identity = _identity(p)
                        item = (p.player_id, p.school_id, p.entry_year, _digest(identity), identity)
                        if p.player_id in people and people[p.player_id] != item:
                            raise ValueError('identity collision across years')
                        people[p.player_id] = item
                for key in totals:
                    totals[key] += len(getattr(t, key))
            if (sorted(con.execute('SELECT * FROM career_school_rosters')) != sorted(expected_rows)
                    or sorted(con.execute('SELECT * FROM career_player_identities')) != sorted(people.values())):
                raise ValueError('saved school snapshot/permanent identity differs')
            summary = dict(year=receipt.year + 1, schools=len(expected_ids), active=20 * len(expected_ids),
                           **totals, scope='roster-only trial', season_start_authorized=False,
                           tournament_status='not_scheduled_not_played',
                           source_sha256=_digest(raw), roster_sha256=_digest(_json(sorted(expected_rows))))
            accepted = con.execute('SELECT * FROM roster_trial_acceptance').fetchall()
            if accepted and (ids != expected_ids or accepted != [(receipt.year + 1, _json(summary))]):
                raise ValueError('partial or conflicting year acceptance')
        self._guard()
        if before != _sha(self.db_path):
            raise ValueError('read-only trial audit changed bytes')
        # Recheck source after target read: consistency, never cross-DB atomicity.
        if self.source.snapshot()[1] != receipt:
            raise ValueError('source changed during audit')
        return (dict(accepted=bool(accepted), generated_schools=len(ids), summary=summary),
                rosters, receipt, tuple(expected_rows))

    def status(self):
        with self._mutex:
            return self._verify()[0]

    def advance(self, *, career_seed, recipe=RECIPE, limit=None, fault=None):
        with self._mutex:
            state, rosters, receipt, _ = self._verify()
            if type(career_seed) is not int or career_seed != receipt.career_seed or recipe != receipt.recipe:
                raise ValueError('original career seed/name recipe required')
            total = len(receipt.schools)
            limit = total if limit is None else limit
            if type(limit) is not int or not 1 <= limit <= total:
                raise ValueError('bounded school limit required')
            if state['accepted']:
                return state
            start = state['generated_schools']
            archive = CareerRosterArchive(self.db_path)
            for r in rosters[start:start + limit]:
                self._guard()
                archive.advance_and_save(self.source.repo.team(r.school_id), next_year=receipt.year + 1,
                                         career_seed=career_seed, generator=PlayerRosterGenerator())
                if fault:
                    fault('school_committed', r.school_id)
            state = self._verify()[0]
            if state['generated_schools'] == total:
                with closing(sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True)) as con, con:
                    con.execute('PRAGMA synchronous=FULL')
                    con.execute('BEGIN IMMEDIATE')
                    con.execute('INSERT INTO roster_trial_acceptance VALUES (?,?)',
                                (receipt.year + 1, _json(state['summary'])))
                    if fault:
                        fault('before_acceptance_commit', None)
                if fault:
                    fault('after_acceptance_commit', None)
                state = self._verify()[0]
            return state

    def browse(self):
        with self._mutex:
            state, _, _, rows = self._verify()
            if not state['accepted']:
                raise ValueError('incomplete roster year cannot be published')
            # Detached payloads from the SAME audited RO transaction.
            return dict(**state['summary'], rosters=tuple(_decode(raw).to_dict() for _, _, _, raw in sorted(rows)),
                        matches=(), school_standalone_outcomes=None)
