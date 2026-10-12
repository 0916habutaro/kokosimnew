"""Stage43G-91 read-only inventory; no restore, migration or save publication.

Callers must explicitly authorize reads of their input. The fixture-only CLI
accepts no save path. This API deliberately rejects WAL/journal/symlink inputs;
use a separately authorized, quiescent copy, not a running game directory.
Results contain role codes/counts only, never paths, IDs, SHA values or errors.
"""
from __future__ import annotations

from contextlib import closing, nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import re
from typing import Mapping

from .career_calendar_v2 import _verified as verify_calendar
from .career_roster_archive import CareerRosterArchive, _identity
from .career_v2_option_a_archive import _verify_match
from .historical_match_archive import _history_payload
from .live_season_save import _validate_save_payload
from .save_slots import SaveSlotManager

FILES = {
    "manual": "manual.json", "autosave": "autosave.json",
    "legacy_history": "historical_matches.sqlite3",
    "rosters": "career_rosters.sqlite3",
    "v2_calendar": "sandbox_calendar_v2.sqlite3",
    "v2_history": "fictional_option_a_v2.sqlite3",
    "legacy_stats": "derived_player_stats.sqlite3",
    "v2_stats": "fictional_v2_player_stat_cache.sqlite3",
    "slot_metadata": "slot_metadata.json",
}
CHECKPOINT_DIRS = (
    "career_previews", "career_multi_previews", "career_regional_previews",
    "career_kanagawa_spring_previews", "career_placement_previews",
    "career_invitational_manifests", "career_year_rulebooks",
    "career_year_continuity", "career_tokai_preflights",
)
CONTRACTS = {
    "legacy_live": {"legacy_history"},
    "legacy_history": {"legacy_history"},
    "legacy_player_history": {"legacy_history", "rosters"},
    "fictional_v2": {"v2_history", "v2_calendar"},
}


class InventoryRefused(ValueError):
    """Only fixed non-sensitive codes cross the public API boundary."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ro(path):
    # immutable avoids SQLite creating/updating SHM. WAL is rejected first,
    # since immutable could otherwise silently ignore committed WAL records.
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _json_file(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InventoryRefused("invalid_json")
    return value


def _check_digest(raw, expected):
    if _digest(raw) != expected:
        raise InventoryRefused("content_mismatch")


def _history(path, *, fictional=False, plans=None):
    table, headers = (("v2_option_a_matches", "v2_game_years") if fictional
                      else ("historical_matches", "career_years"))
    records, years = {}, {}
    with closing(_ro(path)) as con:
        if con.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok":
            raise InventoryRefused("invalid_sqlite")
        for header in con.execute(f"SELECT * FROM {headers} ORDER BY year"):
            year = header["year"]
            rows = con.execute(f"SELECT * FROM {table} WHERE year=? "
                               "ORDER BY competition_id,match_id", (year,)).fetchall()
            items = [(r["competition_id"], r["match_id"], r["record_sha256"]) for r in rows]
            if header["status"] == "sealed":
                if (header["match_count"], header["ledger_sha256"]) != (len(rows), _digest(_canonical(items))):
                    raise InventoryRefused("sealed_ledger_mismatch")
            elif header["status"] != "active":
                raise InventoryRefused("invalid_year_status")
            if fictional:
                if year not in plans or header["calendar_sha256"] != plans[year][1]:
                    raise InventoryRefused("calendar_generation_mismatch")
            else:
                meta = json.loads(header["metadata_json"])
                if meta.get("year") != year:
                    raise InventoryRefused("year_identity_mismatch")
            years[year] = dict(header)
            for row in rows:
                _check_digest(row["payload_json"], row["record_sha256"])
                value = json.loads(row["payload_json"])
                key = (year, row["competition_id"], row["match_id"])
                if key != (value["year"], value["competition_id"], value["match_id"]):
                    raise InventoryRefused("record_identity_mismatch")
                if fictional:
                    value = _verify_match(row, plans[year][0], plans[year][1])
                elif any(row[k] != value[k] for k in (
                        "match_date", "date_source", "team1_id", "team2_id",
                        "team1_score", "team2_score", "score_source")):
                    raise InventoryRefused("record_identity_mismatch")
                # Preserve older score-only rows; never invent missing A data.
                innings = value.get("inning_scores")
                if innings is not None:
                    if not isinstance(innings, list) or not innings:
                        raise InventoryRefused("invalid_innings")
                    for school, score in ((value["team1_id"], value["team1_score"]),
                                          (value["team2_id"], value["team2_score"])):
                        if sum(r["runs"] for r in innings
                               if r["batting_team_id"] == school and r["was_played"]) != score:
                            raise InventoryRefused("inning_total_mismatch")
                records[key] = value
        if len(records) != con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
            raise InventoryRefused("orphan_match")
        if not fictional:
            identity = con.execute("SELECT metadata_json FROM archive_identity WHERE id=1").fetchone()
            if identity is None:
                raise InventoryRefused("archive_identity_missing")
            initial = json.loads(identity[0])
            first = years.get(initial.get("initial_year"))
            if first is None or any(json.loads(first["metadata_json"]).get(k) != initial.get(k)
                                    for k in ("rng_seed", "resolver_contract", "plan_fingerprint")):
                raise InventoryRefused("archive_identity_mismatch")
    return records, years


def _calendar(path):
    plans = {}
    with closing(_ro(path)) as con:
        for row in con.execute("SELECT * FROM sandbox_year_plans ORDER BY game_year"):
            value = verify_calendar(row["plan_json"], row["content_sha256"], row["game_year"])
            if any(value[k] != row[k] for k in ("schema_version", "source_kind", "policy_id")):
                raise InventoryRefused("calendar_identity_mismatch")
            plans[row["game_year"]] = (value, row["content_sha256"])
    return plans


def _rosters(path):
    count = 0
    with closing(_ro(path)) as con:
        identities = {r["player_id"]: r for r in con.execute("SELECT * FROM career_player_identities")}
        for row in con.execute("SELECT year,school_id FROM career_school_rosters"):
            roster = CareerRosterArchive._get(con, row["year"], row["school_id"])
            for player in roster.players:
                identity = identities.get(player.player_id)
                if identity is None or identity["identity_json"] != _identity(player):
                    raise InventoryRefused("player_identity_mismatch")
            count += 1
        for row in identities.values():
            _check_digest(row["identity_json"], row["identity_sha256"])
            data = json.loads(row["identity_json"])
            if any(data[k] != row[k] for k in ("player_id", "school_id", "entry_year")):
                raise InventoryRefused("player_identity_mismatch")
    return count, len(identities)


def _inventory_slot(slot_root: str | Path, *, slot_id: str, contract: str,
                   source: str = "manual", authorized_read: bool = False,
                   expected_files: Mapping[str, str] | None = None) -> dict:
    """Inspect declared contracts, not prove whole-game restore safety.

    expected_files is a PRIVATE in-memory map of relative filename to digest
    from an independently pinned copy. It is not a manifest or authentication.
    Missing/mismatched anchored originals refuse; derived files stay unused.
    legacy JSON/v2 have no slot ID; without an anchor foreign identical content
    and omitted historical years cannot be detected. No replay/load is called.
    """
    if authorized_read is not True:
        raise InventoryRefused("read_authorization_required")
    try:
        slot = SaveSlotManager.validate_slot_id(slot_id)
    except ValueError:
        raise InventoryRefused("invalid_request") from None
    if contract not in CONTRACTS or source not in ("manual", "autosave"):
        raise InventoryRefused("invalid_request")
    root = Path(slot_root)
    if root.absolute() != root.resolve() or root.name != slot or not root.is_dir():
        raise InventoryRefused("slot_root_mismatch")
    # Refuse nested symlinks/active SQLite artifacts BEFORE any reads.
    paths = sorted(root.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise InventoryRefused("symlink_input")
    if any(p.name.endswith(("-wal", "-shm", "-journal")) for p in paths):
        raise InventoryRefused("quiescent_copy_required")
    files = {p.relative_to(root).as_posix(): p for p in paths if p.is_file()}
    before = {name: file_digest(p) for name, p in files.items()}
    required = set(CONTRACTS[contract])
    if contract == "legacy_live":
        required.add(source)
    roles = {role: {"category": "derived" if role.endswith("stats") else
                   "metadata" if role == "slot_metadata" else "original",
                   "present": name in files} for role, name in FILES.items()}
    blockers, notes, counts = [], [], {}
    for role in sorted(required):
        if not roles[role]["present"]:
            blockers.append("required_original_missing:" + role)
    known = set(FILES.values())
    checkpoints = {n: p for n, p in files.items()
                   if p.suffix == ".json" and p.parent.name in CHECKPOINT_DIRS}
    backups = {n: p for n, p in files.items()
               if p.parent.name == "backups" and p.suffix == ".json"}
    known.update(checkpoints)
    known.update(backups)
    # Index names are user-selected; never accept/activate them here.
    # Recognize ONLY the existing v2 index namespace. Unknown DBs may be
    # originals and must never silently be declared disposable.
    index_pattern = re.compile(r"fictional_v2_school_read_index(?:_[A-Za-z0-9][A-Za-z0-9_-]{0,47})?\.sqlite3\Z")
    indexes = {n for n in set(files) | set(expected_files or {})
               if index_pattern.fullmatch(n)}
    known.update(indexes)
    counts.update(files=len(files), checkpoint_files=len(checkpoints),
                  rolling_json_backups=len(backups), unused_indexes=len(indexes),
                  unclassified_files=len(set(files) - known))
    if counts["unclassified_files"]:
        notes.append("unclassified_files_require_manual_review")
    for name, expected in (expected_files or {}).items():
        # Only compare map keys; never follow a caller-provided external path.
        derived = name in indexes or name in (FILES["legacy_stats"], FILES["v2_stats"])
        if name not in before or before[name] != expected:
            (notes if derived else blockers).append(
                "derived_anchor_mismatch_unused" if derived else "pinned_original_missing_or_mismatched")
    if not expected_files:
        notes.append("slot_and_complete_history_not_proven_without_private_anchor")
    live = legacy = plans = v2 = None
    def check(role, action):
        try:
            return action()
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, sqlite3.Error):
            blockers.append("original_contract_invalid:" + role)
            return None
    if "legacy_history" in required and roles["legacy_history"]["present"]:
        legacy = check("legacy_history", lambda: _history(root / FILES["legacy_history"]))
        if legacy is not None:
            counts.update(legacy_matches=len(legacy[0]),
                          legacy_complete_a_matches=sum(all(isinstance(r.get(k), list) and r[k]
                              for k in ("inning_scores", "team_stats", "batter_stats", "pitcher_stats"))
                              for r in legacy[0].values()), legacy_years=len(legacy[1]),
                          legacy_sealed_years=sum(y["status"] == "sealed" for y in legacy[1].values()))
    if contract == "legacy_live" and roles[source]["present"]:
        live = check(source, lambda: _validate_save_payload(_json_file(root / FILES[source])))
        if live is not None and legacy is not None:
            def compare_live():
                year = legacy[1].get(live["year"])
                if year is None or any(json.loads(year["metadata_json"])[k] != live[k]
                                       for k in ("year", "rng_seed", "resolver_contract", "plan_fingerprint")):
                    raise InventoryRefused("live_archive_identity_mismatch")
                replay = { (live["year"], r["competition_id"], r["match_id"]):
                           _history_payload(live["year"], r)
                           for r in live["completed_match_results"].values() }
                for key, value in replay.items():
                    if key not in legacy[0]:
                        notes.append("json_ahead_current_year_replay_sync_candidate")
                    elif legacy[0][key] != value:
                        raise InventoryRefused("live_archive_result_mismatch")
                extra = set(k for k in legacy[0] if k[0] == live["year"]) - set(replay)
                if extra:
                    notes.append("archive_ahead_preserve_history_no_rollback")
                counts["live_completed_matches"] = len(replay)
            check("live_archive_pair", compare_live)
    if "v2_calendar" in required and roles["v2_calendar"]["present"]:
        plans = check("v2_calendar", lambda: _calendar(root / FILES["v2_calendar"]))
        if plans is not None:
            counts["fictional_calendar_years"] = len(plans)
    if "v2_history" in required and roles["v2_history"]["present"] and plans is not None:
        v2 = check("v2_history", lambda: _history(root / FILES["v2_history"], fictional=True, plans=plans))
        if v2 is not None:
            counts.update(fictional_matches=len(v2[0]), fictional_years=len(v2[1]))
            if any(y["status"] != "sealed" for y in v2[1].values()):
                blockers.append("fictional_active_year_not_sealed_history")
            if set(plans) != set(v2[1]):
                blockers.append("fictional_calendar_history_year_set_mismatch")
    if "rosters" in required and roles["rosters"]["present"]:
        roster_counts = check("rosters", lambda: _rosters(root / FILES["rosters"]))
        if roster_counts is not None:
            counts.update(school_year_rosters=roster_counts[0], player_identities=roster_counts[1])
            notes.append("roster_component_verified_match_attribution_requires_separate_review")
    # Checkpoint checksum/slot only. Full feeder/replay validation is separate;
    # calling their existing load would WRITE the archive, so never call it.
    for path in checkpoints.values():
        def inspect_checkpoint(path=path):
            value = _json_file(path)
            checksum = value.pop("payload_checksum", None)
            if checksum != _digest(_canonical(value)) or value.get("slot_id") != slot:
                raise InventoryRefused("checkpoint_slot_or_checksum_mismatch")
        check("checkpoint", inspect_checkpoint)
    if checkpoints:
        notes.append("checkpoint_dependencies_and_replay_require_separate_review")
    # No stat cache/index is selected, read, generated, migrated or repaired.
    notes.append("derived_indexes_unused_explicit_rebuild_and_selection_only")
    try:
        after_paths = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
        unchanged = set(after_paths) == set(before) and all(
            not p.is_symlink() and file_digest(p) == before[n] for n, p in after_paths.items())
    except OSError:
        unchanged = False
    if not unchanged:
        blockers.append("input_changed_during_audit")
    return {
        "contract": contract, "source": source if contract == "legacy_live" else None,
        "roles": roles, "counts": counts, "blockers": sorted(set(blockers)),
        "notes": sorted(set(notes)), "contract_consistent": not blockers,
        "input_bytes_unchanged": unchanged, "restoration_authorized": False,
        "generation_adopted": False, "fictional_v2_is_live_progression": False,
        "whole_game_restore_proven": False,
        "player_membership_and_growth_replay_proven": False,
    }


def inventory_slot(slot_root: str | Path, *, slot_id: str, contract: str,
                   source: str = "manual", authorized_read: bool = False,
                   expected_files: Mapping[str, str] | None = None) -> dict:
    """Read only explicitly authorized, closed input; return sanitized statistics.

    No paths, IDs, full SHA lists, input contents or raw exception text are
    returned. A private expected_files pin is content comparison, not a signed
    identity, persistent approval, or a production generation format.
    """
    try:
        return _inventory_slot(slot_root, slot_id=slot_id, contract=contract,
                               source=source, authorized_read=authorized_read,
                               expected_files=expected_files)
    except InventoryRefused:
        raise
    except (OSError, ValueError, TypeError, sqlite3.Error):
        raise InventoryRefused("unreadable_input") from None


def main(argv=None):
    """No save-path input: run only the regression suite's owned fixtures."""
    import argparse
    import platform
    from time import perf_counter
    import unittest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    # Artifacts are explicitly selected; refuse replacing existing files.
    with args.json_output.open("x", encoding="utf-8") if args.json_output else nullcontext(None) as output:
        start = perf_counter()
        tests = Path(__file__).resolve().parents[1] / "tests"
        suite = unittest.defaultTestLoader.discover(str(tests), pattern="test_stage43g91_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        evidence = dict(tests=result.testsRun, failures=len(result.failures),
                        errors=len(result.errors), skipped=len(result.skipped),
                        successful=result.wasSuccessful(), seconds=perf_counter() - start,
                        python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                        fixture_only=True, generation_adopted=False,
                        production_writers_changed=False, restoration_authorized=False)
        encoded = json.dumps(evidence, ensure_ascii=False, indent=2)
        if output:
            output.write(encoded + "\n")
        print(encoded)
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
