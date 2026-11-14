"""監督の打順の型：打てる順と役割で組む並べ方を、傾向で混ぜる（架空の選手）。"""
from dataclasses import replace
import unittest

from game_core.team_strength import BattingOrderStyle, TeamStrengthGenerator
from test_stage13b3_team_strength import make_roster_abilities


def batter(base, pid, *, contact=50, power=50, discipline=50, strikeouts=50, bunt=50, speed=50):
    return replace(base, player_id=pid, contact=contact, power=power, plate_discipline=discipline,
                   strikeout_resistance=strikeouts, bunt=bunt, speed=speed, baserunning=50)


class CoachBattingOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = TeamStrengthGenerator()
        cls.roster = make_roster_abilities(school_id='FAKE-ORDER')
        base = cls.roster[5]
        cls.players = [
            batter(base, 'A-SLUG', contact=70, power=90),
            batter(base, 'B-CONTACT', contact=85, power=55),
            batter(base, 'C-POWER', contact=60, power=75),
            batter(base, 'D-SPEED', contact=55, power=30, discipline=70, speed=95),
            batter(base, 'E-BUNT', contact=60, power=30, strikeouts=80, bunt=90),
            batter(base, 'F', contact=62, power=50),
            batter(base, 'G', contact=58, power=45),
            batter(base, 'H', contact=50, power=40),
            batter(base, 'I', contact=40, power=35),
        ]

    def order(self, style, players=None):
        return [p.player_id for p in self.generator._batting_order(players or self.players, style)]

    def test_low_style_is_batting_score_order_and_high_style_is_role_order(self):
        by_score = [p.player_id for p in sorted(
            self.players, key=lambda p: (-self.generator._batting_order_score(p), p.player_id))]
        self.assertEqual(by_score, self.order(None))
        self.assertEqual(by_score, self.order(BattingOrderStyle(lineup_style=1)))
        role = self.order(BattingOrderStyle(lineup_style=100))
        # 1番は出塁と足、2番はつなぐ打者、4番は最も長打寄り、3・5番は長打とミートの順
        self.assertEqual(['D-SPEED', 'E-BUNT', 'B-CONTACT', 'A-SLUG', 'C-POWER'], role[:5])
        rest = [pid for pid in by_score if pid not in role[:5]]
        self.assertEqual(rest, role[5:])

    def test_neutral_style_is_between_the_two_orders(self):
        score = self.order(BattingOrderStyle(lineup_style=1))
        role = self.order(BattingOrderStyle(lineup_style=100))
        middle = self.order(BattingOrderStyle(lineup_style=50))
        self.assertNotEqual(score, middle)
        self.assertNotEqual(role, middle)
        for pid in middle:
            low, high = sorted((score.index(pid), role.index(pid)))
            # 2つの打順の平均の順に並べるので、どちらかから大きく外れない
            self.assertLessEqual(low - 1, middle.index(pid))
            self.assertLessEqual(middle.index(pid), high + 1)
        # 打てる順では下位の足の速い打者も、中立では上位に上がる
        self.assertLess(middle.index('D-SPEED'), score.index('D-SPEED'))

    def test_fastest_batter_leads_off_unless_he_is_a_top_power_hitter(self):
        base = self.roster[5]
        # 一番足の速い打者がミートも高く、今までなら3〜5番に吸われていた（長打は上位2人に入らない）
        star = batter(base, 'D-SPEED', contact=75, power=65, speed=95)
        players = [p for p in self.players if p.player_id != 'D-SPEED'] + [star]
        self.assertEqual('D-SPEED', self.order(BattingOrderStyle(100), players)[0])
        self.assertEqual(['A-SLUG', 'D-SPEED'], self.order(BattingOrderStyle(1), players)[:2])
        # 長打が上位2人に入る打者は中軸に残す
        slugger = replace(star, power=95)
        players = [p for p in self.players if p.player_id != 'D-SPEED'] + [slugger]
        self.assertIn('D-SPEED', self.order(BattingOrderStyle(100), players)[2:5])

    def test_mobility_raises_the_leadoff_speed(self):
        base = self.roster[5]
        players = [p for p in self.players if p.player_id != 'D-SPEED'] + [
            batter(base, 'D-SPEED', contact=30, power=30, discipline=30, speed=95),
            batter(base, 'J-ONBASE', contact=75, power=30, discipline=80, speed=70),
        ]
        speeds = [self.generator._batting_order(players, BattingOrderStyle(100, mobility=m))[0].speed
                  for m in (1, 50, 100)]
        self.assertEqual([70, 70, 95], speeds)

    def test_small_ball_puts_a_bunter_second(self):
        base = self.roster[5]
        players = [p for p in self.players if p.player_id != 'E-BUNT'] + [
            batter(base, 'E-BUNT', contact=45, power=30, strikeouts=50, bunt=70),
            batter(base, 'K-CONTACT', contact=68, power=30, strikeouts=70, bunt=40),
        ]
        self.assertEqual('K-CONTACT', self.order(BattingOrderStyle(100, small_ball=50), players)[1])
        self.assertEqual('E-BUNT', self.order(BattingOrderStyle(100, small_ball=95), players)[1])

    def test_starting_lineup_uses_style_only_for_order(self):
        plain = self.generator.select_starting_lineup(self.roster)
        low = self.generator.select_starting_lineup(self.roster, order_style=BattingOrderStyle(1))
        high = self.generator.select_starting_lineup(self.roster, order_style=BattingOrderStyle(100))
        self.assertEqual(plain, low)
        self.assertEqual(sorted(e.player_id for e in plain.entries), sorted(e.player_id for e in high.entries))
        self.assertEqual(list(range(1, 10)), sorted(e.batting_order for e in high.entries))

    def test_same_side_pitcher_does_not_undo_the_role_order(self):
        from game_core.coaches import CoachTactics
        from game_core.match_contract import TeamMatchInput
        from game_core.match_simulator import MatchSimulator

        sim = MatchSimulator()
        opponent = replace(make_roster_abilities(school_id='FAKE-OPP')[0], throws='R')
        checked = 0
        for seed in range(2026100701, 2026100721):
            roster = tuple(make_roster_abilities(school_id='FAKE-ORDER', seed=seed))
            strength = self.generator.generate(roster, order_style=BattingOrderStyle(100))
            lineup = strength.starting_lineup
            team = TeamMatchInput('FAKE-ORDER', strength, roster)
            after = sim._platoon_lineup(lineup, team, opponent, (), CoachTactics())
            before = {e.player_id: e.batting_order for e in lineup.entries}
            kept = {e.player_id: e.batting_order for e in after.entries if e.player_id in before}
            # 全員が右打ちで左右の差がないので、打撃の差だけで隣どうしを入れ替えない
            self.assertEqual({pid: before[pid] for pid in kept}, kept)
            checked += 1
        self.assertEqual(20, checked)


if __name__ == '__main__':
    unittest.main()
