"""Self-generated real legacy service saves, never external save inputs."""
import atexit
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.engine import TournamentEngine
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_season_planner import LiveSeasonGraphPlan
from stage43g91_fixture_support import closed_archive_connection
from test_stage43g91_save_inventory import StaticPlanner
from test_stage43g92_legacy_replay import Stage43G92LegacyReplayTests, ROOT, SEED

METRICS = []


class Fixture:
    templates = {}

    def __init__(self, phase='active'):
        self.temp = tempfile.TemporaryDirectory(prefix='stage94-owned-')
        self.root = Path(self.temp.name).resolve()
        self.save_root = self.root / 'saves'
        self.slot = self.save_root / 'owned94'
        self.destination = self.root / 'backup'
        self.phase = phase
        try:
            if phase not in self.templates:
                self._generate()
                template = tempfile.TemporaryDirectory(prefix='stage94-generated-template-')
                atexit.register(template.cleanup)
                shutil.copytree(self.save_root, Path(template.name) / 'saves')
                self.templates[phase] = template
            else:
                shutil.copytree(Path(self.templates[phase].name) / 'saves', self.save_root)
        except BaseException:
            self.close()
            raise

    def _generate(self):
        if not hasattr(Stage43G92LegacyReplayTests, 'plan'):
            Stage43G92LegacyReplayTests.setUpClass()
        base = Stage43G92LegacyReplayTests
        cid = 'CMP000029'
        plan = LiveSeasonGraphPlan(repo=base.repo, data_dir=ROOT/'data', year=2026, rng_seed=SEED,
            entries={cid: base.plan.entries[cid]}, annual_templates={cid: replace(
                base.plan.annual_templates[cid], entrant_school_ids=base.plan.annual_templates[cid].entrant_school_ids[:8])},
            annual_build_strategies={cid: base.plan.annual_build_strategies[cid]},
            calendar_rows=[r for r in base.plan.calendar_rows if r['competition_id'] == cid],
            stage_calendar_rows=base.plan.stage_calendar_rows, topological_order=[cid])
        service = LiveGameService(base.repo, ROOT/'data', save_root=self.save_root,
                                  planner_factory=lambda *args: StaticPlanner(plan))
        resolver = AbilityMatchResolver(base.repo, ability_config_dir=ROOT/'config'/'abilities',
                                        match_config_dir=ROOT/'config'/'match', team_generation_seed=SEED)
        engine = TournamentEngine(base.repo, main_match_resolver=resolver, pre_main_match_resolver=resolver)
        with patch.object(HistoricalMatchArchive, '_connect', closed_archive_connection), \
             patch.object(CareerRosterArchive, '_connect', closed_archive_connection):
            session = service.new_game('owned94', rng_seed=SEED, start_date='2026-07-01', engine=engine)
            service.advance_through(session, '2026-07-12')
            service.save_game(session, kind='manual')
            if self.phase != 'active':
                service.advance_through(session, '2026-12-31')
                service.finalize_season(session)
                outcomes = CareerCompetitionOutcomes(self.slot/'historical_matches.sqlite3')
                for run in session.state.completed_runs().values():
                    outcomes.record_completed(run)
                service.save_game(session, kind='manual')
                service.save_game(session, kind='autosave')
            if self.phase == 'registered':
                HistoricalMatchArchive(self.slot/'historical_matches.sqlite3').register_next_year(
                    year=2027, rng_seed=SEED, resolver_contract=session.resolver_contract,
                    plan_fingerprint='stage94-registration-only-not-replay')
            archive = CareerRosterArchive(self.slot/'career_rosters.sqlite3')
            for roster in resolver._roster_cache.values():
                archive.save_initial_roster(roster)

    def args(self, **changes):
        args = dict(save_root=self.save_root, slot_id='owned94', source='manual',
                    destination=self.destination, confirm_game_stopped=True)
        args.update(changes)
        return args

    def close(self):
        self.temp.cleanup()
