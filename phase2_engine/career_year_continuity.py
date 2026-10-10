"""Stage 43G-12: provenance-bound, read-only 2026 ↔ career-year bridge.

The 2026 LiveSeason manual/autosave represents a different save contract
from the 2027+ CareerMultiPreview checkpoint. No code here upgrades,
rewrites, or claims that their generated scores are the same game history.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from .career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
from .career_preview_checkpoint import (
    CareerPreviewSaveError, _atomic_write, _checksum, _digest,
)
from .live_season_save import inspect_live_season_save


class CareerYearContinuityBlocked(CareerPreviewSaveError):
    """Historical and roster lineage or optional legacy source is unsafe."""


class CareerYearContinuityService:
    """Bind a saved career year to its *own* sealed source and roster lineage.

    A 2026 LiveSeason save, when explicitly selected, is kept as an unmerged
    read-only reference. It is NEVER treated as source A-games for 2027.
    """

    SCHEMA = 1

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi

    def _path(self, slot: str, year: int) -> Path:
        sid = self.multi.solo.slots.validate_slot_id(slot)
        self.multi._path(sid, year)
        return (self.multi.solo.slots.slot_dir(sid) /
                "career_year_continuity" / f"{year}.json")

    def _legacy(self, slot: str, year: int, source: str | None) -> dict:
        if source is None:
            return {"source": None, "payload_checksum": None,
                    "schema_version": None, "reference_only": False}
        if source not in ("manual", "autosave"):
            raise CareerYearContinuityBlocked(
                "explicit legacy source must be manual or autosave"
            )
        if year != 2027:
            raise CareerYearContinuityBlocked(
                "2026 LiveSeason reference only applies to 2027 career start"
            )
        path = self.multi.solo.slots.save_path(slot, source)
        try:
            info = inspect_live_season_save(path)
        except (OSError, ValueError) as exc:
            raise CareerYearContinuityBlocked(
                "selected 2026 LiveSeason source is invalid"
            ) from exc
        if (info["year"] != 2026
                or not info["payload_checksum"]
                or not info["plan_fingerprint"]):
            raise CareerYearContinuityBlocked(
                "legacy 2026 source year or fingerprint differs"
            )
        return {
            "source": source,
            "payload_checksum": info["payload_checksum"],
            "schema_version": info["schema_version"],
            "resolver_contract": info["resolver_contract"],
            "plan_fingerprint": info["plan_fingerprint"],
            "reference_only": True,
        }

    def _roster_evidence(self, slot: str, year: int, session) -> dict:
        archive = self.multi.solo._rosters(slot)
        schools = sorted({
            school
            for comp in session.inputs
            for school in comp["entrant_school_ids"]
        })
        if not schools:
            raise CareerYearContinuityBlocked("career school set is empty")
        rows = []
        participants = 0
        returning = 0
        graduates = 0
        newcomers = 0
        seed = session.inputs[0]["career_seed"]
        for school in schools:
            previous = archive.roster(year - 1, school)
            current = archive.roster(year, school)
            if (previous is None or current is None
                    or previous.school_id != school
                    or current.school_id != school
                    or previous.reference_year != year - 1
                    or current.reference_year != year
                    or current.cohort_policy != "career_v1"
                    or previous.rng_seed != seed or current.rng_seed != seed):
                raise CareerYearContinuityBlocked(
                    f"school roster transition missing or incompatible: {school}"
                )
            prior = {p.player_id: p for p in previous.players}
            now = {p.player_id: p for p in current.players}
            exp_survivors = {p.player_id for p in previous.players
                             if p.academic_year < 3}
            actual_survivors = set(prior) & set(now)
            if exp_survivors != actual_survivors:
                raise CareerYearContinuityBlocked(
                    f"player continuity set differs for {school}"
                )
            for pid in exp_survivors:
                old = prior[pid]
                new = now[pid]
                if (new.academic_year != old.academic_year + 1
                        or new.entry_year != old.entry_year
                        or new.roster_no != old.roster_no
                        or new.display_name != old.display_name):
                    raise CareerYearContinuityBlocked(
                        f"returning player identity/grade differs: {pid}"
                    )
            fresh = [p for p in current.players if p.player_id not in prior]
            expired = [p for p in previous.players if p.academic_year == 3]
            if len(fresh) != len(expired) or any(
                p.academic_year != 1 or p.entry_year != year
                for p in fresh
            ):
                raise CareerYearContinuityBlocked(
                    f"graduate/newcomer cohort counts differ for {school}"
                )
            # SHA of the *complete* roster payload, including immutable IDs
            # and all fields—not merely the human-readable names.
            rows.extend((
                (year - 1, school, _digest(previous.to_dict())),
                (year, school, _digest(current.to_dict())),
            ))
            participants += len(current.players)
            returning += len(actual_survivors)
            graduates += len(expired)
            newcomers += len(fresh)
        return {
            "verified_school_count": len(schools),
            "current_year_player_count": participants,
            "returning_player_count": returning,
            "graduated_from_previous_roster_count": graduates,
            "newcomer_player_count": newcomers,
            "roster_lineage_sha256": _digest(rows),
        }

    def _evidence(self, slot: str, year: int,
                  legacy_source: str | None) -> dict:
        session = self.multi.load(slot, year=year)
        if (session.year != year or session.slot_id != slot
                or not session.inputs):
            raise CareerYearContinuityBlocked("career year identity differs")
        history = self.multi.solo._archive(slot)
        with sqlite3.connect(history.db_path) as conn:
            conn.row_factory = sqlite3.Row
            prior = conn.execute(
                "SELECT status, match_count, ledger_sha256 "
                "FROM career_years WHERE year=?", (year - 1,),
            ).fetchone()
            current = conn.execute(
                "SELECT status, metadata_json FROM career_years WHERE year=?",
                (year,),
            ).fetchone()
            if (prior is None or prior["status"] != "sealed"
                    or current is None or current["status"] != "active"):
                raise CareerYearContinuityBlocked(
                    "adjacent archived game years must be sealed → active"
                )
            count, ledger = history._ledger(conn, year - 1)
            if ((prior["match_count"], prior["ledger_sha256"])
                    != (count, ledger)
                    or ledger != session.prior_ledger_sha256):
                raise CareerYearContinuityBlocked("prior sealed A ledger differs")
            # The authoritative current-year identity is checked by
            # CareerMultiPreview.load's register+sync, not by a guessed seed.
        return {
            "schema_version": self.SCHEMA,
            "slot_id": slot,
            "year": year,
            "previous_year": year - 1,
            "career_plan_fingerprint": self.multi._fingerprint(session),
            "career_previous_sealed_ledger_sha256": session.prior_ledger_sha256,
            "career_current_year_role": "sandbox_registered_subset",
            "original_2026_save": self._legacy(slot, year, legacy_source),
            "original_2026_live_results_imported": False,
            "original_2026_and_career_simulation_equivalent": False,
            "historical_option_a_archived": True,
            "next_year_automatic_rollover": False,
            "full_year_gameplay": False,
            **self._roster_evidence(slot, year, session),
        }

    def register(self, slot_id: str, *, year: int,
                 legacy_source: str | None = None) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        path = self._path(slot, year)
        body = self._evidence(slot, year, legacy_source)
        body["payload_checksum"] = _checksum(body)
        if path.exists():
            prior = self._read(path)
            if prior != body:
                raise CareerYearContinuityBlocked(
                    "year continuity contract is already locked differently"
                )
            return prior
        _atomic_write(path, body)
        return body

    @staticmethod
    def _read(path: Path) -> dict:
        import json
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CareerYearContinuityBlocked(
                "career year continuity manifest unreadable"
            ) from exc
        if (not isinstance(data, dict)
                or data.get("schema_version") != CareerYearContinuityService.SCHEMA
                or data.get("payload_checksum") != _checksum(data)):
            raise CareerYearContinuityBlocked(
                "career year continuity manifest checksum invalid"
            )
        return data

    def load(self, slot_id: str, *, year: int) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        original = self._read(self._path(slot, year))
        saved_source = original.get("original_2026_save", {})
        if not isinstance(saved_source, dict):
            raise CareerYearContinuityBlocked("legacy source metadata invalid")
        expected = self._evidence(slot, year, saved_source.get("source"))
        expected["payload_checksum"] = _checksum(expected)
        if original != expected:
            raise CareerYearContinuityBlocked(
                "year continuity evidence or roster lineage changed"
            )
        return original

    def readiness(self, slot_id: str, *, year: int) -> dict:
        """A truthful current status, not a full-year migration unlock."""
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        linked = self.load(slot, year=year)
        return {
            "year": year,
            "linked_to_previous_sealed_career_archive": True,
            "roster_lineage_verified": True,
            "verified_school_count": linked["verified_school_count"],
            "legacy_2026_reference_only": linked["original_2026_save"]["reference_only"],
            "legacy_save_results_migrated": False,
            "complete_2026_live_to_career_migration_ready": False,
            "automatic_next_year_start_ready": False,
            "school_player_history_view_ready": True,
        }
