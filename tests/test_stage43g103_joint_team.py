"""Prove the stop boundary before mixed-school input can reach legacy writers."""
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

from game_core.players import POSITION_SLOTS, validate_school_roster
from game_core.tournament_bridge import AbilityMatchResolver
from phase2_engine.engine import TournamentEngine
from phase2_engine.models import AnnualCompetitionInput
from phase2_engine.joint_team_fixture import (JointTeamFixture, JointTeamWriterUnsupported,
    ENTRIES, PREFIX, SCHOOLS, YEAR, COMPETITION, ROSTER_SEED)
from phase2_engine.career_history_browse_model import CareerHistoryBrowseModel
from phase2_engine.live_game_service import LiveGameService
from stage43g103_fixture_support import ROOT, fixture
from stage43g97_acceptance_support import pin
from stage43g99_fixture_support import retained_handles, assert_closed, rename_and_read


class Stage43G103JointTeamTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.rosters, self.model = fixture()

    def test_one_joint_slot_twenty_preview_players_original_schools_and_identity(self):
        page = self.model.preview(ENTRIES[0].team_id)
        self.assertEqual(3, len(self.model.entries))
        self.assertEqual(4, len({s for e in self.model.entries for s in e.school_ids}))
        self.assertEqual(20, len(page['players']))
        self.assertEqual(20, len({p['player_id'] for p in page['players']}))
        self.assertEqual(list(POSITION_SLOTS), [p['primary_position'] for p in page['players']])
        originals = {p.player_id: p.to_dict() for r in self.rosters for p in r.players}
        for sid in SCHOOLS[:2]:
            self.assertEqual(10, sum(p['school_id'] == sid for p in page['players']))
        for p in page['players']:
            self.assertEqual(originals[p['player_id']], {k:v for k,v in p.items() if k not in ('team_id','team_slot')})
        self.assertIsNone(page['archived_results'])
        self.assertFalse(page['match_input_supported'])

    def test_scope_duplicate_school_team_namespace_unknown_member_and_annual_change_refused(self):
        for changed in (
            (replace(ENTRIES[0], team_id=SCHOOLS[0]), *ENTRIES[1:]),
            (replace(ENTRIES[0], team_id='FX103:2027:CMP000041:joint'), *ENTRIES[1:]),
            (ENTRIES[0], replace(ENTRIES[1], team_id=ENTRIES[0].team_id), ENTRIES[2]),
            (ENTRIES[0], replace(ENTRIES[1], school_ids=(SCHOOLS[0],)), ENTRIES[2]),
            (replace(ENTRIES[0], school_ids=(SCHOOLS[0], SCHOOLS[0])), *ENTRIES[1:]),
            (replace(ENTRIES[0], school_ids=('FAKE',)), *ENTRIES[1:]),
            ENTRIES[:2],
        ):
            with self.subTest(entries=changed), self.assertRaises(ValueError):
                JointTeamFixture.from_rosters(self.repo, self.rosters, entries=changed)
        with self.assertRaises(ValueError):
            self.model.preview(PREFIX + 'dissolved')

    def test_missing_duplicate_reassigned_id_grade_entry_and_seed_refused(self):
        for field, value in (('player_id','PLYFORGED'), ('school_id',SCHOOLS[1]),
                ('entry_year',2000), ('academic_year',1), ('generation_seed',1)):
            changed = deepcopy(self.rosters)
            # Use an actual change even if the selected player's grade is already 1.
            if field == 'academic_year':
                value = 1 if changed[0].players[0].academic_year != 1 else 2
            changed[0].players[0] = replace(changed[0].players[0], **{field:value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                JointTeamFixture.from_rosters(self.repo, changed)
        for changed in (self.rosters[:-1], (self.rosters[0],)*4):
            with self.assertRaises(ValueError):
                JointTeamFixture.from_rosters(self.repo, changed)
        changed = deepcopy(self.rosters)
        changed[0].players[1] = replace(changed[0].players[1], player_id=changed[0].players[0].player_id)
        with self.assertRaises(ValueError):
            JointTeamFixture.from_rosters(self.repo, changed)

    def test_detached_preview_original_rosters_and_school_master_unchanged(self):
        before = deepcopy(self.repo.schools)
        first = self.model.preview(ENTRIES[0].team_id)
        self.rosters[0].players.clear()
        first['players'][0]['school_id'] = 'FORGED'
        self.assertEqual(20, len(self.model.preview(ENTRIES[0].team_id)['players']))
        self.assertNotEqual('FORGED', self.model.preview(ENTRIES[0].team_id)['players'][0]['school_id'])
        self.assertEqual(before, self.repo.schools)
        self.assertTrue(all(e.team_id not in self.repo.schools for e in ENTRIES))

    def test_real_engine_rejects_joint_namespace_before_resolver_or_bracket(self):
        resolver = AbilityMatchResolver(self.repo, ability_config_dir=ROOT/'config/abilities',
            match_config_dir=ROOT/'config/match', team_generation_seed=ROSTER_SEED)
        engine = TournamentEngine(self.repo, main_match_resolver=resolver)
        annual = AnnualCompetitionInput(COMPETITION, YEAR, [e.team_id for e in ENTRIES], 430103)
        with self.assertRaisesRegex(ValueError, 'unknown school_id'):
            engine.prepare_main_runtime(annual)
        self.assertEqual(0, resolver.cache_size)
        with patch.object(LiveGameService, 'save_game', side_effect=AssertionError('no writer')):
            with self.assertRaises(JointTeamWriterUnsupported):
                self.model.legacy_annual_input()

    def test_real_resolver_and_strength_reject_mixed_origin_without_relabelling(self):
        page = self.model.preview(ENTRIES[0].team_id)
        by_id = {p.player_id:p for r in self.rosters for p in r.players}
        mixed_players = [by_id[p['player_id']] for p in page['players']]
        mixed = replace(self.rosters[0], players=mixed_players)
        with self.assertRaisesRegex(ValueError, 'roster_no must be 1..20|school_id mismatch'):
            validate_school_roster(mixed)
        resolver = AbilityMatchResolver(self.repo, ability_config_dir=ROOT/'config/abilities',
            match_config_dir=ROOT/'config/match', team_generation_seed=ROSTER_SEED,
            roster_provider=lambda year, sid: mixed)
        with self.assertRaisesRegex(ValueError, 'roster_no must be 1..20|school_id mismatch'):
            resolver(match_id='fixture', competition_id=COMPETITION, reference_year=YEAR,
                     generation_seed=123, team1=SCHOOLS[0], team2=SCHOOLS[2])
        abilities = tuple(resolver.ability_generator.iter_roster(mixed_players, YEAR, ROSTER_SEED))
        with self.assertRaisesRegex(ValueError, 'one school'):
            resolver.team_generator.generate(abilities)
        self.assertEqual(0, resolver.cache_size)

    def test_school_sql_sha_readonly_provenance_and_native_handles(self):
        with tempfile.TemporaryDirectory(prefix='stage103-generated-') as temp:
            slot = Path(temp)
            with retained_handles() as handles:
                repo, rosters, model = fixture(slot)
                assert_closed(self, handles)
                rename_and_read(self, slot)
                before = pin(slot)
                # Independent SQL/JSON/SHA and permanent-ID recipe; no product decoder.
                with closing(sqlite3.connect((slot/'career_rosters.sqlite3').as_uri()+'?mode=ro', uri=True)) as con:
                    originals = {}
                    for sid, raw, digest in con.execute('SELECT school_id,payload_json,content_sha256 FROM career_school_rosters'):
                        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), digest)
                        row = json.loads(raw)
                        for p in row['players']:
                            recipe = f"{ROSTER_SEED}:player_v1:{YEAR}:{sid}:{p['roster_no']}"
                            self.assertEqual('PLY'+hashlib.sha256(recipe.encode()).hexdigest()[:20].upper(),p['player_id'])
                            self.assertEqual(sid,p['school_id'])
                            originals[p['player_id']] = p
                    self.assertEqual(80,len(originals))
                    for pid,sid,raw,digest in con.execute('SELECT player_id,school_id,identity_json,identity_sha256 FROM career_player_identities'):
                        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),digest)
                        self.assertEqual({k:v for k,v in originals[pid].items() if k!='academic_year'},json.loads(raw))
                        self.assertEqual(originals[pid]['school_id'],sid)
                for entry in ENTRIES:
                    for p in model.preview(entry.team_id)['players']:
                        self.assertEqual(originals[p['player_id']]['school_id'],p['school_id'])
                assert_closed(self, handles)
                rename_and_read(self, slot)
                self.assertEqual(before,pin(slot))

    def test_legacy_real_games_full_a_sql_and_school_player_history_remain_independent(self):
        from stage43g101_fixture_support import services, SLOT, SEED, raw_records
        with tempfile.TemporaryDirectory(prefix='stage103-baseline-') as temp:
            service, resolver, engine = services(Path(temp))
            session = service.new_game(SLOT,rng_seed=SEED,engine=engine,start_date='2026-04-01')
            service.advance_through(session,'2026-12-31')
            service.finalize_season(session)
            slot = Path(temp)/SLOT
            raw = raw_records(slot)  # Independent SQL/SHA, scores, innings and personal stats.
            self.assertEqual(6,len(raw['matches']))
            before = pin(slot)
            with retained_handles() as handles:
                browse = CareerHistoryBrowseModel(ROOT/'data',slot)
                for game in raw['matches']:
                    details = browse.match_page(YEAR,game['competition_id'],game['match_id'])['game']
                    for field in ('inning_scores','team_stats','batter_stats','pitcher_stats'):
                        self.assertEqual(game[field],details[field])
                for r in raw['rosters']:
                    page = browse.school_page(YEAR,r['school_id'])
                    self.assertEqual(r['school_id'],page['school_id'])
                    for p in r['players']:
                        self.assertEqual(p['player_id'],browse.player_page(YEAR,p['player_id'])['player_id'])
                assert_closed(self,handles)
                rename_and_read(self,slot)
            self.assertEqual(before,pin(slot))
