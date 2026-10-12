"""Lab only: owns every input/output; deliberately accepts no external root.

The private pins below live only for the lifetime of self-generated fixtures.
They are neither a signed manifest nor a new save/generation contract.
"""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from time import perf_counter
from unittest.mock import patch

import atexit
from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.engine import TournamentEngine
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_season_planner import LiveSeasonGraphPlan
from phase2_engine.save_inventory_audit import inventory_slot
from stage43g91_fixture_support import closed_archive_connection
from test_stage43g91_save_inventory import StaticPlanner, private_anchor
from test_stage43g92_legacy_replay import Stage43G92LegacyReplayTests, ROOT, SEED

METRICS = []
DERIVED = {'derived_player_stats.sqlite3', 'fictional_v2_player_stat_cache.sqlite3'}
DERIVED_RE = re.compile(r'fictional_v2_school_read_index(?:_[A-Za-z0-9][A-Za-z0-9_-]{0,47})?\.sqlite3\Z')
TABLES = {
    'historical_matches.sqlite3': {'archive_identity', 'career_years', 'historical_matches',
                                 'historical_competition_outcomes'},
    'career_rosters.sqlite3': {'career_school_rosters', 'career_player_identities'},
}


class Refused(ValueError):
    """Fixed, non-sensitive diagnostic codes only."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def ro(path):
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    con.execute('PRAGMA query_only=ON')
    return con


def facts(root):
    """Independent raw SQL/payload oracle, including every original table.

    No production _ledger/_history_payload/roster decoder calls. DB backup
    may change physical page layout, so compare schema and full logical rows.
    """
    result = {}
    for name, allowed in TABLES.items():
        with closing(ro(root / name)) as con:
            if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise Refused('sqlite_integrity')
            schema = con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                                 "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            tables = {r[1] for r in schema if r[0] == 'table'}
            if not tables <= allowed:
                raise Refused('unknown_original_table')
            rows = {t: con.execute('SELECT * FROM "' + t + '" ORDER BY 1,2').fetchall()
                    for t in sorted(tables)}
            result[name] = (schema, rows)
            con.row_factory = sqlite3.Row
            if name == 'historical_matches.sqlite3':
                matches = con.execute('SELECT * FROM historical_matches ORDER BY year,competition_id,match_id').fetchall()
                headers = {r['year']: r for r in con.execute('SELECT * FROM career_years')}
                for row in matches:
                    p = json.loads(row['payload_json'])
                    if sha(row['payload_json']) != row['record_sha256'] or any(
                            p[k] != row[k] for k in ('year', 'competition_id', 'match_id',
                            'match_date', 'date_source', 'team1_id', 'team2_id',
                            'team1_score', 'team2_score', 'score_source')) or row['year'] not in headers:
                        raise Refused('raw_match_mismatch')
                    # Older score-only/bye records remain exactly as stored.
                    if p.get('inning_scores') is None:
                        continue
                    for sid, score in ((p['team1_id'], p['team1_score']), (p['team2_id'], p['team2_score'])):
                        if sum(i['runs'] for i in p['inning_scores'] if i['batting_team_id'] == sid and i['was_played']) != score:
                            raise Refused('raw_inning_mismatch')
                for year, h in headers.items():
                    items = [(r['competition_id'], r['match_id'], r['record_sha256']) for r in matches if r['year'] == year]
                    if h['status'] == 'sealed' and (len(items), sha(canonical(items))) != (h['match_count'], h['ledger_sha256']):
                        raise Refused('raw_ledger_mismatch')
                    if h['status'] not in ('active', 'sealed'):
                        raise Refused('raw_year_status')
                if 'historical_competition_outcomes' in tables:
                    for r in con.execute('SELECT * FROM historical_competition_outcomes'):
                        p = json.loads(r['payload_json'])
                        h = headers.get(r['year'])
                        if (sha(r['payload_json']) != r['record_sha256']
                                or (p['year'], p['competition_id']) != (r['year'], r['competition_id'])
                                or h is None or h['status'] != 'sealed'
                                or p['source_year_ledger_sha256'] != h['ledger_sha256']):
                            raise Refused('raw_outcome_mismatch')
                        items = [[m['match_id'], m['record_sha256']] for m in matches
                                 if m['year'] == r['year'] and m['competition_id'] == r['competition_id']
                                 and json.loads(m['payload_json'])['stage_code'] == 'MAIN']
                        if (len(items) != p['main_match_count']
                                or sha(canonical(items)) != p['source_match_sha256']):
                            raise Refused('raw_outcome_source_mismatch')
            else:
                identities = {}
                for r in con.execute('SELECT * FROM career_player_identities'):
                    p = json.loads(r['identity_json'])
                    if sha(r['identity_json']) != r['identity_sha256'] or any(p[k] != r[k] for k in ('player_id', 'school_id', 'entry_year')):
                        raise Refused('raw_identity_mismatch')
                    identities[r['player_id']] = p
                for r in con.execute('SELECT * FROM career_school_rosters'):
                    p = json.loads(r['payload_json'])
                    if sha(r['payload_json']) != r['content_sha256'] or (p['reference_year'], p['school_id']) != (r['year'], r['school_id']):
                        raise Refused('raw_roster_mismatch')
                    for player in p['players']:
                        identity = {k: v for k, v in player.items() if k != 'academic_year'}
                        if identities.get(player['player_id']) != identity:
                            raise Refused('raw_roster_identity_mismatch')
    return result


def derived(name):
    return name in DERIVED or bool(DERIVED_RE.fullmatch(name))


class OwnedLab:
    _templates = {}

    def __init__(self, phase='active'):
        if phase not in ('active', 'sealed', 'registered'):
            raise Refused('invalid_phase')
        self.temp = tempfile.TemporaryDirectory(prefix='stage93-owned-')
        self.root = Path(self.temp.name).resolve()
        self.slot = self.root / 'input' / 'labslot'
        self.compat = self.root / 'compatibility'
        self.outputs = self.root / 'candidates'
        self.outputs.mkdir()
        self.completed = {}
        self.writers_stopped = False
        try:
            if phase in self._templates:
                template = Path(self._templates[phase].name)
                shutil.copytree(template / 'input', self.root / 'input')
                shutil.copytree(template / 'compatibility', self.compat)
                self.compat_pin = private_anchor(self.compat)
                self.input_pin = private_anchor(self.slot)
                self.original_facts = facts(self.slot)
                self.phase = phase
                self.writers_stopped = True
                return
            if not hasattr(Stage43G92LegacyReplayTests, 'plan'):
                Stage43G92LegacyReplayTests.setUpClass()
            base = Stage43G92LegacyReplayTests
            cid = 'CMP000029'
            # Eight explicitly selected schools, one actual summer competition.
            # This is a small game projection, never nationwide annual play.
            plan = LiveSeasonGraphPlan(repo=base.repo, data_dir=ROOT / 'data', year=2026, rng_seed=SEED,
                entries={cid: base.plan.entries[cid]}, annual_templates={cid: replace(
                    base.plan.annual_templates[cid], entrant_school_ids=base.plan.annual_templates[cid].entrant_school_ids[:8])},
                annual_build_strategies={cid: base.plan.annual_build_strategies[cid]},
                calendar_rows=[r for r in base.plan.calendar_rows if r['competition_id'] == cid],
                stage_calendar_rows=base.plan.stage_calendar_rows, topological_order=[cid])
            service = LiveGameService(base.repo, ROOT / 'data', save_root=self.slot.parent,
                resolver_contract='stage93-ability-fixture-v1',
                planner_factory=lambda *args: StaticPlanner(plan))
            resolver = AbilityMatchResolver(base.repo, ability_config_dir=ROOT / 'config' / 'abilities',
                                            match_config_dir=ROOT / 'config' / 'match', team_generation_seed=SEED)
            engine = TournamentEngine(base.repo, main_match_resolver=resolver, pre_main_match_resolver=resolver)
            session = service.new_game('labslot', rng_seed=SEED, start_date='2026-07-01', engine=engine)
            service.advance_through(session, '2026-07-12')
            service.save_game(session, kind='manual')
            if phase != 'active':
                service.advance_through(session, '2026-12-31')
                service.finalize_season(session)
                with patch.object(HistoricalMatchArchive, '_connect', closed_archive_connection):
                    outcomes = CareerCompetitionOutcomes(self.slot / 'historical_matches.sqlite3')
                    for run in session.state.completed_runs().values():
                        outcomes.record_completed(run)
                # Explicitly choose equal final checkpoints; older rolling backups remain.
                service.save_game(session, kind='autosave')
            if phase == 'registered':
                HistoricalMatchArchive(self.slot / 'historical_matches.sqlite3').register_next_year(
                    year=2027, rng_seed=SEED, resolver_contract=session.resolver_contract,
                    plan_fingerprint='fixture93-registration-not-full-year-gameplay')
            with patch.object(CareerRosterArchive, '_connect', closed_archive_connection):
                archive = CareerRosterArchive(self.slot / 'career_rosters.sqlite3')
                for roster in resolver._roster_cache.values():
                    archive.save_initial_roster(roster)
            # A conservative compatibility closure; no real save is read here.
            for folder, suffix in (('data', '*.csv'), ('config', '*.json'),
                                   ('phase2_engine', '*.py'), ('game_core', '*.py')):
                for src in (ROOT / folder).rglob(suffix):
                    dst = self.compat / src.relative_to(ROOT)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
            self.compat_pin = private_anchor(self.compat)
            self.input_pin = private_anchor(self.slot)
            self.original_facts = facts(self.slot)
            self.phase = phase
            self.writers_stopped = True
            template = tempfile.TemporaryDirectory(prefix='stage93-generated-template-')
            atexit.register(template.cleanup)
            shutil.copytree(self.root / 'input', Path(template.name) / 'input')
            shutil.copytree(self.compat, Path(template.name) / 'compatibility')
            self._templates[phase] = template
        except BaseException:
            self.close()
            raise

    def close(self):
        self.writers_stopped = False
        self.temp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _safe(self, root):
        if root.parent.resolve() not in (self.root, self.slot.parent.resolve(), self.outputs):
            raise Refused('outside_owned_lab')
        paths = (root, *root.parents, *root.rglob('*'))
        if any(p.is_symlink() or p.is_junction() for p in paths):
            raise Refused('linked_path')
        if any(p.name.endswith(('-wal', '-shm', '-journal', '.tmp')) for p in paths):
            raise Refused('non_quiescent_artifact')
        if any(p.is_file() and p.stat().st_nlink != 1 for p in paths):
            raise Refused('hardlinked_input')
        if any(p.stat().st_dev != self.root.stat().st_dev for p in (root, *root.rglob('*'))):
            raise Refused('cross_filesystem')

    def diagnose(self, source):
        if source not in ('manual', 'autosave'):
            raise Refused('explicit_checkpoint_required')
        if not self.writers_stopped:
            raise Refused('writer_not_stopped')
        self._safe(self.slot)
        self._safe(self.compat)
        if private_anchor(self.compat) != self.compat_pin:
            raise Refused('compatibility_missing_or_changed')
        present = private_anchor(self.slot)
        if any(n not in self.input_pin and not derived(n) for n in present):
            raise Refused('unknown_original')
        if any(present.get(n) != h for n, h in self.input_pin.items() if not derived(n)):
            raise Refused('private_original_pin_mismatch')
        live = inventory_slot(self.slot, slot_id='labslot', contract='legacy_live',
                              source=source, authorized_read=True, expected_files=self.input_pin)
        players = inventory_slot(self.slot, slot_id='labslot', contract='legacy_player_history',
                                 authorized_read=True, expected_files=self.input_pin)
        if not live['contract_consistent'] or not players['contract_consistent']:
            raise Refused('inventory_contract_refused')
        if live['counts']['unclassified_files']:
            raise Refused('unknown_original')
        if any(n in live['notes'] for n in ('archive_ahead_preserve_history_no_rollback',
                'json_ahead_current_year_replay_sync_candidate',
                'checkpoint_dependencies_and_replay_require_separate_review')):
            raise Refused('manual_judgment_required')
        for path in (self.slot / 'backups').glob('*.json'):
            body = json.loads(path.read_text(encoding='utf-8'))
            checksum = body.pop('payload_checksum', None)
            if checksum != sha(canonical(body)):
                raise Refused('rolling_checkpoint_checksum')
        if facts(self.slot) != self.original_facts:
            raise Refused('raw_original_changed')
        return live

    def candidate_path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,40}', name):
            raise Refused('invalid_candidate_name')
        self._safe(self.outputs)
        return self.outputs / name

    def export(self, name, *, source, include_derived=False, boundary=lambda *args: None):
        """Make a candidate in a new exclusive lab directory, never restore.

        A crash leaves an unapproved partial directory; rerun refuses it.
        boundary is a test-only deterministic injection, never a product hook.
        """
        destination = self.candidate_path(name)
        if destination.exists() or destination.is_symlink():
            raise Refused('output_exists')
        info = self.diagnose(source)
        before, compat_before = private_anchor(self.slot), private_anchor(self.compat)
        start = perf_counter()
        peak = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        destination.mkdir()  # atomic no-clobber; no rename/replace into another slot
        target = destination / 'labslot'
        target.mkdir()
        try:
            boundary('created', destination)
            for n in sorted(before):
                if derived(n) and not include_derived:
                    continue
                src, dst = self.slot / n, target / n
                dst.parent.mkdir(parents=True, exist_ok=True)
                with dst.open('xb') as out:
                    if n not in TABLES:
                        with src.open('rb') as inp:
                            shutil.copyfileobj(inp, out)
                if n in TABLES:
                    with closing(ro(src)) as inp, closing(sqlite3.connect(dst)) as out:
                        inp.backup(out)
                boundary('copied', dst)
                peak = max(peak, sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))
            shutil.copytree(self.compat, destination / 'compatibility')
            boundary('copied_compatibility', destination)
            if private_anchor(self.slot) != before or private_anchor(self.compat) != compat_before:
                raise Refused('input_changed_during_export')
            if facts(target) != self.original_facts:
                raise Refused('candidate_raw_mismatch')
            for n in private_anchor(target):
                if n not in TABLES and (target / n).read_bytes() != (self.slot / n).read_bytes():
                    raise Refused('candidate_json_mismatch')
            if private_anchor(destination / 'compatibility') != self.compat_pin:
                raise Refused('candidate_compatibility_mismatch')
            boundary('verified', destination)
            if facts(target) != self.original_facts or private_anchor(self.slot) != before or private_anchor(self.compat) != compat_before:
                raise Refused('changed_after_verification')
            expected_names = {n for n in before if include_derived or not derived(n)}
            if set(private_anchor(target)) != expected_names or any(
                    (target / n).read_bytes() != (self.slot / n).read_bytes()
                    for n in expected_names if n not in TABLES):
                raise Refused('candidate_json_mismatch')
            if private_anchor(destination / 'compatibility') != self.compat_pin:
                raise Refused('candidate_compatibility_mismatch')
            peak = max(peak, sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))
            metrics = dict(phase=self.phase, source=source, include_derived=include_derived,
                copy_bytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()),
                source_slot_bytes=sum(p.stat().st_size for p in self.slot.rglob('*') if p.is_file()),
                compatibility_bytes=sum(p.stat().st_size for p in self.compat.rglob('*') if p.is_file()),
                peak_payload_file_bytes=peak, complete_a_matches=info['counts']['legacy_complete_a_matches'],
                seconds=round(perf_counter() - start, 6), matches=info['counts']['legacy_matches'],
                sealed_years=info['counts']['legacy_sealed_years'], fixture_only=True,
                generation_adopted=False, whole_game_restore_proven=False, restoration_authorized=False)
            # Unsigned lab evidence is explicitly NOT trusted by verify().
            with (destination / 'lab_evidence.json').open('x', encoding='utf-8') as evidence:
                evidence.write(json.dumps(metrics, indent=2))
            self.completed[name] = (private_anchor(destination), self.original_facts)
            METRICS.append(metrics)
            return metrics
        except (OSError, sqlite3.Error):
            raise Refused('copy_io_failure') from None

    def verify(self, name):
        destination = self.candidate_path(name)
        if name not in self.completed:
            raise Refused('incomplete_or_untrusted_candidate')
        self._safe(destination)
        pin, expected_facts = self.completed[name]
        if private_anchor(destination) != pin:
            raise Refused('candidate_private_pin_mismatch')
        if facts(destination / 'labslot') != expected_facts:
            raise Refused('candidate_raw_mismatch')
        return {'candidate_consistent': True, 'restoration_authorized': False,
                'whole_game_restore_proven': False, 'generation_adopted': False}
