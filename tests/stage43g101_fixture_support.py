"""Disposable two-competition fixture; no existing save/candidate input API."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.engine import TournamentEngine
from phase2_engine.live_game_service import LiveGameService, SharedSchoolYearPersistence as Authority
from phase2_engine.repository import DataRepository
from stage43g97_acceptance_support import actual_runtime, KEYS, DETAILS

ROOT = Path(__file__).resolve().parents[1]
SLOT = "self_generated_shared101"
YEAR, SEED = 2026, Authority.SEASON_SEED


def services(saves):
    repo = DataRepository(ROOT / "data")
    plan = Authority.verification_plan(repo, ROOT / "data")
    resolver = AbilityMatchResolver(repo, ability_config_dir=ROOT / "config/abilities",
        match_config_dir=ROOT / "config/match", team_generation_seed=Authority.ROSTER_SEED)
    engine = TournamentEngine(repo, main_match_resolver=resolver, pre_main_match_resolver=resolver)

    class Planner:
        year, rng_seed = YEAR, SEED
        def build_plan(self):
            return plan

    def planner_factory(repo, data_dir, seed, year):
        if (year, seed) != (YEAR, SEED):
            raise ValueError("fixture year/seed changed")
        return Planner()

    service = LiveGameService(repo, ROOT / "data", save_root=saves, max_backups=0,
        resolver_contract=Authority.RESOLVER_CONTRACT, planner_factory=planner_factory,
        career_persistence=Authority(plan, resolver))
    return service, resolver, engine


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def raw_records(slot, sealed=True):
    """Independent SQL/JSON/SHA oracle: no product decoder/validator is called."""
    output = {}
    for name, table, raw_field, sha_field, file in (
        ("rosters", "career_school_rosters", "payload_json", "content_sha256", "career_rosters.sqlite3"),
        ("identities", "career_player_identities", "identity_json", "identity_sha256", "career_rosters.sqlite3"),
        ("matches", "historical_matches", "payload_json", "record_sha256", "historical_matches.sqlite3"),
        ("outcomes", "historical_competition_outcomes", "payload_json", "record_sha256", "historical_matches.sqlite3"),
    ):
        with closing(sqlite3.connect((slot / file).as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            assert [tuple(r) for r in con.execute("PRAGMA integrity_check")] == [("ok",)]
            output[name] = []
            if not con.execute("SELECT name FROM sqlite_master WHERE name=?", (table,)).fetchone():
                assert name == "outcomes" and not sealed
                continue
            for row in con.execute("SELECT * FROM " + table):
                raw = row[raw_field]
                assert sha(raw) == row[sha_field]
                payload = json.loads(raw)
                fields = (
                    ("year", "school_id") if name == "rosters" else
                    ("player_id", "school_id", "entry_year") if name == "identities" else
                    ("year", "competition_id", "match_id", "match_date", "date_source",
                     "team1_id", "team2_id", "team1_score", "team2_score", "score_source")
                    if name == "matches" else ("year", "competition_id")
                )
                for field in fields:
                    assert row[field] == payload["reference_year" if name == "rosters" and field == "year" else field]
                output[name].append(payload)
    for key, field in (("rosters", "school_id"), ("identities", "player_id"),
                       ("matches", "match_id"), ("outcomes", "competition_id")):
        output[key].sort(key=lambda r: r[field])
    assert (len(output["rosters"]), len(output["identities"])) == (6, 120)
    identities = {r["player_id"]: r for r in output["identities"]}
    for roster in output["rosters"]:
        assert roster["reference_year"] == YEAR and roster["rng_seed"] == Authority.ROSTER_SEED
        assert len(roster["players"]) == 20
        for player in roster["players"]:
            assert player["school_id"] == roster["school_id"]
            assert player["program_id"] == roster["program_id"]
            assert player["entry_year"] == YEAR - player["academic_year"] + 1
            recipe = f'{Authority.ROSTER_SEED}:player_v1:{YEAR}:{roster["school_id"]}:{player["roster_no"]}'
            assert player["player_id"] == "PLY" + sha(recipe)[:20].upper()
            assert {k: v for k, v in player.items() if k != "academic_year"} == identities[player["player_id"]]
    for match in output["matches"]:
        entrants = Authority.FIXTURE_ENTRANTS[Authority.COMPETITION_IDS.index(match["competition_id"])]
        assert {match["team1_id"], match["team2_id"]}.issubset(entrants)
        for field in DETAILS:
            assert match[field]
        for field in ("batter_stats", "pitcher_stats"):
            assert {s["school_id"] for s in match[field]} == {match["team1_id"], match["team2_id"]}
            for stats in match[field]:
                assert identities[stats["player_id"]]["school_id"] == stats["school_id"]
                assert stats["school_id"] in (match["team1_id"], match["team2_id"])
        for team in match["team_stats"]:
            first = team["school_id"] == match["team1_id"]
            assert team["runs"] == match["team1_score" if first else "team2_score"]
            assert sum(s["runs"] for s in match["batter_stats"] if s["school_id"] == team["school_id"]) == team["runs"]
            assert sum(s["hits"] for s in match["batter_stats"] if s["school_id"] == team["school_id"]) == team["hits"]
            assert sum(s["runs_allowed"] for s in match["pitcher_stats"] if s["school_id"] != team["school_id"]) == team["runs"]
            assert sum(s["hits_allowed"] for s in match["pitcher_stats"] if s["school_id"] != team["school_id"]) == team["hits"]
            innings = [s for s in match["inning_scores"] if s["batting_team_id"] == team["school_id"]]
            assert sum(s["runs"] for s in innings if s["was_played"]) == team["runs"]
            assert all(s["runs"] is None for s in innings if not s["was_played"])
    with closing(sqlite3.connect((slot / "historical_matches.sqlite3").as_uri() + "?mode=ro", uri=True)) as con:
        status, count, digest = con.execute("SELECT status,match_count,ledger_sha256 FROM career_years WHERE year=2026").fetchone()
        manifest = [list(r) for r in con.execute("SELECT competition_id,match_id,record_sha256 FROM historical_matches WHERE year=2026 ORDER BY competition_id,match_id")]
        if sealed:
            assert (status, count, digest) == ("sealed", 6, sha(canonical(manifest)))
            assert len(output["outcomes"]) == 2 and len(output["matches"]) == 6
            for outcome in output["outcomes"]:
                games = [m for m in output["matches"] if m["competition_id"] == outcome["competition_id"]]
                sources = [[mid, s] for cid, mid, s in manifest if cid == outcome["competition_id"]]
                assert outcome["source_match_sha256"] == sha(canonical(sources))
                assert outcome["source_year_ledger_sha256"] == digest
                assert outcome["main_match_count"] == len(games) == 3
                entrants = Authority.FIXTURE_ENTRANTS[Authority.COMPETITION_IDS.index(outcome["competition_id"])]
                assert set(outcome["ranked_school_ids"]) == set(entrants)
                assert outcome["ranked_school_ids"][:2] == [outcome["champion_school_id"], outcome["runner_up_school_id"]]
        else:
            assert status == "active" and not output["outcomes"]
    return output


def resume_process(saves, source="manual", finish=False):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=os.pathsep.join((str(ROOT / "tests"), str(ROOT))))
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(saves),
        source, "finish" if finish else "resume"], cwd=ROOT, env=env, capture_output=True, timeout=180)
    if result.returncode:
        raise AssertionError("self-generated fixture child replay failed")
    return json.loads(result.stdout)


if __name__ == "__main__":
    service, resolver, engine = services(Path(sys.argv[1]))
    session = service.load_game(SLOT, source=sys.argv[2], engine=engine)
    if sys.argv[3] == "finish":
        service.advance_through(session, "2026-12-31")
        service.finalize_season(session)
    service.save_game(session)
    service.autosave_game(session)
    slot = service.slots.slot_dir(SLOT)
    sealed = service.career_history_years(SLOT)[0]["status"] == "sealed"
    print(json.dumps({"runtime": actual_runtime(session), "raw": raw_records(slot, sealed)}, ensure_ascii=False))
