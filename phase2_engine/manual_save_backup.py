"""Explicit, stopped legacy-A export candidates. No restore or game hooks.

The caller must stop every writer. File audits cannot establish exclusion.
Completion evidence is unsigned consistency evidence, never restore authority.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
from time import perf_counter

from .legacy_backup_oracle import Refused as OracleRefused, TABLES, facts, ro, live_and_membership
from .legacy_backup_compatibility import CATALOG, CATALOG_VERSION, CATALOG_DIGEST
from .live_season_save import DEFAULT_RESOLVER_CONTRACT, _validate_save_payload
from .save_inventory_audit import InventoryRefused, inventory_slot
from .save_slots import SaveSlotManager

VERSION = 'stage43g94-candidate-v1'
REPLAY_NOTES = {
    'archive_ahead_preserve_history_no_rollback',
    'json_ahead_current_year_replay_sync_candidate',
    'checkpoint_dependencies_and_replay_require_separate_review',
}
DERIVED = re.compile(r'(?:derived_player_stats|fictional_v2_player_stat_cache|'
                     r'fictional_v2_school_read_index(?:_[A-Za-z0-9][A-Za-z0-9_-]{0,47})?)\.sqlite3\Z')
BACKUP = re.compile(r'backups/(?:manual|autosave)\.\d{3,}\.json\Z')
ORIGINALS = {'manual.json', 'autosave.json', 'slot_metadata.json', *TABLES}


class BackupRefused(ValueError):
    """Only fixed diagnostic codes, never input values or native errors."""


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_json(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise BackupRefused('invalid_json')
    return value


def _path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise BackupRefused('explicit_absolute_path_required')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise BackupRefused('linked_path')
    return path.resolve()


def _scan(root):
    """Check before reading: no links, transient writers, mounts or special files."""
    _path(root)
    if not root.is_dir():
        raise BackupRefused('missing_directory')
    device = root.stat().st_dev
    paths = []
    def failed(_error):
        raise BackupRefused('unreadable_directory')
    # Inspect directory entries BEFORE walk descends into them. On Windows
    # a junction need not satisfy is_symlink(); never recurse through it.
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=failed):
        for name in sorted(dirs + files):
            p = Path(directory) / name
            if p.is_symlink() or p.is_junction():
                raise BackupRefused('linked_path')
            info = p.stat()
            if p.name.endswith(('-wal', '-shm', '-journal', '.tmp')):
                raise BackupRefused('non_quiescent_artifact')
            if info.st_dev != device:
                raise BackupRefused('cross_filesystem')
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise BackupRefused('special_file')
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise BackupRefused('hardlinked_file')
            paths.append(p)
    return sorted(paths)


def _anchor(root):
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes())
            for p in _scan(root) if p.is_file()}


def _logical_digest(raw_facts):
    return _sha(_encoded(raw_facts))


def _compatibility(root):
    # Fixed, reviewed names only; never glob an arbitrary working directory.
    pin = {}
    for name in CATALOG:
        p = _path(root / name)
        if not p.is_file() or p.stat().st_nlink != 1:
            raise BackupRefused('compatibility_missing_or_unknown_version')
        pin[name] = _sha(p.read_bytes())
    if _sha(_encoded(pin)) != CATALOG_DIGEST:
        raise BackupRefused('compatibility_missing_or_unknown_version')
    return pin


def _inspect(slot, slot_id, source):
    paths = _scan(slot)
    for p in paths:
        name = p.relative_to(slot).as_posix()
        if p.is_dir():
            if name != 'backups':
                raise BackupRefused('unsupported_needs_manual_review')
        elif name not in ORIGINALS and not BACKUP.fullmatch(name) and not DERIVED.fullmatch(name):
            raise BackupRefused('unknown_or_unsupported_original')
    pin = _anchor(slot)
    live = inventory_slot(slot, slot_id=slot_id, contract='legacy_live', source=source,
                          authorized_read=True, expected_files=pin)
    players = inventory_slot(slot, slot_id=slot_id, contract='legacy_player_history',
                             authorized_read=True, expected_files=pin)
    if not live['contract_consistent'] or not players['contract_consistent']:
        raise BackupRefused('inventory_contract_refused')
    if REPLAY_NOTES.intersection(live['notes']):
        raise BackupRefused('unsupported_needs_manual_review')
    # Both live chains and every historical rolling checkpoint are preserved,
    # while only the explicitly selected current chain must equal the archive.
    checkpoints = []
    for name in pin:
        if name in ('manual.json', 'autosave.json') or BACKUP.fullmatch(name):
            body = _validate_save_payload(_read_json(slot / name))
            if body['resolver_contract'] != DEFAULT_RESOLVER_CONTRACT:
                raise BackupRefused('unsupported_resolver_version')
            summary = body['runtime_summary']
            if (len(body['status_by_competition']) != 1 or summary.get('template_competition_count') != 1
                    or any(summary.get(k) != 0 for k in ('resolution_count',
                        'qualification_resolution_count', 'regional_feeder_resolution_count',
                        'regional_playoff_resolution_count'))):
                raise BackupRefused('unsupported_needs_manual_review')
            checkpoints.append(body)
    metadata = slot / 'slot_metadata.json'
    if metadata.exists() and _read_json(metadata).get('slot_id') != slot_id:
        raise BackupRefused('slot_identity_mismatch')
    raw = facts(slot)
    live_and_membership(slot, source)
    # Year registration must be adjacent, with every earlier year sealed.
    rows = raw['historical_matches.sqlite3'][1]['career_years']
    with closing(ro(slot / 'historical_matches.sqlite3')) as con:
        years = con.execute('SELECT year,status FROM career_years ORDER BY year').fetchall()
        metadata = {y: json.loads(m) for y, m in con.execute('SELECT year,metadata_json FROM career_years')}
        identities = con.execute('SELECT metadata_json FROM archive_identity').fetchall()
    if any(m.get('resolver_contract') != DEFAULT_RESOLVER_CONTRACT for m in metadata.values()):
        raise BackupRefused('unsupported_resolver_version')
    for body in checkpoints:
        header = metadata.get(body['year'])
        if header is None or any(header[k] != body[k] for k in
                                ('year', 'rng_seed', 'resolver_contract', 'plan_fingerprint')):
            raise BackupRefused('checkpoint_collection_identity_mismatch')
    if len(identities) != 1 or not rows or any(
            y != years[0][0] + i or (i < len(years)-1 and status != 'sealed')
            for i, (y, status) in enumerate(years)):
        raise BackupRefused('unsupported_year_registration')
    if _anchor(slot) != pin:
        raise BackupRefused('input_changed_during_audit')
    return pin, raw, live, players


def _request(save_root, slot_id, source, confirm_game_stopped):
    # Declaration and explicit selectors are checked before any filesystem read.
    if confirm_game_stopped is not True:
        raise BackupRefused('game_stopped_declaration_required')
    if source not in ('manual', 'autosave'):
        raise BackupRefused('explicit_checkpoint_required')
    try:
        slot_id = SaveSlotManager.validate_slot_id(slot_id)
    except (ValueError, TypeError):
        raise BackupRefused('invalid_slot_id') from None
    root = _path(save_root)
    slot = _path(root / slot_id)
    if not root.is_dir() or not slot.is_dir() or slot.parent != root:
        raise BackupRefused('slot_root_mismatch')
    return root, slot, slot_id


def _summary(live, players):
    return dict(candidate_consistent=True, restoration_authorized=False,
                whole_game_restore_proven=False, generation_adopted=False,
                writer_exclusion_proven=False, historical_input_versions_proven=False,
                counts={**live['counts'], **{k: v for k, v in players['counts'].items()
                                             if k in ('school_year_rosters', 'player_identities')}})


def _safe_call(action):
    try:
        return action()
    except BackupRefused:
        raise
    except (InventoryRefused, OracleRefused):
        raise BackupRefused('original_or_candidate_contract_refused') from None
    except KeyboardInterrupt:
        raise BackupRefused('interrupted_incomplete_candidate') from None
    except (OSError, sqlite3.Error):
        raise BackupRefused('io_failure') from None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise BackupRefused('invalid_or_unsupported_input') from None


def diagnose_backup(*, save_root, slot_id, source, confirm_game_stopped=False):
    """Read-only diagnostics, including the installed fixed compatibility closure."""
    def run():
        _, slot, sid = _request(save_root, slot_id, source, confirm_game_stopped)
        _, _, live, players = _inspect(slot, sid, source)
        _compatibility(Path(__file__).resolve().parents[1])
        result = _summary(live, players)
        result.update(candidate_consistent=False, export_eligible=True, read_only=True)
        return result
    return _safe_call(run)


def _copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open('rb') as inp, dst.open('xb') as out:
        shutil.copyfileobj(inp, out)


def _copy_database(src, dst):
    # Reserve exclusively before SQLite opens it. No raw SQLite copy.
    with dst.open('xb'):
        pass
    with closing(ro(src)) as inp, closing(sqlite3.connect(dst)) as out:
        inp.backup(out)


def export_backup(*, save_root, slot_id, source, destination, confirm_game_stopped=False):
    """Export one closed slot into an exclusive new directory; retain partials.

    No ownership authentication is possible for an old JSON without slot ID.
    No arbitrary compatibility roots, callbacks, restore targets or overrides.
    """
    def run():
        start = perf_counter()
        root, slot, sid = _request(save_root, slot_id, source, confirm_game_stopped)
        dest = _path(destination)
        if dest == root or dest.is_relative_to(root) or root.is_relative_to(dest):
            raise BackupRefused('destination_overlaps_save_area')
        if os.path.lexists(dest):
            raise BackupRefused('destination_exists')
        if not dest.parent.is_dir():
            raise BackupRefused('destination_parent_missing')
        pin, raw, live, players = _inspect(slot, sid, source)
        repo = Path(__file__).resolve().parents[1]
        compat_pin = _compatibility(repo)
        # Never write inside the installed compatibility tree either.
        if dest == repo or dest.is_relative_to(repo) or repo.is_relative_to(dest):
            raise BackupRefused('destination_overlaps_compatibility')
        dest.mkdir(mode=0o700)  # exclusive directory; private evidence on POSIX
        payload = dest / 'payload' / sid
        payload.mkdir(parents=True)
        for name in sorted(pin):
            if DERIVED.fullmatch(name):
                continue
            src, dst = slot / name, payload / name
            if name in TABLES:
                _copy_database(src, dst)
            else:
                _copy_file(src, dst)
        for name in compat_pin:
            _copy_file(repo / name, dest / 'compatibility' / name)
        if _anchor(slot) != pin or _compatibility(repo) != compat_pin:
            raise BackupRefused('input_changed_during_export')
        copied, copied_raw, copied_live, copied_players = _inspect(payload, sid, source)
        wanted = {n for n in pin if not DERIVED.fullmatch(n)}
        if set(copied) != wanted or copied_raw != raw or any(
                copied[n] != pin[n] for n in wanted if n not in TABLES):
            raise BackupRefused('candidate_content_mismatch')
        if _anchor(dest / 'compatibility') != compat_pin:
            raise BackupRefused('candidate_compatibility_mismatch')
        result = _summary(copied_live, copied_players)
        result.update(source_zero_write=True, no_clobber=True, source=source,
                      source_slot_bytes=sum((slot/n).stat().st_size for n in pin),
                      candidate_payload_bytes=sum((payload/n).stat().st_size for n in copied),
                      compatibility_bytes=sum((repo/n).stat().st_size for n in compat_pin))
        # Private evidence contains only relative paths. Public results above
        # contain no IDs, filenames, source hashes, full paths or native errors.
        evidence = dict(version=VERSION, catalog_version=CATALOG_VERSION,
                        slot_id=sid, source=source, source_files=pin,
                        payload_files=copied, compatibility_files=compat_pin,
                        logical_digest=_logical_digest(raw),
                        runtime=dict(python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                                     os=platform.system()), summary=result)
        with (dest / 'evidence.json').open('xb') as out:
            out.write(_encoded(evidence))
        # Last read boundary, before the completion receipt. No slot lock or
        # crash-durability promise is inferred from this unsigned receipt.
        if (_anchor(slot) != pin or facts(payload) != raw or _anchor(payload) != copied
                or _compatibility(repo) != compat_pin
                or _anchor(dest / 'compatibility') != compat_pin
                or (dest / 'evidence.json').read_bytes() != _encoded(evidence)):
            raise BackupRefused('changed_before_completion')
        receipt = VERSION + '\n' + _sha((dest / 'evidence.json').read_bytes()) + '\n'
        result.update(seconds=round(perf_counter()-start, 6),
                      candidate_total_bytes=sum(p.stat().st_size for p in _scan(dest) if p.is_file())
                                            + len(receipt.encode('utf-8')))
        result['observed_source_and_candidate_bytes'] = result['source_slot_bytes'] + result['candidate_total_bytes']
        with (dest / 'COMPLETE').open('x', encoding='utf-8', newline='\n') as out:
            out.write(receipt)
        return result
    return _safe_call(run)


def verify_candidate(*, candidate):
    """Inspect candidate-contained files only; never load or sync a game.

    Anyone who can replace all evidence can forge it. Consistency is not
    provenance, authorization, historical completeness or replay safety.
    """
    def run():
        root = _path(candidate)
        before = _anchor(root)
        if not {'COMPLETE', 'evidence.json'} <= before.keys():
            raise BackupRefused('incomplete_candidate')
        raw_evidence = (root / 'evidence.json').read_bytes()
        if (root / 'COMPLETE').read_text(encoding='utf-8') != VERSION+'\n'+_sha(raw_evidence)+'\n':
            raise BackupRefused('invalid_completion_receipt')
        evidence = _read_json(root / 'evidence.json')
        if evidence['version'] != VERSION or evidence['catalog_version'] != CATALOG_VERSION:
            raise BackupRefused('unsupported_candidate_version')
        sid = SaveSlotManager.validate_slot_id(evidence['slot_id'])
        source = evidence['source']
        if source not in ('manual', 'autosave'):
            raise BackupRefused('explicit_checkpoint_required')
        payload = root / 'payload' / sid
        copied, raw, live, players = _inspect(payload, sid, source)
        compat_pin = _anchor(root / 'compatibility')
        expected = {'COMPLETE', 'evidence.json'} | {
            'payload/'+sid+'/'+n for n in copied} | {'compatibility/'+n for n in compat_pin}
        if (set(before) != expected or copied != evidence['payload_files']
                or _logical_digest(raw) != evidence['logical_digest']
                or compat_pin != evidence['compatibility_files'] or set(compat_pin) != set(CATALOG)
                or _sha(_encoded(compat_pin)) != CATALOG_DIGEST):
            raise BackupRefused('candidate_content_mismatch')
        if _anchor(root) != before:
            raise BackupRefused('candidate_changed_during_verification')
        result = _summary(live, players)
        result.update(read_only=True, evidence_authenticated=False)
        return result
    return _safe_call(run)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('diagnose', 'export'):
        p = commands.add_parser(command)
        p.add_argument('--save-root', required=True)
        p.add_argument('--slot-id', required=True)
        p.add_argument('--source', required=True, choices=('manual', 'autosave'))
        p.add_argument('--confirm-game-stopped', action='store_true')
        if command == 'export':
            p.add_argument('--destination', required=True)
    commands.add_parser('verify').add_argument('--candidate', required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        result = {'diagnose': diagnose_backup, 'export': export_backup,
                  'verify': verify_candidate}[command](**args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except BackupRefused as error:
        print(json.dumps(dict(successful=False, code=str(error), restoration_authorized=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
