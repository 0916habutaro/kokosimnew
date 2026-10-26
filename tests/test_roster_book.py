"""セーブに入る名簿（game_core/roster_book.py）。架空の学校で確かめる。"""
from __future__ import annotations

from dataclasses import replace
import pickle
import unittest

from game_core.roster_book import RosterBook
from phase2_engine.models import Team


TEAMS = {
    "SCH-A": Team("SCH-A", "PRG-A", "架空第一高校", "13"),
    "SCH-B": Team("SCH-B", "PRG-B", "架空第二高校", "47"),
}


class _NoGeneration:
    """読み込んだ名簿で能力をつくり直していないことを確かめる。"""

    def generate(self, *args):
        raise AssertionError("abilities must come from the save")

    def __getattr__(self, name):
        if name == "base_generator":
            from game_core.abilities import PlayerAbilityGenerator

            return PlayerAbilityGenerator()
        raise AttributeError(name)


def _book():
    return RosterBook(TEAMS.__getitem__, first_year=2026, career_seed=7)


class RosterBookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = _book()
        for school_id in TEAMS:
            cls.book.roster(2027, school_id)

    def _loaded(self, book):
        loaded = pickle.loads(pickle.dumps(book))
        loaded.bind(TEAMS.__getitem__, ability_generator=_NoGeneration())
        return loaded

    def test_saved_rosters_and_abilities_are_restored_without_regeneration(self):
        loaded = self._loaded(self.book)
        for year in (2026, 2027):
            for school_id in TEAMS:
                roster = self.book.roster(year, school_id)
                again = loaded.roster(year, school_id)
                self.assertEqual(roster.to_dict(), again.to_dict())
                for player, other in zip(roster.players, again.players):
                    self.assertEqual(self.book.ability(player), loaded.ability(other))

    def test_promotion_keeps_identity_and_adds_the_grade_difference(self):
        before = {p.player_id: p for p in self.book.roster(2026, "SCH-A").players}
        after = self.book.roster(2027, "SCH-A").players
        returning = [p for p in after if p.player_id in before]
        newcomers = [p for p in after if p.player_id not in before]
        self.assertEqual(12, len(returning))
        self.assertEqual(8, len(newcomers))
        self.assertTrue(all(p.academic_year == 1 for p in newcomers))
        names = [p.display_name for p in after]
        self.assertEqual(len(names), len(set(names)))
        for player in returning:
            old = before[player.player_id]
            self.assertEqual(
                (old.display_name, old.hometown_prefecture_code),
                (player.display_name, player.hometown_prefecture_code),
            )
            then, now = self.book.ability(old), self.book.ability(player)
            # grade_adjustment（1年 -5・2年 0・3年 +5）の差を足す
            self.assertEqual(min(100, then.contact + 5), now.contact)
            self.assertEqual(then.position_aptitude, now.position_aptitude)
            self.assertEqual(2027, now.reference_year)

    def test_march_before_the_first_year_uses_the_first_abilities_one_grade_back(self):
        first = self.book.roster(2026, "SCH-B")
        before = self.book.roster(2025, "SCH-B")
        self.assertEqual(15, len(before.players))
        by_id = {p.player_id: p for p in first.players}
        for player in before.players:
            now = self.book.ability(by_id[player.player_id])
            then = self.book.ability(player)
            self.assertEqual(max(1, now.contact - 5), then.contact)
            self.assertEqual(player.academic_year, then.academic_year)

    def test_forgetting_a_closed_year_keeps_the_next_year(self):
        book = _book()
        book.roster(2026, "SCH-A")
        book.roster(2026, "SCH-B")
        kept = book.roster(2027, "SCH-A").to_dict()
        book.forget(2026)
        self.assertEqual([2027], book.years())
        self.assertEqual(kept, book.roster(2027, "SCH-A").to_dict())
        # 翌年度の名簿は手放す前に全校分つくってある
        self.assertEqual(["SCH-A", "SCH-B"], book.schools(2027))
        for year in (2025, 2026):
            with self.assertRaisesRegex(ValueError, "closed|before"):
                book.roster(year, "SCH-A")
        loaded = self._loaded(book)
        self.assertEqual(kept, loaded.roster(2027, "SCH-A").to_dict())

    def test_same_seed_gives_the_same_book(self):
        other = _book()
        for school_id in TEAMS:
            roster = other.roster(2027, school_id)
            self.assertEqual(self.book.roster(2027, school_id).to_dict(), roster.to_dict())
            player = roster.players[0]
            self.assertEqual(
                self.book.ability(player),
                other.ability(replace(player)),
            )


if __name__ == "__main__":
    unittest.main()
