"""選手の怪我（game_core/injuries.py と名簿 roster_book.py）。架空の学校で確かめる。"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import pickle
import random
import unittest

from game_core.injuries import Injury, InjuryModel
from game_core.roster_book import RosterBook
from phase2_engine.models import Team


TEAMS = {
    "SCH-A": Team("SCH-A", "PRG-A", "架空第一高校", "13"),
    "SCH-B": Team("SCH-B", "PRG-B", "架空第二高校", "27"),
}


def _book(level="normal"):
    book = RosterBook(TEAMS.__getitem__, first_year=2026, career_seed=7, school_ids=tuple(TEAMS))
    book.injury_level = level
    return book


class InjuryModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = InjuryModel()

    def test_levels_scale_the_chance(self):
        chances = [
            self.model.practice_chance(pitcher=False, season_games=0, level=level)
            for level in ("none", "low", "normal", "high")
        ]
        self.assertEqual(0.0, chances[0])
        self.assertAlmostEqual(chances[2] * 0.5, chances[1])
        self.assertAlmostEqual(chances[2] * 2, chances[3])

    def test_pitchers_overuse_and_back_to_back_raise_the_chance(self):
        batter, _ = self.model.match_chance(pitches=0, load7=0, consecutive=0, level="normal")
        light, overuse = self.model.match_chance(pitches=80, load7=80, consecutive=0, level="normal")
        self.assertFalse(overuse)
        heavy, overuse = self.model.match_chance(pitches=150, load7=420, consecutive=2, level="normal")
        self.assertTrue(overuse)
        self.assertGreater(light, batter)
        self.assertGreater(heavy, light * 4)
        busy = self.model.practice_chance(pitcher=True, season_games=20, level="normal")
        idle = self.model.practice_chance(pitcher=True, season_games=0, level="normal")
        self.assertGreater(busy, idle)

    def test_severity_and_recovery(self):
        rng = random.Random(1)
        draws = [self.model.draw(rng, date(2026, 5, 1)) for _ in range(20000)]
        counts = Counter(d.severity for d in draws)
        self.assertGreater(counts[1], counts[2] > counts[3])
        self.assertLess(counts[3] / len(draws), 0.03)
        for d in draws[:200]:
            low, high = self.model.config["severity"][("days", "weeks", "months")[d.severity - 1]]["days_range"]
            self.assertTrue(low <= d.days <= high)
        injury = Injury(date(2026, 5, 1), 60, 3)
        self.assertEqual(0, self.model.recovery_step(injury, date(2026, 5, 10)))  # 休んでいる間
        steps = [self.model.recovery_step(injury, injury.end + timedelta(days=d)) for d in range(0, 35, 7)]
        self.assertEqual(steps, sorted(steps, reverse=True))
        self.assertGreater(steps[0], 0)
        self.assertEqual(0, steps[-1])


class RosterInjuryTests(unittest.TestCase):
    def test_injured_player_rests_does_not_grow_and_recovers(self):
        book = _book()
        players = book.roster(2026, "SCH-A").players
        player = players[0]
        injury = Injury(date(2026, 5, 3), 20, 2)
        book.state(player).injuries.append(injury)
        self.assertEqual(injury, book.injury(player, date(2026, 5, 10)))
        self.assertIsNone(book.injury(player, date(2026, 5, 23)))
        self.assertEqual((True, 0), book.condition(player, date(2026, 5, 10)))
        # 同じ選手を怪我なしで成長させたときと比べる（怪我で休んだ日の分は伸びない）
        healthy = _book()
        healthy.roster(2026, "SCH-A")
        before = bytes(book.state(player).values)
        book.grow(date(2026, 5, 31))
        healthy.grow(date(2026, 5, 31))
        grew = sum(a - b for a, b in zip(book.state(player).values, before))
        healthy_grew = sum(a - b for a, b in zip(healthy.state(player).values, before))
        self.assertLess(grew, healthy_grew)
        # 復帰直後は少し下がり、数週間で戻る
        book.set_today(injury.end)
        dropped = book.ability(player)
        book.set_today(injury.end + timedelta(days=30))
        back = book.ability(player)
        self.assertLess(dropped.contact, back.contact)
        self.assertEqual(book.state(player).values[0], back.contact)

    def test_an_earlier_injury_added_later_does_not_hide_a_planned_one(self):
        book = _book()
        player = book.roster(2026, "SCH-A").players[0]
        state = book.state(player)
        # 月の初めに決めた練習の怪我（9/12から）のあとで、試合の怪我（9/6から3日）が入る
        planned = Injury(date(2026, 9, 12), 10, 2)
        state.injuries.append(planned)
        state.injuries.append(Injury(date(2026, 9, 6), 3, 1))
        self.assertEqual(planned, book.injury(player, date(2026, 9, 12)))
        self.assertEqual((True, 0), book.condition(player, date(2026, 9, 13)))
        # 9/9 に治った怪我の復帰直後
        self.assertGreater(book.condition(player, date(2026, 9, 10))[1], 0)

    def test_practice_injuries_follow_the_level_and_are_saved(self):
        counts = {}
        for level in ("none", "normal", "high"):
            book = _book(level)
            for school in TEAMS:
                book.roster(2026, school)
            for month in range(4, 13):
                book.grow(date(2026, month, 28))
            counts[level] = sum(
                len(book.state(p).injuries)
                for school in TEAMS for p in book.roster(2026, school).players
            )
            if level == "high":
                loaded = pickle.loads(pickle.dumps(book))
                loaded.bind(TEAMS.__getitem__)
                for school in TEAMS:
                    for p in book.roster(2026, school).players:
                        self.assertEqual(book.state(p).injuries, loaded.state(p).injuries)
                self.assertEqual("high", loaded.injury_level)
        self.assertEqual(0, counts["none"])
        self.assertGreaterEqual(counts["high"], counts["normal"])

    def test_heavy_pitching_injures_more_often(self):
        book = _book("high")
        pitchers = [p for p in book.roster(2026, "SCH-A").players if p.primary_position == "P"]
        rng = random.Random(3)
        light = heavy = 0
        for i in range(400):
            day = date(2026, 6, 1) + timedelta(days=i)
            for p in pitchers:
                book.state(p).injuries.clear()
            light += len(book.after_game([(pitchers[0], 70, 70, 0)], day=day, rng=rng))
            heavy += len(book.after_game([(pitchers[1], 160, 450, 2)], day=day, rng=rng))
        self.assertGreater(heavy, light * 3)


if __name__ == "__main__":
    unittest.main()
