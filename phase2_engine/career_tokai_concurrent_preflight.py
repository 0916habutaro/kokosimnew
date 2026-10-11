"""Stage43G-51: immutable-by-service preflight for concurrent Tokai access.

The complete 32-school Senbatsu participant selection and Aichi/Mie group
manifests are frozen BEFORE the first projected district qualifier date.
This does not execute either prefectural tournament. A completion certificate
is issued only after all 31 same-year Senbatsu games have saved A records.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from .career_invitational_manifest import (
    CareerInvitationalManifestService, InvitationalManifestConflict,
)
from .career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, _checkpoint,
)
from .career_preview_checkpoint import (
    CareerPreviewSaveError, _atomic_write, _checksum, _digest,
)
from .career_tokai_senbatsu_access_gate import (
    SENBATSU_ID, TOKAI_PREFECTURES, CareerTokaiSenbatsuAccessService,
    TokaiSenbatsuNotReady, _verify_rule,
)
from .future_season_blueprint import build_future_season_blueprint
from .paths import resolve_data_file


def _reference_group_members(repo, group: dict) -> set[str]:
    """Expand Mie's verified parent areas into their actual eight subareas.

    School memberships are stored on leaf areas only. Never treat a
    parent's lack of direct rows as proof that its schools are unknown.
    """
    known = set(repo.group_school_ids(group, 2026))
    if group.get("competition_id") != "CMP000115":
        return known
    parents = set(group.get("source_area_ids", "").split(";")) - {""}
    area_path = resolve_data_file(repo.data_dir, "competition_areas.csv")
    with area_path.open("r", encoding="utf-8-sig", newline="") as stream:
        areas = list(csv.DictReader(stream))
    children = {
        row["area_id"]
        for row in areas
        if row["parent_area_id"] in parents
        and row["scheme_id"] == group.get("source_scheme_id")
        and row["prefecture_code"] == "24"
    }
    # Stage12B uses exactly eight official leaf subareas for the 3 parent
    # districts; do not invent or infer geography from school names.
    if not children:
        raise TokaiPreflightNotReady("Mie subarea membership contract missing")
    for child in children:
        known.update(repo.area_school_ids.get(("2026", child), set()))
    return known



class TokaiPreflightNotReady(CareerPreviewSaveError):
    """A source plan, early staging deadline or district manifest is invalid."""


class CareerTokaiConcurrentPreflight:
    """Freeze the source and district groups before any annual game.

    The 32 participants form the source of bypass rights, not winners of the
    national event. Main seed positions remain unknown. The 2026 master is
    a reference for school grouping, NOT official 2027 school registration.
    """

    SCHEMA = 1

    def __init__(self, multi: CareerMultiPreviewCheckpointService):
        self.multi = multi
        self.manifests = CareerInvitationalManifestService(multi)
        self.certifier = CareerTokaiSenbatsuAccessService(multi)

    def _path(self, slot_id: str, year: int) -> Path:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        self.multi._path(slot, year)
        return (
            self.multi.solo.slots.slot_dir(slot) / "career_tokai_preflights"
            / f"{year}_aichi_mie.json"
        )

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            import json
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError, TypeError) as exc:
            raise TokaiPreflightNotReady("Tokai preflight unreadable") from exc
        if (not isinstance(payload, dict)
                or payload.get("schema_version") != CareerTokaiConcurrentPreflight.SCHEMA
                or not isinstance(payload.get("payload_checksum"), str)
                or payload["payload_checksum"] != _checksum(payload)):
            raise TokaiPreflightNotReady("Tokai preflight checksum invalid")
        return payload

    def _build(
        self, slot_id: str, year: int,
        groups: Mapping[str, Mapping[str, Sequence[str]]],
        *, require_preseason: bool = True,
    ) -> dict:
        repo = self.multi.solo.repo
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        if set(groups) != set(TOKAI_PREFECTURES):
            raise TokaiPreflightNotReady(
                "both Aichi and Mie explicit district manifests are required"
            )
        session = self.multi.load(slot, year=year)
        try:
            source = self.manifests._manifest(slot, year)
        except InvitationalManifestConflict as exc:
            raise TokaiPreflightNotReady(
                "complete 32-school Senbatsu plan must be recorded first"
            ) from exc
        if (source["source_plan_fingerprint"] != self.multi._fingerprint(session)
                or source["previous_year_sealed_ledger_sha256"]
                != session.prior_ledger_sha256):
            raise TokaiPreflightNotReady("annual Senbatsu source plan changed")
        selection = list(source["entrant_school_ids"])
        if len(selection) != 32 or len(set(selection)) != 32:
            raise TokaiPreflightNotReady("32 distinct annual Senbatsu schools required")
        blueprint = build_future_season_blueprint(
            self.multi.solo.data_root, year=year,
            base_seed=session.inputs[0]["base_seed"],
        )
        normalized = {}
        calendar = {}
        for cid, (prefecture, rule_id, format_id, group_count) in TOKAI_PREFECTURES.items():
            _verify_rule(repo, cid, year)
            stage = repo.stage_by_code(cid, "BRANCH_QUALIFIER")
            master_groups = repo.groups_by_stage[stage["stage_id"]]
            manifest = groups[cid]
            if (not isinstance(manifest, Mapping)
                    or len(master_groups) != group_count
                    or set(manifest) != {x["stage_group_id"] for x in master_groups}):
                raise TokaiPreflightNotReady(
                    f"{cid}: every verified 2026 district must be provided"
                )
            direct = {
                school for school in selection
                if repo.schools[school]["prefecture_code"] == prefecture
            }
            seen = set()
            selected_groups = {}
            quota_sum = 0
            expected_formats = []
            for group in master_groups:
                gid = group["stage_group_id"]
                members = manifest[gid]
                if not isinstance(members, (list, tuple)):
                    raise TokaiPreflightNotReady(
                        f"{gid}: school IDs must be an explicit ordered list"
                    )
                members = list(members)
                model = repo.group_format[gid]["format_model_id"]
                quota = repo.param(
                    stage["stage_id"], "output_slots", gid,
                    int(group.get("advance_slots_to_next") or 0),
                )
                if (type(quota) is not int or quota <= 0
                        or len(members) < quota
                        or len(members) != len(set(members))
                        or any(type(s) is not str
                               or s not in repo.school_to_program
                               or repo.schools[s]["prefecture_code"] != prefecture
                               or s not in _reference_group_members(repo, group)
                               for s in members)):
                    raise TokaiPreflightNotReady(
                        f"{gid}: invalid district affiliation or quota"
                    )
                if any(s in seen or s in direct for s in members):
                    raise TokaiPreflightNotReady(
                        f"{gid}: duplicate or Senbatsu direct school in qualifier"
                    )
                seen.update(members)
                selected_groups[gid] = members
                quota_sum += quota
                expected_formats.append(model)
            if (format_id == "FMT010" and set(expected_formats)
                    != {"FMT010", "FMT011", "FMT012", "FMT013", "FMT014"}):
                raise TokaiPreflightNotReady("Aichi mixed group models changed")
            if format_id == "FMT016" and set(expected_formats) != {"FMT016"}:
                raise TokaiPreflightNotReady("Mie group format changed")
            stage_cal = [
                x for x in blueprint["stage_calendars"]
                if x["competition_id"] == cid
                and x["stage_code"] == "BRANCH_QUALIFIER"
            ]
            main_cal = [
                x for x in blueprint["calendars"]
                if x["competition_id"] == cid
            ]
            if len(stage_cal) != 1 or len(main_cal) != 1:
                raise TokaiPreflightNotReady("projected calendar incomplete")
            qrow, mrow = stage_cal[0], main_cal[0]
            if (qrow.get("date_source") != "game_projection_v1"
                    or qrow.get("real_world_verified") is not False
                    or mrow.get("date_source") != "game_projection_v1"
                    or mrow.get("real_world_verified") is not False):
                raise TokaiPreflightNotReady(
                    "projected 2027 dates must be non-official"
                )
            qdays = [d for d in qrow["date_list"].split(";") if d]
            mdays = [d for d in mrow["game_date_list"].split(";") if d]
            if (not qdays or not mdays
                    or qdays != sorted(set(qdays))
                    or qdays[-1] >= mdays[0]):
                raise TokaiPreflightNotReady(
                    "all district days must precede the prefectural MAIN"
                )
            calendar[cid] = {
                "qualifier_first_date": qdays[0],
                "qualifier_last_date": qdays[-1],
                "main_first_date": mdays[0],
                "qualifier_slots": quota_sum,
                "additional_main_bypass_school_ids": sorted(direct),
            }
            normalized[cid] = {
                gid: selected_groups[gid] for gid in sorted(selected_groups)
            }
        first = min(x["qualifier_first_date"] for x in calendar.values())
        if require_preseason and session.processed_dates:
            raise TokaiPreflightNotReady(
                "freeze must precede ALL annual game dates; never backdate qualification"
            )
        if source["selection_provenance"] != (
            "explicit_sandbox_game_selection_not_committee"
        ):
            raise TokaiPreflightNotReady("only explicit game selection permitted")
        result = {
            "schema_version": self.SCHEMA,
            "year": year,
            "slot_id": slot,
            "source_competition_id": SENBATSU_ID,
            "source_selection_sha256": source["entrant_sha256"],
            "source_selection_manifest_checksum": source["payload_checksum"],
            "source_plan_fingerprint": source["source_plan_fingerprint"],
            "prior_year_sealed_ledger_sha256":
                source["previous_year_sealed_ledger_sha256"],
            "qualifier_groups_by_competition": normalized,
            "destination_schedule": calendar,
            "qualification_frozen_before_date": first,
            "same_year_concurrent_schedule_required": True,
            "senbatsu_results_verified_at_freeze": False,
            "auto_prefectural_activation_enabled": False,
            "game_projection_not_official_schedule": True,
        }
        result["payload_checksum"] = _checksum(result)
        return result

    def freeze(
        self, slot_id: str, *, year: int,
        group_entrant_school_ids: Mapping[
            str, Mapping[str, Sequence[str]]
        ],
    ) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        path = self._path(slot, year)
        if path.exists():
            raise TokaiPreflightNotReady(
                "already frozen; changing participating groups is prohibited"
            )
        expected = self._build(slot, year, group_entrant_school_ids)
        # The national source list must be committed before the first
        # game; the separate participant manifest is idempotent.
        recorded = self.manifests.record(slot, year=year)
        if recorded["payload_checksum"] != expected[
            "source_selection_manifest_checksum"
        ]:
            raise TokaiPreflightNotReady("source selection manifest changed")
        _atomic_write(path, expected)
        return expected

    def audit(self, slot_id: str, *, year: int) -> dict:
        slot = self.multi.solo.slots.validate_slot_id(slot_id)
        path = self._path(slot, year)
        if not path.is_file():
            return {
                "status": "no_preseason_qualification_freeze",
                "year": year,
                "auto_prefectural_activation_enabled": False,
            }
        frozen = self._read(path)
        if frozen["year"] != year or frozen["slot_id"] != slot:
            raise TokaiPreflightNotReady("foreign season preflight")
        session = self.multi.load(slot, year=year)
        source = self.manifests._manifest(slot, year)
        manifest_path = self.manifests._path(slot, year)
        if not manifest_path.is_file():
            raise TokaiPreflightNotReady(
                "original frozen national participant manifest missing"
            )
        recorded = self.manifests._read(manifest_path)
        if recorded != source:
            raise TokaiPreflightNotReady("national participant manifest changed")
        if (recorded["payload_checksum"]
                != frozen["source_selection_manifest_checksum"]
                or source["entrant_sha256"] != frozen["source_selection_sha256"]
                or source["source_plan_fingerprint"]
                != frozen["source_plan_fingerprint"]
                or session.prior_ledger_sha256
                != frozen["prior_year_sealed_ledger_sha256"]):
            raise TokaiPreflightNotReady("preseason selection or ledger changed")
        groups = frozen["qualifier_groups_by_competition"]
        # Recalculate static contract even after games have progressed.
        # This catches master/fixture changes and invalid stored groups.
        replay = self._build(
            slot, year, groups, require_preseason=False,
        )
        if replay != frozen:
            raise TokaiPreflightNotReady("frozen district plan or calendar changed")
        if set(groups) != set(TOKAI_PREFECTURES):
            raise TokaiPreflightNotReady("frozen district contract incomplete")
        if any(
            cid in session.previews for cid in TOKAI_PREFECTURES
        ):
            raise TokaiPreflightNotReady(
                "preflight-only contract cannot be confused with live prefectural fixtures"
            )
        proof = self.certifier.audit(slot, year=year)
        if proof.get("status") != "complete_same_year_saved_senbatsu_verified":
            return {
                "status": "frozen_waiting_for_31_saved_senbatsu_games",
                "year": year,
                "source_selection_sha256": frozen["source_selection_sha256"],
                "qualifier_first_projected_date":
                    frozen["qualification_frozen_before_date"],
                "auto_prefectural_activation_enabled": False,
                "regional_runtime_ready": False,
            }
        for cid in TOKAI_PREFECTURES:
            expected = frozen["destination_schedule"][cid][
                "additional_main_bypass_school_ids"
            ]
            actual = proof["prefectures"][cid]["eligible_direct_main_school_ids"]
            if expected != sorted(actual):
                raise TokaiPreflightNotReady(
                    f"{cid}: saved results disagree with frozen national selection"
                )
        return {
            "status": "source_games_confirm_frozen_preseason_selection",
            "year": year,
            "source_games_sha256": proof["source_games_sha256"],
            "source_selection_sha256": frozen["source_selection_sha256"],
            "prefectures": {
                cid: {
                    "bypass_school_ids": frozen["destination_schedule"][cid][
                        "additional_main_bypass_school_ids"
                    ],
                    "district_groups_frozen": len(groups[cid]),
                    "qualifier_first_date": frozen["destination_schedule"][cid][
                        "qualifier_first_date"
                    ],
                }
                for cid in TOKAI_PREFECTURES
            },
            "schedule_conflict_requires_simultaneous_activation":
                proof["schedule_conflict_requires_separate_activation_contract"],
            "auto_prefectural_activation_enabled": False,
            "regional_runtime_ready": False,
        }
