"""Stage92 actual live save/load/finalize with unchanged roster/v2 sidecars."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from game_core.players import PlayerRosterGenerator
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_v2_national_storage_audit import synthetic_storage_fixture
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_season_planner import LiveSeasonGraphPlan, LiveSeasonGraphPlanner
from phase2_engine.repository import DataRepository
from phase2_engine.save_inventory_audit import inventory_slot
from stage43g91_fixture_support import closed_archive_connection
from stage43g92_fixture_support import oracle, snapshot
from test_stage43g91_save_inventory import StaticPlanner, private_anchor

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026101201


class Stage43G92LegacyReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(ROOT / 'data')
        full = LiveSeasonGraphPlanner(cls.repo, ROOT / 'data', SEED, year=2026).build_plan()
        keep = ['CMP000029', 'CMP000077']
        cls.plan = LiveSeasonGraphPlan(
            repo=full.repo, data_dir=full.data_dir, year=full.year, rng_seed=full.rng_seed,
            entries={k: full.entries[k] for k in keep},
            annual_templates={k: full.annual_templates[k] for k in keep},
            annual_build_strategies={k: full.annual_build_strategies[k] for k in keep},
            calendar_rows=[r for r in full.calendar_rows if r['competition_id'] in keep],
            stage_calendar_rows=full.stage_calendar_rows,
            dependency_edges=[tuple(keep)], topological_order=keep)

    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix='stage92-live-only-'))
        self.root = Path(self.temp)
        self.service = LiveGameService(self.repo, ROOT / 'data', save_root=self.root,
            planner_factory=lambda *args: StaticPlanner(self.plan))
        self.session = self.service.new_game('fixture92', rng_seed=SEED, start_date='2026-07-01')
        self.slot = self.root / 'fixture92'
        self.archive = HistoricalMatchArchive(self.slot / 'historical_matches.sqlite3')

    def test_manual_autosave_replay_finalize_and_sealed_load_preserve_all_sources(self):
        # Both roster and v2 are independently created temporary originals.
        sid = sorted(self.repo.school_to_program)[0]
        rosters = CareerRosterArchive(self.slot / 'career_rosters.sqlite3')
        with patch.object(CareerRosterArchive, '_connect', closed_archive_connection):
            rosters.save_initial_roster(PlayerRosterGenerator().generate_for_school_id(
                self.repo, sid, 2026, SEED))
        with synthetic_storage_fixture(ROOT / 'data', schools=2, years=2,
                                       rounds=1, first_year=10099, seed=SEED) as fixture:
            for source in (fixture.source, fixture.calendar):
                shutil.copy2(source, self.slot / source.name)
        sidecars = {p.name: p.read_bytes() for p in self.slot.glob('*.sqlite3')
                    if p != self.archive.db_path}
        self.service.advance_through(self.session, '2026-07-12')
        first = self.service.load_game('fixture92', source='autosave')
        second = self.service.load_game('fixture92', source='autosave')
        self.assertEqual(first.state.public_snapshot(), second.state.public_snapshot())
        before = snapshot(self.archive)
        self.service.load_game('fixture92', source='manual')
        self.assertEqual(before, snapshot(self.archive))
        self.service.save_game(self.session, kind='manual')
        self.service.advance_through(self.session, '2026-12-31')
        finalized = self.service.finalize_season(self.session)
        self.assertTrue(finalized['archive_sealed'])
        self.assertFalse(finalized['next_year_gameplay_started'])
        rows, years = oracle(self, self.archive)
        self.assertGreater(len(rows), 0)
        self.assertEqual('sealed', years[0][1])
        anchor = private_anchor(self.slot)
        for source in ('manual', 'autosave', 'manual_backup_001'):
            self.service.load_game('fixture92', source=source)
            self.assertEqual((rows, years), oracle(self, self.archive))
            self.assertEqual(anchor, private_anchor(self.slot))
        for name, raw in sidecars.items():
            self.assertEqual(raw, (self.slot / name).read_bytes())
        result = inventory_slot(self.slot, slot_id='fixture92', contract='legacy_live',
                                source='manual', authorized_read=True, expected_files=anchor)
        self.assertTrue(result['contract_consistent'], result['blockers'])
        self.assertTrue(result['input_bytes_unchanged'])
        self.assertTrue(all(row['year'] == 2026 for row in self.archive.list_matches(2026)))
