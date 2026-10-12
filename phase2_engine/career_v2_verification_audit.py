"""Stage43G-88: paired old/new reads of the exact same disposable full-A DB."""
from __future__ import annotations

import argparse
import cProfile
import json
from pathlib import Path
import platform
import pstats
import sqlite3
import subprocess
from time import perf_counter
from types import ModuleType

from .career_history_scale_benchmark import file_sha256
from .career_v2_national_storage_audit import (
    SEED, _summary, audit_fixture, synthetic_storage_fixture,
)
from .career_v2_school_century_shards import (
    build_v2_school_century_shards, read_v2_school_century_page,
)

BASELINE = "cfedd2f13a3f8688f5b5b6597c97f8530807a66b"
ROOT = Path(__file__).resolve().parents[1]


def _baseline_reader(ref):
    # Explicit source control baseline, not a persistent proof or DB shortcut.
    modules = []
    for name in ("career_v2_school_read_index", "career_v2_school_century_shards"):
        raw = subprocess.check_output(
            ["git", "show", f"{ref}:phase2_engine/{name}.py"], cwd=ROOT, text=True,
        )
        module = ModuleType(f"phase2_engine._stage88_before_{name}")
        module.__package__ = "phase2_engine"
        exec(compile(raw, f"baseline:{ref}/{name}.py", "exec"), module.__dict__)
        modules.append(module)
    modules[1].read_indexed_v2_school_page = modules[0].read_indexed_v2_school_page
    return modules[1].read_v2_school_century_page


def _profile(call):
    profiler = cProfile.Profile()
    profiler.enable()
    result = call()
    profiler.disable()
    stats = pstats.Stats(profiler)
    wanted = ("_verify_index_years", "_source_checked_header", "_ledger", "_verify_match")
    counts = {name: sum(value[1] for key, value in stats.stats.items() if key[2] == name)
              for name in wanted}
    return result, {"calls": counts, "profiled_seconds": round(stats.total_tt, 6)}


def compare_verification(*, schools=100, years=2, rounds=4, year_step=1,
                         first_year=10000, seed=SEED, repeats=3,
                         allow_large=False, baseline_ref=BASELINE):
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("one to five paired repetitions required")
    before_reader = _baseline_reader(baseline_ref)
    with synthetic_storage_fixture(ROOT / "data", schools=schools, years=years,
            rounds=rounds, year_step=year_step, first_year=first_year,
            seed=seed, allow_large=allow_large) as f:
        indexes = [Path(s["index_path"]) for s in build_v2_school_century_shards(
            f.source, f.calendar, start_year=f.years[0], end_year=f.years[-1])["shards"]]
        protected = {p: file_sha256(p) for p in (f.source, f.calendar, f.legacy, *indexes)}
        results = {}
        for scope in ("page", "selected_years"):
            def call(reader):
                return reader(f.source, f.calendar, indexes, f.schools[0],
                    start_year=f.years[0], end_year=f.years[-1], verify_scope=scope)
            calls = {"before": lambda: call(before_reader),
                     "after": lambda: call(read_v2_school_century_page)}
            # Warm both APIs once; do not flush the OS/SQLite caches.
            expected = calls["before"]()
            if calls["after"]() != expected:
                raise AssertionError("before/after return contract differs")
            oracle = f.expected[f.schools[0]]
            if expected["total"] != len(oracle) or [
                    {k: row[k] for k in oracle[0]} for row in expected["records"]] != oracle[:30]:
                raise AssertionError("paired reads differ from independent input oracle")
            samples = {"before": [], "after": []}
            orders = []
            for trial in range(repeats):
                order = ("before", "after") if trial % 2 == 0 else ("after", "before")
                orders.append(list(order))
                for label in order:
                    started = perf_counter()
                    result = calls[label]()
                    samples[label].append((perf_counter() - started) * 1000)
                    if result != expected:
                        raise AssertionError("paired read changed")
            profiles = {}
            for label, invoke in calls.items():
                result, profiles[label] = _profile(invoke)
                if result != expected:
                    raise AssertionError("profiled read changed")
            results[scope] = {label: _summary(values) for label, values in samples.items()}
            results[scope].update(profiles=profiles, orders=orders,
                before_over_after_median=round(
                    results[scope]["before"]["median_ms"] / results[scope]["after"]["median_ms"], 4))
        probes = audit_fixture(f, indexes, repeats=1)
        if any(file_sha256(p) != sha for p, sha in protected.items()):
            raise AssertionError("paired audit changed saved files")
        result = {"stage": "43G-88", "baseline_commit": baseline_ref, "seed": seed,
            "schools": schools, "saved_years": list(f.years), "rounds": rounds,
            "matches": schools * years * rounds // 2, "repeats": repeats,
            "index_shards": len(indexes), "search": results,
            "independent_oracle_calls": probes["verified_page_calls"],
            "same_files_seed_density_and_verification_level": True,
            "source_calendar_legacy_indexes_sha_unchanged": True,
            "warmup_each_api": 1, "cache_flushed": False,
            "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                "platform": platform.platform(), "cpu_quota": Path('/sys/fs/cgroup/cpu.max').read_text().strip()
                if Path('/sys/fs/cgroup/cpu.max').is_file() else None}}
    result["temporary_fixture_deleted"] = not f.source.parent.exists()
    return result


def main():
    parser = argparse.ArgumentParser(description="同一完全A fixtureのStage43G-88変更前後比較")
    for name, default in (("schools", 100), ("years", 2), ("rounds", 4),
                          ("year-step", 1), ("first-year", 10000), ("seed", SEED), ("repeats", 3)):
        parser.add_argument("--" + name, type=int, default=default)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--baseline-ref", default=BASELINE)
    result = compare_verification(**vars(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
