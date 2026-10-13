"""Stage98 owned-demo child only. Product services remain unchanged.

The private JSON protocol has no import/restore API. All connections die with
this process. Roster/outcome wiring below is explicitly pilot-only.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys

from game_core.tournament_bridge import AbilityMatchResolver
from .engine import TournamentEngine
from .repository import DataRepository
from .live_season_planner import LiveSeasonGraphPlan, LiveSeasonGraphPlanner
from .live_game_service import LiveGameService
from .career_roster_archive import CareerRosterArchive
from .career_competition_outcomes import CareerCompetitionOutcomes
from .historical_match_archive import HistoricalMatchArchive

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026101201
YEAR = 2026
CID = 'CMP000029'
SLOT = 'demo98'
CONTRACT = 'stage98_ability_demo_v1'


def services(saves):
    repo = DataRepository(ROOT / 'data')
    full = LiveSeasonGraphPlanner(repo, ROOT / 'data', SEED, year=YEAR).build_plan()
    plan = LiveSeasonGraphPlan(repo=repo, data_dir=ROOT / 'data', year=YEAR, rng_seed=SEED,
        entries={CID: full.entries[CID]}, annual_templates={CID: replace(
            full.annual_templates[CID], entrant_school_ids=full.annual_templates[CID].entrant_school_ids[:8])},
        annual_build_strategies={CID: full.annual_build_strategies[CID]},
        calendar_rows=[r for r in full.calendar_rows if r['competition_id'] == CID],
        stage_calendar_rows=full.stage_calendar_rows, topological_order=[CID])

    class DemoPlanner:
        year, rng_seed = YEAR, SEED

        def build_plan(self):
            return plan

    service = LiveGameService(repo, ROOT / 'data', save_root=saves, max_backups=0,
        resolver_contract=CONTRACT, planner_factory=lambda *args: DemoPlanner())
    resolver = AbilityMatchResolver(repo, ability_config_dir=ROOT / 'config' / 'abilities',
        match_config_dir=ROOT / 'config' / 'match', team_generation_seed=SEED)
    engine = TournamentEngine(repo, main_match_resolver=resolver, pre_main_match_resolver=resolver)
    return service, resolver, engine


def run(request):
    saves = Path(request['saves'])
    action, source = request['action'], request['source']
    if action not in ('new', 'load', 'manual', 'today', 'day', 'next_match', 'seal'):
        raise ValueError('未対応の操作です')
    if source not in ('manual', 'autosave'):
        raise ValueError('保存元を明示してください')
    service, resolver, engine = services(saves)
    slot = saves / SLOT
    if action == 'new':
        if slot.exists():
            raise ValueError('既存スロットへの新規作成はできません')
        session = service.new_game(SLOT, rng_seed=SEED, start_date='2026-07-01',
            title='8校単大会・隔離demo', engine=engine)
        active_source = 'manual'
    else:
        metadata = service.slots.inspect(SLOT, source=source)
        if metadata['year'] != YEAR or metadata['rng_seed'] != SEED:
            raise ValueError('試験条件が一致しません')
        payload = json.loads((slot / (source + '.json')).read_text(encoding='utf-8'))
        archive = HistoricalMatchArchive(slot / 'historical_matches.sqlite3')
        if len(archive.list_matches(YEAR)) != len(payload['completed_match_results']):
            raise ValueError('古い保存と履歴が一致しません。別の保存元を選択してください')
        session = service.load_game(SLOT, source=source, engine=engine)
        active_source = source

    archive = HistoricalMatchArchive(slot / 'historical_matches.sqlite3')
    sealed = any(r['year'] == YEAR and r['status'] == 'sealed' for r in archive.list_years())
    if sealed and action not in ('load', 'manual'):
        raise ValueError('封印済年度は進行できません')
    if action == 'manual':
        service.save_game(session, kind='manual')
        active_source = 'manual'
    elif action in ('today', 'day', 'next_match'):
        if action == 'today':
            service.play_today(session)
        elif action == 'day':
            service.next_day(session)
        else:
            dates = [c.next_scheduled_date() for c in session.state.competitions.values()]
            dates = [d for d in dates if d]
            if not dates:
                raise ValueError('次の試合がありません')
            service.advance_through(session, min(dates))
        active_source = 'autosave'
    elif action == 'seal':
        if session.state.summary()['completed_runtime_count'] != 1:
            raise ValueError('全試合が終了していません')
        service.advance_through(session, '2026-12-31')
        service.finalize_season(session)
        # Pilot-only integration. Not a completed production facade contract.
        outcomes = CareerCompetitionOutcomes(slot / 'historical_matches.sqlite3')
        for completed in session.state.completed_runs().values():
            outcomes.record_completed(completed)
        rosters = CareerRosterArchive(slot / 'career_rosters.sqlite3')
        for roster in resolver._roster_cache.values():
            rosters.save_initial_roster(roster)
        service.save_game(session, kind='manual')
        service.save_game(session, kind='autosave')
        active_source, sealed = 'manual', True

    competitions = [c.public_snapshot() for c in session.state.competitions.values()]
    summary = {**session.state.summary(), 'completed_match_count': len(session.state.completed_results())}
    return dict(summary=summary, competitions=competitions,
        schools=session.plan.annual_templates[CID].entrant_school_ids,
        school_labels={sid:service.repo.team(sid).display_name
                       for sid in session.plan.annual_templates[CID].entrant_school_ids},
        today=session.state.today_matches(), readiness=service.year_end_status(session),
        sealed=sealed, active_source=active_source,
        # Capture actual engine output before consulting the archive (test oracle).
        actual_games=[{**m.__dict__, 'year': YEAR} for c in session.state.competitions.values()
                      for m in c.matches.values() if m.status == 'completed'])


if __name__ == '__main__':
    try:
        result = run(json.load(sys.stdin))
        print(json.dumps({'ok': True, 'state': result}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
