"""Explicit product-only integration, disposable generated games and raw SQL oracles."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.live_game_service import InitialCareerPersistence, LiveGameService
from phase2_engine.live_game_demo_worker import services, YEAR, SEED, SLOT, CID, ROOT
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_competition_outcomes import CareerCompetitionOutcomes
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from stage43g97_acceptance_support import actual_runtime, sql_games, pin, KEYS, DETAILS
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read


def raw_records(slot):
    """Read without any product decoder. Verify payload and year manifest independently."""
    out = {}
    for name, query in (
        ('rosters', 'SELECT payload_json,content_sha256 FROM career_school_rosters ORDER BY school_id'),
        ('identities', 'SELECT identity_json,identity_sha256 FROM career_player_identities ORDER BY player_id'),
        ('matches', 'SELECT payload_json,record_sha256 FROM historical_matches ORDER BY match_id'),
        ('outcomes', 'SELECT payload_json,record_sha256 FROM historical_competition_outcomes ORDER BY competition_id'),
    ):
        path = slot / ('career_rosters.sqlite3' if name in ('rosters','identities') else 'historical_matches.sqlite3')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as con:
            assert con.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            rows = []
            for raw, digest in con.execute(query):
                assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == digest
                rows.append(json.loads(raw))
            out[name] = rows
    with closing(sqlite3.connect((slot/'historical_matches.sqlite3').as_uri()+'?mode=ro', uri=True)) as con:
        status, count, digest = con.execute('SELECT status,match_count,ledger_sha256 FROM career_years WHERE year=2026').fetchone()
        manifest = [list(r) for r in con.execute('SELECT competition_id,match_id,record_sha256 FROM historical_matches WHERE year=2026 ORDER BY competition_id,match_id')]
        raw = json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        assert (status,count,digest) == ('sealed',7,hashlib.sha256(raw.encode()).hexdigest())
        assert out['outcomes'][0]['source_year_ledger_sha256'] == digest
    return out


class Stage43G100PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(prefix='stage100-owned-'))
        self.saves = Path(self.temp).resolve()/'保存 日本語'
        self.service, self.resolver, self.engine = services(self.saves)
        self.slot = self.saves/SLOT

    def new(self, initial=True):
        return self.service.new_game(SLOT,rng_seed=SEED,start_date='2026-07-01',
                                     engine=self.engine,save_initial=initial)

    def six(self):
        session = self.new()
        self.assertEqual(6,self.service.advance_through(session,'2026-07-12')['played_match_count'])
        self.service.save_game(session)
        return session

    def finish(self):
        session = self.six()
        self.service.advance_through(session,'2026-12-31')
        self.service.finalize_season(session)
        self.service.autosave_game(session)
        return session

    def assert_db_same(self, before):
        after = pin(self.slot)
        self.assertEqual({k:v for k,v in before.items() if k.endswith('.sqlite3')},
                         {k:v for k,v in after.items() if k.endswith('.sqlite3')})

    def test_service_new_six_both_sources_replay_seal_reload_twice_raw_oracle_and_handles(self):
        with retained_handles() as handles:
            session = self.six()
            self.assertEqual(8,len(self.resolver.initial_roster_snapshot(
                reference_year=YEAR,generation_seed=SEED,school_ids=InitialCareerPersistence.SCHOOL_IDS)))
            with closing(sqlite3.connect(self.slot/'career_rosters.sqlite3')) as con:
                self.assertEqual((8,160),(con.execute('SELECT count(*) FROM career_school_rosters').fetchone()[0],
                                        con.execute('SELECT count(*) FROM career_player_identities').fetchone()[0]))
            # Oracle read was explicitly closed too, before Windows rename.
            assert_closed(self,handles);rename_and_read(self,self.slot)
            self.service.autosave_game(session)
            before = pin(self.slot)
            for source in ('manual','autosave'):
                service,resolver,engine = services(self.saves)
                session = service.load_game(SLOT,source=source,engine=engine)
                self.assertEqual(before,pin(self.slot))
                self.assertEqual(6,len(actual_runtime(session)))
                assert_closed(self,handles);rename_and_read(self,self.slot)
            self.service, self.resolver, self.engine = service,resolver,engine
            service.advance_through(session,'2026-12-31')
            actual = actual_runtime(session)
            boundary = service.finalize_season(session)
            self.assertTrue(boundary['archive_sealed'])
            self.assertTrue(boundary['career_outcomes'][0]['inserted'])
            service.autosave_game(session)
            raw = raw_records(self.slot)
            self.assertEqual(raw['outcomes'][0],InitialCareerPersistence.sealed_results(self.slot))
            assert_closed(self,handles);rename_and_read(self,self.slot)
            self.assertEqual(actual,[{k:r[k] for k in KEYS+DETAILS} for r in raw['matches']])
            self.assertEqual(list(session.state.completed_runs()[CID].outcome.final_ranking_school_ids),
                             raw['outcomes'][0]['ranked_school_ids'])
            identities = {r['player_id']:r for r in raw['identities']}
            for roster in raw['rosters']:
                for player in roster['players']:
                    self.assertEqual({k:v for k,v in player.items() if k!='academic_year'},identities[player['player_id']])
                    self.assertEqual(YEAR-player['academic_year']+1,player['entry_year'])
            before = pin(self.slot)
            for source in ('manual','autosave'):
                service,resolver,engine = services(self.saves)
                session = service.load_game(SLOT,source=source,engine=engine)
                self.assertEqual(before,pin(self.slot))
                for _ in range(2):
                    service.save_game(session);service.autosave_game(session)
                    self.assert_db_same(before)
                self.assertEqual(raw,raw_records(self.slot))
                self.assertFalse(service.finalize_season(session)['career_outcomes'][0]['inserted'])
                assert_closed(self,handles);rename_and_read(self,self.slot)
                before = pin(self.slot)

    def test_default_service_remains_opt_out_and_existing_new_slot_refused(self):
        self.service.career_persistence = None
        self.service.resolver_contract = 'untouched-default-test'
        self.new()
        self.assertFalse((self.slot/'career_rosters.sqlite3').exists())
        service,resolver,engine = services(self.saves)
        before = pin(self.slot)
        with self.assertRaises(ValueError):
            service.new_game(SLOT,rng_seed=SEED,engine=engine)
        with self.assertRaises(ValueError):
            service.load_game(SLOT,source='manual',engine=engine)
        self.assertEqual(before,pin(self.slot))

    def test_scope_unknown_plan_year_seed_engine_provider_and_early_cache_refused(self):
        plan = self.service._planner(SEED).build_plan()
        for changed in (replace(plan,year=2027),replace(plan,rng_seed=SEED+1),
                        replace(plan,topological_order=['unknown'])):
            with self.subTest(plan=changed.year):
                with self.assertRaises(ValueError):
                    self.service.career_persistence.prepare(changed,self.engine,self.service.resolver_contract)
        with self.assertRaises(ValueError):
            self.service.career_persistence.prepare(plan,None,self.service.resolver_contract)
        self.resolver.roster_provider = lambda y,s: None
        with self.assertRaises(ValueError): self.new()
        self.resolver.roster_provider = None
        self.resolver.team_input(school_id=InitialCareerPersistence.SCHOOL_IDS[0],reference_year=YEAR,generation_seed=SEED)
        with self.assertRaises(ValueError): self.new()
        self.assertFalse(self.slot.exists())

    def test_missing_source_and_changed_year_seed_id_grade_membership_fail_without_writes(self):
        session = self.new()
        original = deepcopy(self.resolver._initial_roster_source)
        sid = InitialCareerPersistence.SCHOOL_IDS[0]
        before = pin(self.slot)
        cases = ['missing','year','seed','id','grade','school','name']
        for case in cases:
            self.resolver._initial_roster_source = deepcopy(original)
            roster = self.resolver._initial_roster_source[sid]
            if case=='missing': del self.resolver._initial_roster_source[sid]
            elif case=='year': roster.reference_year += 1
            elif case=='seed': roster.rng_seed += 1
            else:
                field,value = {'id':('player_id','same-name-different-id'),
                    'grade':('academic_year',9),'school':('school_id','other-school'),
                    'name':('display_name',roster.players[0].display_name+'変更')}[case]
                roster.players[0] = replace(roster.players[0],**{field:value})
            with self.subTest(case=case), self.assertRaises(ValueError): self.service.save_game(session)
            self.assertEqual(before,pin(self.slot))

    def test_cache_clear_uses_pinned_source_and_detached_snapshot_mutation_has_no_effect(self):
        session = self.new()
        snapshot = self.resolver.initial_roster_snapshot(reference_year=YEAR,generation_seed=SEED,
                                                        school_ids=InitialCareerPersistence.SCHOOL_IDS)
        snapshot[0].players.clear()
        self.resolver.clear_cache()
        self.service.advance_through(session,'2026-07-12')
        self.assertEqual(6,len(sql_games(self.slot)))

    def test_option_a_missing_wrong_player_team_seed_or_inconsistent_stats_refused(self):
        session = self.six()
        m = next(m for c in session.state.competitions.values() for m in c.matches.values() if m.status=='completed')
        detail = deepcopy(m.ability_detail)
        before = pin(self.slot)
        for case in ('missing','player','team','seed','match_seed','stat','participant'):
            m.ability_detail = deepcopy(detail)
            if case=='missing': m.ability_detail['pitcher_stats'] = None
            elif case=='player': m.ability_detail['batter_stats'][0]['player_id'] = 'invented'
            elif case=='team': m.ability_detail['batter_stats'][0]['school_id'] = 'foreign'
            elif case=='seed': m.ability_detail['team_generation_seed'] += 1
            elif case=='match_seed': m.ability_detail['generation_seed'] += 1
            elif case=='participant': m.ability_detail['batter_stats'].pop()
            else: m.ability_detail['batter_stats'][0]['plate_appearances'] += 1
            with self.subTest(case=case),self.assertRaises(ValueError): self.service.autosave_game(session)
            self.assertEqual(before,pin(self.slot))
        m.ability_detail = detail

    def test_unfinished_outcomes_refused_and_no_outcome_before_seal(self):
        session = self.six()
        with closing(sqlite3.connect(self.slot/'historical_matches.sqlite3')) as con:
            self.assertEqual([],con.execute("SELECT name FROM sqlite_master WHERE name='historical_competition_outcomes'").fetchall())
        with self.assertRaises(ValueError): self.service.finalize_season(session)
        self.service.advance_through(session,'2026-12-31')
        before = pin(self.slot)
        with self.assertRaises(ValueError):
            self.service.career_persistence.sync_outcomes(session,self.slot)
        # The service refuses before invoking the outcome writer or its DDL.
        with closing(sqlite3.connect(self.slot/'historical_matches.sqlite3')) as con:
            self.assertEqual([],con.execute("SELECT name FROM sqlite_master WHERE name='historical_competition_outcomes'").fetchall())
        self.assertEqual(before,pin(self.slot))
        self.service.finalize_season(session)
        self.assertEqual(1,len(raw_records(self.slot)['outcomes']))

    def test_json_commit_roster_or_match_commit_failure_replayed_safely_without_gc(self):
        for boundary in ('json','roster','match'):
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory(prefix='stage100-crash-') as temp:
                root=Path(temp).resolve()/'saves'
                service,resolver,engine=services(root)
                session=service.new_game(SLOT,rng_seed=SEED,engine=engine,start_date='2026-07-01',save_initial=False)
                service.advance_through(session,'2026-07-12',autosave=False)
                if boundary=='json':
                    original=service.slots.save
                    def saved_then_failed(*args,**kwargs):
                        original(*args,**kwargs);raise OSError('after JSON commit')
                    target,method,side=service.slots,'save',saved_then_failed
                elif boundary=='roster':
                    original=CareerRosterArchive.save_initial_roster
                    counter=[0]
                    def partial_roster(archive,roster):
                        counter[0]+=1
                        if counter[0]==4: raise OSError('partial school commit')
                        return original(archive,roster)
                    target,method,side=CareerRosterArchive,'save_initial_roster',partial_roster
                else: target,method,side=HistoricalMatchArchive,'sync',OSError('before archive commit')
                errors=[]
                with retained_handles() as handles:
                    with patch.object(target,method,side_effect=side,autospec=boundary=='roster'):
                        try: service.save_game(session)
                        except OSError as error: errors.append(error)
                    self.assertEqual(1,len(errors))
                    if handles: assert_closed(self,handles)
                    fresh,r,e=services(root)
                    resumed=fresh.load_game(SLOT,source='manual',engine=e)
                    self.assertEqual(6,len(sql_games(root/SLOT)))
                    self.assertEqual(actual_runtime(session),actual_runtime(resumed))
                    assert_closed(self,handles);rename_and_read(self,root/SLOT)

    def test_seal_commit_then_outcome_failure_and_outcome_commit_then_failure_retry(self):
        original=CareerCompetitionOutcomes.record_completed
        for committed in (False,True):
            with self.subTest(committed=committed),tempfile.TemporaryDirectory(prefix='stage100-seal-crash-') as temp:
                root=Path(temp).resolve()/'saves'
                service,resolver,engine=services(root)
                session=service.new_game(SLOT,rng_seed=SEED,engine=engine,start_date='2026-07-01')
                service.advance_through(session,'2026-12-31')
                slot=root/SLOT
                def interrupted(writer,run):
                    if committed: original(writer,run)
                    raise OSError('outcome boundary')
                errors=[]
                with retained_handles() as handles:
                    with patch.object(CareerCompetitionOutcomes,'record_completed',side_effect=interrupted,autospec=True):
                        try: service.finalize_season(session)
                        except OSError as error: errors.append(error)
                    self.assertEqual(1,len(errors))
                    assert_closed(self,handles);rename_and_read(self,slot)
                    self.assertEqual('sealed',service.career_history_years(SLOT)[0]['status'])
                    with closing(sqlite3.connect(slot/'historical_matches.sqlite3')) as con:
                        tables=con.execute("SELECT name FROM sqlite_master WHERE name='historical_competition_outcomes'").fetchall()
                        self.assertEqual(bool(committed),bool(tables))
                        if committed: self.assertEqual((1,),con.execute('SELECT count(*) FROM historical_competition_outcomes').fetchone())
                before={k:v for k,v in pin(slot).items() if k=='career_rosters.sqlite3'}
                fresh,r,e=services(root)
                resumed=fresh.load_game(SLOT,source='manual',engine=e)
                fresh.save_game(resumed);fresh.autosave_game(resumed)
                self.assertEqual(1,len(raw_records(slot)['outcomes']))
                self.assertEqual(before,{k:v for k,v in pin(slot).items() if k=='career_rosters.sqlite3'})

    def test_roster_insert_transaction_rollback_and_collision_keep_existing_records(self):
        session=self.new(initial=False)
        original=CareerRosterArchive._insert
        def failed(con,roster):
            original(con,roster);raise RuntimeError('rollback after identity inserts')
        with retained_handles() as handles:
            with patch.object(CareerRosterArchive,'_insert',side_effect=failed):
                with self.assertRaises(RuntimeError): self.service.save_game(session)
            assert_closed(self,handles);rename_and_read(self,self.slot)
        with closing(sqlite3.connect(self.slot/'career_rosters.sqlite3')) as con:
            self.assertEqual((0,),con.execute('SELECT count(*) FROM career_player_identities').fetchone())
        self.service.save_game(session)
        with closing(sqlite3.connect(self.slot/'career_rosters.sqlite3')) as con:
            con.execute("UPDATE career_player_identities SET identity_json='{}'");con.commit()
        before=pin(self.slot)
        with retained_handles() as handles:
            with self.assertRaises(ValueError): self.service.save_game(session)
            assert_closed(self,handles);rename_and_read(self,self.slot)
        self.assertEqual(before,pin(self.slot))

    def test_stale_checkpoint_and_sealed_ledger_tampering_do_not_rewrite_history(self):
        session=self.six()
        self.service.advance_through(session,'2026-12-31')
        before=pin(self.slot)
        fresh,r,e=services(self.saves)
        with self.assertRaises(ValueError): fresh.load_game(SLOT,source='manual',engine=e)
        self.assertEqual(before,pin(self.slot))
        self.service.finalize_season(session)
        with closing(sqlite3.connect(self.slot/'historical_matches.sqlite3')) as con:
            con.execute("UPDATE career_years SET ledger_sha256='modified'");con.commit()
        before=pin(self.slot)
        fresh,r,e=services(self.saves)
        with retained_handles() as handles:
            with self.assertRaises(ValueError): fresh.load_game(SLOT,source='manual',engine=e)
            assert_closed(self,handles);rename_and_read(self,self.slot)
        self.assertEqual(before,pin(self.slot))


if __name__=='__main__': unittest.main()
