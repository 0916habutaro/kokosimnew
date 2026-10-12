"""Stage43G-87: disposable full-A storage and verified school-search audit.

Real 2026 master IDs; synthetic box scores/calendar/pairings, never a career
simulation. All writes use existing archive APIs in a new TemporaryDirectory.
No user save, migration, index replacement or integrity bypass is exposed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import random
import sqlite3
from statistics import median
import tempfile
from time import perf_counter

from game_core.match_contract import BatterGameStats, PitcherGameStats, TeamGameStats
from .career_calendar_v2 import CareerCalendarV2Archive, explicit_sandbox_plan
from .career_history_scale_audit import synthetic_ability_record
from .career_history_scale_benchmark import file_sha256
from .career_option_a_storage_profile import _canonical_bytes, _read_only, sqlite_file_profile
from .career_v2_option_a_archive import CareerV2OptionAArchive
from .career_v2_school_century_shards import build_v2_school_century_shards, read_v2_school_century_page
from .historical_match_archive import HistoricalMatchArchive
from .repository import DataRepository
from .season import SeasonOrchestrator

SEED = 2026101201
COMPETITIONS = ("CMPAUDIT87A", "CMPAUDIT87B")
FIELDS = ("inning_scores", "team_stats", "batter_stats", "pitcher_stats")


def survey_2026_master(data_root: str | Path, *, seed: int = SEED) -> dict:
    """Count master and existing structural engine games, not live progress."""
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    root = Path(data_root)
    repo = DataRepository(root)
    season = SeasonOrchestrator(repo, root).run_structural_season(2026, seed)
    segments = Counter()
    rows = []
    for cid, run in sorted(season.competition_runs.items()):
        count = sum(len(stage.matches) for stage in run.stage_executions)
        segment = repo.competitions[cid]["season_segment"]
        segments[segment] += count
        rows.append({"competition_id": cid, "season_segment": segment,
                     "entrants": len(run.entrant_school_ids), "matches": count})
    # Preserve evidence fingerprints, including the area's membership files.
    fingerprints = {str(p.relative_to(root)): file_sha256(p)
                    for p in sorted(root.rglob("*.csv"))}
    return {
        "reference_year": 2026, "seed": seed,
        "schools": len(repo.schools), "hardball_schools": len(repo.school_to_program),
        "prefectures": len({r["prefecture_code"] for r in repo.schools.values()}),
        "master_competitions": len(repo.competitions),
        "structural_competition_runs": len(rows),
        "structural_matches": sum(segments.values()),
        "structural_matches_by_segment": dict(sorted(segments.items())),
        "regional_playoff_resolutions_separate_from_match_rows": len(season.regional_playoff_resolutions),
        "competition_counts": rows, "master_csv_sha256": fingerprints,
        "engine_summary": season.summary(),
        "actual_historical_results": False, "live_calendar_progression_verified": False,
        "prior_year_rankings_and_combined_team_school_proxies_are_structural": True,
    }


def _validate(schools, years, rounds, year_step, first_year, seed, repeats, allow_large):
    for value, low, high in ((schools, 2, 10000), (years, 1, 3200),
                             (rounds, 1, 40), (year_step, 1, 3100),
                             (repeats, 1, 5)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("invalid bounded storage audit dimensions")
    if (schools % 2 or type(first_year) is not int or first_year < 10000
            or type(seed) is not int or type(allow_large) is not bool):
        raise ValueError("invalid school pair/year/seed/large option")
    span = (years - 1) * year_step
    if (first_year + span) // 100 - first_year // 100 >= 32:
        raise ValueError("audit read spans at most 32 century shards")
    matches = schools * years * rounds // 2
    if matches > 100000 or (matches > 1000 and not allow_large):
        raise ValueError("large fixture requires allow_large; hard cap 100000 matches")


def _box_score(year, mid, cid, first, second, day, rng):
    """Nine-inning fictional fixture with complete current GameStats fields.

    Simplified home-runs-only, one pitcher per team. No ability simulation,
    substitutions, career roster attribution or official tournament draw.
    """
    row = synthetic_ability_record(year, cid, mid, first, second, 1)
    a = rng.randint(1, 12)
    b = rng.randrange(a)
    detail = row["ability_detail"]
    row.update(team1_score=a, team2_score=b, competition_name="合成容量監査・公式結果ではない")
    detail.update(team1_score=a, team2_score=b)
    innings = {sid: [0] * 9 for sid in (first, second)}
    for sid, score in ((first, a), (second, b)):
        for _ in range(score):
            innings[sid][rng.randrange(9)] += 1
    for half in detail["inning_scores"]:
        half["runs"] = innings[half["batting_team_id"]][half["inning"] - 1]
    detail["team_stats"] = [TeamGameStats(sid, runs, runs, 0).to_dict()
                            for sid, runs in ((first, a), (second, b))]
    detail["batter_stats"] = []
    detail["pitcher_stats"] = []
    for sid, score, allowed in ((first, a, b), (second, b, a)):
        # Nine hitters each record three outs plus their solo home runs.
        counts = [score // 9 + (i < score % 9) for i in range(9)]
        for i, hits in enumerate(counts):
            detail["batter_stats"].append(BatterGameStats(
                f"AUDIT87-{year}-{sid}-B{i}", sid, plate_appearances=3 + hits,
                at_bats=3 + hits, runs=hits, hits=hits, home_runs=hits, rbi=hits,
            ).to_dict())
        detail["pitcher_stats"].append(PitcherGameStats(
            f"AUDIT87-{year}-{sid}-P", sid, outs_recorded=27,
            batters_faced=27 + allowed, runs_allowed=allowed, earned_runs=allowed,
            hits_allowed=allowed, home_runs_allowed=allowed,
        ).to_dict())
    row.pop("match_date")
    row.update(game_day_token=f"G{year}:{day}", date_source="fictional_v2_day_slot", completed_on="")
    return row


@dataclass
class AuditFixture:
    source: Path
    calendar: Path
    legacy: Path
    archive: CareerV2OptionAArchive
    schools: tuple[str, ...]
    years: tuple[int, ...]
    # Independent expectations from input, without asking the search reader.
    expected: dict[str, list[dict]]
    append_ms: float
    seal_ms: float
    annual_storage: list[dict]


@contextmanager
def synthetic_storage_fixture(data_root: str | Path, *, schools=100, years=2,
                              rounds=4, year_step=1, first_year=10000,
                              seed=SEED, allow_large=False):
    _validate(schools, years, rounds, year_step, first_year, seed, 1, allow_large)
    repo = DataRepository(Path(data_root))
    selected = tuple(sorted(repo.school_to_program)[:schools])
    if len(selected) != schools:
        raise ValueError("not enough hardball schools in current master")
    rng = random.Random(seed)
    saved_years = tuple(first_year + i * year_step for i in range(years))
    with tempfile.TemporaryDirectory(prefix="kokosim-stage87-") as temp:
        root = Path(temp)
        source, calendar, legacy = (root / name for name in (
            "fictional_option_a_v2.sqlite3", "sandbox_calendar_v2.sqlite3", "historical_matches.sqlite3"))
        # A genuine separate legacy sealed A record, protected through every probe.
        old = HistoricalMatchArchive(legacy)
        old.sync(year=2026, rng_seed=seed, resolver_contract="audit87_legacy_guard",
                 plan_fingerprint="audit87-guard", completed=[synthetic_ability_record(
                     2026, "CMPLEGACY87", "LEGACY87", selected[0], selected[1], 1)])
        old.seal_year(2026, expected_match_count=1)
        legacy_sha = file_sha256(legacy)
        cal = CareerCalendarV2Archive(calendar)
        archive = CareerV2OptionAArchive(source, calendar, legacy_archive_path=legacy)
        expected = {sid: [] for sid in selected}
        append_ms = seal_ms = 0.0
        annual_storage = []
        for year in saved_years:
            # Spring/summer labels and dates below are synthetic calendar slots.
            cal.record(explicit_sandbox_plan(
                year, {COMPETITIONS[0]: ["04-01", "04-02"],
                       COMPETITIONS[1]: ["08-01", "08-02"]},
                approved_for_fictional_game=True))
            started = perf_counter()
            for turn in range(rounds):
                paired = list(selected)
                rng.shuffle(paired)
                cid = COMPETITIONS[turn % 2]
                day = ("04" if turn % 2 == 0 else "08") + f"-{1 + (turn // 2) % 2:02d}"
                for pair in range(schools // 2):
                    first, second = paired[2 * pair:2 * pair + 2]
                    mid = f"AUDIT87-{year}-{turn:02d}-{pair:05d}"
                    row = _box_score(year, mid, cid, first, second, day, rng)
                    if not archive.append(year, row)["inserted"]:
                        raise AssertionError("fixture must only insert new games")
                    for sid, opp, own, against in (
                        (first, second, row["team1_score"], row["team2_score"]),
                        (second, first, row["team2_score"], row["team1_score"])):
                        expected[sid].append({
                            "year": year, "competition_id": cid, "match_id": mid,
                            "game_day_token": row["game_day_token"], "school_id": sid,
                            "opponent_school_id": opp, "runs_for": own, "runs_against": against,
                            "result_for_school": "win" if own > against else "loss"})
            append_ms += (perf_counter() - started) * 1000
            started = perf_counter()
            archive.seal_year(year, expected_match_count=schools * rounds // 2)
            seal_ms += (perf_counter() - started) * 1000
            annual_storage.append({"year": year, "source_bytes": source.stat().st_size,
                                   "calendar_bytes": calendar.stat().st_size})
        for rows in expected.values():
            rows.sort(key=lambda x: (x["year"], x["game_day_token"], x["competition_id"], x["match_id"]))
        if file_sha256(legacy) != legacy_sha:
            raise AssertionError("legacy guard changed during generation")
        yield AuditFixture(source, calendar, legacy, archive, selected, saved_years,
                           expected, append_ms, seal_ms, annual_storage)


def _summary(values):
    return {"samples_ms": [round(v, 3) for v in values],
            "median_ms": round(median(values), 3),
            "min_ms": round(min(values), 3), "max_ms": round(max(values), 3)}


def _payload_profile(path):
    totals = Counter()
    sizes = []
    digest = hashlib.sha256()
    shapes = {field: set() for field in FIELDS}
    with closing(_read_only(path)) as db:
        for year, cid, mid, sha, raw in db.execute(
            "SELECT year,competition_id,match_id,record_sha256,payload_json "
            "FROM v2_option_a_matches ORDER BY year,competition_id,match_id"):
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != sha:
                raise ValueError("persisted full-A checksum differs")
            value = json.loads(raw)
            size = len(raw.encode("utf-8"))
            sizes.append(size)
            digest.update(json.dumps([year, cid, mid, sha], separators=(",", ":")).encode())
            for field in FIELDS:
                totals[field + "_rows"] += len(value[field])
                totals[field + "_value_bytes"] += _canonical_bytes(value[field])
                for stat in value[field]:
                    shapes[field].add(tuple(sorted(stat)))
    logical = sum(sizes)
    sections = sum(totals[f + "_value_bytes"] for f in FIELDS)
    return {"matches": len(sizes), "payload_bytes": logical,
            "payload_bytes_per_match": {"min": min(sizes), "median": median(sizes), "max": max(sizes)},
            "metadata_and_json_syntax_bytes": logical - sections,
            "field_counts_and_bytes": dict(totals),
            "field_shapes": {k: [list(shape) for shape in sorted(v)] for k, v in shapes.items()},
            "content_sha256": digest.hexdigest(), "full_events_retained": False}


def audit_fixture(fixture: AuditFixture, index_paths, *, repeats=3) -> dict:
    """Read-only probes on explicit disposable sources/indexes; fail closed."""
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("repeats must be 1..5")
    paths = [fixture.source, fixture.calendar, fixture.legacy, *map(Path, index_paths)]
    before = {str(p): file_sha256(p) for p in paths}
    if len(before) != len(paths):
        raise ValueError("all audit files must be distinct")
    first, last = fixture.years[0], fixture.years[-1]
    timings = {}
    checked = 0
    sampled = tuple(dict.fromkeys((fixture.schools[0], fixture.schools[len(fixture.schools) // 2], fixture.schools[-1])))
    try:
        for sid in (*sampled, "AUDIT87-ZERO-SCHOOL"):
            expected = fixture.expected.get(sid, [])
            last_offset = max(0, ((len(expected) - 1) // 30) * 30)
            cases = (
                ("first_page", first, last, None, 0, "page"),
                ("last_page", first, last, None, last_offset, "page"),
                ("strict_selected_years", first, last, None, 0, "selected_years"),
                ("first_year", first, first, None, 0, "page"),
                ("last_year", last, last, None, 0, "page"),
                ("competition_a", first, last, COMPETITIONS[0], 0, "page"),
                ("competition_b", first, last, COMPETITIONS[1], 0, "page"),
                ("no_competition", first, last, "AUDIT87-NONE", 0, "page"),
                ("past_last_page", first, last, None, len(expected), "page"))
            for label, start, end, cid, offset, scope in cases:
                # Supply only shards overlapping a narrow-year query.
                active = [p for p in index_paths if _overlaps(p, start, end)]
                wanted = [x for x in expected if start <= x["year"] <= end
                          and (cid is None or x["competition_id"] == cid)]
                samples = []
                for _ in range(repeats):
                    started = perf_counter()
                    page = read_v2_school_century_page(
                        fixture.source, fixture.calendar, active, sid,
                        start_year=start, end_year=end, competition_id=cid,
                        offset=offset, limit=30, verify_scope=scope)
                    samples.append((perf_counter() - started) * 1000)
                    projection = [{k: r[k] for k in wanted[0]} for r in page["records"]] if wanted else page["records"]
                    if (page["total"] != len(wanted) or projection != wanted[offset:offset + 30]
                            or not page["visible_match_checksums_verified"]
                            or page["all_selected_year_payloads_verified"] != (scope == "selected_years")):
                        raise AssertionError("school page differs from independent input oracle")
                    checked += 1
                timings[sid + ":" + label] = _summary(samples)
        # Read JSON1 as an independent baseline for the first saved year.
        samples = []
        wanted = [x for x in fixture.expected[sampled[0]] if x["year"] == first]
        for _ in range(repeats):
            started = perf_counter()
            data = fixture.archive.school_game_page(sampled[0], start_year=first, end_year=first)
            samples.append((perf_counter() - started) * 1000)
            if data["total"] != len(wanted) or [{k: r[k] for k in wanted[0]} for r in data["records"]] != wanted[:30]:
                raise AssertionError("JSON1 differs from fixture input")
        timings["original_json1_first_year"] = _summary(samples)
    finally:
        if any(file_sha256(p) != before[str(p)] for p in paths):
            raise RuntimeError("audit mutated source/calendar/legacy/index")
    return {"sampled_schools": list(sampled), "verified_page_calls": checked,
            "timings": timings, "source_calendar_legacy_indexes_sha_unchanged": True}


def _overlaps(path, start, end):
    with closing(_read_only(Path(path))) as db:
        low, high = db.execute("SELECT start_year,end_year FROM meta").fetchone()
    return low <= end and start <= high


def run_national_storage_audit(data_root: str | Path, *, schools=100, years=2,
                               rounds=4, year_step=1, first_year=10000,
                               seed=SEED, repeats=3, allow_large=False) -> dict:
    _validate(schools, years, rounds, year_step, first_year, seed, repeats, allow_large)
    with synthetic_storage_fixture(data_root, schools=schools, years=years, rounds=rounds,
                                   year_step=year_step, first_year=first_year,
                                   seed=seed, allow_large=allow_large) as fixture:
        original = {p.name: file_sha256(p) for p in (fixture.source, fixture.calendar, fixture.legacy)}
        started = perf_counter()
        made = build_v2_school_century_shards(
            fixture.source, fixture.calendar, start_year=fixture.years[0], end_year=fixture.years[-1])
        index_ms = (perf_counter() - started) * 1000
        indexes = [Path(x["index_path"]) for x in made["shards"]]
        probes = audit_fixture(fixture, indexes, repeats=repeats)
        sha_samples = []
        for _ in range(repeats):
            started = perf_counter()
            for p in (fixture.source, fixture.calendar, fixture.legacy, *indexes):
                file_sha256(p)
            sha_samples.append((perf_counter() - started) * 1000)
        storage = {p.name: sqlite_file_profile(p) for p in (fixture.source, fixture.calendar, fixture.legacy, *indexes)}
        payload = _payload_profile(fixture.source)
        with closing(_read_only(indexes[0])) as db:
            sql = ("SELECT * FROM school_game WHERE school_id=? AND year BETWEEN ? AND ? "
                   "ORDER BY year,game_day_token,competition_id,match_id LIMIT ? OFFSET ?")
            args = (fixture.schools[0], fixture.years[0], fixture.years[-1], 30, 0)
            plans = {"school_page": [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql, args)],
                     "competition_page": [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql.replace(
                         " ORDER BY", " AND competition_id=? ORDER BY"), args[:3] + (COMPETITIONS[0],) + args[3:])]}
            definitions = [list(r) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name")]
        membership_count = 0
        for p in indexes:
            with closing(_read_only(p)) as db:
                membership_count += db.execute("SELECT COUNT(*) FROM school_game").fetchone()[0]
        if membership_count != payload["matches"] * 2:
            raise AssertionError("indexed memberships must equal twice full-A matches")
        if any(file_sha256(p) != original[p.name] for p in (fixture.source, fixture.calendar, fixture.legacy)):
            raise AssertionError("original changed while indexing/profiling")
        result = {
            "stage": "43G-87", "seed": seed, "schools": schools,
            "saved_years": list(fixture.years), "year_step": year_step,
            "synthetic_games_per_school_year": rounds, "repetitions": repeats,
            "full_a": payload, "index_shards": len(indexes), "indexed_memberships": membership_count,
            "append_ms": round(fixture.append_ms, 3), "seal_ms": round(fixture.seal_ms, 3),
            "index_build_ms": round(index_ms, 3), "file_sha256_verification": _summary(sha_samples),
            "storage": storage, "annual_storage": fixture.annual_storage,
            "source_and_calendar_bytes": storage[fixture.source.name]["file_bytes"] + storage[fixture.calendar.name]["file_bytes"],
            "derived_school_index_bytes": sum(storage[p.name]["file_bytes"] for p in indexes),
            "sql_plans": plans, "index_definitions": definitions, "search": probes,
            "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                            "platform": platform.platform(), "machine": platform.machine()},
            "synthetic_calendar_and_pairings_not_current_tournament_schedule": True,
            "nine_innings_18_batters_2_pitchers_no_substitutions": True,
            "career_roster_archive_and_player_stats_cache_included": False,
            "national_100_or_200_year_full_tournaments_verified": False,
            "game_save_year_limit_imposed": False,
        }
    result["temporary_fixture_deleted"] = not fixture.source.parent.exists()
    return result


def main():
    parser = argparse.ArgumentParser(description="架空完全A・全国校規模の容量/厳密検索監査（既存セーブ不使用）")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--survey-master", action="store_true")
    parser.add_argument("--schools", type=int, default=100)
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--year-step", type=int, default=1)
    parser.add_argument("--first-year", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--allow-large", action="store_true")
    args = parser.parse_args()
    if args.survey_master:
        result = survey_2026_master(args.data_root, seed=args.seed)
    else:
        result = run_national_storage_audit(args.data_root, schools=args.schools, years=args.years,
            rounds=args.rounds, year_step=args.year_step, first_year=args.first_year,
            seed=args.seed, repeats=args.repeats, allow_large=args.allow_large)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
