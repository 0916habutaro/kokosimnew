"""Owned 8-school acceptance tooling; no external save or restore API."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SLOT = 'owned97'
DETAILS = ('inning_scores', 'team_stats', 'batter_stats', 'pitcher_stats')
KEYS = ('year', 'competition_id', 'match_id', 'team1_id', 'team2_id',
        'team1_score', 'team2_score', 'winner_id', 'loser_id')


def pin(root):
    # Independent byte oracle, never supplied to a product writer.
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def sql_games(slot):
    with closing(sqlite3.connect((slot/'historical_matches.sqlite3').as_uri()
                                    + '?mode=ro', uri=True)) as con:
        assert con.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        result = []
        for raw, digest in con.execute('SELECT payload_json,record_sha256 FROM historical_matches ORDER BY match_id'):
            assert hashlib.sha256(raw.encode()).hexdigest() == digest
            result.append(json.loads(raw))
        return result


def actual_runtime(session):
    # Capture runtime output before reading ANY saved/archive payload.
    result = []
    for competition in session.state.competitions.values():
        for m in competition.matches.values():
            if m.status == 'completed':
                row = {k: getattr(m, k) for k in KEYS if k != 'year'}
                row['year'] = session.state.year
                row.update({k: m.ability_detail[k] for k in DETAILS})
                result.append(row)
    return sorted(result, key=lambda x: x['match_id'])


def services(root):
    # The static 8-school graph is a test restriction, not the product planner.
    import stage43g96_continuation_harness as stage96
    stage96.Stage43G92LegacyReplayTests.setUpClass()
    repo = stage96.Stage43G92LegacyReplayTests.repo
    plan = stage96.fixture_plan()
    resolver = stage96.AbilityMatchResolver(repo, ability_config_dir=ROOT/'config'/'abilities',
        match_config_dir=ROOT/'config'/'match', team_generation_seed=stage96.SEED)
    engine = stage96.TournamentEngine(repo, main_match_resolver=resolver, pre_main_match_resolver=resolver)
    service = stage96.LiveGameService(repo, ROOT/'data', save_root=root/'保存 日本語',
        planner_factory=lambda *args: stage96.StaticPlanner(plan))
    return stage96, service, resolver, engine


def worker(root, action, source):
    """Child process works only on a parent's newly generated temporary game."""
    stage96, service, resolver, engine = services(root)
    slot = root/'保存 日本語'/SLOT
    if action == 'new':
        session = service.new_game(SLOT, rng_seed=stage96.SEED, start_date='2026-07-01',
                                   title='模擬高校野球・受入専用', engine=engine)
        assert service.advance_through(session, '2026-07-12')['played_match_count'] == 6
        expected = actual_runtime(session)
        service.save_game(session, kind='manual')
    else:
        before = pin(slot)
        session = service.load_game(SLOT, source=source, engine=engine)
        assert before == pin(slot), 'reload changed already synchronized bytes'
        if action == 'finish':
            assert len(actual_runtime(session)) == 6
            assert service.advance_through(session, '2026-12-31')['played_match_count'] == 1
            expected = actual_runtime(session)
            boundary = service.finalize_season(session)
            assert boundary['archive_sealed'] and not boundary['next_year_gameplay_started']
            # These are explicit test connections, still absent from the facade.
            outcomes = stage96.CareerCompetitionOutcomes(slot/'historical_matches.sqlite3')
            for run in session.state.completed_runs().values():
                outcomes.record_completed(run)
            rosters = stage96.CareerRosterArchive(slot/'career_rosters.sqlite3')
            for roster in resolver._roster_cache.values():
                rosters.save_initial_roster(roster)
            service.save_game(session, kind='autosave')
        elif action == 'register':
            expected = actual_runtime(session)
            stage96.HistoricalMatchArchive(slot/'historical_matches.sqlite3').register_next_year(
                year=2027, rng_seed=stage96.SEED, resolver_contract=session.resolver_contract,
                plan_fingerprint='stage97-registration-only')
        elif action == 'reload':
            expected = actual_runtime(session)
        else:
            raise ValueError('unknown fixture action')
        if action != 'finish':
            try:
                service.advance_through(session, '2027-01-01')
            except ValueError:
                pass
            else:
                raise AssertionError('next-year gameplay unexpectedly started')
    stored = sql_games(slot)
    assert [{k: row[k] for k in KEYS+DETAILS} for row in stored] == expected
    return dict(games=expected, runtime=session.state.public_snapshot(),
                pid=os.getpid(), source=source, action=action)


class OwnedGame:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stage97-owned-')
        self.root = Path(self.temp.name).resolve()
        self.saves = self.root/'保存 日本語'
        self.slot = self.saves/SLOT
        self.cwd = self.root/'別作業 directory'
        self.cwd.mkdir()

    def run(self, action, source='manual'):
        env = dict(os.environ, PYTHONUTF8='1',
                   PYTHONPATH=os.pathsep.join((str(ROOT/'tests'), str(ROOT))))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
            str(self.root), action, source], env=env, cwd=self.cwd,
            capture_output=True, text=True, encoding='utf-8', timeout=180)
        if result.returncode:
            raise AssertionError(f'fixture {action}/{source} failed:\n{result.stdout}\n{result.stderr}')
        return json.loads(result.stdout)

    def ready(self, source='manual'):
        self.initial = self.run('new')
        self.finished = self.run('finish', source)
        return self.finished['games']

    def close(self):
        self.temp.cleanup()


if __name__ == '__main__':
    # Internal child entry point, not a supported product/local-save command.
    print(json.dumps(worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3]),
                     ensure_ascii=False))
