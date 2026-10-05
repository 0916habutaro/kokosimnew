from __future__ import annotations
from pathlib import Path

FILE_SUBDIR = {
    'baseball_programs.csv': "master",
    'prefectures.csv': "master",
    'schools.csv': "master",
    'sources.csv': "master",
    'area_branch_prefecture_status.csv': "areas",
    'area_registration_2026_summer_all47.csv': "areas",
    'area_scheme_policy.csv': "areas",
    'area_schemes.csv': "areas",
    'competition_areas.csv': "areas",
    'school_area_memberships.csv': "areas",
    'baseball_regions.csv': "competitions",
    'bracket_generation_policies.csv': "competitions",
    'competition_access_rules.csv': "competitions",
    'competition_seed_rules.csv': "competitions",
    'competition_stage_action_bindings.csv': "competitions",
    'competition_stage_format_assignments.csv': "competitions",
    'competition_stage_format_models.csv': "competitions",
    'competition_stage_format_parameters.csv': "competitions",
    'competition_stage_format_phases.csv': "competitions",
    'competition_stage_group_format_overrides.csv': "competitions",
    'competition_stage_groups.csv': "competitions",
    'competition_stage_internal_transitions.csv': "competitions",
    'competition_stage_transitions.csv': "competitions",
    'competition_stages.csv': "competitions",
    'competitions.csv': "competitions",
    'main_tournament_engine_policies.csv': "competitions",
    'prefectural_branch_usage_2026.csv': "competitions",
    'prefectural_competition_index_2026.csv': "competitions",
    'prefecture_region_memberships.csv': "competitions",
    'qualification_rules.csv': "competitions",
    'regional_feeder_rules.csv': "competitions",
    'regional_qualification_playoffs.csv': "competitions",
    'selection_rules.csv': "competitions",
    'stage12c3_structured_competition_execution.csv': "competitions",
    'tokyo_autumn_preliminary_policies.csv': "competitions",
    'season_calendar.csv': "schedules/2026",
    'stage12g_tohoku_match_days_20261005.csv': "schedules/2026",
    'phase2_sources.csv': "sources",
}

def resolve_data_file(data_root: str | Path, name: str) -> Path:
    root = Path(data_root)
    legacy = root / name
    if legacy.exists():
        return legacy
    subdir = FILE_SUBDIR.get(name)
    if subdir:
        candidate = root / subdir / name
        if candidate.exists():
            return candidate
    hits = list(root.rglob(name)) if root.exists() else []
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise RuntimeError(f"ambiguous data file {name}: {hits}")
    return root / (subdir or "") / name
