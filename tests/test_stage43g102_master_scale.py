"""Real service 33-school persistence, independent SQL oracle and crash boundaries."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.career_history_browse_model import CareerHistoryBrowseModel
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import Yamanashi33FixturePersistence as Authority
from phase2_engine.year_transition import YearTransitionBlockedError
from stage43g97_acceptance_support import actual_runtime, pin, KEYS, DETAILS
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read
from stage43g102_fixture_support import (
    services, raw_records, resume_process, canonical, sha, ROOT, SLOT, SEED,
    MEASUREMENTS,
)


class Stage43G102MasterScaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix="stage102-generated-"))
        self.saves = Path(self.temp).resolve() / "保存 日本語"
        self.slot = self.saves / SLOT
        self.service, self.resolver, self.engine = services(self.saves)

    def new(self, initial=True):
        return self.service.new_game(SLOT, rng_seed=SEED, engine=self.engine,
            start_date="2026-07-01", save_initial=initial)

    def partial(self):
        session = self.new()
        self.assertEqual(17, self.service.advance_through(session, "2026-07-06")["played_match_count"])
        self.service.save_game(session)
        return session

    def finish(self):
        session = self.partial()
        self.assertEqual(15, self.service.advance_through(session, "2026-12-31")["played_match_count"])
        self.service.finalize_season(session)
        self.service.autosave_game(session)
        return session

    def db_pin(self):
        return {k: v for k, v in pin(self.slot).items() if k.endswith(".sqlite3")}

    def test_first_manual_both_sources_process_replay_33schools_full_a_and_idempotence(self):
        with retained_handles() as handles:
            start = perf_counter()
            session = self.new()
            MEASUREMENTS["initial33_generation_manual_seconds"] = round(perf_counter()-start, 3)
            # All 33 authorities are pinned before any match/cache entry exists.
            self.assertEqual(0, self.resolver.cache_size)
            first = raw_records(self.slot, sealed=False)
            self.assertEqual([], first["matches"])
            source = [r.to_dict() for r in self.resolver.initial_roster_snapshot(
                reference_year=2026, generation_seed=Authority.ROSTER_SEED,
                school_ids=Authority.SCHOOL_IDS)]
            self.assertEqual(source, first["rosters"])
            start = perf_counter()
            self.service.advance_through(session, "2026-07-06")
            MEASUREMENTS["first17_progress_autosave_seconds"] = round(perf_counter()-start, 3)
            expected_partial = actual_runtime(session)
            self.service.save_game(session)
            self.service.autosave_game(session)
            snapshot = self.db_pin()
            assert_closed(self, handles)
            rename_and_read(self, self.slot)
        for choice in ("manual", "autosave"):
            result = resume_process(self.saves, choice)
            self.assertEqual(expected_partial, result["runtime"])
            self.assertEqual(first["identities"], result["raw"]["identities"])
            self.assertEqual(snapshot, self.db_pin())
        service, resolver, engine = services(self.saves)
        session = service.load_game(SLOT, source="manual", engine=engine)
        resolver.clear_cache()
        start = perf_counter()
        self.assertEqual(15, service.advance_through(session, "2026-12-31")["played_match_count"])
        MEASUREMENTS["remaining15_progress_autosave_seconds"] = round(perf_counter()-start, 3)
        expected = actual_runtime(session)
        start = perf_counter()
        result = service.finalize_season(session)
        MEASUREMENTS["year_seal_outcome_seconds"] = round(perf_counter()-start, 3)
        self.assertEqual(1, result["year_end_readiness"]["competition_count"])
        self.assertEqual(32, result["year_end_readiness"]["completed_match_count"])
        self.assertFalse(result["next_year_gameplay_started"])
        service.autosave_game(session)
        raw = raw_records(self.slot)
        MEASUREMENTS["final_save_bytes"] = sum(p.stat().st_size for p in self.slot.rglob("*") if p.is_file())
        self.assertEqual(raw["outcomes"][0], Authority.sealed_results(self.slot))
        self.assertEqual(expected, [{k: r[k] for k in KEYS + DETAILS} for r in raw["matches"]])
        self.assertEqual(first["rosters"], raw["rosters"])
        self.assertEqual(first["identities"], raw["identities"])
        for outcome in raw["outcomes"]:
            ranking = session.state.completed_runs()[outcome["competition_id"]].outcome.final_ranking_school_ids
            self.assertEqual(list(ranking), outcome["ranked_school_ids"])
        snapshot = self.db_pin()
        for choice in ("manual", "autosave"):
            for _ in range(2):
                result = resume_process(self.saves, choice)
                self.assertEqual(raw, result["raw"])
                self.assertEqual(expected, result["runtime"])
                self.assertEqual(snapshot, self.db_pin())

    def test_scope_plan_school_year_seed_contract_provider_cache_and_runtime_refused(self):
        plan = self.service._planner(SEED).build_plan()
        cases = (
            replace(plan, year=2027), replace(plan, rng_seed=SEED + 1),
            replace(plan, dependency_edges=[("CMP000105", "CMP000041")]),
            replace(plan, annual_templates={k: replace(v, entrant_school_ids=v.entrant_school_ids[:-1])
                for k, v in plan.annual_templates.items()}),
            replace(plan, entries={k: replace(v, has_pre_main=True) for k, v in plan.entries.items()}),
            replace(plan, annual_build_strategies={k: "deferred_structural" for k in plan.entries}),
            replace(plan, calendar_rows=[{**r, "game_date_list": "2026-04-11;2026-07-06"}
                for r in plan.calendar_rows]),
        )
        for changed in cases:
            with self.assertRaises(ValueError):
                Authority(changed, self.resolver)
        for year, seed in ((2027, SEED), (2026, SEED + 1)):
            with self.assertRaises(ValueError):
                self.service._planner(seed, year=year)
        with self.assertRaises(ValueError):
            self.service.career_persistence.prepare(plan, self.engine, "initial_ability_career_v1")
        self.resolver.roster_provider = lambda *args: None
        with self.assertRaises(ValueError):
            self.new()
        self.resolver.roster_provider = None
        original_name_provider = self.resolver.roster_generator.name_provider
        self.resolver.roster_generator.name_provider = lambda *args: ("検証名", "placeholder_v1")
        with self.assertRaises(ValueError):
            self.new()
        self.resolver.roster_generator.name_provider = original_name_provider
        self.resolver.team_input(school_id=Authority.SCHOOL_IDS[0], reference_year=2026,
            generation_seed=Authority.ROSTER_SEED)
        with self.assertRaises(ValueError):
            self.new()
        self.assertFalse(self.slot.exists())
        self.service, self.resolver, self.engine = services(self.saves)
        session = self.new()
        before = pin(self.slot)
        session.state.annual_templates["CMP000041"].entrant_school_ids.pop()
        with self.assertRaises(ValueError):
            self.service.save_game(session)
        self.assertEqual(before, pin(self.slot))

    def test_input_version_memory_master_ability_config_and_unknown_provider_refused(self):
        plan = self.service._planner(SEED).build_plan()
        sid = Authority.SCHOOL_IDS[0]
        old = self.resolver.repo.schools[sid]["display_name"]
        self.resolver.repo.schools[sid]["display_name"] = "未確認校名"
        with self.assertRaises(ValueError):
            self.new()
        self.resolver.repo.schools[sid]["display_name"] = old
        self.resolver.simulator.params["unreviewed"] = True
        with self.assertRaises(ValueError):
            self.new()
        del self.resolver.simulator.params["unreviewed"]
        baseline = self.resolver.simulator
        self.resolver.simulator = object()
        with self.assertRaises(ValueError):
            self.new()
        self.resolver.simulator = baseline
        with tempfile.TemporaryDirectory(prefix="stage102-version-") as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "config", root / "config")
            source = root / "data/competitions/competitions.csv"
            source.write_bytes(source.read_bytes() + b"\n")
            changed = replace(plan, data_dir=root / "data")
            with self.assertRaises(ValueError):
                Authority(changed, self.resolver)
        self.assertFalse(self.slot.exists())

    def test_different_checkpoint_conflicts_with_history_before_json_write(self):
        session = self.partial()
        before = pin(self.slot)
        # A changed in-memory match-date checkpoint must not replace immutable
        # earlier history, even when its date/seed/entrant plan is unchanged.
        match = next(iter(session.state.competitions[Authority.COMPETITION_ID].matches.values()))
        match.match_date = date(2026, 7, 6)
        with self.assertRaises(ValueError):
            self.service.save_game(session)
        self.assertEqual(before, pin(self.slot))

    def test_pinned_source_id_grade_entry_membership_and_recipe_changes_refused(self):
        session = self.new()
        original = deepcopy(self.resolver._initial_roster_source)
        before = pin(self.slot)
        sid = Authority.SCHOOL_IDS[0]
        changes = {
            "player_id": "same_name_different_id",
            "academic_year": original[sid].players[0].academic_year % 3 + 1,
            "entry_year": 1900, "school_id": "SCH001862",
            "program_id": "unknown", "generation_seed": 7,
        }
        for key, value in changes.items():
            self.resolver._initial_roster_source = deepcopy(original)
            roster = self.resolver._initial_roster_source[sid]
            roster.players[0] = replace(roster.players[0], **{key: value})
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.service.save_game(session)
            self.assertEqual(before, pin(self.slot))
        self.resolver._initial_roster_source = deepcopy(original)
        del self.resolver._initial_roster_source[sid]
        with self.assertRaises(ValueError):
            self.service.save_game(session)
        self.assertEqual(before, pin(self.slot))

    def test_incomplete_33school_bracket_blocks_seal_and_outcome(self):
        session = self.partial()
        session.state.current_date = date(2026, 12, 31)
        status = self.service.year_end_status(session)
        self.assertEqual(1, status["competition_count"])
        self.assertEqual(["CMP000041"], status["unfinished_competition_ids"])
        self.assertFalse(status["eligible_to_seal"])
        before = pin(self.slot)
        with patch.object(HistoricalMatchArchive, "seal_year", side_effect=AssertionError("no seal")):
            with self.assertRaises(YearTransitionBlockedError):
                self.service.finalize_season(session)
            with self.assertRaises(ValueError):
                self.service.career_persistence.sync_outcomes(session, self.slot)
        self.assertEqual(before, pin(self.slot))
        self.assertEqual([], raw_records(self.slot, sealed=False)["outcomes"])

    def test_option_a_each_tournament_missing_changed_player_seed_stats_and_stage_refused(self):
        session = self.finish()
        before = pin(self.slot)
        for competition in session.state.competitions.values():
            match = next(iter(competition.matches.values()))
            original = deepcopy(match.ability_detail)
            for case in ("inning", "batter", "pitcher", "id", "school", "seed", "match_seed", "stats"):
                match.ability_detail = deepcopy(original)
                detail = match.ability_detail
                if case in ("inning", "batter", "pitcher"):
                    detail[{"inning": "inning_scores", "batter": "batter_stats", "pitcher": "pitcher_stats"}[case]] = None
                elif case == "id":
                    detail["batter_stats"][0]["player_id"] = "invented"
                elif case == "school":
                    detail["batter_stats"][0]["school_id"] = "SCH001862"
                elif case == "seed":
                    detail["team_generation_seed"] += 1
                elif case == "match_seed":
                    detail["generation_seed"] += 1
                else:
                    detail["batter_stats"][0]["plate_appearances"] += 1
                with self.subTest(cid=competition.competition_id, case=case), self.assertRaises(ValueError):
                    self.service.autosave_game(session)
                self.assertEqual(before, pin(self.slot))
            match.ability_detail = original
            match.stage_code = "QUALIFIER"
            with self.assertRaises(ValueError):
                self.service.save_game(session)
            match.stage_code = "MAIN"
        self.assertEqual(before, pin(self.slot))

    def test_json_and_first_last_roster_commit_interruptions_process_retry_and_close(self):
        for boundary in ("json", "first_roster", "last_roster"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(prefix="stage102-crash-") as temp:
                root = Path(temp).resolve() / "saves"
                service, resolver, engine = services(root)
                session = service.new_game(SLOT, rng_seed=SEED, engine=engine,
                    start_date="2026-07-01", save_initial=False)
                if boundary == "json":
                    target, method = service.slots, "save"
                    original = target.save
                    def interrupted(*args, **kwargs):
                        original(*args, **kwargs)
                        raise OSError("after JSON checkpoint")
                    auto = False
                else:
                    target, method = CareerRosterArchive, "save_initial_roster"
                    original = CareerRosterArchive.save_initial_roster
                    counter = [0]
                    def interrupted(archive, roster):
                        result = original(archive, roster)
                        counter[0] += 1
                        if counter[0] == (1 if boundary == "first_roster" else 33):
                            raise OSError("after school commit")
                        return result
                    auto = True
                errors = []
                with retained_handles() as handles:
                    with patch.object(target, method, side_effect=interrupted, autospec=auto):
                        try:
                            service.save_game(session)
                        except OSError as error:
                            errors.append(error)  # Keep traceback and handles alive.
                    self.assertEqual(1, len(errors))
                    if handles:
                        assert_closed(self, handles)
                        rename_and_read(self, root / SLOT)
                child = resume_process(root)
                self.assertEqual([], child["runtime"])
                self.assertEqual((33, 660), (len(child["raw"]["rosters"]), len(child["raw"]["identities"])))

    def test_partial_archive_commit_failure_retries_same_json_without_duplicate_rows(self):
        session = self.new()
        self.service.advance_through(session, "2026-12-31", autosave=False)
        expected = actual_runtime(session)
        original = HistoricalMatchArchive.sync
        def interrupted(archive, **kwargs):
            all_games = list(kwargs.pop("completed"))
            original(archive, **kwargs, completed=all_games[:17])
            raise OSError("after first tournament match commit")
        errors = []
        with retained_handles() as handles:
            with patch.object(HistoricalMatchArchive, "sync", side_effect=interrupted, autospec=True):
                try:
                    self.service.save_game(session)
                except OSError as error:
                    errors.append(error)
            self.assertEqual(1, len(errors))
            assert_closed(self, handles)
            rename_and_read(self, self.slot)
            with closing(sqlite3.connect(self.slot / "historical_matches.sqlite3")) as conn:
                self.assertEqual((17,), conn.execute("SELECT count(*) FROM historical_matches").fetchone())
        result = resume_process(self.saves, finish=True)
        self.assertEqual(expected, result["runtime"])
        self.assertEqual(32, len(result["raw"]["matches"]))

    def test_seal_before_after_and_outcome_commit_failure_process_retry(self):
        for boundary in ("before_seal", "after_seal", "one_outcome"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(prefix="stage102-seal-") as temp:
                root = Path(temp).resolve() / "saves"
                service, resolver, engine = services(root)
                session = service.new_game(SLOT, rng_seed=SEED, engine=engine, start_date="2026-07-01")
                service.advance_through(session, "2026-12-31", autosave=False)
                expected = actual_runtime(session)
                counter = [0]
                if "seal" in boundary:
                    target, method = HistoricalMatchArchive, "seal_year"
                    original = target.seal_year
                    def interrupted(archive, *args, **kwargs):
                        if boundary == "after_seal":
                            original(archive, *args, **kwargs)
                        raise OSError("seal boundary")
                else:
                    target, method = CareerCompetitionOutcomes, "record_completed"
                    original = target.record_completed
                    def interrupted(writer, run):
                        result = original(writer, run)
                        counter[0] += 1
                        if counter[0] == (1 if boundary == "one_outcome" else 2):
                            raise OSError("outcome boundary")
                        return result
                errors = []
                with retained_handles() as handles:
                    with patch.object(target, method, side_effect=interrupted, autospec=True):
                        try:
                            service.finalize_season(session)
                        except OSError as error:
                            errors.append(error)
                    self.assertEqual(1, len(errors))
                    assert_closed(self, handles)
                    rename_and_read(self, root / SLOT)
                    with closing(sqlite3.connect(root / SLOT / "historical_matches.sqlite3")) as conn:
                        self.assertEqual("active" if boundary == "before_seal" else "sealed",
                            conn.execute("SELECT status FROM career_years").fetchone()[0])
                        if "outcome" in boundary:
                            self.assertEqual(1 if boundary == "one_outcome" else 2,
                                conn.execute("SELECT count(*) FROM historical_competition_outcomes").fetchone()[0])
                result = resume_process(root, finish=True)
                self.assertEqual(expected, result["runtime"])
                self.assertEqual((33, 660, 32, 1), tuple(len(result["raw"][k]) for k in
                    ("rosters", "identities", "matches", "outcomes")))

    def test_stale_save_corrupt_identity_sql_match_ledger_and_outcome_refused_before_writes(self):
        session = self.partial()
        self.service.advance_through(session, "2026-12-31")
        before = pin(self.slot)
        service, resolver, engine = services(self.saves)
        with self.assertRaises(ValueError):
            service.load_game(SLOT, source="manual", engine=engine)
        self.assertEqual(before, pin(self.slot))
        self.service.finalize_season(session)
        original = {p.name: p.read_bytes() for p in self.slot.glob("*.sqlite3")}
        for case in ("identity", "sql_match", "ledger", "outcome"):
            for name, data in original.items():
                (self.slot / name).write_bytes(data)  # Only a disposable fixture.
            path = self.slot / ("career_rosters.sqlite3" if case == "identity" else "historical_matches.sqlite3")
            with closing(sqlite3.connect(path)) as conn:
                if case == "identity":
                    conn.execute("UPDATE career_player_identities SET school_id='unknown'")
                elif case == "sql_match":
                    conn.execute("UPDATE historical_matches SET competition_id='unknown'")
                elif case == "ledger":
                    conn.execute("UPDATE career_years SET ledger_sha256='changed'")
                else:
                    cid, raw = conn.execute("SELECT competition_id,payload_json FROM historical_competition_outcomes LIMIT 1").fetchone()
                    result = json.loads(raw)
                    result["ranked_school_ids"].reverse()
                    raw = canonical(result)
                    conn.execute("UPDATE historical_competition_outcomes SET payload_json=?,record_sha256=? WHERE competition_id=?",
                        (raw, sha(raw), cid))
                conn.commit()
            before = pin(self.slot)
            errors = []
            with retained_handles() as handles:
                try:
                    self.service.save_game(session)
                except ValueError as error:
                    errors.append(error)
                self.assertEqual(1, len(errors))
                assert_closed(self, handles)
                rename_and_read(self, self.slot)
            self.assertEqual(before, pin(self.slot))

    def test_readonly_all33schools_all660players_totals_sql_oracle_bytes_unchanged(self):
        self.finish()
        raw = raw_records(self.slot)
        before = pin(self.slot)
        with retained_handles() as handles:
            start = perf_counter()
            model = CareerHistoryBrowseModel(ROOT / "data", self.slot)
            for sid in Authority.SCHOOL_IDS:
                expected = []
                for cid in sorted(Authority.COMPETITION_IDS):
                    games = [g for g in raw["matches"] if sid in (g["team1_id"], g["team2_id"]) and g["competition_id"] == cid]
                    scores = [(g["team1_score"], g["team2_score"]) if g["team1_id"] == sid
                        else (g["team2_score"], g["team1_score"]) for g in games]
                    expected.append(dict(year=2026, competition_id=cid, games=len(games),
                        wins=sum(a > b for a, b in scores), losses=sum(a < b for a, b in scores),
                        runs_for=sum(a for a, b in scores), runs_against=sum(b for a, b in scores),
                        historical_record_source="archived_game_scores"))
                self.assertEqual(expected, model.school_page(2026, sid)["year_results"]["records"])
                players = [r for r in raw["identities"] if r["school_id"] == sid]
                for player in players:
                    page = model.player_page(2026, player["player_id"])
                    self.assertEqual(1, len(page["membership"]))
                    for kind, field in (("batting", "batter_stats"), ("pitching", "pitcher_stats")):
                        rows = [s for g in raw["matches"] for s in g[field] if s["player_id"] == player["player_id"]]
                        totals = page["career_stats"][kind]
                        self.assertEqual(len(rows), totals["games"])
                        for stat in (rows[0] if rows else {}):
                            if stat not in ("player_id", "school_id", "singles"):
                                self.assertEqual(sum(s[stat] for s in rows), totals[stat])
            assert_closed(self, handles)
            rename_and_read(self, self.slot)
            MEASUREMENTS["all33schools_660players_history_seconds"] = round(perf_counter()-start, 3)
        self.assertEqual(before, pin(self.slot))


if __name__ == "__main__":
    unittest.main()
