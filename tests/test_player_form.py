"""選手の調子と、監督の調子の重視（段階F4。架空の学校・選手）。"""
from dataclasses import replace
from datetime import date, timedelta
import pickle
import unittest

from game_core.form import form_model
from game_core.team_strength import BattingOrderStyle, TeamStrengthGenerator
from test_coach_intake import books
from test_stage13b3_team_strength import make_roster_abilities

DAY = date(2026, 7, 10)


def coach_book(form_reliance, player_eye=100, player_selection=50):
    f = books(50)
    book = f[1]
    coach = book.coaches['C-FAKE-A']
    book.coaches[coach.coach_id] = replace(coach, form_reliance=form_reliance, player_eye=player_eye,
                                           player_selection=player_selection)
    return book


class FormModelTests(unittest.TestCase):
    def test_moves_with_results_returns_to_zero_and_stays_in_range(self):
        model = form_model()
        unit = model.config['unit']
        good = model.after_game(0.0, 7, on_base=4)
        bad = model.after_game(0.0, 7, outs_made=4)
        self.assertGreater(good, bad)
        self.assertEqual(good, model.after_game(0.0, 7, on_base=4))
        self.assertEqual(model.limit_units, model.after_game(0.0, 7, on_base=100))
        self.assertEqual(-model.limit_units, model.after_game(0.0, 7, earned_runs=100))
        value = model.value(model.limit_units, DAY, DAY)
        self.assertAlmostEqual(model.config['limit'], value)
        self.assertLess(abs(model.value(model.limit_units, DAY, DAY + timedelta(days=120))), 0.1)
        # 乱数だけで動かしても、長い期間の平均は0の近く
        form, values = 0.0, []
        for seed in range(2000):
            form = model.after_game(form, seed) * unit
            values.append(form)
        self.assertLess(abs(sum(values) / len(values)), 0.1)
        self.assertLess(max(abs(v) for v in values), model.config['limit'] + 1e-9)

    def test_ability_moves_a_few_points_on_the_main_abilities(self):
        model = form_model()
        snapshot = make_roster_abilities(school_id='FAKE-FORM')[0]
        self.assertEqual(3, model.points(2.0))
        self.assertEqual(-3, model.points(-2.0))
        up = model.apply(snapshot, model.points(2.0))
        self.assertEqual(snapshot.contact + 3, up.contact)
        self.assertEqual(snapshot.control + 3, up.control)
        self.assertEqual(snapshot.speed, up.speed)
        self.assertIs(snapshot, model.apply(snapshot, 0))


class RosterFormTests(unittest.TestCase):
    def test_form_is_per_player_and_survives_save_and_load(self):
        repo, coaches, reputation, rosters = books()
        players = rosters.roster(2026, 'FAKE-A').players[:4]
        rows = [(players[0], 3, 0, 0, 0), (players[1], 0, 4, 0, 0), (players[2], 0, 0, 27, 0),
                (players[3], 0, 0, 3, 6)]
        rosters.after_game_form(rows, day=DAY)
        forms = [rosters.form(p, DAY) for p in players]
        # 同じ選手・同じ日（同じ乱数）なら、結果が良いほど調子が上がる
        swapped = books()[3]
        swapped.after_game_form([(players[0], 0, 4, 0, 0), (players[1], 3, 0, 0, 0),
                                 (players[2], 0, 0, 3, 6), (players[3], 0, 0, 27, 0)], day=DAY)
        flipped = [swapped.form(p, DAY) for p in players]
        self.assertGreater(forms[0], flipped[0])
        self.assertLess(forms[1], flipped[1])
        self.assertGreater(forms[2], flipped[2])
        self.assertLess(forms[3], flipped[3])
        # 並べる順を変えても同じ（選手・日ごとの乱数）
        other = books()[3]
        other.after_game_form(list(reversed(rows)), day=DAY)
        self.assertEqual(forms, [other.form(p, DAY) for p in players])
        # セーブには名簿の今日からの日数で入れる（試合の日が今日より先でも、古すぎても同じ値に戻る）
        rosters.set_today(DAY - timedelta(days=1))
        loaded = pickle.loads(pickle.dumps(rosters))
        loaded.bind(repo.team)
        later = DAY + timedelta(days=5)
        self.assertEqual([rosters.form(p, later) for p in players],
                         [loaded.form(p, later) for p in players])
        rosters.after_game_form(rows, day=later)
        loaded.after_game_form(rows, day=later)
        self.assertEqual([rosters.form(p, later) for p in players],
                         [loaded.form(p, later) for p in players])
        self.assertEqual(0.0, rosters.form(rosters.roster(2026, 'FAKE-B').players[0], DAY))
        far = later + timedelta(days=form_model().max_age_days + 1)
        self.assertEqual([0.0] * 4, [rosters.form(p, far) for p in players])
        rosters.set_today(far)
        again = pickle.loads(pickle.dumps(rosters))
        again.bind(repo.team)
        self.assertEqual([0.0] * 4, [again.form(p, far) for p in players])
        self.assertEqual([0] * 4, [again.state(p).form for p in players])


class CoachFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = TeamStrengthGenerator()
        cls.roster = tuple(make_roster_abilities(school_id='FAKE-A'))

    def scores(self):
        return {p.player_id: self.generator._batting_composite(p)
                for p in self.roster if p.primary_position != 'P'}

    def test_low_reliance_ignores_form(self):
        forms = {p.player_id: 2.0 for p in self.roster}
        for value in (1, 30, 50):
            self.assertEqual((), coach_book(value).form_reading('FAKE-A', DAY, forms, self.scores()))

    def test_high_reliance_starts_a_hot_bench_player_and_moves_him_up(self):
        plain = self.generator.select_starting_lineup(self.roster, order_style=BattingOrderStyle(50))
        starters = set(plain.starter_ids)
        bench = [p for p in self.roster if p.player_id not in starters and p.primary_position != 'P']
        hot = max(bench, key=lambda p: (self.generator._selection_score(p, p.primary_position), p.player_id))
        forms = {p.player_id: 0.0 for p in self.roster}
        forms[hot.player_id] = 2.0
        bonus = dict(coach_book(100).form_reading('FAKE-A', DAY, forms, self.scores()))
        self.assertEqual({hot.player_id: 8.0}, bonus)
        chosen = self.generator.select_starting_lineup(self.roster, order_style=BattingOrderStyle(50),
                                                       form_bonus=bonus)
        self.assertIn(hot.player_id, chosen.starter_ids)
        # 同じ9人で比べても、調子の良い選手の打順が上がる
        nine = [p for p in self.roster if p.player_id in chosen.starter_ids]
        order = [p.player_id for p in self.generator._batting_order(nine, BattingOrderStyle(50))]
        hot_order = [p.player_id for p in self.generator._batting_order(nine, BattingOrderStyle(50), bonus)]
        self.assertLess(hot_order.index(hot.player_id), order.index(hot.player_id))

    def test_dh_choice_uses_the_same_form_bonus_as_the_lineup(self):
        plain = self.generator.select_starting_lineup(self.roster)
        starters = set(plain.starter_ids)
        pitcher = plain.player_for_position('P')
        # 守備に入っていない一番打てる野手（DHの候補）を、調子の加点で守備に入れる
        bench = [p for p in self.roster if p.player_id not in starters and p.primary_position != 'P']
        hot = max(bench, key=lambda p: (self.generator._batting_composite(p), p.player_id))
        bonus = {hot.player_id: 8.0}
        decision = self.generator.select_dh_mode(
            self.roster, starting_pitcher_id=pitcher, replacement_batter_id=pitcher,
            starter_share=1.0, form_bonus=bonus)
        self.assertEqual('normal', decision.mode)
        self.assertNotEqual(hot.player_id, decision.normal_candidate_id)
        strength = self.generator.generate(
            self.roster, dh_mode='normal', starting_pitcher_id=pitcher,
            designated_hitter_id=decision.normal_candidate_id, form_bonus=bonus)
        self.assertIn(hot.player_id, strength.starting_lineup.starter_ids)

    def test_cold_players_drop_but_core_players_are_protected(self):
        scores = self.scores()
        ranked = sorted(scores, key=lambda pid: (-scores[pid], pid))
        star, regular = ranked[0], ranked[5]
        forms = {pid: 0.0 for pid in scores}
        forms[star] = forms[regular] = -2.0
        bonus = dict(coach_book(100).form_reading('FAKE-A', DAY, forms, scores))
        self.assertEqual(-8.0, bonus[regular])
        self.assertEqual(-2.0, bonus[star])
        chosen = self.generator.select_starting_lineup(self.roster, form_bonus=bonus)
        self.assertIn(star, chosen.starter_ids)

    def test_low_player_eye_misreads_the_form(self):
        scores = self.scores()
        forms = {pid: 1.0 for pid in scores}
        sharp = dict(coach_book(100, 100).form_reading('FAKE-A', DAY, forms, scores))
        self.assertEqual({4.0}, set(sharp.values()))
        dull = dict(coach_book(100, 1).form_reading('FAKE-A', DAY, forms, scores))
        self.assertGreater(len(set(dull.values())), 5)
        self.assertTrue(any(v < 0 for v in dull.values()))
        # 同じ監督・選手・日なら同じ読み違え
        self.assertEqual(dull, dict(coach_book(100, 1).form_reading('FAKE-A', DAY, forms, scores)))
        # 下級生・上級生の起用の傾向（player_selection）は読み違いに関係しない
        for selection in (1, 100):
            self.assertEqual(sharp, dict(coach_book(100, 100, selection).form_reading(
                'FAKE-A', DAY, forms, scores)))


class MatchStartFormTests(unittest.TestCase):
    def test_hot_starter_chosen_by_form_is_kept_at_the_first_pitch(self):
        from game_core.coaches import CoachTactics
        from game_core.match_contract import TeamMatchInput
        from game_core.match_simulator import MatchSimulator

        generator, sim = TeamStrengthGenerator(), MatchSimulator()
        opponent = replace(make_roster_abilities(school_id='FAKE-OPP')[0], throws='R')
        checked = 0
        for seed in range(2026100701, 2026100711):
            roster = tuple(make_roster_abilities(school_id='FAKE-A', seed=seed))
            plain_strength = generator.generate(roster)
            plain = plain_strength.starting_lineup
            by_id = {p.player_id: p for p in roster}
            # 加点がなければ、試合直前の入れ替えが起きないチームだけで確かめる
            # （左右の差のない入れ替えは、打撃の差だけで起きることがある。この変更とは別の話）
            kept = sim._initial_state(TeamMatchInput('FAKE-A', plain_strength, roster),
                                      plain.player_for_position('P'), opponent_pitcher=opponent)
            if set(plain.starter_ids) != {slot.player_id for slot in kept.batting_order}:
                continue
            for hot in roster:
                if hot.primary_position == 'P' or hot.player_id in plain.starter_ids:
                    continue
                bonus = {hot.player_id: 8.0}
                strength = generator.generate(roster, form_bonus=bonus)
                lineup = strength.starting_lineup
                if hot.player_id not in lineup.starter_ids:
                    continue
                position = next(e.defensive_position for e in lineup.entries if e.player_id == hot.player_id)
                original = by_id[plain.player_for_position(position)]
                # 加点がなければ、試合直前の比較で元の先発に戻される選手（全員右打ち・相手も右投手）
                if (sim._hitting_value(original, opponent) - sim._hitting_value(hot, opponent) < 3
                        or position in ('C', 'DH')):
                    continue
                team = TeamMatchInput('FAKE-A', strength, roster)
                tactics = CoachTactics(form_bonus=tuple(bonus.items()))
                state = sim._initial_state(team, lineup.player_for_position('P'),
                                           opponent_pitcher=opponent, tactics=tactics)
                start = {e.player_id: (e.batting_order, e.defensive_position)
                         for e in state.initial_lineup.entries}
                planned = {e.player_id: (e.batting_order, e.defensive_position) for e in lineup.entries}
                self.assertEqual(planned[hot.player_id], start.get(hot.player_id))
                checked += 1
        self.assertGreater(checked, 0)


class BridgeFormTests(unittest.TestCase):
    """試合の入口：先発・打順は調子を入れない能力で決め、試合の中身は調子入りの能力。"""

    def team(self, form_reliance, units):
        from test_coach_tactics import resolver

        f = books(50)
        book, rosters = f[1], f[3]
        coach = book.coaches['C-FAKE-A']
        book.coaches[coach.coach_id] = replace(coach, form_reliance=form_reliance, player_eye=100)
        players = rosters.roster(2026, 'FAKE-A').players
        for index, player in enumerate(players):
            state = rosters.state(player)
            state.form, state.form_day = units[index % len(units)], DAY
        bridge = resolver(f, DAY)
        return players, bridge.team_input(school_id='FAKE-A', reference_year=2026,
                                          generation_seed=7, competition_id='FAKE-CUP')

    def test_low_reliance_lineup_ignores_form_but_the_game_uses_it(self):
        _, plain = self.team(40, [0])
        for units in ([100, -100], [-100, 100], [100, 0, -100]):
            players, team = self.team(40, units)
            self.assertEqual(plain.team_strength.starting_lineup, team.team_strength.starting_lineup)
            self.assertEqual(plain.player_abilities, team.selection_abilities)
            hot = next(p for i, p in enumerate(players) if units[i % len(units)] == 100)
            playing = {a.player_id: a for a in team.player_abilities}[hot.player_id]
            base = {a.player_id: a for a in team.selection_abilities}[hot.player_id]
            self.assertEqual(min(100, base.contact + 3), playing.contact)

    def test_high_reliance_uses_the_form_it_sees(self):
        _, plain = self.team(100, [0])
        changed = 0
        for units in ([100, -100], [-100, 100], [100, 0, -100]):
            _, team = self.team(100, units)
            changed += plain.team_strength.starting_lineup != team.team_strength.starting_lineup
        self.assertGreater(changed, 0)


if __name__ == '__main__':
    unittest.main()
