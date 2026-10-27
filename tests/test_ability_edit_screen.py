"""既存の学校・選手画面からの編集API。保存後の表示とエラーを検証する。"""
from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService, PLAYER_RESOLVER_CONTRACT
from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.app import ScreenApi

ROOT = Path(__file__).resolve().parents[1]


class AbilityEditScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = LiveGameService(DataRepository(ROOT / 'data'), ROOT / 'data', save_root=self.tmp.name,
                                       resolver_contract=PLAYER_RESOLVER_CONTRACT, autosave_after_action=False)
        self.session = self.service.new_game('edit', rng_seed=23, save_initial=False)
        self.sid = self.session.state.today_matches()[0]['team1_id']
        self.players = self.service.editable_players(self.session, self.sid)
        self.data = GameScreenData(self.service, self.session)
        # 画面APIの検証対象を1校に絞る。名簿と試合の処理は本番のまま。
        self.data._today_members = lambda: {self.sid: self.players}
        self.api = ScreenApi(self.data)
        self.api.warm_up = lambda: None

    def test_school_edits_show_results_and_retain_current_players_for_reputation(self):
        school = self.api.school(self.sid)
        self.assertTrue(school['edit']['team_editable'])
        target = school['abilities']['overall'] + 5
        old = bytes(self.session.state.rosters.state(self.players[0]).values)
        preview = self.api.preview_team(self.sid, target)
        self.assertTrue(preview['reached'])
        self.assertEqual(old, bytes(self.session.state.rosters.state(self.players[0]).values))
        result = self.api.edit_school(self.sid, {'operation': 'team', 'target': target})
        self.assertNotIn('error', result)
        self.assertAlmostEqual(target, result['school']['abilities']['overall'], delta=.5)
        self.assertEqual(1, len(result['school']['edit']['team_history']))
        after = bytes(self.session.state.rosters.state(self.players[0]).values)
        rep = self.api.edit_school(self.sid, {'operation': 'reputation', 'value': 2.5, 'mode': 'fixed'})
        self.assertEqual(after, bytes(self.session.state.rosters.state(self.players[0]).values))
        form = rep['school']['edit']['reputation']
        self.assertEqual(2.5, form['current'])
        self.assertEqual('fixed', form['setting']['mode'])
        loaded = self.service.load_game('edit')
        self.assertEqual(2.5, loaded.state.reputation.edits[self.sid]['requested'])

    def test_player_form_uses_base_abilities_and_validates_without_changes(self):
        p = next(p for p in self.players if p.primary_position == 'P')
        detail = self.api.player(self.sid, p.player_id)
        fields = {f['key']: f for f in detail['edit']['fields']}
        self.assertEqual((100, 165), (fields['velocity_kmh']['minimum'], fields['velocity_kmh']['maximum']))
        before = bytes(self.session.state.rosters.state(p).values)
        self.assertIn('error', self.api.edit_player(self.sid, p.player_id, {'velocity_kmh': 999}))
        self.assertEqual(before, bytes(self.session.state.rosters.state(p).values))
        updated = self.api.edit_player(self.sid, p.player_id, {'contact': 91, 'velocity_kmh': 151})
        values = {f['key']: f['value'] for f in updated['edit']['fields']}
        self.assertEqual((91, 151), (values['contact'], values['velocity_kmh']))
        self.assertEqual(1, len(updated['edit']['history']))
        loaded = self.service.load_game('edit')
        self.assertEqual(91, loaded.state.rosters.base_ability(p).contact)
        self.assertIn('error', self.api.edit_player(self.sid, 'wrong-id', {'contact': 70}))

    def test_invalid_team_and_reputation_preserve_state(self):
        before = [bytes(self.session.state.rosters.state(p).values) for p in self.players]
        self.assertIn('error', self.api.edit_school(self.sid, {'operation': 'team', 'target': 100}))
        self.assertIn('error', self.api.edit_school(self.sid, {'operation': 'reputation', 'value': 20, 'mode': 'fixed'}))
        self.assertIn('error', self.api.edit_school(self.sid, {'operation': 'reputation', 'value': 1, 'mode': 'invalid'}))
        self.assertIn('error', self.api.edit_school(self.sid, {'operation': 'invalid'}))
        self.assertEqual(before, [bytes(self.session.state.rosters.state(p).values) for p in self.players])
        self.assertNotIn(self.sid, self.session.state.reputation.edits)


if __name__ == '__main__':
    unittest.main()
