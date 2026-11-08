"""部員の人数（game_core/roster_size.py）：新入部員・退部・最低人数・守備位置・ベンチ入り。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
import random
import statistics
import unittest

from game_core.roster_size import (
    RosterSizeModel, SizeContext, bench_score, free_numbers, roster_size_model, select_bench,
    standalone_floor_players,
)


@dataclass(frozen=True)
class _P:
    player_id: str
    primary_position: str
    academic_year: int = 2


class ExpectedFreshmenTests(unittest.TestCase):
    def setUp(self):
        self.model = roster_size_model()

    def target(self, ownership, z):
        return math.exp(self.model.target_appeal(ownership, z))

    def test_reputation_rank_and_private_raise_the_target(self):
        # 評判の順位が上ほど多い。中位では私立・公立の差は小さく、強豪では私立が大きく多い
        for ownership in ("private", "prefectural"):
            values = [self.target(ownership, z) for z in (-1.5, 0.0, 1.0, 2.0, 2.7)]
            self.assertEqual(values, sorted(values))
        self.assertLess(abs(self.target("private", 0.0) - self.target("prefectural", 0.0)), 1.0)
        self.assertGreater(self.target("private", 2.7), 1.5 * self.target("prefectural", 2.7))
        # 公立は強豪でも1学年20人前後まで
        self.assertLessEqual(self.target("prefectural", 3.5), 20.0)
        self.assertEqual(self.target("municipal", 2.0), self.target("prefectural", 2.0))

    def test_appeal_and_coach_raise_the_mean_a_little(self):
        base = self.model.expected_freshmen(appeal=math.log(10.0))
        self.assertAlmostEqual(10.0, base)
        self.assertGreater(self.model.expected_freshmen(appeal=math.log(10.0), coach_z=0.2), base)
        self.assertLess(self.model.expected_freshmen(appeal=math.log(10.0), coach_z=0.2) / base, 1.15)

    def test_draws_follow_the_mean_with_extra_spread(self):
        rng = random.Random(1)
        draws = [self.model.draw_freshmen(rng, 10.0) for _ in range(4000)]
        self.assertAlmostEqual(10.0, statistics.mean(draws), delta=0.4)
        # 負の二項：Poisson（分散=平均）より広い
        self.assertGreater(statistics.variance(draws), 11.0)
        self.assertLessEqual(max(self.model.draw_freshmen(rng, 200.0, maximum=26)
                                 for _ in range(50)), 26)
        self.assertEqual(42, self.model.max_freshmen("private"))
        self.assertEqual(26, self.model.max_freshmen("prefectural"))

    def test_strong_private_schools_vary_less(self):
        strong = self.model.stability("private", 2.7)
        middle = self.model.stability("private", 0.0)
        self.assertGreater(strong, self.model.stability("prefectural", 2.7))
        self.assertEqual(0.0, middle)
        rng = random.Random(2)
        steady = [self.model.draw_freshmen(rng, 25.0, stability=strong) for _ in range(3000)]
        loose = [self.model.draw_freshmen(rng, 25.0, stability=middle) for _ in range(3000)]
        self.assertAlmostEqual(25.0, statistics.mean(steady), delta=0.6)
        self.assertLess(statistics.pstdev(steady), 0.6 * statistics.pstdev(loose))

    def test_appeal_starts_near_the_reputation_and_follows_it_slowly(self):
        model = self.model
        first = model.initial_appeal_state(7, "SCH-A", 2026, ownership="private", reputation_z=2.7)
        self.assertEqual(round(model.target_appeal("private", 2.7), 6), first.anchor)
        # 評判が下がった次の年：目安は follow の割合だけ近づく（一気には下がらない）
        after = model.next_appeal_state(7, "SCH-A", 2027, first, ownership="private",
                                        reputation_z=0.0)
        follow = model.config["school_appeal"]["follow"]
        expected = first.anchor + (model.target_appeal("private", 0.0) - first.anchor) * follow
        self.assertAlmostEqual(expected, after.anchor, places=5)
        self.assertGreater(after.anchor, model.target_appeal("private", 0.0))
        # ずれは強豪の私立ほど小さい
        def spread(ownership, z):
            return statistics.pstdev(
                model.initial_appeal_state(7, f"SCH-{n}", 2026, ownership=ownership,
                                           reputation_z=z).deviation for n in range(800))
        self.assertLess(spread("private", 2.7), 0.6 * spread("private", 0.0))
        self.assertLess(spread("private", 2.7), spread("prefectural", 2.7))

    def test_school_appeal_changes_a_little_each_year(self):
        state = self.model.initial_appeal_state(7, "SCH-A", 2026, ownership="prefectural",
                                                reputation_z=0.0)
        values = [state.value]
        for year in range(2027, 2037):
            state = self.model.next_appeal_state(7, "SCH-A", year, state, ownership="prefectural",
                                                 reputation_z=0.0)
            values.append(state.value)
        steps = [abs(b - a) for a, b in zip(values, values[1:])]
        self.assertLess(max(steps), 0.5)


class MinimumAndPositionTests(unittest.TestCase):
    def setUp(self):
        self.model = roster_size_model()
        # 最低人数に当たりやすい学校（評判も集まりやすさも低い）
        self.small = SizeContext(reputation_z=lambda y: -2.5, appeal=lambda y: -1.2)

    def test_game_rosters_are_not_topped_up(self):
        # ゲームの名簿はかさ上げしない（足りない学校は連合チームを組む）
        self.assertEqual(0, self.model.config["minimum"]["players"])
        plans = [self.model.plan_freshmen(7, f"SCH-{n}", 2027, self.small, second_years=["SS"] * 3)
                 for n in range(40)]
        self.assertTrue(any(plan.count + 3 < 9 for plan in plans))
        self.assertFalse(any(plan.floor_hit for plan in plans))

    def test_standalone_rosters_are_topped_up(self):
        # 連合を組まない経路（名簿だけを試すとき）は新チームをそろえる
        standalone = replace(self.small, floor_players=standalone_floor_players())
        hits = 0
        for n in range(40):
            school = f"SCH-{n}"
            second = ["SS"] * 3
            plan = self.model.plan_freshmen(7, school, 2027, standalone, second_years=second)
            self.assertGreaterEqual(plan.count + len(second), standalone_floor_players())
            hits += plan.floor_hit
            positions = self.model.positions(7, school, 2027, list(range(1, plan.count + 1)),
                                             second_years=second)
            self.assertGreaterEqual(positions.count("P"), 2)
            self.assertGreaterEqual(positions.count("C"), 1)
        self.assertGreater(hits, 0)

    def test_catcher_is_taken_from_extra_pitchers(self):
        # 新入部員が全員投手に引かれても、最低人数を超える投手から捕手に振り替える
        config = deepcopy(roster_size_model().config)
        for position in config["positions"]:
            if position != "rng_namespaces" and isinstance(config["positions"][position], float):
                config["positions"][position] = 0.0
        config["positions"]["P"] = 1.0
        model = RosterSizeModel(config)
        for second in ([], ["P"] * 5, ["SS"] * 9):
            # plan_freshmen と同じく、足りない投手・捕手の人数以上は入部する
            need = max(0, 2 - second.count("P")) + max(0, 1 - second.count("C"))
            count = max(need, 10 - len(second))
            out = model.positions(7, "SCH-A", 2027, list(range(1, count + 1)), second_years=second)
            team = [*second, *out]
            self.assertGreaterEqual(team.count("P"), 2, second)
            self.assertGreaterEqual(team.count("C"), 1, second)

    def test_minimum_is_not_used_when_not_asked(self):
        plans = [self.model.plan_freshmen(7, f"SCH-{n}", 2024, self.small, enforce_minimum=False)
                 for n in range(40)]
        self.assertTrue(any(plan.count < 10 for plan in plans))
        self.assertFalse(any(plan.floor_hit for plan in plans))

    def test_positions_are_drawn_per_member_number(self):
        a = self.model.positions(7, "SCH-A", 2027, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                                 enforce_minimum=False)
        b = self.model.positions(7, "SCH-A", 2027, [3, 4], enforce_minimum=False)
        self.assertEqual(a[2:4], b)
        many = self.model.positions(7, "SCH-B", 2027, list(range(1, 201)), enforce_minimum=False)
        self.assertAlmostEqual(0.27, many.count("P") / 200, delta=0.08)
        self.assertEqual(set(many), {"P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"})

    def test_free_numbers_fill_gaps_first(self):
        self.assertEqual([2, 4, 6], free_numbers([1, 3, 5], 3))


class WithdrawalTests(unittest.TestCase):
    def test_weaker_schools_lose_a_few_more_players(self):
        model = roster_size_model()
        self.assertGreater(model.withdrawal_chance(-2.0), model.withdrawal_chance(2.0))
        self.assertLessEqual(model.withdrawal_chance(-10.0), model.config["withdrawal"]["max"])
        quits = sum(model.withdraws(7, "SCH-A", 2027, 2026, n, 0.0) for n in range(4000))
        self.assertAlmostEqual(model.withdrawal_chance(0.0), quits / 4000, delta=0.01)

    def test_zero_rate_keeps_everyone(self):
        config = deepcopy(roster_size_model().config)
        config["withdrawal"]["base"] = 0.0
        model = RosterSizeModel(config)
        self.assertFalse(any(model.withdraws(7, "SCH-A", 2027, 2026, n, -2.0) for n in range(200)))


class BenchTests(unittest.TestCase):
    def players(self):
        out = [_P(f"P{i:02d}", "P") for i in range(6)]
        out += [_P(f"C{i:02d}", "C") for i in range(3)]
        out += [_P(f"F{i:02d}", "SS") for i in range(30)]
        return out

    def test_bench_keeps_pitchers_catchers_and_the_best(self):
        players = self.players()
        # 野手が強く、投手・捕手は弱い
        score = {p.player_id: (90 - i if p.primary_position == "SS" else 10 - i)
                 for i, p in enumerate(players)}
        bench = select_bench(players, lambda p: score[p.player_id])
        self.assertEqual(20, len(bench))
        self.assertEqual(4, sum(p.primary_position == "P" for p in bench))
        self.assertEqual(2, sum(p.primary_position == "C" for p in bench))
        # 名簿の順を保つ
        self.assertEqual([p for p in players if p in bench], list(bench))
        self.assertIn(players[9], bench)  # 野手でいちばん強い
        self.assertNotIn(players[-1], bench)

    def test_small_rosters_are_unchanged(self):
        players = self.players()[:15]
        self.assertEqual(tuple(players), select_bench(players, lambda p: 0))

    def test_bench_score_uses_pitching_for_pitchers(self):
        from game_core.abilities import PlayerAbilityGenerator
        from game_core.players import PlayerRosterGenerator
        from phase2_engine.models import Team

        team = Team("SCH-T", "PRG-T", "架空高校", "13")
        roster = PlayerRosterGenerator().generate_school(team, 2026, 7)
        abilities = PlayerAbilityGenerator()
        for player in roster.players[:6]:
            snapshot = abilities.generate(player, 2026, 7)
            score = bench_score(snapshot)
            self.assertGreater(score, 0)


class ProspectCountTests(unittest.TestCase):
    def test_prospect_count_does_not_grow_with_the_number_of_freshmen(self):
        from game_core.school_intake import SchoolAwarePlayerAbilityGenerator

        generator = SchoolAwarePlayerAbilityGenerator()
        profile = generator.intake_model.profile(school_id="SCH-T", entry_year=2027, base_seed=7)
        count = generator.prospect_count(profile, 7)
        small = generator.prospects(profile, range(1, 11), 7)
        large = generator.prospects(profile, range(1, 41), 7)
        self.assertEqual(min(count, 10), len(small))
        self.assertEqual(min(count, 40), len(large))


if __name__ == "__main__":
    unittest.main()
