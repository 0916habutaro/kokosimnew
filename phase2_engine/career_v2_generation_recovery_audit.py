"""Stage43G-90 disposable generation experiments, NOT a save/restore API.

Only self-generated TemporaryDirectory fixtures are inputs and destinations.
No production imports this module. No user-save path, overwrite, GC or automatic
index activation is exposed. The manifest is an unadopted laboratory format.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import copy
import errno
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import random
import shutil
import sqlite3
from time import perf_counter

from game_core.players import PlayerRosterGenerator
from .career_calendar_v2 import CareerCalendarV2Archive, explicit_sandbox_plan
from .career_roster_archive import CareerRosterArchive
from .career_v2_national_storage_audit import (
    COMPETITIONS, SEED, _box_score, synthetic_storage_fixture,
)
from .career_v2_option_a_archive import CareerV2OptionAArchive
from .career_v2_school_century_shards import (
    build_v2_school_century_shards, read_v2_school_century_page,
)
from .repository import DataRepository

DATA = Path(__file__).resolve().parents[1] / "data"
FORMAT = "stage90-laboratory-only-v1"
TIMEOUT = 20


class Refused(ValueError):
    """Incomplete/untrusted/foreign experiment: no usable result."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def sql_fingerprint(path):
    """Independent raw relational proof; excludes path/page/WAL layout."""
    with closing(ro(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise Refused("SQLite integrity failed")
        tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        rows = []
        for name, schema in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            values = list(db.execute(f"SELECT * FROM {quoted}"))
            rows.append([schema, sorted(values, key=canonical)])
        return digest(canonical(rows))


def raw_oracle(source, calendar, expected):
    """No production ledger/normalizer/reader generates these expectations."""
    with closing(ro(calendar)) as cal, closing(ro(source)) as db:
        plans = {}
        for year, raw, checksum in cal.execute(
                "SELECT game_year,plan_json,content_sha256 FROM sandbox_year_plans"):
            if digest(raw) != checksum:
                raise Refused("calendar SHA differs")
            plans[year] = (json.loads(raw), checksum)
        actual = {school: [] for school in expected}
        for year, status, count, ledger, calendar_sha in db.execute(
                "SELECT year,status,match_count,ledger_sha256,calendar_sha256 FROM v2_game_years ORDER BY year"):
            if status != "sealed" or year not in plans or plans[year][1] != calendar_sha:
                raise Refused("active/missing/mismatched annual calendar")
            records = list(db.execute(
                "SELECT competition_id,match_id,record_sha256,payload_json,game_day_token,calendar_sha256 "
                "FROM v2_option_a_matches WHERE year=? ORDER BY competition_id,match_id", (year,)))
            if count != len(records) or ledger != digest(canonical([r[:3] for r in records])):
                raise Refused("sealed ledger differs")
            for cid, mid, checksum, raw, token, plan_sha in records:
                value = json.loads(raw)
                if (digest(raw) != checksum or plan_sha != calendar_sha
                        or token not in plans[year][0]["competition_days"].get(cid, [])
                        or (value["year"], value["competition_id"], value["match_id"], value["match_date"])
                        != (year, cid, mid, token) or not token.startswith(f"G{year}:")):
                    raise Refused("full-A identity/SHA/day differs")
                a, b = value["team1_id"], value["team2_id"]
                for school, opponent, own, against in (
                    (a, b, value["team1_score"], value["team2_score"]),
                    (b, a, value["team2_score"], value["team1_score"])):
                    if (sum(x["runs"] for x in value["inning_scores"] if x["batting_team_id"] == school) != own
                            or sum(x["runs"] for x in value["batter_stats"] if x["school_id"] == school) != own
                            or sum(x["runs_allowed"] for x in value["pitcher_stats"] if x["school_id"] == school) != against):
                        raise Refused("inning/individual scores differ from final score")
                    actual.setdefault(school, []).append(dict(year=year, competition_id=cid,
                        match_id=mid, game_day_token=token, school_id=school,
                        opponent_school_id=opponent, runs_for=own, runs_against=against,
                        result_for_school="win" if own > against else "loss"))
        for rows in actual.values():
            rows.sort(key=lambda r: (r["year"], r["game_day_token"], r["competition_id"], r["match_id"]))
        if actual != expected:
            raise Refused("raw school history differs from independent input")
        return sum(len(rows) for rows in actual.values()) // 2


def pause(pipe, label):
    pipe.send(label)
    if not pipe.poll(TIMEOUT):
        raise TimeoutError("parent did not release boundary")
    pipe.recv()


def _worker(root, stage, boundary, row, pipe):
    """Child uses only parent's owned temporary fixture; never public CLI."""
    root = Path(root)
    source, calendar = root / "fictional_option_a_v2.sqlite3", root / "sandbox_calendar_v2.sqlite3"
    real_connect, real_link = sqlite3.connect, os.link
    target = calendar if stage == "calendar" else source
    fired = False

    class BoundaryConnection(sqlite3.Connection):
        def around(self, action):
            nonlocal fired
            eligible = stage == "index" or Path(self.execute("PRAGMA database_list").fetchone()[2]).resolve() == target.resolve()
            if eligible and self.in_transaction and not fired:
                fired = True
                if boundary == "commit_before":
                    pause(pipe, boundary)
                result = action()
                if boundary == "commit_after":
                    pause(pipe, boundary)
                return result
            return action()

        def __exit__(self, *args):
            return self.around(lambda: super(BoundaryConnection, self).__exit__(*args))

        def commit(self):
            return self.around(lambda: super(BoundaryConnection, self).commit())

    def connect(*args, **kwargs):
        kwargs["factory"] = BoundaryConnection
        return real_connect(*args, **kwargs)

    def link(*args, **kwargs):
        if boundary == "publish_before":
            pause(pipe, boundary)
        result = real_link(*args, **kwargs)
        if boundary == "publish_after":
            pause(pipe, boundary)
        return result

    sqlite3.connect, os.link = connect, link
    try:
        archive = CareerV2OptionAArchive(source, calendar)
        if stage == "calendar":
            CareerCalendarV2Archive(calendar).record(explicit_sandbox_plan(10100,
                {COMPETITIONS[0]: ["04-01"]}, approved_for_fictional_game=True))
        elif stage == "append":
            archive.append(10100, row)
        elif stage == "seal":
            archive.seal_year(10100, expected_match_count=1)
        elif stage == "index":
            build_v2_school_century_shards(source, calendar, start_year=10099,
                                          end_year=10100, version="killed")
        pipe.send("completed_without_boundary")
    except BaseException as exc:
        pipe.send("error:" + type(exc).__name__ + ":" + str(exc))
    finally:
        pipe.close()


class GenerationLab:
    """Own all inputs; no constructor parameter can specify a saved DB."""

    def __init__(self, *, schools=4, years=2, rounds=4, year_step=1, allow_large=False):
        self.dimensions = dict(schools=schools, years=years, rounds=rounds,
            year_step=year_step, first_year=10099, seed=SEED, allow_large=allow_large)
        self.stack = ExitStack()
        self.approvals = {}
        self.evidence = []

    def __enter__(self):
        try:
            self.f = self.stack.enter_context(synthetic_storage_fixture(DATA, **self.dimensions))
            self.root = self.f.source.parent
            self.roster = self.root / "career_rosters.sqlite3"
            repo = DataRepository(DATA)
            for school in self.f.schools[:2]:
                CareerRosterArchive(self.roster).save_initial_roster(
                    PlayerRosterGenerator().generate_for_school_id(repo, school, self.f.years[0], SEED))
            self.roles = {"source": self.f.source, "calendar": self.f.calendar,
                          "legacy": self.f.legacy, "roster": self.roster}
            self.indexes = []
            self.expected = copy.deepcopy(self.f.expected)
            self.baseline = {k: sha(p) for k, p in self.roles.items()}
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def local(self, path):
        p = Path(path)
        if p.is_symlink() or not p.resolve().is_relative_to(self.root.resolve()):
            raise Refused("experiment paths must stay in owned fixture")
        return p

    def new_dir(self, name):
        if not name.isalnum():
            raise Refused("simple experiment label required")
        path = self.local(self.root / name)
        path.mkdir()  # never reuse/overwrite a target
        return path

    def build(self, *, approved=False, restored=None, version=None):
        if not approved:
            raise Refused("index generation needs explicit experiment approval")
        roles = self.roles if restored is None else self.restored_roles(restored)
        result = build_v2_school_century_shards(roles["source"], roles["calendar"],
            start_year=self.f.years[0], end_year=max(r["year"] for rows in self.expected.values() for r in rows),
            version=("rebuilt" if restored is not None else version))
        indexes = [Path(r["index_path"]) for r in result["shards"]]
        if restored is None:
            self.indexes = indexes
        return indexes

    def approve(self, label):
        if label in self.approvals or not label.isalnum():
            raise Refused("new candidate approval label required")
        raw_oracle(self.f.source, self.f.calendar, self.expected)
        self.approvals[label] = {
            "format": FORMAT, "slot": "laboratory-slot-A", "generation": label,
            "proofs": {role: sql_fingerprint(path) for role, path in self.roles.items()},
            "expected": copy.deepcopy(self.expected),
        }
        return label

    def check_live(self, label):
        trust = self.approvals[label]
        if trust["proofs"] != {k: sql_fingerprint(p) for k, p in self.roles.items()}:
            raise Refused("candidate changed since explicit approval")

    def backup(self, label, *, include_indexes=False, fault=None, hook=lambda point: None):
        self.check_live(label)
        started = perf_counter()
        staging = self.new_dir(label + "staging")
        sizes, files = {}, {}
        for role, path in self.roles.items():
            dest = staging / path.name
            hook(role + "_copy_before")
            with closing(ro(path)) as src, closing(sqlite3.connect(dest)) as dst:
                src.backup(dst)
            hook(role + "_copy_after")
            if fault == "enospc" and role == "source":
                raise OSError(errno.ENOSPC, "injected storage exhaustion, no actual disk fill")
            if fault == "shortcopy" and role == "source":
                with dest.open("r+b") as stream:
                    stream.truncate(max(1, dest.stat().st_size // 2))
            sizes[role] = dest.stat().st_size
            files[role] = {"name": dest.name, "sha256": sha(dest)}
        # Indexes are diagnostic copies only. Their absolute provenance is NOT rewritten.
        for i, path in enumerate(self.indexes if include_indexes else []):
            dest = staging / path.name
            with closing(ro(path)) as src, closing(sqlite3.connect(dest)) as dst:
                src.backup(dst)
            files[f"index{i}"] = {"name": dest.name, "sha256": sha(dest)}
            sizes[f"index{i}"] = dest.stat().st_size
        trust = self.approvals[label]
        raw_oracle(staging / files["source"]["name"], staging / files["calendar"]["name"], trust["expected"])
        if {k: sql_fingerprint(staging / files[k]["name"]) for k in self.roles} != trust["proofs"]:
            raise Refused("copied DBs belong to different candidate generations")
        self.check_live(label)
        manifest = {k: v for k, v in trust.items() if k != "expected"}
        manifest["files"] = files
        hook("manifest_before")
        with (staging / "manifest.json").open("x", encoding="utf-8") as stream:
            stream.write(canonical(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        hook("manifest_after")
        final = self.local(self.root / (label + "published"))
        hook("publish_before")
        if final.exists() or final.is_symlink():
            raise FileExistsError("published experiment target exists")
        if fault == "rename":
            raise OSError(errno.EACCES, "injected rename failure")
        # Private single-owner directory only. Not a concurrent no-clobber API.
        os.rename(staging, final)
        hook("publish_after")
        self.evidence.append({"generation": label, "backup_ms": round((perf_counter()-started)*1000, 3),
                              "bytes_by_role": sizes, "backup_bytes": sum(sizes.values())})
        return final

    def validate(self, path, label, *, slot="laboratory-slot-A"):
        root = self.local(path)
        trust = self.approvals[label]  # private approval anchor, never trust manifest alone
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if any(manifest[k] != trust[k] for k in ("format", "slot", "generation", "proofs")) or slot != trust["slot"]:
                raise Refused("foreign/stale/untrusted manifest")
            if not set(self.roles).issubset(manifest["files"]):
                raise Refused("mandatory original missing")
            for record in manifest["files"].values():
                name = record["name"]
                if Path(name).name != name or name in (".", ".."):
                    raise Refused("manifest path is not a local basename")
                file = self.local(root / name)
                if sha(file) != record["sha256"]:
                    raise Refused("file SHA differs")
            roles = {k: root / manifest["files"][k]["name"] for k in self.roles}
            if {k: sql_fingerprint(p) for k, p in roles.items()} != trust["proofs"]:
                raise Refused("original/calendar/roster generation differs")
            raw_oracle(roles["source"], roles["calendar"], trust["expected"])
            return manifest
        except (OSError, KeyError, TypeError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
            raise Refused("incomplete experiment generation") from exc

    def restore(self, published, label, *, hook=lambda point: None):
        manifest = self.validate(published, label)
        started = perf_counter()
        destination = self.new_dir(label + "restored")
        for role, record in manifest["files"].items():
            hook(role + "_copy_before")
            with (destination / record["name"]).open("xb") as output, (Path(published) / record["name"]).open("rb") as src:
                shutil.copyfileobj(src, output)
            hook(role + "_copy_after")
        hook("manifest_before")
        with (destination / "manifest.json").open("x", encoding="utf-8") as stream:
            stream.write(canonical(manifest))
        hook("manifest_after")
        self.validate(destination, label)
        hook("read_before")
        self.evidence[-1]["restore_ms"] = round((perf_counter()-started)*1000, 3)
        return destination

    def restored_roles(self, path):
        manifest = json.loads((self.local(path) / "manifest.json").read_text(encoding="utf-8"))
        return {k: Path(path) / manifest["files"][k]["name"] for k in self.roles}

    def read(self, restored, label, indexes):
        self.validate(restored, label)
        roles = self.restored_roles(restored)
        expected = self.approvals[label]["expected"]
        first = min(r["year"] for rows in expected.values() for r in rows)
        last = max(r["year"] for rows in expected.values() for r in rows)
        calls, pages = 0, []
        for school in (*list(expected)[:3], "AUDIT90-ZERO"):
            for cid in (None, *COMPETITIONS):
                wanted = [r for r in expected.get(school, []) if cid is None or r["competition_id"] == cid]
                for offset in sorted({0, 30, 60, len(wanted)}):
                    page = read_v2_school_century_page(roles["source"], roles["calendar"], indexes,
                        school, start_year=first, end_year=last, competition_id=cid,
                        offset=offset, limit=30, verify_scope="selected_years")
                    actual = [{k: row[k] for k in wanted[0]} for row in page["records"]] if wanted else page["records"]
                    if page["total"] != len(wanted) or actual != wanted[offset:offset + 30]:
                        raise AssertionError("restored reader differs from independent input")
                    calls += 1
                    if school == next(iter(expected)) and cid is None:
                        pages.append(len(actual))
        return {"verified_queries": calls, "first_school_page_sizes": pages}

    def kill_writer(self, stage, boundary):
        row = _box_score(10100, "KILL90", COMPETITIONS[0], *self.f.schools[:2], "04-01", random.Random(SEED))
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        process = ctx.Process(target=_worker, args=(str(self.root), stage, boundary, row, child))
        process.start()
        child.close()
        try:
            if not parent.poll(TIMEOUT):
                raise TimeoutError("child did not reach deterministic boundary")
            hit = parent.recv()
            if hit != boundary:
                raise AssertionError(hit)
            process.kill()
            process.join(TIMEOUT)
            if process.is_alive() or process.exitcode == 0:
                raise AssertionError("child kill did not finish")
        finally:
            if process.is_alive():
                process.kill()
                process.join(TIMEOUT)
            parent.close()
        return row

    def disk_bytes(self):
        # Observed live file-size sum, including retained generations/WAL/temp indexes.
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())


def _generation_worker(root, stage, boundary, trust, index_names, pipe):
    # Reconstitute only the parent's disposable lab, never a user-supplied save.
    lab = object.__new__(GenerationLab)
    lab.root = Path(root)
    lab.roles = {k: lab.root / name for k, name in {
        "source": "fictional_option_a_v2.sqlite3", "calendar": "sandbox_calendar_v2.sqlite3",
        "legacy": "historical_matches.sqlite3", "roster": "career_rosters.sqlite3"}.items()}
    lab.approvals = {trust["generation"]: trust}
    lab.indexes = [lab.root / name for name in index_names]
    lab.evidence = [{}]
    def hook(point):
        if point == boundary:
            pause(pipe, point)
    try:
        label = trust["generation"]
        if stage == "backup":
            lab.backup(label, include_indexes=bool(index_names), hook=hook)
        else:
            lab.restore(lab.root / (label + "published"), label, hook=hook)
        pipe.send("completed_without_boundary")
    except BaseException as exc:
        pipe.send("error:" + type(exc).__name__ + ":" + str(exc))
    finally:
        pipe.close()


def kill_generation(lab, label, stage, boundary):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_generation_worker, args=(str(lab.root), stage, boundary,
        lab.approvals[label], [p.name for p in lab.indexes], child))
    process.start()
    child.close()
    try:
        if not parent.poll(TIMEOUT):
            raise TimeoutError("generation child boundary timed out")
        hit = parent.recv()
        if hit != boundary:
            raise AssertionError(hit)
        process.kill()
        process.join(TIMEOUT)
        if process.is_alive() or process.exitcode == 0:
            raise AssertionError("generation kill failed")
    finally:
        if process.is_alive():
            process.kill()
            process.join(TIMEOUT)
        parent.close()


def measure(profile):
    dimensions = {
        "small": dict(schools=4, years=2, rounds=34),
        "national3746": dict(schools=3746, years=1, rounds=2, allow_large=True),
        "sparse200": dict(schools=2, years=200, rounds=2, allow_large=True),
    }[profile]
    with GenerationLab(**dimensions) as lab:
        lab.build(approved=True)
        live_bytes = lab.disk_bytes()
        peaks = [live_bytes]
        for label in ("old", "new"):
            lab.approve(label)
            published = lab.backup(label, include_indexes=True, hook=lambda _: peaks.append(lab.disk_bytes()))
            restored = lab.restore(published, label, hook=lambda _: peaks.append(lab.disk_bytes()))
            copied_indexes = sorted(restored.glob("fictional_v2_school_read_index*.sqlite3"))
            try:
                lab.read(restored, label, copied_indexes)
            except ValueError:
                pass
            else:
                raise AssertionError("relocated index must fail closed")
            started = perf_counter()
            indexes = lab.build(approved=True, restored=restored)
            rebuild_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            reading = lab.read(restored, label, indexes)
            lab.evidence[-1].update(index_rebuild_ms=round(rebuild_ms, 3),
                verified_read_ms=round((perf_counter()-started)*1000, 3), **reading)
            peaks.append(lab.disk_bytes())
        if {k: sha(p) for k, p in lab.roles.items()} != lab.baseline:
            raise AssertionError("original fixture changed")
        return dict(stage="43G-90", profile=profile, seed=SEED, **dimensions,
            python=platform.python_version(), sqlite=sqlite3.sqlite_version, os=platform.system(),
            actual_continuous_national_career=False, synthetic_full_a=True,
            rounds_are_not_tournament_progression=True, legacy_iso_preserved=True,
            roster_scope="two independent initial school rosters, not synthetic box-score attribution",
            manifest_adopted=False, fixture_source_sha_unchanged=True,
            retained_backups=2, generations_have_same_content_for_capacity_measurement=True,
            live_bytes=live_bytes, observed_peak_file_bytes=max(peaks),
            peak_definition="sampled file-size sum; not allocated blocks, RSS or power-loss durability",
            samples=lab.evidence)


def run_regressions():
    import unittest
    suite = unittest.defaultTestLoader.discover(str(DATA.parent / "tests"), pattern="test_stage43g90_*.py")
    class EvidenceResult(unittest.TextTestResult):
        def __init__(self, *args):
            super().__init__(*args)
            self.schedules = []
        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            self.schedules.append({"test": test.id(), "schedule": str(subtest), "successful": err is None})
    started = perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    return dict(stage="43G-90", python=platform.python_version(), sqlite=sqlite3.sqlite_version,
        os=platform.system(), tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped), successful=result.wasSuccessful(),
        seconds=round(perf_counter()-started, 3), schedules=result.schedules,
        subtest_schedules=len(result.schedules), ordering="spawn + Pipe handshake + process.kill; no random sleep" )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regressions", action="store_true", help="run deterministic fault regressions instead of measurement")
    parser.add_argument("--profile", choices=("small", "national3746", "sparse200"), default="small")
    parser.add_argument("--json-output", type=Path, required=True, help="NEW evidence file only; never a save destination")
    args = parser.parse_args()
    with args.json_output.open("x", encoding="utf-8") as stream:
        result = run_regressions() if args.regressions else measure(args.profile)
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if args.regressions and not result["successful"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
