"""能力の自由編集：選手ID、成長・怪我、総合力、評判の年度更新と保存。"""
from dataclasses import replace
from datetime import date
from pathlib import Path
import json
import pickle
import tempfile
import unittest

from game_core.annual_reputation import AnnualReputation
from game_core.injuries import Injury
from game_core.roster_book import RosterBook
from game_core.school_edits import AbilityEditor
from phase2_engine.models import Team
from phase2_engine import DataRepository, LiveGameService, PLAYER_RESOLVER_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
TEAMS = {sid: Team(sid, 'P' + sid, '架空高校' + sid[-1], '13') for sid in ('SCH-A', 'SCH-B')}


def book():
    b = RosterBook(TEAMS.__getitem__, first_year=2026, career_seed=7)
    for sid in TEAMS:
        b.roster(2026, sid)
    return b


class AbilityEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.editor = AbilityEditor(ROOT / 'config')

    def test_player_edit_is_saved_by_id_and_other_players_are_unchanged(self):
        b = book()
        players = b.roster(2026, 'SCH-A').players
        p = players[0]
        old = {q.player_id: bytes(b.state(q).values) for sid in TEAMS for q in b.roster(2026, sid).players}
        original = b.base_ability(p)
        edited = self.editor.player(original, {'contact': 99, 'position_aptitude': {'CF': 60}}, b.pitch_types())
        b.edit_abilities([p], [edited], day='2026-04-01', source='player')
        self.assertEqual(99, b.ability(p).contact)
        for sid in TEAMS:
            for q in b.roster(2026, sid).players:
                if q.player_id != p.player_id:
                    self.assertEqual(old[q.player_id], bytes(b.state(q).values))
        restored = pickle.loads(pickle.dumps(b))
        restored.bind(TEAMS.__getitem__)
        self.assertEqual(b.ability(p), restored.ability(p))
        self.assertIn(p.player_id, restored.ability_edits)
        with self.assertRaises(ValueError):
            b.edit_abilities([p], [replace(edited, player_id='another')], day='2026-04-01', source='player')

    def test_invalid_input_does_not_change_any_values(self):
        b = book(); p = b.roster(2026, 'SCH-A').players[0]
        original = b.base_ability(p)
        for changes in ({'contact': 101}, {'contact': True}, {'contact': 3.5}, {'contact': float('nan')},
                        {'player_id': 'another'}, {'position_aptitude': {p.primary_position: 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.editor.player(original, changes, b.pitch_types())
        self.assertEqual(original, b.base_ability(p))

    def test_pitch_abilities_and_repertoire_validation(self):
        b = book(); p = next(p for p in b.roster(2026, 'SCH-A').players if p.primary_position == 'P')
        original = b.base_ability(p)
        pitches = [q.to_dict() for q in original.pitch_repertoire]
        pitches[-1]['quality'] = 99
        edited = self.editor.player(original, {'velocity_kmh': 155, 'control': 90, 'pitch_repertoire': pitches}, b.pitch_types())
        self.assertEqual((155, 90, 99), (edited.velocity_kmh, edited.control, edited.pitch_repertoire[-1].quality))
        pitches[-1]['usage'] += 1
        with self.assertRaisesRegex(ValueError, '合計100'):
            self.editor.player(original, {'pitch_repertoire': pitches}, b.pitch_types())
        with self.assertRaises(ValueError):
            self.editor.player(original, {'velocity_kmh': 166}, b.pitch_types())

    def test_edits_are_the_base_for_growth_and_recovery(self):
        b = book(); p = b.roster(2026, 'SCH-A').players[0]
        injury = Injury(date(2026, 4, 1), 20, 2)
        b.state(p).injuries.append(injury)
        edited = self.editor.player(b.base_ability(p), {'contact': 70}, b.pitch_types())
        b.edit_abilities([p], [edited], day='2026-04-10', source='player')
        b.set_today(injury.end)
        self.assertLess(b.ability(p).contact, 70)
        b.set_today(date(2026, 5, 20))
        self.assertEqual(70, b.ability(p).contact)
        b.grow(date(2026, 5, 31))
        self.assertGreaterEqual(b.ability(p).contact, 70)
        self.assertEqual(1, len(b.state(p).injuries))

    def test_growth_does_not_lower_manually_edited_velocity_above_growth_cap(self):
        b = book()
        p = next(p for p in b.roster(2026, 'SCH-A').players if p.primary_position == 'P')
        edited = self.editor.player(b.base_ability(p), {'velocity_kmh': 165}, b.pitch_types())
        b.edit_abilities([p], [edited], day='2026-05-01', source='player')
        b.state(p).games = 255
        b.grow(date(2026, 5, 31))
        self.assertEqual(165, b.base_ability(p).velocity_kmh)

    def test_team_target_is_computed_from_players_without_future_bonus(self):
        b = book(); players = b.roster(2026, 'SCH-A').players
        before = self.editor.overall([b.ability(p) for p in players])
        result, snapshots = self.editor.team(b, players, before + 8)
        self.assertTrue(result['reached'], result)
        self.assertAlmostEqual(before + 8, result['achieved'], delta=.5)
        self.assertTrue(all(s.velocity_kmh is None or s.velocity_kmh <= 160 for s in snapshots))
        untouched = pickle.loads(pickle.dumps(b)); untouched.bind(TEAMS.__getitem__)
        b.edit_abilities(players, snapshots, day='2026-04-01', source='team')
        self.assertAlmostEqual(result['achieved'], self.editor.overall([b.ability(p) for p in players]))
        for b0 in (b, untouched):
            b0.roster(2027, 'SCH-A')
        for p in b.roster(2027, 'SCH-A').players:
            if p.entry_year == 2027:
                self.assertEqual(b.ability(p), untouched.ability(p))
        ranked, _ = self.editor.team(b, players, 'C')
        self.assertTrue(ranked['reached'], ranked)
        bands = json.loads((ROOT / 'config' / 'screen' / 'screen_v1.json').read_text(encoding='utf-8'))['ability_ranks']
        self.assertTrue(bands['C'] <= ranked['achieved'] < bands['B'])
        result, _ = self.editor.team(b, players, 100)
        self.assertFalse(result['reached'])
        self.assertTrue(result['reason'])

    def test_reputation_modes_and_intake_timing_survive_years_and_load(self):
        r = AnnualReputation(ROOT, 7)
        # 架空の学校の評判。既存選手は評判の編集では変更しない。
        r.values = {'SCH-A': -1., 'SCH-B': 1.}
        r.intake_by_year = {2026: dict(r.values)}
        b = book(); b.reputation = r
        p = b.roster(2026, 'SCH-A').players[0]
        before = b.ability(p)
        r.edit('SCH-A', 3., 'fixed', '2026-04-02', minimum=-4, maximum=4)
        r.edit('SCH-B', -3., 'automatic', '2026-04-02', minimum=-4, maximum=4)
        self.assertEqual(-1, r.program_z('SCH-A', 2026))
        for year in range(2027, 2031):
            r.update(date(year, 4, 1))
            self.assertEqual(3, r.values['SCH-A'])
        self.assertGreater(r.values['SCH-B'], -3)
        self.assertEqual(3, r.edits['SCH-A']['requested'])
        self.assertEqual(before, b.ability(p))
        self.assertGreater(r.program_z('SCH-A', 2030), r.program_z('SCH-B', 2030))
        restored = pickle.loads(pickle.dumps(b))
        self.assertEqual(r.__dict__, restored.reputation.__dict__)


class AbilityEditServiceTests(unittest.TestCase):
    def test_next_match_uses_edit_and_real_save_load_retains_it(self):
        repo = DataRepository(ROOT / 'data')
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(repo, ROOT / 'data', save_root=tmp,
                                      resolver_contract=PLAYER_RESOLVER_CONTRACT, autosave_after_action=False)
            session = service.new_game('edit', rng_seed=7, save_initial=False)
            match = session.state.today_matches()[0]
            sid = match['team1_id']
            players = service.editable_players(session, sid)
            p = players[0]
            resolver = session.state.primary.engine.main_match_resolver
            old = resolver._competition_team_input(match['competition_id'], sid, 2026, 7)
            service.edit_player(session, sid, p.player_id, {'contact': 99})
            new = resolver._competition_team_input(match['competition_id'], sid, 2026, 7)
            self.assertEqual(99, next(s.contact for s in new.player_abilities if s.player_id == p.player_id))
            self.assertNotEqual(old.player_abilities, new.player_abilities)
            service.edit_reputation(session, sid, 2.0, 'fixed')
            before_failure = bytes(session.state.rosters.state(p).values)
            failure = service.edit_team(session, sid, 100)
            self.assertFalse(failure['reached'])
            self.assertEqual(before_failure, bytes(session.state.rosters.state(p).values))
            service.play_today(session)
            service.save_game(session)
            loaded = service.load_game('edit')
            self.assertEqual(99, loaded.state.rosters.base_ability(p).contact)
            self.assertEqual({'requested': 2.0, 'mode': 'fixed', 'date': '2026-04-01'},
                             loaded.state.reputation.edits[sid])
            self.assertEqual(session.state.completed_results(), loaded.state.completed_results())
            with self.assertRaises(ValueError):
                service.edit_player(loaded, sid, 'wrong-player', {'contact': 50})
