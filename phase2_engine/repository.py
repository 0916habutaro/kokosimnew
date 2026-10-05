from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .models import Team
from .paths import resolve_data_file


class DataRepository:
    REQUIRED = [
        "competitions.csv",
        "competition_stages.csv",
        "competition_stage_groups.csv",
        "competition_stage_transitions.csv",
        "competition_stage_action_bindings.csv",
        "competition_access_rules.csv",
        "competition_seed_rules.csv",
        "competition_stage_format_models.csv",
        "competition_stage_format_phases.csv",
        "competition_stage_internal_transitions.csv",
        "competition_stage_format_assignments.csv",
        "competition_stage_group_format_overrides.csv",
        "competition_stage_format_parameters.csv",
        "school_area_memberships.csv",
        "baseball_programs.csv",
        "schools.csv",
    ]

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.tables: Dict[str, List[dict]] = {}
        for name in self.REQUIRED:
            path = resolve_data_file(self.data_dir, name)
            if not path.exists():
                raise FileNotFoundError(path)
            self.tables[name] = self._read(path)
        self._index()

    @staticmethod
    def _read(path: Path) -> List[dict]:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def _index(self) -> None:
        self.competitions = {r["competition_id"]: r for r in self.tables["competitions.csv"]}
        self.stages_by_comp = defaultdict(list)
        for r in self.tables["competition_stages.csv"]:
            self.stages_by_comp[r["competition_id"]].append(r)
        for rows in self.stages_by_comp.values():
            rows.sort(key=lambda r: int(r.get("sequence") or 0))

        self.groups_by_stage = defaultdict(list)
        self.groups = {}
        for r in self.tables["competition_stage_groups.csv"]:
            self.groups[r["stage_group_id"]] = r
            self.groups_by_stage[r["stage_id"]].append(r)

        self.assignments_by_stage = {}
        for r in self.tables["competition_stage_format_assignments.csv"]:
            self.assignments_by_stage[r["stage_id"]] = r

        self.group_format = {}
        for r in self.tables["competition_stage_group_format_overrides.csv"]:
            self.group_format[r["stage_group_id"]] = r

        self.params_by_stage_group = defaultdict(list)
        self.params_by_stage = defaultdict(list)
        for r in self.tables["competition_stage_format_parameters.csv"]:
            self.params_by_stage[r["stage_id"]].append(r)
            if r["stage_group_id"]:
                self.params_by_stage_group[(r["stage_id"], r["stage_group_id"])].append(r)

        self.seed_rules_by_comp = defaultdict(list)
        for r in self.tables["competition_seed_rules.csv"]:
            self.seed_rules_by_comp[r["destination_competition_id"]].append(r)

        self.access_rules_by_comp = defaultdict(list)
        for r in self.tables["competition_access_rules.csv"]:
            self.access_rules_by_comp[r["destination_competition_id"]].append(r)

        self.transitions_by_comp = defaultdict(list)
        for r in self.tables["competition_stage_transitions.csv"]:
            self.transitions_by_comp[r["competition_id"]].append(r)

        self.format_models = {r["format_model_id"]: r for r in self.tables["competition_stage_format_models.csv"]}
        self.format_phases_by_model = defaultdict(list)
        for r in self.tables["competition_stage_format_phases.csv"]:
            self.format_phases_by_model[r["format_model_id"]].append(r)
        for rows in self.format_phases_by_model.values():
            rows.sort(key=lambda r: int(r.get("phase_sequence") or 0))

        self.program_to_school: Dict[str, str] = {}
        self.school_to_program: Dict[str, str] = {}
        for r in self.tables["baseball_programs.csv"]:
            if r.get("discipline") == "hardball":
                self.program_to_school[r["program_id"]] = r["school_id"]
                self.school_to_program[r["school_id"]] = r["program_id"]

        self.schools = {r["school_id"]: r for r in self.tables["schools.csv"]}

        self.area_school_ids = defaultdict(set)
        self.scheme_school_ids = defaultdict(set)
        self.school_areas_by_scheme = defaultdict(lambda: defaultdict(set))
        for r in self.tables["school_area_memberships.csv"]:
            school_id = self.program_to_school.get(r["program_id"])
            if not school_id:
                continue
            self.area_school_ids[(r["reference_year"], r["area_id"])].add(school_id)
            self.scheme_school_ids[(r["reference_year"], r["scheme_id"])].add(school_id)
            self.school_areas_by_scheme[(r["reference_year"], r["scheme_id"])][school_id].add(r["area_id"])

    def competition(self, competition_id: str) -> dict:
        try:
            return self.competitions[competition_id]
        except KeyError as e:
            raise KeyError(f"unknown competition_id: {competition_id}") from e

    def stages(self, competition_id: str) -> List[dict]:
        return list(self.stages_by_comp.get(competition_id, []))

    def stage_by_code(self, competition_id: str, stage_code: str) -> dict:
        for row in self.stages(competition_id):
            if row["stage_code"] == stage_code:
                return row
        raise KeyError(f"stage {competition_id}/{stage_code} not found")

    def group_school_ids(self, group: dict, year: int) -> Set[str]:
        area_ids = [x for x in group.get("source_area_ids", "").split(";") if x]
        out: Set[str] = set()
        for area_id in area_ids:
            out |= set(self.area_school_ids.get((str(year), area_id), set()))
        return out

    def area_school_ids_for_group(self, group: dict, year: int) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for area_id in [x for x in group.get("source_area_ids", "").split(";") if x]:
            out[area_id] = set(self.area_school_ids.get((str(year), area_id), set()))
        return out

    def access_rules(self, competition_id: str) -> List[dict]:
        return list(self.access_rules_by_comp.get(competition_id, []))

    def seed_rules(self, competition_id: str) -> List[dict]:
        return list(self.seed_rules_by_comp.get(competition_id, []))

    def transition_rows(self, competition_id: str) -> List[dict]:
        return list(self.transitions_by_comp.get(competition_id, []))

    def team(self, school_id: str) -> Team:
        s = self.schools[school_id]
        return Team(
            school_id=school_id,
            program_id=self.school_to_program.get(school_id, ""),
            display_name=s.get("display_name") or s.get("federation_name") or school_id,
            prefecture_code=s.get("prefecture_code", ""),
        )

    def param(self, stage_id: str, name: str, group_id: str = "", default=None):
        rows = self.params_by_stage_group.get((stage_id, group_id), []) if group_id else self.params_by_stage.get(stage_id, [])
        for r in rows:
            if r["parameter_name"] == name:
                t = r.get("value_type", "")
                v = r.get("parameter_value", "")
                if t == "integer":
                    return int(v)
                if t == "boolean":
                    return v.lower() in {"1", "true", "yes"}
                return v
        return default
