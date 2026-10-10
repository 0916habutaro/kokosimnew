"""Stage 43G-11: immutable game-year rulebook and opt-in season control.

This is a *sandbox* coordinator over already implemented career services.
It never extrapolates a 2026 host/berth distribution to a future year without
an explicit game projection; it does not unlock full-year auto rollover.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import json

from .career_preview_checkpoint import (
    CareerPreviewSaveError, _atomic_write, _checksum, _digest,
)
from .career_multi_preview_checkpoint import CareerMultiPreviewCheckpointService
from .career_kanagawa_spring_checkpoint import CareerKanagawaSpringCheckpointService
from .career_regional_main_checkpoint import CareerRegionalMainCheckpointService
from .chiba_third_place_checkpoint import ChibaThirdPlaceCheckpointService
from .same_year_regional_feeder_gate import (
    _csv_rows, project_same_year_regional_feeders,
)

KANTO = "CMP000006"
CHIBA = "CMP000092"
KANAGAWA = "CMP000095"
REGION_SOURCE_YEAR = 2026
# The 2026 Kanto spring model has a three-berth Chiba and seven two-berth
# prefectures. This is *not* a permanent rule for every following year.
EXPECTED_2026_KANTO = {
    "08": 2, "09": 2, "10": 2, "11": 2,
    "12": 3, "13": 2, "14": 2, "19": 2,
}
SCHEMA_VERSION = 1


class CareerYearPolicyBlocked(CareerPreviewSaveError):
    """The requested season has no verified game-policy or altered evidence."""


@dataclass(frozen=True)
class YearOperationStatus:
    year: int
    registered_competition_ids: tuple[str, ...]
    completed_competition_ids: tuple[str, ...]
    year_rulebook_registered: bool
    regional_game_projection_supported: bool
    regional_runtime_ready: bool
    full_year_gameplay_available: bool

    def as_dict(self) -> dict:
        return {
            "year": self.year,
            "registered_competition_ids": list(self.registered_competition_ids),
            "completed_competition_ids": list(self.completed_competition_ids),
            "year_rulebook_registered": self.year_rulebook_registered,
            "regional_game_projection_supported": self.regional_game_projection_supported,
            "regional_runtime_ready": self.regional_runtime_ready,
            "full_year_gameplay_available": self.full_year_gameplay_available,
            "next_year_automatic_rollover": False,
        }


class CareerYearOperationService:
    """Safe entry point for *registered* future-year game projections.

    A rulebook stores the venue assumption and the exact feeder authority. Its
    SHA is independent of daily match progress, but binds the same immutable
    annual entrant plan and sealed prior-year ledger. A non-Chiba host is an
    explicit unresolved scenario; the 2026 Chiba quota may not be applied.
    """

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi
        self.kanagawa = CareerKanagawaSpringCheckpointService(multi)
        self.chiba = ChibaThirdPlaceCheckpointService(multi)
        self.regional = CareerRegionalMainCheckpointService(multi)

    def _path(self, slot_id: str, year: int) -> Path:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        self.multi._path(slot, year)  # Retain existing future-year/ID validation.
        return (self.multi.solo.slots.slot_dir(slot) /
                "career_year_rulebooks" / f"{year}.json")

    def _feeder_rules(self) -> list[dict]:
        rows = _csv_rows(self.multi.solo.data_root, "regional_feeder_rules.csv")
        rows = sorted(
            (r for r in rows if r["destination_competition_id"] == KANTO
             and r.get("season_segment") == "spring"),
            key=lambda r: r["feeder_rule_id"],
        )
        if (len(rows) != 8 or len({r["feeder_rule_id"] for r in rows}) != 8
                or len({r["source_competition_id"] for r in rows}) != 8
                or {r["source_prefecture_code"]: int(r["quota"]) for r in rows}
                != EXPECTED_2026_KANTO
                or any(r.get("effective_year") != str(REGION_SOURCE_YEAR)
                       or r.get("qualification_mode") != "direct"
                       or r.get("selector") != "rank_range"
                       or r.get("rank_from") != "1"
                       or int(r.get("rank_to") or 0) != int(r["quota"])
                       for r in rows)):
            raise CareerYearPolicyBlocked(
                "2026 Kanto feeder graph changed: cannot project historical quotas"
            )
        return rows

    def _evidence(self, slot: str, year: int) -> dict:
        session = self.multi.load(slot, year=year)
        if session.slot_id != slot or session.year != year:
            raise CareerYearPolicyBlocked("multi-year save identity differs")
        rules = self._feeder_rules()
        return {
            "annual_plan_fingerprint": self.multi._fingerprint(session),
            "prior_sealed_year_ledger_sha256": session.prior_ledger_sha256,
            "regional_feeder_structure_sha256": _digest(rules),
        }

    def _policy(self, slot: str, year: int,
                host_prefecture_code: str | None) -> dict:
        if host_prefecture_code is not None and (
            not isinstance(host_prefecture_code, str)
            or host_prefecture_code not in EXPECTED_2026_KANTO
        ):
            raise CareerYearPolicyBlocked("unknown Kanto host prefecture")
        evidence = self._evidence(slot, year)
        supported = host_prefecture_code == "12"
        data = {
            "schema_version": SCHEMA_VERSION,
            "slot_id": slot,
            "year": year,
            "regional_competition_id": KANTO,
            "region_source_structure_year": REGION_SOURCE_YEAR,
            "host_prefecture_code": host_prefecture_code,
            "host_choice_source": (
                "explicit_game_projection" if host_prefecture_code is not None
                else "unresolved"
            ),
            "region_berth_quota_by_prefecture": (
                dict(EXPECTED_2026_KANTO) if supported else None
            ),
            "region_expected_school_count": 17 if supported else None,
            "regional_game_projection_supported": supported,
            "regional_rule_refresh_required": not supported,
            "region_game_calendar_source": (
                "2026_month_day_game_projection_only" if supported else None
            ),
            "year_official_rules_verified": False,
            "full_year_runtime_enabled": False,
            "next_year_automatic_rollover": False,
            **evidence,
        }
        data["payload_checksum"] = _checksum(data)
        return data

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CareerYearPolicyBlocked("year rulebook unreadable") from exc
        if (not isinstance(record, dict)
                or record.get("schema_version") != SCHEMA_VERSION
                or record.get("payload_checksum") != _checksum(record)):
            raise CareerYearPolicyBlocked("year rulebook checksum invalid")
        return record

    def register(self, slot_id: str, *, year: int,
                 host_prefecture_code: str | None = None) -> dict:
        """Explicitly lock the regional host *assumption* for one saved year."""
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        path = self._path(slot, year)
        proposed = self._policy(slot, year, host_prefecture_code)
        if path.is_file():
            existing = self._read(path)
            if existing != proposed:
                raise CareerYearPolicyBlocked("year rulebook already locked differently")
            return dict(existing)
        _atomic_write(path, proposed)
        return dict(proposed)

    def load(self, slot_id: str, *, year: int) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        saved = self._read(self._path(slot, year))
        if saved != self._policy(slot, year, saved.get("host_prefecture_code")):
            raise CareerYearPolicyBlocked(
                "year rulebook no longer matches sealed save or 2026 source"
            )
        return saved

    def audit(self, slot_id: str, *, year: int) -> dict:
        """Report the current *registered subset*, not a completed full season."""
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        session = self.multi.load(slot, year=year)
        path = self._path(slot, year)
        policy = self.load(slot, year=year) if path.is_file() else None
        support = bool(policy and policy["regional_game_projection_supported"])
        eligible = False
        blocking = []
        if not policy:
            blocking.append("year_rulebook_missing")
        elif not support:
            blocking.append("host_or_regional_berths_require_rule_refresh")
        elif not all(p.scheduled.is_complete for p in session.previews.values()):
            blocking.append("yearly_registered_competitions_incomplete")
        else:
            placements = {}
            chiba_path = self.chiba._path(slot, year)
            if chiba_path.is_file():
                game = self.chiba.load(slot, year=year)
                placements[CHIBA] = game["match_id"]
            try:
                feeder = project_same_year_regional_feeders(
                    self.multi, session, KANTO,
                    placement_decider_match_ids=placements,
                    kanagawa_sidecar_enabled=True,
                )
                eligible = bool(
                    feeder["all_feeder_results_verified"]
                    and feeder["verified_entrant_count"] == 17
                )
                if not eligible:
                    blocking.extend(feeder["unresolved_feeder_rule_ids"])
            except CareerPreviewSaveError:
                # Missing/incomplete sidecars are not authorization. Corrupted
                # existing manifests/checkpoints should be surfaced by load.
                if self.kanagawa._path(slot, year).is_file():
                    raise
                blocking.append("same_year_kanagawa_qualification_not_registered")
        if not eligible and not blocking:
            blocking.append("17_verified_regional_sources_missing")
        state = YearOperationStatus(
            year=year,
            registered_competition_ids=tuple(sorted(session.previews)),
            completed_competition_ids=tuple(sorted(session.completed_runs())),
            year_rulebook_registered=policy is not None,
            regional_game_projection_supported=support,
            regional_runtime_ready=eligible,
            full_year_gameplay_available=False,
        )
        return {
            **state.as_dict(),
            "blockers": blocking,
            "regional_expected_school_count": (
                policy["region_expected_school_count"] if policy else None
            ),
            "regional_host_prefecture_code": (
                policy["host_prefecture_code"] if policy else None
            ),
            "future_real_world_calendar_verified": False,
            "historical_storage": "sqlite_option_a_score_innings_players",
            "unbounded_years_implemented": False,
            "year_limit_current_iso_calendar": 9999,
        }

    def start_regional(self, slot_id: str, *, year: int):
        """Gate an already supported regional MAIN, never extrapolate a new host."""
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        policy = self.load(slot, year=year)
        if not policy["regional_game_projection_supported"]:
            raise CareerYearPolicyBlocked(
                "non-2026-Chiba host: regional berths and days must be revalidated"
            )
        report = self.audit(slot, year=year)
        if not report["regional_runtime_ready"]:
            raise CareerYearPolicyBlocked(
                "regional game entry unverified: " + ",".join(report["blockers"])
            )
        decider = self.chiba.load(slot, year=year)
        return self.regional.start(
            slot, year=year,
            placement_decider_match_ids={CHIBA: decider["match_id"]},
            kanagawa_sidecar_enabled=True,
        )

    def next_date(self, slot_id: str, *, year: int) -> dict:
        """Continue only the already-registered game sources in date order."""
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        self.load(slot, year=year)
        if self.kanagawa._path(slot, year).is_file():
            spring = self.kanagawa.load(slot, year=year)
            return self.kanagawa.play_next_global_date(spring)
        session = self.multi.load(slot, year=year)
        return self.multi.play_next_date(session)

    def next_year_readiness(self, slot_id: str, *, year: int) -> dict:
        """Never use a projected subset as evidence of a full playable year."""
        status = self.audit(slot_id, year=year)
        return {
            "year": year,
            "next_year": year + 1,
            "auto_rollover_ready": False,
            "blockers": [
                "complete_national_season_not_instantiated",
                "future_year_hosts_and_qualification_rules_unverified",
                "next_year_roster_calendar_and_full_competition_graph_not_ready",
            ],
            "registered_competition_count": len(status["registered_competition_ids"]),
            "region_projection_ready": status["regional_runtime_ready"],
            "unbounded_years_implemented": False,
        }
