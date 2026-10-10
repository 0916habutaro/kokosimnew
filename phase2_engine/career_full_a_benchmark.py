"""Stage43G-21: bounded real-roster-linked full Option-A storage benchmark.

Produces synthetic matches with innings/team/batter/pitcher records referring
to actual generated career player IDs. Persists via real append-only archive,
then materializes the sealed-year derived stats cache for every school/year.
No user save is accessed, and this is NOT a full tournament simulation.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
from statistics import median
import sqlite3
import tempfile
from time import perf_counter
import tracemalloc

from game_core.players import PlayerRosterGenerator
from .career_history_scale_audit import synthetic_ability_record
from .career_history_scale_benchmark import file_sha256
from .career_longitudinal_read import CareerLongitudinalReadModel
from .career_player_records import BATTER, PITCHER, CareerPlayerRecordView
from .career_player_stat_cache import CareerPlayerStatCache
from .career_stats_readonly_adapter import CareerStatsReadOnlyAdapter
from .career_roster_archive import CareerRosterArchive
from .historical_match_archive import HistoricalMatchArchive
from .repository import DataRepository

SEED = 2026101101
START_YEAR = 2026
SOURCE = "synthetic_option_a_real_roster_ids_not_simulated_tournament"


def validate_options(schools: int, years: int, games_per_school_year: int,
                     repeats: int, allow_large: bool = False) -> None:
    if (type(schools) is not int or not 2 <= schools <= 100
            or schools % 2
            or type(years) is not int or not 1 <= years <= 100
            or type(games_per_school_year) is not int
            or not 1 <= games_per_school_year <= 20
            or type(repeats) is not int or not 1 <= repeats <= 10
            or type(allow_large) is not bool):
        raise ValueError("invalid full-A synthetic benchmark parameters")
    if schools * years * games_per_school_year > 1000 and not allow_large:
        raise ValueError(
            "large full-A roster benchmark requires --allow-large"
        )


def _link_roster_ids(row: dict, school_rosters: dict) -> None:
    """Complete the Stage43G-13 synthetic box scores using REAL saved IDs."""
    detail = row["ability_detail"]
    for school_id, roster in school_rosters.items():
        hitters = roster.players[:9]
        pitcher = next(
            player for player in roster.players
            if player.primary_position == "P"
        )
        batters = [
            rec for rec in detail["batter_stats"]
            if rec["school_id"] == school_id
        ]
        if len(batters) != len(hitters):
            raise AssertionError("synthetic lineup differs from roster")
        for rec, member in zip(batters, hitters):
            rec["player_id"] = member.player_id
            for key in BATTER:
                rec.setdefault(key, 0)
            rec["plate_appearances"] = 4
        arms = [
            rec for rec in detail["pitcher_stats"]
            if rec["school_id"] == school_id
        ]
        if len(arms) != 1:
            raise AssertionError("synthetic pitcher count differs")
        arms[0]["player_id"] = pitcher.player_id
        for key in PITCHER:
            arms[0].setdefault(key, 0)
        arms[0]["outs_recorded"] = 27


def _read_stats(path: Path, *queries: tuple[str, tuple]) -> list[int]:
    with closing(sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True
    )) as conn:
        return [int(conn.execute(sql, params).fetchone()[0])
                for sql, params in queries]


def _time_call(fn, repeats: int) -> dict:
    values = []
    peaks = []
    for _ in range(repeats):
        tracemalloc.start()
        start = perf_counter()
        try:
            fn()
        finally:
            values.append(round((perf_counter() - start) * 1000, 3))
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
    return {
        "repeats": repeats, "elapsed_ms": values,
        "median_elapsed_ms": median(values),
        "max_traced_python_bytes": max(peaks),
    }


def run_full_a_benchmark(
    data_root: str | Path, *, schools: int = 2, years: int = 3,
    games_per_school_year: int = 2, repeats: int = 2,
    allow_large: bool = False,
) -> dict:
    validate_options(schools, years, games_per_school_year, repeats, allow_large)
    repo = DataRepository(Path(data_root))
    selected = sorted(repo.school_to_program)[:schools]
    if len(selected) != schools:
        raise ValueError("not enough real school IDs in master")
    generator = PlayerRosterGenerator()
    with tempfile.TemporaryDirectory(prefix="kokosim-full-a-") as temp:
        path = Path(temp)
        match_file = path / "historical_matches.sqlite3"
        roster_file = path / "career_rosters.sqlite3"
        cache_file = path / "derived_player_stats.sqlite3"
        matches = HistoricalMatchArchive(match_file)
        rosters = CareerRosterArchive(roster_file)
        view = CareerPlayerRecordView(matches, rosters)
        builder = CareerPlayerStatCache(view, cache_file)
        start = perf_counter()
        total_matches = 0
        for year in range(START_YEAR, START_YEAR + years):
            if year > START_YEAR:
                matches.register_next_year(
                    year=year, rng_seed=SEED,
                    resolver_contract="full_a_synthetic_v1",
                    plan_fingerprint=f"stage43g21-{year}",
                )
            squad = {}
            for school_id in selected:
                if year == START_YEAR:
                    rosters.save_initial_roster(
                        generator.generate_for_school_id(
                            repo, school_id, START_YEAR, SEED,
                        )
                    )
                else:
                    rosters.advance_and_save(
                        repo.team(school_id),
                        next_year=year, career_seed=SEED,
                    )
                squad[school_id] = rosters.roster(year, school_id)
            annual_matches = 0
            for match_no in range(games_per_school_year):
                chunk = []
                for pair in range(schools // 2):
                    first = selected[(2 * pair + match_no) % schools]
                    second = selected[(2 * pair + 1 + match_no) % schools]
                    competition = (
                        "CMP000086" if match_no % 2 == 0 else "CMP000088"
                    )
                    row = synthetic_ability_record(
                        year, competition,
                        f"FULLA-{year}-{match_no}-{pair}",
                        first, second, match_no + 1,
                    )
                    _link_roster_ids(row, {
                        first: squad[first], second: squad[second]
                    })
                    chunk.append(row)
                out = matches.sync(
                    year=year, rng_seed=SEED,
                    resolver_contract="full_a_synthetic_v1",
                    plan_fingerprint=f"stage43g21-{year}",
                    completed=chunk,
                )
                annual_matches += out["inserted"]
            matches.seal_year(
                year, expected_match_count=annual_matches,
            )
            total_matches += annual_matches
            # Cache only after year is sealed and full raw player stats pass
            # actual source-SHA and roster-ID attribution checks.
            for school_id in selected:
                builder.materialize(school_id, year=year)

        build_ms = round((perf_counter() - start) * 1000, 3)
        file_sizes = {
            "matches": match_file.stat().st_size,
            "rosters": roster_file.stat().st_size,
            "derived_cache": cache_file.stat().st_size,
        }
        before = {
            file.name: file_sha256(file)
            for file in (match_file, roster_file, cache_file)
        }
        reader = CareerStatsReadOnlyAdapter(view, cache_file)
        history = CareerLongitudinalReadModel(matches, rosters)
        sampled = []
        for school_id in sorted({
            selected[0], selected[len(selected) // 2], selected[-1]
        }):
            roster = rosters.roster(START_YEAR, school_id)
            player_id = roster.players[0].player_id
            start_year, end_year = START_YEAR, START_YEAR + years - 1
            # Strict source and faster cache must match even when players
            # graduate and disappear from later rosters.
            original = view.player_seasons(
                player_id, start_year=start_year, end_year=end_year
            )
            cached = reader.player_seasons(
                player_id, start_year=start_year, end_year=end_year
            )
            if (original["seasons"] != cached["seasons"]
                    or original["totals"] != cached["totals"]):
                raise AssertionError("raw/cache player statistics disagree")
            ranks_raw = view.school_leaders(
                school_id, start_year=start_year, end_year=end_year,
                category="batting_hits",
            )
            ranks_cached = reader.school_leaders(
                school_id, start_year=start_year, end_year=end_year,
                category="batting_hits",
            )
            if (ranks_raw["rows"] != ranks_cached["rows"]
                    or ranks_raw["candidate_count"]
                    != ranks_cached["candidate_count"]):
                raise AssertionError("raw/cache historical leaders disagree")
            reads = {
                "raw_player": lambda: view.player_seasons(
                    player_id, start_year=start_year, end_year=end_year
                ),
                "cached_player": lambda: reader.player_seasons(
                    player_id, start_year=start_year, end_year=end_year
                ),
                "raw_leaders": lambda: view.school_leaders(
                    school_id, start_year=start_year, end_year=end_year,
                    category="batting_hits",
                ),
                "cached_leaders": lambda: reader.school_leaders(
                    school_id, start_year=start_year, end_year=end_year,
                    category="batting_hits",
                ),
                "school_results_page": lambda: history.school_results(
                    school_id, start_year=start_year, end_year=end_year,
                    limit=30, offset=0,
                ),
            }
            sampled.append({
                "school_id": school_id, "player_id": player_id,
                "cached_matches_raw": True,
                "read_latency": {
                    name: _time_call(fn, repeats)
                    for name, fn in reads.items()
                },
            })
        after = {
            file.name: file_sha256(file)
            for file in (match_file, roster_file, cache_file)
        }
        if before != after:
            raise AssertionError("read-only benchmark changed databases")
        counts = {
            "matches": _read_stats(
                match_file, (
                    "SELECT COUNT(*) FROM historical_matches", ()
                ),
            )[0],
            "school_year_rosters": _read_stats(
                roster_file, (
                    "SELECT COUNT(*) FROM career_school_rosters", ()
                ),
            )[0],
            "player_identities": _read_stats(
                roster_file, (
                    "SELECT COUNT(*) FROM career_player_identities", ()
                ),
            )[0],
            "cached_school_years": _read_stats(
                cache_file, (
                    "SELECT COUNT(*) FROM school_year_stat_cache", ()
                ),
            )[0],
            "cached_player_years": _read_stats(
                cache_file, (
                    "SELECT COUNT(*) FROM player_year_stat_cache", ()
                ),
            )[0],
        }
        # Count the *actual stored* complete A shape, not merely metadata
        # claiming a box score was generated.
        option_a_count = 0
        with closing(sqlite3.connect(
            match_file.resolve().as_uri() + "?mode=ro", uri=True
        )) as conn:
            for (raw,) in conn.execute(
                "SELECT payload_json FROM historical_matches"
            ):
                event = json.loads(raw)
                if all(
                    isinstance(event.get(field), list) and event[field]
                    for field in (
                        "inning_scores", "team_stats",
                        "batter_stats", "pitcher_stats",
                    )
                ):
                    option_a_count += 1
        counts["full_option_a_matches"] = option_a_count
        expected_matches = schools * years * games_per_school_year // 2
        if option_a_count != expected_matches:
            raise AssertionError("full Option-A game records absent")
        if counts["matches"] != expected_matches or total_matches != expected_matches:
            raise AssertionError("synthetic full-A match count mismatch")
        if counts["school_year_rosters"] != schools * years:
            raise AssertionError("school-year roster count differs")
        if counts["cached_school_years"] != schools * years:
            raise AssertionError("cache coverage incomplete")
    return {
        "stage": "43G-21",
        "source_kind": SOURCE,
        "schools": schools, "years": years,
        "games_per_school_year": games_per_school_year,
        "expected_matches": expected_matches,
        "start_year": START_YEAR,
        "counts": counts,
        "database_bytes": file_sizes,
        "total_database_bytes": sum(file_sizes.values()),
        "fixture_build_and_cache_elapsed_ms": build_ms,
        "reads": sampled,
        "all_db_hashes_unchanged_on_read": True,
        "temporary_fixture_deleted_after_run": True,
        "genuine_roster_identity_attribution": True,
        "option_a_innings_teams_batters_pitchers_present": True,
        "real_game_tournament_progression_verified": False,
        "nationwide_3000_school_100_year_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full Option-A records+rosters+cache synthetic SQLite audit"
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--schools", type=int, default=2)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--games-per-school-year", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    result = run_full_a_benchmark(
        args.data_root, schools=args.schools, years=args.years,
        games_per_school_year=args.games_per_school_year,
        repeats=args.repeats, allow_large=args.allow_large,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
