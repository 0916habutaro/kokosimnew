"""Stage43G-13: opt-in synthetic SQLite 50/100-year history scale audit.

This benchmark writes *synthetic* line-scores/player-stat lists through the
real HistoricalMatchArchive and real CareerRosterArchive APIs. It does NOT
simulate actual tournaments, official fixtures, or historical winners.

CI runs only a small fixture. --allow-large must be supplied for full
3,000-school x 50/100-year runs; measurements are never extrapolated and
reported as if a full-scale run occurred.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from statistics import median
import sqlite3
import tempfile
from time import perf_counter

from game_core.players import PlayerRosterGenerator
from .career_longitudinal_read import CareerLongitudinalReadModel
from .career_roster_archive import CareerRosterArchive
from .historical_match_archive import HistoricalMatchArchive
from .repository import DataRepository

SEED = 2026100701
_START = 2026
_RESOLVER = "synthetic_history_scale_v1"
_SAMPLE_LIMIT = 100


def synthetic_ability_record(
    year: int, competition_id: str, match_id: str,
    first: str, second: str, match_day: int,
) -> dict:
    """Small valid Option-A-style synthetic sample, not a true simulated game."""
    one, two = 5, 3
    innings = []
    for inning in range(1, 10):
        for half, school, total in (
            ("top", first, one), ("bottom", second, two)
        ):
            innings.append({
                "inning": inning, "half": half,
                "batting_team_id": school,
                "was_played": True,
                "runs": total if inning == 1 else 0,
            })
    batters = [
        {"school_id": school, "player_id": f"SCALE-{school}-{i:02d}",
         "at_bats": 4, "hits": 1 if i < 5 else 0}
        for school in (first, second) for i in range(1, 10)
    ]
    pitchers = [
        {"school_id": school, "player_id": f"SCALE-{school}-P",
         "innings_pitched_outs": 27, "earned_runs": 3 if school == first else 5}
        for school in (first, second)
    ]
    detail = {
        "reference_year": year,
        "competition_id": competition_id,
        "match_id": match_id,
        "team1_school_id": first,
        "team2_school_id": second,
        "team1_score": one,
        "team2_score": two,
        "score_source": "ability_model_v1",
        "last_inning": 9, "ending_half": "bottom",
        "inning_scores": innings,
        "team_stats": [
            {"school_id": first, "runs": one},
            {"school_id": second, "runs": two},
        ],
        "batter_stats": batters,
        "pitcher_stats": pitchers,
    }
    return {
        "competition_id": competition_id,
        "match_id": match_id,
        "competition_name": "合成ストレス試験・公式結果ではない",
        "match_date": f"{year}-04-{match_day:02d}",
        "completed_on": f"{year}-04-{match_day:02d}",
        "date_source": "synthetic_scale_only_v1",
        "status": "completed", "stage_code": "MAIN",
        "phase_code": "MAIN_BRACKET", "round_no": 1,
        "team1_id": first, "team2_id": second,
        "winner_id": first, "loser_id": second,
        "team1_score": one, "team2_score": two,
        "score_source": "ability_model_v1",
        "ability_detail": detail,
    }


def _quantile_ms(samples: list[float], numerator: int, denominator: int) -> float:
    if not samples:
        return 0.0
    values = sorted(samples)
    at = ((len(values) - 1) * numerator) // denominator
    return round(values[at] * 1000, 3)


def _sql_size(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        page = conn.execute("PRAGMA page_size").fetchone()[0]
        used = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return {
        "file_bytes": path.stat().st_size,
        "allocated_page_count": used,
        "free_page_count": free,
        "page_size": page,
    }


def _index_plan(path: Path, query: str, params: tuple) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [
            str(row[3]) for row in conn.execute(
                "EXPLAIN QUERY PLAN " + query, params,
            )
        ]


def run_scale_audit(
    data_root: str | Path, *, school_count: int, years: int,
    games_per_school_year: int = 4,
    output_root: str | Path | None = None,
    allow_large: bool = False,
) -> dict:
    """Return actual measured bytes/latencies for exactly this synthetic run."""
    for label, number, minimum in (
        ("school_count", school_count, 2),
        ("years", years, 1),
        ("games_per_school_year", games_per_school_year, 2),
    ):
        if (not isinstance(number, int) or isinstance(number, bool)
                or number < minimum):
            raise ValueError(f"{label} must be an integer >= {minimum}")
    if school_count % 2 or games_per_school_year > 29:
        raise ValueError("even school_count and <=29 games per school-year required")
    if _START + years - 1 > 9999:
        raise ValueError("ISO calendar ends at year 9999")
    expected_matches = school_count * years * games_per_school_year // 2
    if (school_count * years > 3000 or expected_matches > 30000) and not allow_large:
        raise ValueError(
            "large 50/100-year synthetic fixtures require allow_large=True"
        )
    repo = DataRepository(Path(data_root))
    schools = sorted(repo.school_to_program)[:school_count]
    if len(schools) != school_count:
        raise ValueError("not enough real school identifiers for synthetic audit")

    lifetime = (
        tempfile.TemporaryDirectory(prefix="kokosim-history-scale-")
        if output_root is None else nullcontext(str(output_root))
    )
    with lifetime as root:
        workspace = Path(root)
        workspace.mkdir(parents=True, exist_ok=True)
        match_file = workspace / "historical_matches.sqlite3"
        roster_file = workspace / "career_rosters.sqlite3"
        if match_file.exists() or roster_file.exists():
            raise ValueError("benchmark refuses to overwrite existing SQLite")
        matches = HistoricalMatchArchive(match_file)
        rosters = CareerRosterArchive(roster_file)
        generator = PlayerRosterGenerator()
        previous_year_roster_count = 0
        archive_count = 0
        t0 = perf_counter()

        for year in range(_START, _START + years):
            if year > _START:
                matches.register_next_year(
                    year=year, rng_seed=SEED, resolver_contract=_RESOLVER,
                    plan_fingerprint=f"synthetic_scale_{year}_v1",
                )
            for sid in schools:
                if year == _START:
                    roster = generator.generate_for_school_id(
                        repo, sid, _START, SEED,
                    )
                    rosters.save_initial_roster(roster)
                else:
                    rosters.advance_and_save(
                        repo.team(sid), next_year=year, career_seed=SEED,
                    )
                previous_year_roster_count += 1
            yearly_matches = 0
            chunk = []
            for round_no in range(games_per_school_year):
                for pair_idx in range(school_count // 2):
                    first = schools[(2 * pair_idx + round_no) % school_count]
                    second = schools[(2 * pair_idx + 1 + round_no) % school_count]
                    cid = "CMP000086" if round_no % 2 == 0 else "CMP000088"
                    row = synthetic_ability_record(
                        year, cid, f"SCALE-{year}-{round_no:02d}-{pair_idx:06d}",
                        first, second, round_no + 1,
                    )
                    chunk.append(row)
                    if len(chunk) >= 250:
                        saved = matches.sync(
                            year=year, rng_seed=SEED, resolver_contract=_RESOLVER,
                            plan_fingerprint=f"synthetic_scale_{year}_v1",
                            completed=chunk,
                        )
                        archive_count += saved["inserted"]
                        yearly_matches += saved["inserted"]
                        chunk.clear()
            if chunk:
                saved = matches.sync(
                    year=year, rng_seed=SEED, resolver_contract=_RESOLVER,
                    plan_fingerprint=f"synthetic_scale_{year}_v1",
                    completed=chunk,
                )
                archive_count += saved["inserted"]
                yearly_matches += saved["inserted"]
            matches.seal_year(year, expected_match_count=yearly_matches)

        write_seconds = round(perf_counter() - t0, 3)
        view = CareerLongitudinalReadModel(matches, rosters)
        samples = {
            "school_results": [], "school_player_index": [],
            "player_years": [],
        }
        checks = {}
        for sid in (schools[0], schools[school_count // 2], schools[-1]):
            for _ in range(3):
                start = perf_counter()
                result = view.school_results(
                    sid, start_year=_START,
                    end_year=_START + years - 1, limit=20, offset=0,
                )
                samples["school_results"].append(perf_counter() - start)
                if result["total_groups"] != 2 * years:
                    raise AssertionError("synthetic school/year score groups missing")
                start = perf_counter()
                members = view.school_player_index(sid, limit=100)
                samples["school_player_index"].append(perf_counter() - start)
                if not members["players"]:
                    raise AssertionError("synthetic historic players missing")
            initial = rosters.roster(_START, sid)
            child = next(p for p in initial.players if p.academic_year == 1)
            start = perf_counter()
            history = view.player_years(child.player_id)
            samples["player_years"].append(perf_counter() - start)
            if not history or history[0]["year"] != _START:
                raise AssertionError("annual player ID continuity lost")
        for name, values in samples.items():
            checks[name] = {
                "sample_count": len(values),
                "median_ms": round(median(values) * 1000, 3),
                "p95_nearest_rank_ms": _quantile_ms(values, 95, 100),
                "max_ms": round(max(values) * 1000, 3),
            }

        hplan = _index_plan(
            match_file,
            "SELECT match_id FROM historical_matches "
            "WHERE team1_id=? AND year BETWEEN ? AND ?",
            (schools[0], _START, _START + years - 1),
        )
        aplan = _index_plan(
            match_file,
            "SELECT match_id FROM historical_matches "
            "WHERE team2_id=? AND year BETWEEN ? AND ?",
            (schools[0], _START, _START + years - 1),
        )
        playerplan = _index_plan(
            roster_file,
            "SELECT player_id FROM career_player_identities "
            "WHERE school_id=? ORDER BY entry_year, player_id "
            "LIMIT ? OFFSET ?",
            (schools[0], 100, 0),
        )
        if not any("idx_history_school1_year" in row for row in hplan):
            raise AssertionError("school home-match index not selected")
        if not any("idx_history_school2_year" in row for row in aplan):
            raise AssertionError("school away-match index not selected")
        if not any("idx_career_players_school_entry" in row for row in playerplan):
            raise AssertionError("historic player-identity index not selected")

        return {
            "profile": "synthetic_performance_only_not_real_game_results",
            "source_school_ids": "real_id_master; simulated opponents/statistics",
            "measured_not_extrapolated": True,
            "schools": school_count, "years": years,
            "games_per_school_year": games_per_school_year,
            "synthetic_match_count": archive_count,
            "synthetic_school_year_roster_count": previous_year_roster_count,
            "write_elapsed_seconds": write_seconds,
            "history_sqlite": _sql_size(match_file),
            "roster_sqlite": _sql_size(roster_file),
            "total_sqlite_bytes": match_file.stat().st_size + roster_file.stat().st_size,
            "bytes_per_synthetic_match_including_indexes": round(
                match_file.stat().st_size / archive_count, 2
            ),
            "bytes_per_synthetic_school_year_roster_including_identity_index": round(
                roster_file.stat().st_size / previous_year_roster_count, 2
            ),
            "read_latency": checks,
            "query_plans": {
                "home_game": hplan, "away_game": aplan,
                "school_player_index": playerplan,
            },
            "year_range": [_START, _START + years - 1],
            "full_year_tournament_runtime_tested": False,
            "100_year_unbounded_simulation_verified": False,
            "test_excluded": [
                "full tournament simulation", "complete national calendar",
                "official school and match results", "live season date rollover",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic school/roster/Option-A SQLite scalability audit",
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--schools", type=int, default=16)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--games-per-school-year", type=int, default=4)
    parser.add_argument("--output-root",
                        help="Use a new empty directory and preserve the SQLite fixture")
    parser.add_argument("--report", help="Write measured JSON report to path")
    parser.add_argument("--allow-large", action="store_true")
    args = parser.parse_args()
    report = run_scale_audit(
        args.data_root, school_count=args.schools, years=args.years,
        games_per_school_year=args.games_per_school_year,
        output_root=args.output_root, allow_large=args.allow_large,
    )
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
