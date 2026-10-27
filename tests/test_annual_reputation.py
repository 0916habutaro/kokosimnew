"""年度評判：架空の確定成績、年度境界、入学・保存の再現性。"""
from datetime import date
from pathlib import Path
import pickle
from types import SimpleNamespace
import unittest

from game_core.annual_reputation import AnnualReputation
from game_core.roster_book import RosterBook
from game_core.school_reputation import reputation_for
from phase2_engine.career_state import CareerState
from phase2_engine.models import Team

ROOT = Path(__file__).resolve().parents[1]


def reputation(seed=7):
    book = AnnualReputation(ROOT, seed)
    book.values = {'SCH-A': -1., 'SCH-B': 1., 'SCH-C': 0.}
    book.intake_by_year = {2026: dict(book.values)}
    return book


def season(completed=True, day='2027-03-31'):
    outcome = SimpleNamespace(
        champion_school_id='SCH-A', runner_up_school_id='SCH-C',
        semifinalist_school_ids=['SCH-B'], quarterfinalist_school_ids=[],
    )
    run = SimpleNamespace(entrant_school_ids=['SCH-A', 'SCH-B', 'SCH-C'], outcome=outcome)
    tournament = SimpleNamespace(
        is_complete=completed, to_competition_run=lambda: run,
        matches={'final': SimpleNamespace(completed_on=day)},
    )
    return SimpleNamespace(
        competitions={'CUP': tournament},
        repo=SimpleNamespace(competitions={'CUP': {'competition_type': 'summer_local_qualifier'}}),
    )


class AnnualReputationTests(unittest.TestCase):
    def test_initial_values_and_ranks_are_exactly_the_existing_values(self):
        initial = reputation_for(str(ROOT))
        saved = AnnualReputation(ROOT, 7)
        for sid in initial.school_ids:
            self.assertEqual(initial.program_z(sid, 7), saved.program_z(sid, 2026))
            self.assertEqual(initial.program_z(sid, 7), saved.program_z(sid, 2024))
        # ランクの各境界も含む全校を一度に比較する。
        order = sorted(saved.values, key=lambda sid: (saved.values[sid], sid))
        for i, sid in enumerate(order):
            expected = next(label for label, minimum in saved.rank_labels
                            if (i + .5) / len(order) >= minimum)
            self.assertEqual(initial.rank(sid, 7), expected)
            if i % 100 == 0 or i == len(order) - 1:
                self.assertEqual(initial.rank(sid, 7), saved.rank(sid))
        self.assertFalse(saved.update(date(2026, 4, 1)))

    def test_better_results_raise_reputation_more_from_equal_starting_values(self):
        book = reputation()
        book.values = dict.fromkeys(book.values, 0.0)
        book.collect({2026: season()})
        book.update(date(2027, 4, 1))
        self.assertGreater(book.values['SCH-A'], book.values['SCH-C'])
        self.assertGreater(book.values['SCH-C'], book.values['SCH-B'])

    def test_success_improves_reputation_and_several_years_reverse_the_order(self):
        book = reputation()
        start = dict(book.values)
        for year in range(2027, 2037):
            book.collect({year - 1: season(day=f'{year}-03-31')})
            self.assertTrue(book.update(date(year, 4, 1)))
            self.assertLessEqual(max(abs(book.values[s] - start[s]) for s in start),
                                 (year - 2026) * book.config['max_annual_change_z'] + 1e-12)
            if year == 2027:
                self.assertGreater(book.values['SCH-A'] - start['SCH-A'],
                                   book.values['SCH-B'] - start['SCH-B'])
                self.assertLess(book.values['SCH-A'], book.values['SCH-B'])
        self.assertGreater(book.values['SCH-A'], book.values['SCH-B'])

    def test_unfinished_march_cup_waits_until_next_april_and_is_counted_once(self):
        book = reputation()
        cup = season(completed=False)
        book.collect({2027: cup})
        self.assertFalse(book.pending)
        book.update(date(2027, 4, 1))
        self.assertNotIn((2027, 'CUP'), book.counted)
        cup.competitions['CUP'].is_complete = True
        cup.competitions['CUP'].matches['final'].completed_on = '2027-04-04'
        book.collect({2027: cup})
        book.collect({2027: cup})
        self.assertEqual(1, len(book.pending))
        self.assertFalse(book.update(date(2027, 4, 5)))
        saved = pickle.loads(pickle.dumps(book))
        for each in (book, saved):
            each.update(date(2028, 4, 1))
            self.assertFalse(each.pending)
            self.assertEqual({(2027, 'CUP')}, each.counted)
            values = dict(each.values)
            each.collect({2027: cup})
            self.assertFalse(each.update(date(2028, 4, 1)))
            self.assertEqual(values, each.values)
            self.assertFalse(each.pending)
        self.assertEqual(book.__dict__, saved.__dict__)

    def test_april_first_completion_is_excluded_and_year_ids_are_distinct(self):
        book = reputation()
        book.collect({2026: season(day='2027-04-01')})
        book.update(date(2027, 4, 1))
        self.assertEqual(1, len(book.pending))
        book.collect({2027: season(day='2028-03-31')})
        book.update(date(2028, 4, 1))
        self.assertEqual({(2026, 'CUP'), (2027, 'CUP')}, book.counted)

    def test_same_seed_same_actions_and_resume_are_identical(self):
        left, right = reputation(19), reputation(19)
        for year in range(2027, 2032):
            for book in (left, right):
                book.collect({year - 1: season(day=f'{year}-03-31')})
                book.update(date(year, 4, 1))
            right = pickle.loads(pickle.dumps(right))
        self.assertEqual(left.__dict__, right.__dict__)

    def test_update_alone_preserves_players_and_changes_only_new_intake(self):
        teams = {sid: Team(sid, 'P-' + sid, '架空高校' + sid[-1], '13')
                 for sid in ('SCH-A', 'SCH-B', 'SCH-C')}
        rep = reputation()
        rosters = RosterBook(teams.__getitem__, first_year=2026, career_seed=7)
        rosters.reputation = rep
        old = rosters.roster(2026, 'SCH-A')
        abilities = [rosters.ability(p) for p in old.players]
        profile = rosters.ability_generator.intake_model.profile
        before = profile(school_id='SCH-A', entry_year=2026, base_seed=7)
        # 条件をそろえ、同一入学年・同一選手の能力で評判だけを変える比較対象。
        control = pickle.loads(pickle.dumps(rosters))
        control.bind(teams.__getitem__)
        control.reputation.intake_by_year[2027] = dict(rep.values)
        rep.collect({2026: season()})
        rep.update(date(2027, 4, 1))
        self.assertEqual(abilities, [rosters.ability(p) for p in old.players])
        self.assertEqual(before, profile(school_id='SCH-A', entry_year=2026, base_seed=7))
        updated_profile = profile(school_id='SCH-A', entry_year=2027, base_seed=7)
        control_profile = control.ability_generator.intake_model.profile(
            school_id='SCH-A', entry_year=2027, base_seed=7,
        )
        self.assertEqual(updated_profile.cohort_quality_z, control_profile.cohort_quality_z)
        new = rosters.roster(2027, 'SCH-A')
        other = control.roster(2027, 'SCH-A')
        fresh = [p for p in new.players if p.entry_year == 2027]
        self.assertEqual(new, other)
        self.assertGreater(sum(rosters.ability(p).contact for p in fresh),
                           sum(control.ability(p).contact for p in fresh))
        returned = [p for p in new.players if p.entry_year < 2027]
        by_id = dict(zip((p.player_id for p in old.players), abilities))
        self.assertTrue(all(rosters.ability(p).contact == by_id[p.player_id].contact for p in returned))

    def test_career_updates_before_growth_can_generate_april_newcomers(self):
        rep = reputation()
        fake = season()
        fake.start_date = fake.current_date = date(2027, 3, 31)
        fake.play_today = lambda: []
        fake.calendar_rows = {}
        fake.annual_templates = {}
        observed = []
        rosters = SimpleNamespace(grow=lambda _: observed.append(rep.updated_year), set_today=lambda _: None)
        state = CareerState({2026: fake}, current_date=fake.current_date, reputation=rep, rosters=rosters)
        state.next_day()
        self.assertEqual([2027], observed)
        self.assertEqual(2027, rep.updated_year)
        self.assertEqual({(2026, 'CUP')}, rep.counted)


if __name__ == '__main__':
    unittest.main()
