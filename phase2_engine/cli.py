from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import TournamentEngine
from .models import AnnualCompetitionInput
from .repository import DataRepository
from .results import save_competition_run


def _gifu_demo_entrants(repo: DataRepository, year: int = 2026):
    stage = repo.stage_by_code("CMP000110", "SEED_EVENT")
    target_counts = [20, 10, 18, 10]  # 58 total; enough for the 16 seed slots.
    out = []
    for group, n in zip(repo.groups_by_stage[stage["stage_id"]], target_counts):
        ids = sorted(repo.group_school_ids(group, year))
        if len(ids) < n:
            raise ValueError(f"demo target exceeds membership for {group['group_name']}")
        out.extend(ids[:n])
    return out


def _kanagawa_demo(repo: DataRepository, competition_id: str = "CMP000095", year: int = 2026):
    stage = repo.stage_by_code(competition_id, "BRANCH_QUALIFIER")
    groups = repo.groups_by_stage[stage["stage_id"]]
    direct = None
    entrants = []
    for idx, group in enumerate(groups):
        ids = sorted(repo.group_school_ids(group, year))
        slots = repo.param(stage["stage_id"], "output_slots", group["stage_group_id"])
        target = 2 * slots
        if idx == 0:
            direct = ids[-1]
            ids = [x for x in ids if x != direct]
        entrants.extend(ids[:target])
    if direct is None:
        raise AssertionError("no direct entry selected")
    entrants.append(direct)
    return entrants, [direct]


def _chiba_autumn_demo(repo: DataRepository, year: int = 2026):
    stage = repo.stage_by_code("CMP000093", "BRANCH_QUALIFIER")
    all_ids = set()
    for group in repo.groups_by_stage[stage["stage_id"]]:
        all_ids |= repo.group_school_ids(group, year)
    ids = sorted(all_ids)
    if len(ids) < 141:
        raise ValueError("Chiba demo requires at least 141 affiliated schools")
    direct = ids[0]
    stage_entrants = ids[1:141]  # 140 -> 28 primary + 112 repechage entrants.
    return stage_entrants + [direct], [direct]


def _hokkaido_autumn_demo(repo: DataRepository, year: int = 2026):
    stage = repo.stage_by_code("CMP000013", "BRANCH_QUALIFIER")
    out = set()
    for group in repo.groups_by_stage[stage["stage_id"]]:
        out |= repo.group_school_ids(group, year)
    return sorted(out), []


def _aomori_autumn_demo(repo: DataRepository, year: int = 2026):
    stage = repo.stage_by_code("CMP000073", "SEED_EVENT")
    out = set()
    for group in repo.groups_by_stage[stage["stage_id"]]:
        out |= repo.group_school_ids(group, year)
    return sorted(out), []


def build_demo(repo: DataRepository, name: str, year: int):
    if name == "gifu-autumn":
        return "CMP000110", _gifu_demo_entrants(repo, year), []
    if name == "kanagawa-spring":
        entrants, direct = _kanagawa_demo(repo, "CMP000095", year)
        return "CMP000095", entrants, direct
    if name == "kanagawa-autumn":
        entrants, direct = _kanagawa_demo(repo, "CMP000096", year)
        return "CMP000096", entrants, direct
    if name == "chiba-autumn":
        entrants, direct = _chiba_autumn_demo(repo, year)
        return "CMP000093", entrants, direct
    if name == "hokkaido-autumn":
        entrants, direct = _hokkaido_autumn_demo(repo, year)
        return "CMP000013", entrants, direct
    if name == "aomori-autumn":
        entrants, direct = _aomori_autumn_demo(repo, year)
        return "CMP000073", entrants, direct
    raise ValueError(name)


def _read_ids(path: str | None):
    if not path:
        return []
    return [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _read_json_mapping(path: str | None):
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON mapping expected: {path}")
    return payload


def _read_json_list(path: str | None):
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"JSON list expected: {path}")
    return payload


def main():
    p = argparse.ArgumentParser(description="Phase 2 Stage 12C tournament engine")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--competition-id")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--seed", type=int, default=2026100401)
    p.add_argument("--entrant-file", help="text file containing one school_id per line")
    p.add_argument("--direct-main-entry-file", help="text file containing pre-qualified MAIN school ids")
    p.add_argument("--group-entrant-json", help="JSON object: stage_group_id -> [school_id,...]")
    p.add_argument("--group-ranking-json", help="JSON object: stage_group_id -> ranked [school_id,...]")
    p.add_argument("--group-pool-json", help="JSON object: stage_group_id -> [[school_id,...], ...]")
    p.add_argument("--main-seed-file", help="text file containing ordered MAIN seed school ids")
    p.add_argument("--main-draw-json", help="JSON array of exact power-of-two MAIN slots; empty string=bye")
    p.add_argument("--main-winner-json", help="JSON object: MAIN match_id -> winning school_id")
    p.add_argument("--result-dir", help="write summary JSON, match CSV and placement CSV")
    p.add_argument("--demo", choices=[
        "gifu-autumn", "kanagawa-spring", "kanagawa-autumn",
        "chiba-autumn", "hokkaido-autumn", "aomori-autumn",
    ])
    p.add_argument("--gifu-demo", action="store_true", help="backward-compatible alias for --demo gifu-autumn")
    p.add_argument("--output")
    args = p.parse_args()

    repo = DataRepository(Path(args.data_dir))
    if args.gifu_demo:
        args.demo = "gifu-autumn"
    if args.demo:
        competition_id, entrants, direct = build_demo(repo, args.demo, args.year)
    elif args.entrant_file and args.competition_id:
        competition_id = args.competition_id
        entrants = _read_ids(args.entrant_file)
        direct = _read_ids(args.direct_main_entry_file)
    else:
        raise SystemExit("Provide --demo, or --competition-id with --entrant-file.")

    run = TournamentEngine(repo).run(AnnualCompetitionInput(
        competition_id=competition_id,
        year=args.year,
        entrant_school_ids=entrants,
        direct_main_entry_school_ids=direct,
        rng_seed=args.seed,
        group_entrant_school_ids=_read_json_mapping(args.group_entrant_json),
        group_rankings=_read_json_mapping(args.group_ranking_json),
        group_pool_assignments=_read_json_mapping(args.group_pool_json),
        main_seed_school_ids=_read_ids(args.main_seed_file),
        main_bracket_slots=_read_json_list(args.main_draw_json),
        main_match_winner_overrides=_read_json_mapping(args.main_winner_json),
    ))
    if args.result_dir:
        save_competition_run(run, args.result_dir)
    payload = json.dumps(run.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
