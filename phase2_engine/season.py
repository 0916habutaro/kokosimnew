from __future__ import annotations

import csv
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .engine import TournamentEngine
from .models import AnnualCompetitionInput, CompetitionRun
from .randomness import shuffled
from .repository import DataRepository
from .paths import resolve_data_file


@dataclass
class AccessResolution:
    access_rule_id: str
    destination_competition_id: str
    source_event_kind: str
    source_competition_id: str
    source_year: int
    action_type: str
    resolved_school_ids: List[str]
    expected_count: int
    resolution_source: str
    date_status: str
    status: str
    notes: str = ""


@dataclass
class QualificationResolution:
    rule_id: str
    source_competition_id: str
    destination_competition_id: str
    source_result: str
    resolved_school_ids: List[str]
    expected_count: int
    date_status: str
    status: str
    notes: str = ""


@dataclass
class RegionalFeederResolution:
    feeder_rule_id: str
    destination_competition_id: str
    source_competition_id: str
    source_prefecture_code: str
    selector: str
    qualification_mode: str
    resolved_school_ids: List[str]
    expected_count: int
    status: str
    notes: str = ""


@dataclass
class RegionalPlayoffResolution:
    playoff_id: str
    destination_competition_id: str
    candidate_school_id_a: str
    candidate_school_id_b: str
    winner_school_id: str
    status: str
    notes: str = ""


@dataclass
class RegionalCompetitionRow:
    competition_id: str
    season_segment: str
    region_id: str
    entrant_count: int
    expected_team_count: int
    champion_school_id: str
    runner_up_school_id: str
    match_count: int
    status: str


@dataclass
class RegionalBridgeGap:
    competition_id: str
    season_segment: str
    region_id: str
    expected_team_count: int
    source_prefectural_competition_ids: List[str]
    member_prefecture_codes: List[str]
    status: str = "BLOCKED_MISSING_QUALIFICATION_RULE"
    notes: str = "県大会→地区大会の進出枠・順位selectorがqualification_rules.csvに未登録"


@dataclass
class CalendarGap:
    competition_id: str
    prefecture_code: str
    prefecture_name: str
    season_segment: str
    calendar_status: str
    start_date: str
    end_date: str
    status: str = "GAP_CALENDAR_NOT_VERIFIED"
    notes: str = "県大会の正式会期・抽選日・会場がresearch_pending"


@dataclass
class InternalStructureGap:
    competition_id: str
    prefecture_code: str
    prefecture_name: str
    season_segment: str
    expected_main_team_count: int
    simulated_main_team_count: int
    status: str = "GAP_INTERNAL_PREMAIN_STAGE_NOT_STRUCTURED"
    notes: str = "MAIN team_countと全加盟校直入れ結果が不一致。内部予選/一次予選等の追加構造化が必要"


@dataclass
class CompetitionSeasonRow:
    competition_id: str
    prefecture_code: str
    prefecture_name: str
    season_segment: str
    start_date: str
    end_date: str
    entrant_count: int
    direct_main_entry_count: int
    seed_event_bypass_count: int
    main_entrant_count: int
    champion_school_id: str
    runner_up_school_id: str
    match_count: int
    warning_count: int
    status: str


@dataclass
class SeasonExecution:
    year: int
    rng_seed: int
    competition_runs: Dict[str, CompetitionRun] = field(default_factory=dict)
    prefectural_rows: List[CompetitionSeasonRow] = field(default_factory=list)
    access_resolutions: List[AccessResolution] = field(default_factory=list)
    qualification_resolutions: List[QualificationResolution] = field(default_factory=list)
    regional_feeder_resolutions: List[RegionalFeederResolution] = field(default_factory=list)
    regional_playoff_resolutions: List[RegionalPlayoffResolution] = field(default_factory=list)
    regional_rows: List[RegionalCompetitionRow] = field(default_factory=list)
    regional_bridge_gaps: List[RegionalBridgeGap] = field(default_factory=list)
    calendar_gaps: List[CalendarGap] = field(default_factory=list)
    internal_structure_gaps: List[InternalStructureGap] = field(default_factory=list)
    senbatsu_participant_school_ids: List[str] = field(default_factory=list)
    bootstrap_prior_prefectural_rankings: Dict[str, List[str]] = field(default_factory=dict)
    bootstrap_prior_regional_participants: Dict[str, List[str]] = field(default_factory=dict)
    summer_local_competition_ids: List[str] = field(default_factory=list)
    player_master_records: Dict[str, dict] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> dict:
        spring = [r for r in self.prefectural_rows if r.season_segment == "spring"]
        autumn = [r for r in self.prefectural_rows if r.season_segment == "autumn"]
        summer_runs = [cid for cid in self.summer_local_competition_ids if cid in self.competition_runs]
        ability_match_count = sum(
            len(run.match_simulation_results)
            for run in self.competition_runs.values()
        )
        ability_competition_count = sum(
            bool(run.match_simulation_results)
            for run in self.competition_runs.values()
        )
        return {
            "year": self.year,
            "rng_seed": self.rng_seed,
            "ability_match_count": ability_match_count,
            "ability_competition_count": ability_competition_count,
            "player_master_count": len(self.player_master_records),
            "spring_prefectural_executed": len(spring),
            "autumn_prefectural_executed": len(autumn),
            "spring_prefectural_pass": sum(r.status == "PASS" for r in spring),
            "autumn_prefectural_pass": sum(r.status == "PASS" for r in autumn),
            "prefectural_total": len(self.prefectural_rows),
            "prefectural_pass_total": sum(r.status == "PASS" for r in self.prefectural_rows),
            "prefectural_gap_total": sum(r.status != "PASS" for r in self.prefectural_rows),
            "access_rules_resolved": sum(r.status == "PASS" for r in self.access_resolutions),
            "access_rules_total": len(self.access_resolutions),
            "summer_local_completed": len(summer_runs),
            "summer_local_total": len(self.summer_local_competition_ids),
            "summer_national_completed": "CMP000002" in self.competition_runs,
            "qualification_rules_resolved": sum(r.status == "PASS" for r in self.qualification_resolutions),
            "qualification_rules_blocked": sum(r.status != "PASS" for r in self.qualification_resolutions),
            "qualification_rules_total": len(self.qualification_resolutions),
            "regional_feeder_rules_resolved": sum(r.status == "PASS" for r in self.regional_feeder_resolutions),
            "regional_feeder_rules_total": len(self.regional_feeder_resolutions),
            "regional_playoffs_resolved": sum(r.status == "PASS" for r in self.regional_playoff_resolutions),
            "regional_playoffs_total": len(self.regional_playoff_resolutions),
            "spring_regional_executed": sum(r.season_segment == "spring" for r in self.regional_rows),
            "autumn_regional_executed": sum(r.season_segment == "autumn" for r in self.regional_rows),
            "regional_competitions_pass": sum(r.status == "PASS" for r in self.regional_rows),
            "regional_competitions_total": len(self.regional_rows),
            "jingu_completed": "CMP000003" in self.competition_runs,
            "regional_bridge_gap_count": len(self.regional_bridge_gaps),
            "prefectural_calendar_gap_count": len(self.calendar_gaps),
            "internal_structure_gap_count": len(self.internal_structure_gaps),
            "senbatsu_bootstrap_count": len(self.senbatsu_participant_school_ids),
            "warnings": list(self.warnings),
        }


class StructuralAnnualInputFactory:
    """Create annual structural inputs without hardcoding school names.

    This is an audit/simulation helper, not an official 2026 draw replay.  It uses the
    permanent area master plus Stage 12C structural entrant counts where a competition
    is known to use a participating subset (Chiba/Kanagawa/Gifu etc.).
    """

    def __init__(self, repo: DataRepository, data_dir: str | Path, base_seed: int):
        self.repo = repo
        self.data_dir = Path(data_dir)
        self.base_seed = base_seed
        self.pref_index = self._read("prefectural_competition_index_2026.csv")
        self.pref_by_comp = {r["competition_id"]: r for r in self.pref_index}
        self.exec_targets = {}
        p = resolve_data_file(self.data_dir, "stage12c3_structured_competition_execution.csv")
        if p.exists():
            for r in self._read(p.name):
                if r.get("status") == "PASS" and r.get("entrant_count"):
                    self.exec_targets[r["competition_id"]] = int(r["entrant_count"])

    def _begin_match_resolver_season(
        self,
        year: int,
        rng_seed: int,
    ) -> None:
        hook = getattr(self.match_resolver, "begin_season", None)
        if callable(hook):
            hook(year, rng_seed)

    def _capture_player_master(
        self,
        season: SeasonExecution,
    ) -> None:
        hook = getattr(self.match_resolver, "player_master_records", None)
        if not callable(hook):
            return
        records = hook()
        if not isinstance(records, dict):
            raise TypeError(
                "match_resolver.player_master_records() must return dict"
            )
        normalized: Dict[str, dict] = {}
        for player_id, row in records.items():
            if not isinstance(row, dict):
                raise TypeError(
                    f"{player_id}: player master record must be dict"
                )
            if str(row.get("player_id") or "") != str(player_id):
                raise ValueError(
                    f"{player_id}: player master player_id mismatch"
                )
            if int(row.get("reference_year") or 0) != season.year:
                raise ValueError(
                    f"{player_id}: player master reference_year mismatch"
                )
            normalized[str(player_id)] = dict(row)
        season.player_master_records = normalized

    def _read(self, name: str) -> List[dict]:
        with resolve_data_file(self.data_dir, name).open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def prefecture_code(self, competition_id: str) -> str:
        comp = self.repo.competition(competition_id)
        return comp.get("prefecture_code") or self.pref_by_comp.get(competition_id, {}).get("prefecture_code", "")

    def prefecture_school_ids(self, competition_id: str) -> List[str]:
        pcode = self.prefecture_code(competition_id)
        return sorted(sid for sid, row in self.repo.schools.items() if row.get("prefecture_code") == pcode)

    def summer_area_school_ids(self, competition_id: str, year: int) -> List[str]:
        comp = self.repo.competition(competition_id)
        area_id = comp.get("qualifying_area_id", "")
        ids = sorted(self.repo.area_school_ids.get((str(year), area_id), set()))
        if not ids:
            raise ValueError(f"{competition_id}: no summer-area membership for {area_id}/{year}")
        return ids

    def build_prefectural(
        self,
        competition_id: str,
        year: int,
        *,
        direct_main_entry_school_ids: Sequence[str] = (),
        seed_event_bypass_school_ids: Sequence[str] = (),
        rng_seed: int,
    ) -> AnnualCompetitionInput:
        direct = list(dict.fromkeys(direct_main_entry_school_ids))
        seed_bypass = list(dict.fromkeys(seed_event_bypass_school_ids))
        stages = self.repo.stages(competition_id)
        assigned_stages = [s for s in stages if s["stage_id"] in self.repo.assignments_by_stage]
        groups = []
        entrants = set()
        for stage in assigned_stages:
            for group in self.repo.groups_by_stage.get(stage["stage_id"], []):
                groups.append(group)
                entrants |= self.repo.group_school_ids(group, year)

        group_override: Dict[str, List[str]] = {}
        full_candidates = self.prefecture_school_ids(competition_id)
        if not entrants:
            entrants = set(full_candidates)
            if groups:
                for i, sid in enumerate(full_candidates):
                    gid = groups[i % len(groups)]["stage_group_id"]
                    group_override.setdefault(gid, []).append(sid)
        elif "MAIN" in {s["stage_code"] for s in stages} and not assigned_stages:
            entrants = set(full_candidates)

        # Tokyo autumn: the official 2026 structure has 232 team units.  The two
        # current summer East/West Tokyo champions bypass the preliminary round, leaving
        # 230 preliminary team units.  Phase 1 currently stores schools rather than
        # annual combined-team units, so structural audit chooses 232 deterministic
        # school proxies and distributes the 230 non-direct proxies over the 62 A/B
        # representative brackets as 44 four-team + 18 three-team groups.  Exact annual
        # combined-team mapping can later replace group_entrant_school_ids.
        if competition_id == "CMP000016":
            qstage = self.repo.stage_by_code(competition_id, "PRELIMINARY_QUALIFIER")
            qgroups = self.repo.groups_by_stage[qstage["stage_id"]]
            if len(qgroups) != 62:
                raise ValueError(f"{competition_id}: expected 62 Tokyo preliminary representative groups")
            forced = list(dict.fromkeys(direct))
            if year == 2026 and len(forced) != 2:
                raise ValueError(f"{competition_id}: 2026 structural input requires two summer direct entries")
            candidates = [x for x in full_candidates if x not in set(forced)]
            target_prelim = 230
            selected = shuffled(candidates, rng_seed, f"{competition_id}:2026_team_unit_proxy")[:target_prelim]
            if len(selected) != target_prelim:
                raise ValueError(f"{competition_id}: insufficient school proxies for 230 preliminary team units")
            sizes = [4] * 44 + [3] * 18
            sizes = shuffled(sizes, rng_seed, f"{competition_id}:preliminary_group_sizes")
            selected = shuffled(selected, rng_seed, f"{competition_id}:preliminary_group_draw")
            group_override = {}
            pos = 0
            for group, size in zip(qgroups, sizes):
                group_override[group["stage_group_id"]] = selected[pos:pos + size]
                pos += size
            if pos != target_prelim:
                raise AssertionError("Tokyo preliminary proxy partition mismatch")
            entrants = set(selected) | set(forced) | set(seed_bypass)

        # Kanagawa FMT006 requires exactly the annual participating subset so that the
        # 3/4-team pool equations match official MAIN quotas.  The actual direct team is
        # removed from its district pool, not a hardcoded placeholder.
        if competition_id in {"CMP000095", "CMP000096"}:
            qstage = self.repo.stage_by_code(competition_id, "BRANCH_QUALIFIER")
            reduced: List[str] = []
            direct_set = set(direct)
            for group in self.repo.groups_by_stage[qstage["stage_id"]]:
                ids = sorted(self.repo.group_school_ids(group, year))
                ids = [x for x in ids if x not in direct_set]
                slots = int(self.repo.param(qstage["stage_id"], "output_slots", group["stage_group_id"]))
                target = 2 * slots
                if len(ids) < target:
                    raise ValueError(f"{competition_id}/{group['group_name']}: insufficient pool entrants")
                reduced.extend(shuffled(ids, rng_seed, f"{competition_id}:{group['stage_group_id']}:annual_subset")[:target])
            entrants = set(reduced) | direct_set | set(seed_bypass)

        # Chiba autumn primary+repechage was observed as 140 qualifier entrants plus
        # one summer champion direct entry = 141 annual entrants in the Stage12C contract.
        elif competition_id == "CMP000093":
            target = self.exec_targets.get(competition_id, 141)
            forced = set(direct) | set(seed_bypass)
            candidates = [x for x in sorted(entrants) if x not in forced]
            need = target - len(forced)
            entrants = set(shuffled(candidates, rng_seed, f"{competition_id}:annual_subset")[:need]) | forced

        # Gifu autumn requires 58 annual entrants so 16 seeds leave 42 non-seeds, which
        # becomes the official one-match gate of 21 winners before the second tournament.
        elif competition_id == "CMP000110":
            target = self.exec_targets.get(competition_id, 58)
            seed_stage = self.repo.stage_by_code(competition_id, "SEED_EVENT")
            sgroups = self.repo.groups_by_stage[seed_stage["stage_id"]]
            available = {g["stage_group_id"]: sorted(self.repo.group_school_ids(g, year)) for g in sgroups}
            mins = {
                g["stage_group_id"]: int(g.get("seed_slots_generated") or 0)
                for g in sgroups
            }
            counts = self._allocate_group_counts(available, mins, target)
            chosen = []
            group_override = {}
            for g in sgroups:
                gid = g["stage_group_id"]
                ids = shuffled(available[gid], rng_seed, f"{competition_id}:{gid}:annual_subset")[:counts[gid]]
                group_override[gid] = ids
                chosen.extend(ids)
            entrants = set(chosen) | set(direct) | set(seed_bypass)

        # If a structural target says fewer annual participants than affiliations, trim
        # only when the generic format tolerates it.  This currently applies to the
        # Kagoshima seed event and is usually already achieved by group membership union.
        target = self.exec_targets.get(competition_id)
        if target and len(entrants) > target and competition_id not in {"CMP000095", "CMP000096", "CMP000093", "CMP000110"}:
            forced = set(direct) | set(seed_bypass)
            candidates = [x for x in sorted(entrants) if x not in forced]
            need = target - len(forced)
            entrants = set(shuffled(candidates, rng_seed, f"{competition_id}:generic_annual_subset")[:need]) | forced
            if group_override:
                entrant_set = set(entrants)
                group_override = {gid: [x for x in ids if x in entrant_set] for gid, ids in group_override.items()}

        entrants |= set(direct) | set(seed_bypass)

        # Ehime autumn uses permanent district groups only for the preceding seed event.
        # Its actual prefectural preliminary is a non-geographic annual draw, so feed the
        # complete annual entrant set into that global qualifier group explicitly.
        if competition_id == "CMP000144":
            qstage = self.repo.stage_by_code(competition_id, "PRELIMINARY_QUALIFIER")
            qgroups = self.repo.groups_by_stage[qstage["stage_id"]]
            if len(qgroups) != 1:
                raise ValueError(f"{competition_id}: expected one global preliminary group")
            group_override[qgroups[0]["stage_group_id"]] = sorted(entrants)

        if direct and group_override:
            direct_set = set(direct)
            group_override = {gid: [x for x in ids if x not in direct_set] for gid, ids in group_override.items()}

        return AnnualCompetitionInput(
            competition_id=competition_id,
            year=year,
            entrant_school_ids=sorted(entrants),
            direct_main_entry_school_ids=direct,
            seed_event_bypass_school_ids=seed_bypass,
            rng_seed=rng_seed,
            group_entrant_school_ids=group_override,
        )

    @staticmethod
    def _allocate_group_counts(
        available: Dict[str, List[str]], minimums: Dict[str, int], total: int
    ) -> Dict[str, int]:
        gids = list(available)
        counts = {gid: min(len(available[gid]), max(minimums.get(gid, 0), 0)) for gid in gids}
        if sum(counts.values()) > total:
            raise ValueError("minimum group counts exceed annual target")
        while sum(counts.values()) < total:
            candidates = [gid for gid in gids if counts[gid] < len(available[gid])]
            if not candidates:
                raise ValueError("annual target exceeds group membership")
            # Add to the group with the greatest remaining capacity; tie by id for determinism.
            gid = sorted(candidates, key=lambda g: (-(len(available[g]) - counts[g]), g))[0]
            counts[gid] += 1
        return counts


class SeasonOrchestrator:
    """Stage 12E season resolver including prefectural->regional qualification."""

    def __init__(
        self,
        repo: DataRepository,
        data_dir: str | Path,
        *,
        match_resolver=None,
    ):
        self.repo = repo
        self.data_dir = Path(data_dir)
        self.match_resolver = match_resolver
        self.engine = TournamentEngine(
            repo,
            main_match_resolver=match_resolver,
            pre_main_match_resolver=match_resolver,
        )
        self.pref_index = self._read("prefectural_competition_index_2026.csv")
        self.calendars = {r["competition_id"]: r for r in self._read("season_calendar.csv")}
        self.access_rules = self._read("competition_access_rules.csv")
        self.qualification_rules = self._read("qualification_rules.csv")
        self.regional_feeder_rules = self._read("regional_feeder_rules.csv")
        self.regional_playoffs = self._read("regional_qualification_playoffs.csv")
        self.selection_rules = self._read("selection_rules.csv")
        self.region_memberships = self._read("prefecture_region_memberships.csv")
        self.factory: StructuralAnnualInputFactory | None = None

    def _read(self, name: str) -> List[dict]:
        with resolve_data_file(self.data_dir, name).open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def run_structural_season(self, year: int = 2026, rng_seed: int = 2026100501) -> SeasonExecution:
        if year != 2026:
            raise NotImplementedError("Stage 12E structural audit currently targets the 2026 dataset")
        self._begin_match_resolver_season(year, rng_seed)
        self.factory = StructuralAnnualInputFactory(self.repo, self.data_dir, rng_seed)
        result = SeasonExecution(year=year, rng_seed=rng_seed)

        # Bootstrap inputs whose 2025 result database or actual committee selection is
        # not yet present.  They are deterministic structural fixtures, explicitly not
        # claims about the historical schools selected.
        prior_pref, prior_reg = self._bootstrap_prior_context(year, rng_seed)
        result.bootstrap_prior_prefectural_rankings = prior_pref
        result.bootstrap_prior_regional_participants = prior_reg
        senbatsu_ids = self._bootstrap_senbatsu_participants(year, rng_seed)
        result.senbatsu_participant_school_ids = senbatsu_ids
        senbatsu_run = self.engine.run(AnnualCompetitionInput(
            competition_id="CMP000001", year=year, entrant_school_ids=senbatsu_ids,
            rng_seed=self._seed(rng_seed, "CMP000001"),
        ))
        result.competition_runs["CMP000001"] = senbatsu_run

        # Spring: resolve all prior-year / Senbatsu access rules before running each
        # prefectural competition.  Use calendar order only as an audit ordering key.
        spring_rows = [r for r in self.pref_index if r["season_segment"] == "spring"]
        for row in sorted(spring_rows, key=lambda r: self._calendar_start(r["competition_id"])):
            cid = row["competition_id"]
            direct, seed_bypass, resolutions = self._resolve_access_for_destination(
                cid, year, result, prior_pref, prior_reg
            )
            result.access_resolutions.extend(resolutions)
            annual = self.factory.build_prefectural(
                cid, year, direct_main_entry_school_ids=direct,
                seed_event_bypass_school_ids=seed_bypass,
                rng_seed=self._seed(rng_seed, cid),
            )
            run = self.engine.run(annual)
            result.competition_runs[cid] = run
            result.prefectural_rows.append(self._season_row(row, run, annual))

        # Stage 12E: prefectural spring results feed the eight non-Hokkaido regional
        # tournaments.  Hokkaido spring is already a regional competition itself.
        self._run_regional_segment("spring", year, rng_seed, result)

        # Summer local qualifiers generate the current-year winners consumed by autumn
        # direct-entry and special-seed rules.  Then verify the 49 automatic national
        # qualification rules by actually running the 49-team national tournament.
        summer_ids = [
            cid for cid, c in self.repo.competitions.items()
            if c.get("competition_type") == "summer_local_qualifier" and c.get("reference_year") == str(year)
        ]
        summer_ids.sort(key=self._calendar_start)
        result.summer_local_competition_ids = summer_ids
        for cid in summer_ids:
            entrants = self.factory.summer_area_school_ids(cid, year)
            run = self.engine.run(AnnualCompetitionInput(
                competition_id=cid, year=year, entrant_school_ids=entrants,
                rng_seed=self._seed(rng_seed, cid),
            ))
            result.competition_runs[cid] = run

        # Automatic summer qualifications (49/49) are resolver-tested before national.
        summer_qualifiers = []
        for rule in self.qualification_rules:
            if rule["destination_competition_id"] != "CMP000002":
                continue
            qr = self._resolve_qualification(rule, result)
            result.qualification_resolutions.append(qr)
            if qr.status == "PASS":
                summer_qualifiers.extend(qr.resolved_school_ids)
        summer_qualifiers = list(dict.fromkeys(summer_qualifiers))
        if len(summer_qualifiers) == 49:
            result.competition_runs["CMP000002"] = self.engine.run(AnnualCompetitionInput(
                competition_id="CMP000002", year=year, entrant_school_ids=summer_qualifiers,
                rng_seed=self._seed(rng_seed, "CMP000002"),
            ))
        else:
            result.warnings.append(f"summer national qualifier count={len(summer_qualifiers)}; expected 49")

        # Autumn: current summer results are now in state, so direct-entry / special-seed
        # rules resolve from actual simulated source CompetitionRun objects.
        autumn_rows = [r for r in self.pref_index if r["season_segment"] == "autumn"]
        for row in sorted(autumn_rows, key=lambda r: self._calendar_start(r["competition_id"])):
            cid = row["competition_id"]
            direct, seed_bypass, resolutions = self._resolve_access_for_destination(
                cid, year, result, prior_pref, prior_reg
            )
            result.access_resolutions.extend(resolutions)
            annual = self.factory.build_prefectural(
                cid, year, direct_main_entry_school_ids=direct,
                seed_event_bypass_school_ids=seed_bypass,
                rng_seed=self._seed(rng_seed, cid),
            )
            run = self.engine.run(annual)
            result.competition_runs[cid] = run
            result.prefectural_rows.append(self._season_row(row, run, annual))

        # Stage 12E: run all eight autumn regionals from prefectural results. Hokkaido
        # and Tokyo are already represented by CMP000013/CMP000016.
        self._run_regional_segment("autumn", year, rng_seed, result)

        # All ten Jingu qualifiers can now be resolved and the national autumn
        # championship itself is executable.
        jingu_entrants: List[str] = []
        for rule in self.qualification_rules:
            if rule["destination_competition_id"] == "CMP000003":
                qr = self._resolve_qualification(rule, result)
                result.qualification_resolutions.append(qr)
                if qr.status == "PASS":
                    jingu_entrants.extend(qr.resolved_school_ids)
        jingu_entrants = list(dict.fromkeys(jingu_entrants))
        if len(jingu_entrants) == 10:
            result.competition_runs["CMP000003"] = self.engine.run(AnnualCompetitionInput(
                competition_id="CMP000003", year=year, entrant_school_ids=jingu_entrants,
                rng_seed=self._seed(rng_seed, "CMP000003"),
            ))
        else:
            result.warnings.append(f"Jingu qualifier count={len(jingu_entrants)}; expected 10")

        result.regional_bridge_gaps = self._regional_bridge_gaps(year)
        result.calendar_gaps = self._calendar_gaps(year)
        result.internal_structure_gaps = self._internal_structure_gaps(result)
        self._capture_player_master(result)
        return result

    def _run_regional_segment(self, segment: str, year: int, rng_seed: int, season: SeasonExecution) -> None:
        destinations = sorted({
            r["destination_competition_id"] for r in self.regional_feeder_rules
            if r.get("season_segment") == segment and r.get("effective_year") == str(year)
        }, key=self._calendar_start)
        for dest in destinations:
            entrants, resolutions, playoff_resolutions = self._resolve_regional_feeders(dest, year, rng_seed, season)
            season.regional_feeder_resolutions.extend(resolutions)
            season.regional_playoff_resolutions.extend(playoff_resolutions)
            expected = int(self.repo.competition(dest).get("team_count") or 0)
            status = "PASS" if len(entrants) == expected else "FAIL"
            if status == "PASS":
                run = self.engine.run(AnnualCompetitionInput(
                    competition_id=dest, year=year, entrant_school_ids=entrants,
                    rng_seed=self._seed(rng_seed, dest),
                ))
                season.competition_runs[dest] = run
                champion = run.outcome.champion_school_id if run.outcome else ""
                runner = run.outcome.runner_up_school_id if run.outcome else ""
                match_count = run.outcome.match_count if run.outcome else 0
            else:
                champion = runner = ""; match_count = 0
                season.warnings.append(f"{dest}: regional entrants={len(entrants)} expected={expected}")
            comp = self.repo.competition(dest)
            season.regional_rows.append(RegionalCompetitionRow(
                competition_id=dest, season_segment=segment, region_id=comp.get("region_id", ""),
                entrant_count=len(entrants), expected_team_count=expected,
                champion_school_id=champion, runner_up_school_id=runner,
                match_count=match_count, status=status,
            ))

    def _resolve_regional_feeders(
        self, destination_competition_id: str, year: int, rng_seed: int, season: SeasonExecution
    ) -> Tuple[List[str], List[RegionalFeederResolution], List[RegionalPlayoffResolution]]:
        rows = [r for r in self.regional_feeder_rules
                if r.get("destination_competition_id") == destination_competition_id
                and r.get("effective_year") == str(year)]
        rows.sort(key=lambda r: (int(r.get("priority") or 0), r["feeder_rule_id"]))
        selected: List[str] = []
        selected_set = set()
        candidate_by_rule: Dict[str, str] = {}
        resolutions: List[RegionalFeederResolution] = []

        for rule in rows:
            quota = int(rule.get("quota") or 0)
            source = rule.get("source_competition_id", "")
            source_type = rule.get("source_type", "")
            selector = rule.get("selector", "")
            ids: List[str] = []
            notes = ""

            if source_type == "national_invitational_participants" and selector == "participants_from_region":
                region = rule.get("source_region_filter", "")
                pref_codes = {
                    r["prefecture_code"] for r in self.region_memberships
                    if r.get("region_id") == region and r.get("season_segment") == "autumn"
                    and r.get("effective_year") == str(year)
                }
                ids = [sid for sid in season.senbatsu_participant_school_ids
                       if self.repo.schools[sid].get("prefecture_code") in pref_codes]
                ids = ids[:quota]
                notes = "current Senbatsu participant set filtered by regional membership"
            else:
                run = season.competition_runs.get(source)
                if run and run.outcome:
                    ranking = list(run.outcome.final_ranking_school_ids)
                    if selector == "rank_range":
                        lo = max(int(rule.get("rank_from") or 1), 1)
                        hi = max(int(rule.get("rank_to") or lo), lo)
                        if rule.get("fill_to_quota") == "yes":
                            # Scan beyond rank_to only to replace a team already qualified by
                            # an earlier route (notably the 2026 spring Kyushu Senbatsu recommendations).
                            pool = ranking[lo-1:]
                            if rule.get("exclude_already_selected") == "yes":
                                pool = [sid for sid in pool if sid not in selected_set]
                            ids = pool[:quota]
                        else:
                            pool = ranking[lo-1:hi]
                            if rule.get("exclude_already_selected") == "yes":
                                pool = [sid for sid in pool if sid not in selected_set]
                            ids = pool[:quota]
                    else:
                        notes = f"unsupported selector={selector}"
                else:
                    notes = "source competition not completed"

            mode = rule.get("qualification_mode", "direct")
            status = "PASS" if len(ids) == quota else "BLOCKED"
            if mode == "direct" and status == "PASS":
                for sid in ids:
                    if sid not in selected_set:
                        selected.append(sid); selected_set.add(sid)
            elif mode == "playoff_candidate" and status == "PASS":
                candidate_by_rule[rule["feeder_rule_id"]] = ids[0]

            resolutions.append(RegionalFeederResolution(
                feeder_rule_id=rule["feeder_rule_id"], destination_competition_id=destination_competition_id,
                source_competition_id=source, source_prefecture_code=rule.get("source_prefecture_code", ""),
                selector=selector, qualification_mode=mode, resolved_school_ids=ids,
                expected_count=quota, status=status, notes=notes,
            ))

        playoff_resolutions: List[RegionalPlayoffResolution] = []
        for p in [x for x in self.regional_playoffs
                  if x.get("destination_competition_id") == destination_competition_id
                  and x.get("effective_year") == str(year)]:
            a = candidate_by_rule.get(p["candidate_rule_id_a"], "")
            b = candidate_by_rule.get(p["candidate_rule_id_b"], "")
            if a and b:
                winner = shuffled([a, b], rng_seed, f"regional_playoff:{p['playoff_id']}:{a}:{b}")[0]
                if winner not in selected_set:
                    selected.append(winner); selected_set.add(winner)
                status = "PASS"; notes = "deterministic structural playoff; official annual result may override later"
            else:
                winner = ""; status = "BLOCKED"; notes = "playoff candidate missing"
            playoff_resolutions.append(RegionalPlayoffResolution(
                playoff_id=p["playoff_id"], destination_competition_id=destination_competition_id,
                candidate_school_id_a=a, candidate_school_id_b=b, winner_school_id=winner,
                status=status, notes=notes,
            ))

        return selected, resolutions, playoff_resolutions

    def _resolve_access_for_destination(
        self,
        destination_competition_id: str,
        year: int,
        season: SeasonExecution,
        prior_pref: Dict[str, List[str]],
        prior_reg: Dict[str, List[str]],
    ) -> Tuple[List[str], List[str], List[AccessResolution]]:
        direct: List[str] = []
        seed_bypass: List[str] = []
        resolutions: List[AccessResolution] = []
        for rule in [r for r in self.access_rules if r["destination_competition_id"] == destination_competition_id]:
            source_year = year + int(rule.get("source_year_offset") or 0)
            selector = rule.get("source_result_selector", "")
            pcode = rule.get("destination_prefecture_code", "")
            source_kind = rule.get("source_event_kind", "")
            source_comp = rule.get("source_competition_id_2026", "")
            ids: List[str] = []
            resolution_source = ""
            notes = ""

            if source_kind == "national_invitational":
                ids = [
                    sid for sid in season.senbatsu_participant_school_ids
                    if self.repo.schools[sid].get("prefecture_code") == pcode
                ]
                resolution_source = "structural_senbatsu_bootstrap"
            elif source_kind == "summer_local_qualifier":
                run = season.competition_runs.get(source_comp)
                if run and run.outcome:
                    ids = [run.outcome.champion_school_id]
                    resolution_source = "current_season_competition_result"
                else:
                    notes = "source summer competition has not completed"
            elif source_kind == "prefectural_newcomer_tournament":
                expected_event_count = int(
                    rule.get("observed_2026_count") or rule.get("quota") or 0
                )
                candidates = sorted(
                    sid for sid, row in self.repo.schools.items()
                    if row.get("prefecture_code") == pcode
                )
                ids = shuffled(
                    candidates,
                    season.rng_seed,
                    f"{destination_competition_id}:{rule['access_rule_id']}:newcomer_bootstrap",
                )[:expected_event_count]
                resolution_source = "current_year_structural_event_bootstrap"
                notes = (
                    "newcomer tournament result competition is not materialized; "
                    "deterministic same-prefecture proxies preserve the verified direct-entry quota"
                )
            elif source_kind == "autumn_prefectural" and int(rule.get("source_year_offset") or 0) == -1:
                ranking = prior_pref.get(pcode, [])
                lo = int(rule.get("source_rank_from") or 1)
                hi = int(rule.get("source_rank_to") or lo)
                ids = ranking[lo - 1:hi]
                resolution_source = "prior_year_structural_bootstrap"
            elif source_kind == "autumn_regional" and int(rule.get("source_year_offset") or 0) == -1:
                ids = list(prior_reg.get(pcode, []))
                resolution_source = "prior_year_structural_bootstrap"
            else:
                notes = f"unsupported access source/selector: {source_kind}/{selector}"

            expected = int(rule.get("observed_2026_count") or rule.get("quota") or 0)
            # Structural Senbatsu bootstrap can contain additional schools from the same
            # prefecture because it preserves national selection quotas rather than the
            # exact historical school list.  For a 2026 access-rule replay, cap that
            # bootstrap to the observed destination count.  Real annual participant
            # input can later replace the bootstrap and `all_matches` will remain valid.
            if expected and len(ids) > expected and (
                rule.get("quota_mode") != "all_matches"
                or resolution_source == "structural_senbatsu_bootstrap"
            ):
                ids = ids[:expected]
            status = "PASS" if (not expected or len(ids) == expected) else "FAIL"
            date_status = self._dependency_date_status(source_comp, destination_competition_id, int(rule.get("source_year_offset") or 0))
            if date_status == "FAIL":
                status = "FAIL"
            resolutions.append(AccessResolution(
                access_rule_id=rule["access_rule_id"],
                destination_competition_id=destination_competition_id,
                source_event_kind=source_kind,
                source_competition_id=source_comp,
                source_year=source_year,
                action_type=rule.get("action_type", ""),
                resolved_school_ids=list(ids),
                expected_count=expected,
                resolution_source=resolution_source,
                date_status=date_status,
                status=status,
                notes=notes,
            ))
            if rule.get("grants_main_entry") == "yes":
                direct.extend(ids)
            elif rule.get("action_type") == "bypass_branch_seed_event_assign_seed":
                seed_bypass.extend(ids)

        return list(dict.fromkeys(direct)), list(dict.fromkeys(seed_bypass)), resolutions

    def _resolve_qualification(self, rule: dict, season: SeasonExecution) -> QualificationResolution:
        source = rule["source_competition_id"]
        dest = rule["destination_competition_id"]
        run = season.competition_runs.get(source)
        ids: List[str] = []
        notes = ""
        if run and run.outcome and rule.get("source_result") == "winner":
            ids = [run.outcome.champion_school_id]
        else:
            notes = "source competition is not executable in current season graph"
        expected = int(rule.get("quota") or 0)
        date_status = self._dependency_date_status(source, dest, 0)
        status = "PASS" if len(ids) == expected and date_status != "FAIL" else "BLOCKED"
        return QualificationResolution(
            rule_id=rule["rule_id"], source_competition_id=source,
            destination_competition_id=dest, source_result=rule.get("source_result", ""),
            resolved_school_ids=ids, expected_count=expected, date_status=date_status,
            status=status, notes=notes,
        )

    def _bootstrap_prior_context(self, year: int, rng_seed: int) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        prior_pref: Dict[str, List[str]] = {}
        prior_reg: Dict[str, List[str]] = {}
        for rule in self.access_rules:
            if int(rule.get("source_year_offset") or 0) != -1:
                continue
            pcode = rule.get("destination_prefecture_code", "")
            schools = sorted(sid for sid, row in self.repo.schools.items() if row.get("prefecture_code") == pcode)
            if rule.get("source_event_kind") == "autumn_prefectural":
                need = int(rule.get("source_rank_to") or rule.get("observed_2026_count") or 0)
                if pcode not in prior_pref or len(prior_pref[pcode]) < need:
                    prior_pref[pcode] = shuffled(schools, rng_seed, f"bootstrap:{year-1}:autumn_pref:{pcode}")
            elif rule.get("source_event_kind") == "autumn_regional":
                need = int(rule.get("observed_2026_count") or 0)
                prior_reg[pcode] = shuffled(schools, rng_seed, f"bootstrap:{year-1}:autumn_reg:{pcode}")[:need]
        return prior_pref, prior_reg

    def _bootstrap_senbatsu_participants(self, year: int, rng_seed: int) -> List[str]:
        # Required prefectures are those whose spring access rule expects a current
        # Senbatsu participant.  Force one structural participant from each such
        # prefecture, then fill the official selection quotas by region.
        required_pcodes = {
            r["destination_prefecture_code"] for r in self.access_rules
            if r.get("source_event_kind") == "national_invitational"
        }
        autumn_region_by_pref = {
            r["prefecture_code"]: r["region_id"] for r in self.region_memberships
            if r.get("season_segment") == "autumn" and r.get("effective_year") == str(year)
        }
        schools_by_region: Dict[str, List[str]] = {}
        for sid, school in self.repo.schools.items():
            region = autumn_region_by_pref.get(school.get("prefecture_code", ""), "")
            if region:
                schools_by_region.setdefault(region, []).append(sid)
        for region in schools_by_region:
            schools_by_region[region].sort()

        selected: List[str] = []
        selected_set = set()
        # Region-specific rules first, excluding Kanto-Tokyo comparison and 21st century.
        for rule in self.selection_rules:
            region = rule.get("region_id", "")
            if not region:
                continue
            quota = int(rule.get("total_quota") or 0)
            pool = list(schools_by_region.get(region, []))
            required_here = [
                p for p in sorted(required_pcodes)
                if autumn_region_by_pref.get(p) == region
            ]
            picks: List[str] = []
            for pcode in required_here:
                candidates = [
                    sid for sid in pool
                    if self.repo.schools[sid].get("prefecture_code") == pcode and sid not in selected_set
                ]
                if candidates and len(picks) < quota:
                    sid = shuffled(candidates, rng_seed, f"senbatsu:{region}:required:{pcode}")[0]
                    picks.append(sid)
                    selected_set.add(sid)
            remainder = [sid for sid in pool if sid not in selected_set]
            for sid in shuffled(remainder, rng_seed, f"senbatsu:{region}:fill"):
                if len(picks) >= quota:
                    break
                picks.append(sid)
                selected_set.add(sid)
            if len(picks) != quota:
                raise ValueError(f"Senbatsu bootstrap {region}: selected={len(picks)} quota={quota}")
            selected.extend(picks)

        # Kanto/Tokyo comparison slot.
        compare_rule = next((r for r in self.selection_rules if r.get("selection_scope") == "関東・東京"), None)
        if compare_rule:
            quota = int(compare_rule.get("total_quota") or 0)
            pool = [
                sid for reg in ("REG03", "REG04") for sid in schools_by_region.get(reg, [])
                if sid not in selected_set
            ]
            picks = shuffled(pool, rng_seed, "senbatsu:kanto_tokyo_compare")[:quota]
            selected.extend(picks); selected_set.update(picks)

        # 21st century slots remain structural fixtures, but satisfy any known same-year
        # regional-participant count needed by a later spring feeder. In 2026, spring
        # Kyushu explicitly has six Senbatsu participants while the ordinary regional
        # selection quota supplies five, so one structural 21st-century slot is drawn
        # from REG10. This enforces only the known count, not a historical school name.
        century_rule = next((r for r in self.selection_rules if r.get("selection_scope") == "21世紀枠"), None)
        if century_rule:
            quota = int(century_rule.get("total_quota") or 0)
            picks: List[str] = []
            feeder_minimums = {
                r.get("source_region_filter", ""): int(r.get("quota") or 0)
                for r in self.regional_feeder_rules
                if r.get("source_type") == "national_invitational_participants"
                and r.get("effective_year") == str(year)
            }
            for region, minimum in sorted(feeder_minimums.items()):
                current = sum(1 for sid in selected if autumn_region_by_pref.get(self.repo.schools[sid].get("prefecture_code", "")) == region)
                need = min(max(minimum - current, 0), quota - len(picks))
                if need:
                    region_pool = [sid for sid in schools_by_region.get(region, []) if sid not in selected_set]
                    extra = shuffled(region_pool, rng_seed, f"senbatsu:21st_century:{region}")[:need]
                    picks.extend(extra); selected_set.update(extra)
            remaining = quota - len(picks)
            if remaining:
                pool = [sid for sid in sorted(self.repo.schools) if sid not in selected_set]
                extra = shuffled(pool, rng_seed, "senbatsu:21st_century_structural")[:remaining]
                picks.extend(extra); selected_set.update(extra)
            selected.extend(picks)

        if len(selected) != 32:
            raise AssertionError(f"Senbatsu structural bootstrap count={len(selected)} expected=32")
        for pcode in required_pcodes:
            if not any(self.repo.schools[sid].get("prefecture_code") == pcode for sid in selected):
                raise AssertionError(f"Senbatsu bootstrap missing access-rule prefecture {pcode}")
        return selected

    def _regional_bridge_gaps(self, year: int) -> List[RegionalBridgeGap]:
        # Regional competitions that are also prefectural competition IDs (Hokkaido and
        # Tokyo autumn) need no feeder bridge. Stage 12E considers a bridge structured
        # when regional_feeder_rules.csv has a destination definition.
        pref_comp_ids = {r["competition_id"] for r in self.pref_index}
        feeder_destinations = {r["destination_competition_id"] for r in self.regional_feeder_rules}
        by_region_segment: Dict[Tuple[str, str], List[str]] = {}
        for r in self.region_memberships:
            if r.get("effective_year") != str(year):
                continue
            by_region_segment.setdefault((r["region_id"], r["season_segment"]), []).append(r["prefecture_code"])
        pref_cid_by_key = {
            (r["prefecture_code"], r["season_segment"]): r["competition_id"]
            for r in self.pref_index
        }
        gaps: List[RegionalBridgeGap] = []
        for cid, comp in sorted(self.repo.competitions.items()):
            if comp.get("reference_year") != str(year) or comp.get("competition_level") != "regional":
                continue
            segment = comp.get("season_segment")
            if segment not in {"spring", "autumn"}:
                continue
            if cid in pref_comp_ids:
                continue
            if cid in feeder_destinations:
                continue
            region = comp.get("region_id", "")
            pcodes = sorted(by_region_segment.get((region, segment), []))
            source_cids = [pref_cid_by_key[(p, segment)] for p in pcodes if (p, segment) in pref_cid_by_key]
            gaps.append(RegionalBridgeGap(
                competition_id=cid, season_segment=segment, region_id=region,
                expected_team_count=int(comp.get("team_count") or 0),
                source_prefectural_competition_ids=source_cids,
                member_prefecture_codes=pcodes,
            ))
        return gaps

    def _season_row(self, index_row: dict, run: CompetitionRun, annual: AnnualCompetitionInput) -> CompetitionSeasonRow:
        cal = self.calendars.get(run.competition_id, {})
        return CompetitionSeasonRow(
            competition_id=run.competition_id,
            prefecture_code=index_row["prefecture_code"],
            prefecture_name=index_row["prefecture_name"],
            season_segment=index_row["season_segment"],
            start_date=cal.get("start_date", ""), end_date=cal.get("end_date", ""),
            entrant_count=len(run.entrant_school_ids),
            direct_main_entry_count=len(annual.direct_main_entry_school_ids),
            seed_event_bypass_count=len(annual.seed_event_bypass_school_ids),
            main_entrant_count=len(run.main_entrant_school_ids),
            champion_school_id=run.outcome.champion_school_id if run.outcome else "",
            runner_up_school_id=run.outcome.runner_up_school_id if run.outcome else "",
            match_count=run.outcome.match_count if run.outcome else 0,
            warning_count=len(run.warnings), status=self._prefectural_run_status(run),
        )

    def _calendar_gaps(self, year: int) -> List[CalendarGap]:
        gaps: List[CalendarGap] = []
        for row in self.pref_index:
            if row.get("reference_year") != str(year):
                continue
            cal = self.calendars.get(row["competition_id"], {})
            if cal.get("calendar_status") == "official_schedule" and cal.get("start_date") and cal.get("end_date"):
                continue
            gaps.append(CalendarGap(
                competition_id=row["competition_id"], prefecture_code=row["prefecture_code"],
                prefecture_name=row["prefecture_name"], season_segment=row["season_segment"],
                calendar_status=cal.get("calendar_status", "missing"),
                start_date=cal.get("start_date", ""), end_date=cal.get("end_date", ""),
            ))
        return gaps

    def _internal_structure_gaps(self, season: SeasonExecution) -> List[InternalStructureGap]:
        by_comp = {r.competition_id: r for r in season.prefectural_rows}
        gaps: List[InternalStructureGap] = []
        for idx in self.pref_index:
            cid = idx["competition_id"]
            row = by_comp.get(cid)
            if not row:
                continue
            try:
                main = self.repo.stage_by_code(cid, "MAIN")
            except KeyError:
                continue
            expected = int(main.get("team_count") or 0)
            if expected and expected != row.main_entrant_count:
                gaps.append(InternalStructureGap(
                    competition_id=cid, prefecture_code=idx["prefecture_code"],
                    prefecture_name=idx["prefecture_name"], season_segment=idx["season_segment"],
                    expected_main_team_count=expected, simulated_main_team_count=row.main_entrant_count,
                ))
        return gaps

    def _prefectural_run_status(self, run: CompetitionRun) -> str:
        if not run.outcome:
            return "FAIL"
        try:
            main = self.repo.stage_by_code(run.competition_id, "MAIN")
            expected = int(main.get("team_count") or 0)
        except (KeyError, ValueError):
            expected = 0
        if expected and expected != len(run.main_entrant_school_ids):
            return "GAP_MAIN_COUNT_MISMATCH"
        return "PASS"

    def _dependency_date_status(self, source_comp: str, dest_comp: str, year_offset: int) -> str:
        if year_offset < 0:
            return "PASS_PRIOR_YEAR"
        if not source_comp:
            # Current Senbatsu is known by event kind even when source id is omitted;
            # access rules in this dataset include CMP000001, so this is defensive.
            return "UNKNOWN"
        src = self.calendars.get(source_comp)
        dst = self.calendars.get(dest_comp)
        if not src or not dst or not src.get("end_date") or not dst.get("start_date"):
            return "UNKNOWN"
        return "PASS" if src["end_date"] <= dst["start_date"] else "FAIL"

    def _calendar_start(self, competition_id: str) -> str:
        return self.calendars.get(competition_id, {}).get("start_date", "9999-12-31")

    @staticmethod
    def _seed(base_seed: int, namespace: str) -> int:
        # Tournament randomness is already namespaced internally; this stable per-event
        # integer mainly keeps result files easy to reproduce independently.
        import hashlib
        digest = hashlib.sha256(f"{base_seed}:{namespace}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & 0x7FFFFFFF
