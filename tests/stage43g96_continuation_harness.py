"""Owned temporary experiment only; no product restore/activation interface."""
from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
from time import perf_counter
from unittest.mock import patch

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.engine import TournamentEngine
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.live_game_service import LiveGameService
from phase2_engine.live_season_planner import LiveSeasonGraphPlan
from phase2_engine.live_season_save import create_live_season_save, plan_fingerprint
from phase2_engine.save_slots import SaveSlotManager
from stage43g94_fixture_support import owned_sqlite_handles
from stage43g95_isolated_harness import Experiment, anchor, browse, copy_file, product, facts
from test_stage43g91_save_inventory import StaticPlanner
from test_stage43g92_legacy_replay import Stage43G92LegacyReplayTests, ROOT, SEED

METRICS = []


def fixture_plan():
    base = Stage43G92LegacyReplayTests
    cid = 'CMP000029'
    return LiveSeasonGraphPlan(repo=base.repo, data_dir=ROOT/'data', year=2026, rng_seed=SEED,
        entries={cid: base.plan.entries[cid]}, annual_templates={cid: replace(
            base.plan.annual_templates[cid], entrant_school_ids=base.plan.annual_templates[cid].entrant_school_ids[:8])},
        annual_build_strategies={cid: base.plan.annual_build_strategies[cid]},
        calendar_rows=[r for r in base.plan.calendar_rows if r['competition_id'] == cid],
        stage_calendar_rows=base.plan.stage_calendar_rows, topological_order=[cid])


class Continuation:
    def __init__(self, phase='active', source='manual'):
        self.e = Experiment(phase, source)
        try:
            self.e.relocate()
            self.source = source
            self.evidence_pin = anchor(self.e.target)
            self.plan = fixture_plan()
            self.roots = {k: self.e.fixture.root/k for k in ('baseline-work', 'isolated-work')}
            self.work_pins = {}
            # Process-local provenance established at fixture generation, not a receipt claim.
            self.generated_compatibility_known = True
        except BaseException:
            self.close()
            raise

    def close(self):
        self.e.close()

    def protected(self):
        e = self.e
        if (anchor(e.fixture.slot) != e.source_pin or anchor(e.fixture.destination) != e.pin
                or anchor(e.target) != self.evidence_pin):
            raise product.BackupRefused('protected_input_changed')
        e.trusted(e.fixture.destination)
        e.trusted(e.target)

    def preflight(self):
        self.protected()
        if set(self.roots) != {'baseline-work','isolated-work'}:
            raise product.BackupRefused('work_not_owned')
        for key, root in self.roots.items():
            if root != self.e.fixture.root/key or product._path(root) != root:
                raise product.BackupRefused('work_not_owned')
        if self.source not in ('manual', 'autosave') or self.source != self.e.source:
            raise product.BackupRefused('checkpoint_selection_mismatch')
        if not self.generated_compatibility_known:
            raise product.BackupRefused('generation_compatibility_unknown')
        product._compatibility(ROOT)
        payload = json.loads((self.e.fixture.slot/(self.source+'.json')).read_text(encoding='utf-8'))
        if (payload['year'] != 2026 or payload['rng_seed'] != SEED
                or payload['plan_fingerprint'] != plan_fingerprint(self.plan)):
            raise product.BackupRefused('fixture_plan_mismatch')

    def prepare(self):
        """Exclusive owned roots, preserving slot identity in independent namespaces."""
        self.preflight()
        for key, root in self.roots.items():
            # Reject traversal, links/junctions and any substituted destination.
            if root != self.e.fixture.root/key or product._path(root) != root:
                raise product.BackupRefused('work_not_owned')
            if os.path.lexists(root):
                raise product.BackupRefused('destination_exists')
        for key, root in self.roots.items():
            root.mkdir(mode=0o700)
            slot = root/'owned94'
            slot.mkdir(mode=0o700)
            src = (self.e.fixture.slot if key == 'baseline-work'
                   else self.e.target/'payload'/'owned94')
            wanted = anchor(src)
            for name in sorted(wanted):
                copy_file(src/name, slot/name)
            if anchor(slot) != wanted or facts(slot) != self.e.sql or browse(slot) != self.e.views:
                raise product.BackupRefused('work_copy_mismatch')
            self.work_pins[key] = wanted
        self.preflight()

    def check_work(self, key):
        self.preflight()
        if key not in self.work_pins:
            raise product.BackupRefused('work_evidence_missing')
        slot = self.roots[key]/'owned94'
        if anchor(slot) != self.work_pins[key]:
            raise product.BackupRefused('work_changed_before_load')
        product._safe_call(lambda: product._inspect(slot, 'owned94', self.source))
        return slot

    def run_one(self, key):
        slot = self.check_work(key)
        expected = json.loads((slot/(self.source+'.json')).read_text(encoding='utf-8'))
        repo = Stage43G92LegacyReplayTests.repo
        service = LiveGameService(repo, ROOT/'data', save_root=self.roots[key],
            max_backups=0, planner_factory=lambda *args: StaticPlanner(self.plan))
        def engine():
            resolver = AbilityMatchResolver(repo, ability_config_dir=ROOT/'config'/'abilities',
                match_config_dir=ROOT/'config'/'match', team_generation_seed=SEED)
            return resolver, TournamentEngine(repo, main_match_resolver=resolver, pre_main_match_resolver=resolver)
        resolver, eng = engine()
        count = len(expected['completed_match_results'])
        start = perf_counter()
        initial = facts(slot)
        backups = {n:v for n,v in anchor(slot).items() if n.startswith('backups/')}
        with owned_sqlite_handles(), patch.object(SaveSlotManager, '_now_iso', return_value='2026-10-13T00:00:00+00:00'):
            # Count actual ability simulations, rather than trusting replay flags.
            with patch.object(resolver.simulator, 'simulate', wraps=resolver.simulator.simulate) as simulations:
                session = service.load_game('owned94', source=self.source, engine=eng)
                replayed = simulations.call_count
            if replayed != count or replayed == 0:
                raise product.BackupRefused('replay_not_proven')
            if create_live_season_save(session.plan, session.state) != expected or facts(slot) != initial:
                raise product.BackupRefused('reload_mismatch')
            # Only active fixtures have a next playable match. Sealed fixtures
            # recheck the annual boundary; registered fixtures still load 2026.
            played = 0
            if self.e.phase == 'active':
                result = service.advance_through(session, '2026-12-31')
                played = result['played_match_count']
                if played != 1:
                    raise product.BackupRefused('next_match_not_proven')
            boundary = service.finalize_season(session)
            outcomes = CareerCompetitionOutcomes(slot/'historical_matches.sqlite3')
            for run in session.state.completed_runs().values():
                outcomes.record_completed(run)
            rosters = CareerRosterArchive(slot/'career_rosters.sqlite3')
            for roster in resolver._roster_cache.values():
                rosters.save_initial_roster(roster)
            service.save_game(session, kind='manual')
            service.save_game(session, kind='autosave')
            final = facts(slot)
            before_sync = anchor(slot)
            service._sync_history(session)
            service._sync_history(session)
            if final != facts(slot) or before_sync != anchor(slot):
                raise product.BackupRefused('sync_not_idempotent')
            again_resolver, again_engine = engine()
            with patch.object(again_resolver.simulator, 'simulate', wraps=again_resolver.simulator.simulate) as simulations:
                again = service.load_game('owned94', source=self.source, engine=again_engine)
                if simulations.call_count != 7:
                    raise product.BackupRefused('second_replay_not_proven')
            if session.state.public_snapshot() != again.state.public_snapshot() or facts(slot) != final:
                raise product.BackupRefused('second_reload_mismatch')
            # Registration is metadata, never proof of next-year gameplay.
            next_year_refused = False
            try:
                service.advance_through(again, '2027-01-01')
            except ValueError:
                next_year_refused = True
            if not next_year_refused:
                raise product.BackupRefused('unsupported_next_year_started')
        product.live_and_membership(slot, self.source)
        if backups != {n:v for n,v in anchor(slot).items() if n.startswith('backups/')}:
            raise product.BackupRefused('rolling_history_changed')
        checkpoint = {s: json.loads((slot/(s+'.json')).read_text(encoding='utf-8')) for s in ('manual','autosave')}
        return dict(sql=final, views=browse(slot), checkpoint=checkpoint,
            runtime=session.state.public_snapshot(), readiness=boundary['year_end_readiness'],
            replayed=replayed, played=played, next_year_refused=next_year_refused,
            seconds=round(perf_counter()-start,6), bytes=sum(p.stat().st_size for p in product._scan(slot) if p.is_file()),
            work_changed=anchor(slot) != self.work_pins[key])

    def compare(self, measure=False):
        start = perf_counter()
        try:
            self.prepare()
            a = self.run_one('baseline-work')
            b = self.run_one('isolated-work')
            for key in ('sql','views','checkpoint','runtime','readiness','replayed','played','next_year_refused'):
                if a[key] != b[key]:
                    raise product.BackupRefused('continuation_mismatch')
            metric = dict(phase=self.e.phase, source=self.source, reloaded=True,
                replay_matches_per_series=a['replayed'], final_replay_matches_per_series=7,
                continued_matches_per_series=a['played'], final_matches=len(a['views']['details']),
                years=len(a['views']['years']), next_year_gameplay_started=False,
                next_year_refused=a['next_year_refused'], baseline_seconds=a['seconds'],
                isolated_seconds=b['seconds'], seconds=round(perf_counter()-start,6),
                baseline_bytes=a['bytes'], isolated_bytes=b['bytes'],
                source_bytes=self.e.export['source_slot_bytes'],candidate_bytes=self.e.export['candidate_total_bytes'],
                evidence_bytes=sum(p.stat().st_size for p in product._scan(self.e.target) if p.is_file()),
                logical_sql_equal=True, checkpoint_equal=True, runtime_equal=True,
                full_a_roster_ledger_outcomes_equal=True, sync_idempotent=True,
                source_zero_write=True,candidate_zero_write=True,evidence_zero_write=True,
                baseline_changed=a['work_changed'],isolated_changed=b['work_changed'])
            if measure:
                METRICS.append(metric)
            return metric
        finally:
            self.protected()
