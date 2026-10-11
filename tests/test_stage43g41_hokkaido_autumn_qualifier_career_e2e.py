"""Stage43G-41: Hokkaido autumn 10 branch qualifiers -> MAIN, saved/replayed.

2027 entrants and dates are game-only projections. Spring Hokkaido requires
a verified Senbatsu award and must not be substituted by this autumn mode.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import shutil
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_cross_era_navigation import CareerCrossEraNavigator
from phase2_engine.career_history_scale_benchmark import file_sha256
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService, CareerPreviewSaveError,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101141
HOKKAIDO_AUTUMN = "CMP000013"
SHIKOKU_SPRING = "CMP000011"


class Stage43G41HokkaidoAutumnCareerE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.base = tempfile.TemporaryDirectory()
        root = Path(cls.base.name)
        cls.initial_history = root / "historical_matches.sqlite3"
        cls.initial_rosters = root / "career_rosters.sqlite3"
        history = HistoricalMatchArchive(cls.initial_history)
        history.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g41-empty-sealed-sandbox-year",
            completed=[],
        )
        history.seal_year(2026, expected_match_count=0)
        roster_archive = CareerRosterArchive(cls.initial_rosters)
        generator = PlayerRosterGenerator()

        qualifier = cls.repo.stage_by_code(
            HOKKAIDO_AUTUMN, "BRANCH_QUALIFIER",
        )
        cls.groups = cls.repo.groups_by_stage[qualifier["stage_id"]]
        assert len(cls.groups) == 10, "Hokkaido should have ten 2026 branches"
        assert cls.repo.access_rules(HOKKAIDO_AUTUMN) == []
        group_map = {}
        all_hokkaido = []
        cls.slots = {}
        for group in cls.groups:
            gid = group["stage_group_id"]
            quota = cls.repo.param(
                qualifier["stage_id"], "output_slots", gid,
                int(group.get("advance_slots_to_next") or 0),
            )
            assert quota > 0
            eligible = sorted(cls.repo.group_school_ids(group, 2026))
            assert len(eligible) >= quota + 1, (
                gid, "insufficient real 2026 branch master schools", len(eligible), quota
            )
            group_map[gid] = eligible[:quota + 1]
            cls.slots[gid] = quota
            all_hokkaido.extend(group_map[gid])
        assert len(all_hokkaido) == len(set(all_hokkaido))
        assert sum(cls.slots.values()) == 20
        assert all(
            cls.repo.schools[sid]["prefecture_code"] == "01"
            for sid in all_hokkaido
        )
        cls.hokkaido_schools = all_hokkaido

        # The existing multi-event checkpoint requires >=2 competitions.
        # Shikoku is a small independently proven MAIN fixture sharing the
        # same 2027 save; no result from it is treated as a Hokkaido qualifier.
        shikoku = []
        for code in ("36", "37", "38", "39"):
            candidates = sorted(
                sid for sid in cls.repo.school_to_program
                if cls.repo.schools[sid]["prefecture_code"] == code
            )
            assert len(candidates) >= 2
            shikoku.extend(candidates[:2])
        assert len(shikoku) == 8
        cls.specs = [
            {
                "competition_id": HOKKAIDO_AUTUMN,
                "entry_mode": "hokkaido_autumn_fmt001_sandbox_v1",
                "entrant_school_ids": list(all_hokkaido),
                "group_entrant_school_ids": group_map,
            },
            {
                "competition_id": SHIKOKU_SPRING,
                "entry_mode": "non_kanto_regional_main_sandbox_v1",
                "entrant_school_ids": shikoku,
                "group_entrant_school_ids": {},
            },
        ]
        for sid in sorted(set(all_hokkaido + shikoku)):
            roster_archive.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            roster_archive.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.slot = self.root / "hokkaido"
        self.slot.mkdir()
        shutil.copy2(self.initial_history,
                     self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.initial_rosters,
                     self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def _start(self, specs=None):
        return self.service.start(
            "hokkaido", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _history(self):
        return HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def test_ten_branch_to_main_saves_and_replays_without_premature_main(self):
        source_file = self.slot / "manual.json"
        source_file.write_bytes(b"previous manual save must remain unchanged")
        with sqlite3.connect(self.slot / "historical_matches.sqlite3") as db:
            previous_sha = db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]

        session = self._start()
        hokkaido = session.previews[HOKKAIDO_AUTUMN]
        self.assertEqual(10, len(self.groups))
        self.assertFalse(hokkaido.scheduled.is_complete)
        self.assertEqual([], hokkaido.scheduled.processed_dates)
        self.assertEqual(20, sum(self.slots.values()))
        self.assertEqual(
            0,
            len([m for m in hokkaido.scheduled.matches.values()
                 if m.stage_code == "MAIN"]),
        )
        # Shikoku spring progresses first, then the September Hokkaido branch
        # qualifiers. This is one shared year, not a feeder relationship.
        first_day = self.service.play_next_date(session)
        self.assertGreater(first_day["played_match_count"], 0)
        self.assertEqual("2027-04-25", first_day["date"])
        early = self.service.load("hokkaido", year=2027)
        self.assertEqual(
            session.previews[HOKKAIDO_AUTUMN].scheduled.public_snapshot(),
            early.previews[HOKKAIDO_AUTUMN].scheduled.public_snapshot(),
        )
        reached_hokkaido = False
        for _ in range(35):
            if HOKKAIDO_AUTUMN in early.completed_runs():
                break
            step = self.service.play_next_date(early)
            if HOKKAIDO_AUTUMN in step["competition_match_counts"]:
                reached_hokkaido = True
                if step["date"] < "2027-10-07":
                    self.assertFalse(any(
                        x.status == "completed" and x.stage_code == "MAIN"
                        for x in early.previews[HOKKAIDO_AUTUMN].scheduled.matches.values()
                    ))
        self.assertTrue(reached_hokkaido)
        self.assertIn(HOKKAIDO_AUTUMN, early.completed_runs())
        self.assertIn(SHIKOKU_SPRING, early.completed_runs())
        run = early.completed_runs()[HOKKAIDO_AUTUMN]
        self.assertEqual(20, len(run.main_entrant_school_ids))
        self.assertEqual(19, run.outcome.match_count)
        self.assertIn(run.outcome.champion_school_id, self.hokkaido_schools)

        records = self._history().list_matches(2027, limit=500)
        hok_rows = [r for r in records if r["competition_id"] == HOKKAIDO_AUTUMN]
        pre = [r for r in hok_rows if r["stage_code"] == "BRANCH_QUALIFIER"]
        main = [r for r in hok_rows if r["stage_code"] == "MAIN"]
        self.assertGreaterEqual(len(pre), 10)
        self.assertEqual(19, len(main))
        self.assertEqual(7, len([
            r for r in records if r["competition_id"] == SHIKOKU_SPRING
        ]))
        self.assertTrue(all(row["date_source"] == "game_projection_v1"
                            and row["score_source"] == "ability_model_v1"
                            and row["batter_stats"] and row["pitcher_stats"]
                            and row["inning_scores"] and len(row["team_stats"]) == 2
                            for row in hok_rows))
        self.assertTrue(all(row["match_date"] < "2027-10-07" for row in pre))
        self.assertTrue(all(row["match_date"] >= "2027-10-07" for row in main))
        for row in hok_rows:
            self.assertEqual("01", self.repo.schools[
                row["team1_id"]]["prefecture_code"])
            self.assertEqual("01", self.repo.schools[
                row["team2_id"]]["prefecture_code"])

        reloaded = self.service.load("hokkaido", year=2027)
        self.assertEqual(
            run.outcome.champion_school_id,
            reloaded.completed_runs()[HOKKAIDO_AUTUMN].outcome.champion_school_id,
        )
        with sqlite3.connect(self.slot / "historical_matches.sqlite3") as db:
            self.assertEqual(previous_sha, db.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0])
        self.assertEqual([], self._history().list_matches(2026))
        self.assertEqual(b"previous manual save must remain unchanged",
                         source_file.read_bytes())

        # Seal only the two sampled events. The 2027 official full year is
        # NOT considered simulated or certified.
        count = len(records)
        self._history().seal_year(2027, expected_match_count=count)
        before = (
            file_sha256(self.slot / "historical_matches.sqlite3"),
            file_sha256(self.slot / "career_rosters.sqlite3"),
        )
        nav = CareerCrossEraNavigator(self.slot)
        visited = set()
        for row in hok_rows:
            sid = row["team1_id"]
            if sid in visited:
                continue
            visited.add(sid)
            school = nav.school_page(
                [2027], sid, selected_year=2027, verify_source=True,
            )
            target = next(
                t["target"] for t in school["match_detail_targets"]
                if t["competition_id"] == HOKKAIDO_AUTUMN
            )
            detail = nav.follow(target, verify_source=True)
            self.assertEqual("cross_era_match", detail["screen"])
            self.assertTrue(detail["details"]["inning_scores"])
            self.assertTrue(detail["details"]["batter_stats"])
            self.assertTrue(detail["details"]["pitcher_stats"])
            if len(visited) >= 2:
                break
        self.assertEqual(before, (
            file_sha256(self.slot / "historical_matches.sqlite3"),
            file_sha256(self.slot / "career_rosters.sqlite3"),
        ))

    def test_wrong_group_and_spring_reuse_cannot_be_accepted(self):
        # Only CMP000013 can use Hokkaido autumn FMT001 mode.
        spring = [{**x, "entrant_school_ids": list(x["entrant_school_ids"])}
                  for x in self.specs]
        spring[0]["competition_id"] = "CMP000004"
        with self.assertRaisesRegex(CareerPreviewSaveError, "Hokkaido autumn"):
            self._start(spring)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )
        wrong = [{
            **x, "group_entrant_school_ids": {
                k: list(v) for k, v in x["group_entrant_school_ids"].items()
            },
        } for x in self.specs]
        gid = next(iter(wrong[0]["group_entrant_school_ids"]))
        wrong[0]["group_entrant_school_ids"][gid][0] = self.specs[1][
            "entrant_school_ids"
        ][0]
        with self.assertRaises(FutureCompetitionNotReady):
            self._start(wrong)

    def test_unsaved_future_roster_and_invalid_checkpoint_fail_closed(self):
        wrong = [{
            **x, "entrant_school_ids": list(x["entrant_school_ids"]),
            "group_entrant_school_ids": {
                k: list(v) for k, v in x["group_entrant_school_ids"].items()
            },
        } for x in self.specs]
        selected = set(self.hokkaido_schools)
        candidate = next(
            sid for sid in self.repo.school_to_program
            if self.repo.schools[sid]["prefecture_code"] == "01"
            and sid not in selected
        )
        gid = next(iter(wrong[0]["group_entrant_school_ids"]))
        old = wrong[0]["group_entrant_school_ids"][gid][0]
        wrong[0]["group_entrant_school_ids"][gid][0] = candidate
        wrong[0]["entrant_school_ids"].remove(old)
        wrong[0]["entrant_school_ids"].append(candidate)
        with self.assertRaisesRegex(FutureCompetitionNotReady, "roster"):
            self._start(wrong)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )
        self._start()
        checkpoint = self.slot / "career_multi_previews" / "2027.json"
        data = json.loads(checkpoint.read_text(encoding="utf-8"))
        data["processed_dates"].append("2027-01-01")
        checkpoint.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CareerPreviewSaveError):
            self.service.load("hokkaido", year=2027)


if __name__ == "__main__":
    unittest.main()
