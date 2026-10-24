"""Stage43G-40: five non-Kanto spring regional saved-match E2Es in one year.

2027 is game-projected. Entrants are arbitrary 2026 master-school IDs for
smoke tests, never claimed actual prefectural qualifiers or official draws.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
import shutil
import tempfile
import unittest

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_multi_preview_checkpoint import (
    CareerMultiPreviewCheckpointService,
)
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_competition_bridge import FutureCompetitionNotReady
from phase2_engine.future_non_kanto_regional_main_bridge import (
    NON_KANTO_REGIONAL_MAIN_IDS,
)
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 2026101140
# IDs/region membership are the verified 2026 structure, NOT persistent
# future-year competition quotas or automatic prefectural qualifications.
REGIONS_2026 = {
    "CMP000005": (("02", "03", "04", "05", "06", "07"), 14),  # Tohoku
    "CMP000007": (("15", "16", "17", "18", "20"), 8),  # Hokushinetsu
    "CMP000009": (("25", "26", "27", "28", "29", "30"), 8),  # Kinki
    "CMP000010": (("31", "32", "33", "34", "35"), 8),  # Chugoku
    "CMP000012": (("40", "41", "42", "43", "44", "45", "46", "47"), 16),  # Kyushu
}
MATCH_COUNT = sum(n - 1 for _, n in REGIONS_2026.values())


class Stage43G40FiveRegionCareerE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.base = tempfile.TemporaryDirectory()
        cls.master_history = Path(cls.base.name) / "historical_matches.sqlite3"
        cls.master_rosters = Path(cls.base.name) / "career_rosters.sqlite3"
        hist = HistoricalMatchArchive(cls.master_history)
        hist.sync(
            year=2026, rng_seed=SEED, resolver_contract="game_v1",
            plan_fingerprint="stage43g40-empty-sealed-prior-sandbox",
            completed=[],
        )
        hist.seal_year(2026, expected_match_count=0)
        rosters = CareerRosterArchive(cls.master_rosters)
        generator = PlayerRosterGenerator()

        cls.specs = []
        cls.entrants = {}
        all_ids = set()
        for cid, (prefectures, expected_count) in REGIONS_2026.items():
            assert cid in NON_KANTO_REGIONAL_MAIN_IDS
            stages = cls.repo.stages(cid)
            assert len(stages) == 1 and stages[0]["stage_code"] == "MAIN"
            assert int(stages[0]["team_count"]) == expected_count
            buckets = []
            for pref in prefectures:
                available = sorted(
                    sid for sid in cls.repo.school_to_program
                    if cls.repo.schools[sid]["prefecture_code"] == pref
                )
                assert len(available) >= 3, (cid, pref)
                buckets.append(available)
            # Fair, deterministic spread. At least one school per prefecture.
            chosen = []
            ix = 0
            while len(chosen) < expected_count:
                for bucket in buckets:
                    if len(chosen) == expected_count:
                        break
                    chosen.append(bucket[ix])
                ix += 1
            assert len(chosen) == len(set(chosen)) == expected_count
            assert not all_ids.intersection(chosen)
            all_ids.update(chosen)
            cls.entrants[cid] = chosen
            cls.specs.append({
                "competition_id": cid,
                "entry_mode": "non_kanto_regional_main_sandbox_v1",
                "entrant_school_ids": chosen,
                "group_entrant_school_ids": {},
            })
        assert len(all_ids) == 54
        for sid in sorted(all_ids):
            rosters.save_initial_roster(
                generator.generate_for_school_id(cls.repo, sid, 2026, SEED)
            )
            rosters.advance_and_save(
                cls.repo.team(sid), next_year=2027, career_seed=SEED,
            )

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.slot = self.root / "national_sample"
        self.slot.mkdir()
        shutil.copy2(self.master_history,
                     self.slot / "historical_matches.sqlite3")
        shutil.copy2(self.master_rosters,
                     self.slot / "career_rosters.sqlite3")
        self.service = CareerMultiPreviewCheckpointService(
            self.repo, DATA, save_root=self.root,
            ability_config_dir=ROOT / "config" / "abilities",
            match_config_dir=ROOT / "config" / "match",
        )

    def _start(self, specs=None):
        return self.service.start(
            "national_sample", year=2027,
            competitions=self.specs if specs is None else specs,
            base_seed=SEED, career_seed=SEED,
        )

    def _history(self):
        return HistoricalMatchArchive(self.slot / "historical_matches.sqlite3")

    def test_five_regions_share_2027_save_replay_final_and_readonly_details(self):
        legacy = self.slot / "manual.json"
        legacy.write_bytes(b"unchanged original manual 2026 save")
        with sqlite3.connect(self.slot / "historical_matches.sqlite3") as conn:
            old_ledger = conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
        started = self._start()
        self.assertEqual(5, started.summary()["competition_count"])
        self.assertFalse(started.summary()["competition_advancement_automatic"])
        self.assertFalse(started.summary()["full_year_gameplay"])
        self.assertFalse(started.summary()["official_future_calendar"])
        first = self.service.play_next_date(started)
        self.assertGreater(first["played_match_count"], 0)
        first_date = first["date"]
        snapshot_before = {
            cid: preview.scheduled.public_snapshot()
            for cid, preview in started.previews.items()
        }
        resumed = self.service.load("national_sample", year=2027)
        self.assertEqual(
            snapshot_before, {
                cid: preview.scheduled.public_snapshot()
                for cid, preview in resumed.previews.items()
            },
        )
        self.assertEqual([first_date], resumed.processed_dates)

        for _ in range(30):
            if len(resumed.completed_runs()) == len(REGIONS_2026):
                break
            self.service.play_next_date(resumed)
        completed = resumed.completed_runs()
        self.assertEqual(sorted(REGIONS_2026), sorted(completed))
        self.assertEqual(MATCH_COUNT, resumed.summary()["completed_match_count"])
        self.assertEqual(49, MATCH_COUNT)
        history = self._history()
        records = history.list_matches(2027, limit=500)
        self.assertEqual(MATCH_COUNT, len(records))
        self.assertEqual(MATCH_COUNT, len({
            (r["year"], r["competition_id"], r["match_id"]) for r in records
        }))
        for cid, run in completed.items():
            with self.subTest(cid=cid):
                self.assertEqual(len(self.entrants[cid]),
                                 len(run.main_entrant_school_ids))
                self.assertEqual(len(self.entrants[cid]) - 1,
                                 run.outcome.match_count)
                self.assertIn(run.outcome.champion_school_id,
                              self.entrants[cid])
        for record in records:
            self.assertEqual("game_projection_v1", record["date_source"])
            self.assertEqual("ability_model_v1", record["score_source"])
            self.assertTrue(record["inning_scores"])
            self.assertEqual(2, len(record["team_stats"]))
            self.assertTrue(record["batter_stats"])
            self.assertTrue(record["pitcher_stats"])
            self.assertIn(record["team1_id"],
                          self.entrants[record["competition_id"]])
            self.assertIn(record["team2_id"],
                          self.entrants[record["competition_id"]])
        reloaded = self.service.load("national_sample", year=2027)
        self.assertEqual(
            {cid: run.outcome.champion_school_id for cid, run in completed.items()},
            {cid: run.outcome.champion_school_id
             for cid, run in reloaded.completed_runs().items()},
        )
        with sqlite3.connect(self.slot / "historical_matches.sqlite3") as conn:
            after_ledger = conn.execute(
                "SELECT ledger_sha256 FROM career_years WHERE year=2026"
            ).fetchone()[0]
        self.assertEqual(old_ledger, after_ledger)
        self.assertEqual([], history.list_matches(2026))
        self.assertEqual(b"unchanged original manual 2026 save",
                         legacy.read_bytes())

        # Seal the *five sampled events only*; do not claim a nationwide
        # 2027 annual season or automatically award prefectural qualifiers.
        history.seal_year(2027, expected_match_count=MATCH_COUNT)

    def test_incorrect_count_or_foreign_region_and_unsaved_roster_rejected(self):
        bad = [{**spec, "entrant_school_ids": list(spec["entrant_school_ids"])}
               for spec in self.specs]
        bad[0]["entrant_school_ids"][-1] = self.entrants["CMP000012"][0]
        with self.assertRaisesRegex(FutureCompetitionNotReady, "region"):
            self._start(bad)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )

        bad = [{**spec, "entrant_school_ids": list(spec["entrant_school_ids"])}
               for spec in self.specs]
        bad[0]["entrant_school_ids"].pop()
        with self.assertRaisesRegex(FutureCompetitionNotReady, "exactly"):
            self._start(bad)

        bad = [{**spec, "entrant_school_ids": list(spec["entrant_school_ids"])}
               for spec in self.specs]
        first = self.entrants["CMP000005"][0]
        pref = self.repo.schools[first]["prefecture_code"]
        substitute = next(
            sid for sid in self.repo.school_to_program
            if self.repo.schools[sid]["prefecture_code"] == pref
            and sid not in self.entrants["CMP000005"]
        )
        bad[0]["entrant_school_ids"][0] = substitute
        with self.assertRaisesRegex(FutureCompetitionNotReady, "roster"):
            self._start(bad)
        self.assertFalse(
            (self.slot / "career_multi_previews" / "2027.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
