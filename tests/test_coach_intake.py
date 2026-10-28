"""監督評判は入学時だけに適用し、学校成分と潜在能力から分離する。"""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
import pickle
import unittest

from game_core.annual_reputation import AnnualReputation
from game_core.coaches import Coach, CoachBook
from game_core.roster_book import RosterBook
from phase2_engine.models import Team

ROOT = Path(__file__).resolve().parents[1]


class Repository:
    def __init__(self):
        self.schools = {s: {} for s in ('FAKE-A', 'FAKE-B', 'FAKE-C')}

    def team(self, sid):
        return Team(sid, 'P-' + sid, '架空高校' + sid[-1], '13')

    def ownership_type(self, sid):
        return 'prefectural'


def books(reputation=80, *, zero=False, fixed=False):
    repo = Repository()
    coaches = CoachBook([Coach('C-' + sid, '架空 監督' + sid[-1], 1980, sid, 2020,
                               reputation if sid == 'FAKE-A' else 50, 50, 50, 50)
                         for sid in repo.schools], seed=7)
    for group in ('public', 'private'):
        coaches.config['transfer'][group] = [[1, 0.0]]
        coaches.config['retirement'][group]['maximum_bonus'] = 0.0
    coaches.config['retirement']['age_probabilities'] = [[40, 0.0]]
    if zero:
        coaches.intake_config['max_abs_z'] = 0.0
    rep = AnnualReputation(ROOT, 7)
    rep.values = dict.fromkeys(repo.schools, 0.0)
    rep.intake_by_year = {2026: dict(rep.values)}
    if fixed:
        for sid in repo.schools:
            rep.edit(sid, 0.0, 'fixed', '2026-05-01', minimum=-3.5, maximum=3.5)
    rosters = RosterBook(repo.team, first_year=2026, career_seed=7)
    rosters.reputation = rep
    rosters.coaches = coaches
    rosters.injury_level = 'none'
    return repo, coaches, rep, rosters


def annual(fixture, year):
    repo, coaches, reputation, _ = fixture
    coaches.update(date(year, 4, 1), repo)
    coaches.finalize_intake(year)
    reputation.update(date(year, 4, 1))


def freshmen(rosters, year, sid='FAKE-A'):
    return [p for p in rosters.roster(year, sid).players if p.entry_year == year]


def abilities(rosters, players):
    return [rosters.base_ability(p) for p in players]


class CoachIntakeTests(unittest.TestCase):
    def test_neutral_is_zero_and_effect_is_bounded_monotone(self):
        effects = []
        for reputation in (1, 20, 50, 80, 100):
            f = books(reputation)
            annual(f, 2027)
            cid, saved, z = f[1].intake_for('FAKE-A', 2027)
            self.assertEqual('C-FAKE-A', cid)
            self.assertEqual(reputation, saved)
            self.assertLessEqual(abs(z), .20)
            effects.append(z)
        self.assertEqual(0, effects[2])
        self.assertEqual(sorted(effects), effects)
        self.assertEqual(.12, effects[3])
        self.assertEqual(-.12, effects[1])

    def test_initial_players_and_random_cohort_are_unchanged(self):
        f, control = books(80), books(80, zero=True)
        left, right = f[3], control[3]
        for sid in f[0].schools:
            a, b = left.roster(2026, sid), right.roster(2026, sid)
            self.assertEqual(a, b)
            self.assertEqual(abilities(left, a.players), abilities(right, b.players))
        annual(f, 2027)
        annual(control, 2027)
        a = left.ability_generator.intake_model.profile(school_id='FAKE-A', entry_year=2027, base_seed=7)
        b = right.ability_generator.intake_model.profile(school_id='FAKE-A', entry_year=2027, base_seed=7)
        self.assertEqual(a.program_quality_z, b.program_quality_z)
        self.assertEqual(a.cohort_quality_z, b.cohort_quality_z)
        self.assertAlmostEqual(.12, a.intake_quality_z-b.intake_quality_z, places=5)
        self.assertEqual((None, None, 0.0), f[1].intake_for('FAKE-A', 2026))

    def test_high_reputation_raises_freshmen_without_changing_potential(self):
        high, low = books(80), books(20)
        for f in (high, low):
            annual(f, 2027)
        a, b = freshmen(high[3], 2027), freshmen(low[3], 2027)
        self.assertEqual(a, b)
        av, bv = abilities(high[3], a), abilities(low[3], b)
        self.assertTrue(all(x.contact >= y.contact for x, y in zip(av, bv)))
        self.assertGreater(sum(x.contact for x in av), sum(x.contact for x in bv))
        self.assertGreater(sum(x.power for x in av), sum(x.power for x in bv))
        for p in a:
            x, y = high[3].state(p), low[3].state(p)
            self.assertEqual((x.growth_type, x.potential), (y.growth_type, y.potential))

    def test_transfer_follows_person_and_successor_while_old_students_stay(self):
        f = books(80)
        annual(f, 2027)
        repo, coaches, _, rosters = f
        before = rosters.roster(2027, 'FAKE-A').players
        old_values = abilities(rosters, before)
        coaches.config['transfer']['public'] = [[1, 1.0]]
        annual(f, 2028)
        destination = coaches.coaches['C-FAKE-A'].school_id
        self.assertNotEqual('FAKE-A', destination)
        self.assertEqual(('C-FAKE-A', 80, .12), coaches.intake_for(destination, 2028))
        self.assertEqual(50, coaches.intake_for('FAKE-A', 2028)[1])
        self.assertEqual(('C-FAKE-A', 80, .12), coaches.intake_for('FAKE-A', 2027))
        self.assertEqual(old_values, abilities(rosters, before))
        for sid in repo.schools:
            rosters.roster(2027, sid)
            for p in freshmen(rosters, 2028, sid):
                profile = rosters.ability_generator.intake_model.profile(school_id=sid, entry_year=p.entry_year, base_seed=7)
                self.assertEqual(coaches.for_school(sid, date(2028, 4, 1)).coach_id, profile.coach_id)
        # 在任者が退任した次の年度は後任の評判を使い、旧年度は維持する。
        coaches.coaches['C-FAKE-A'] = replace(coaches.coaches['C-FAKE-A'], birth_year=1940)
        annual(f, 2029)
        current = coaches.for_school(destination)
        self.assertNotEqual('C-FAKE-A', current.coach_id)
        self.assertEqual(current.coach_id, coaches.intake_for(destination, 2029)[0])
        self.assertEqual(('C-FAKE-A', 80, .12), coaches.intake_for(destination, 2028))

    def test_delayed_generation_and_load_use_entry_coach_and_frozen_rating(self):
        early, delayed = books(80), books(80)
        for f in (early, delayed):
            annual(f, 2027)
        expected = abilities(early[3], freshmen(early[3], 2027))
        for f in (early, delayed):
            f[1].config['transfer']['public'] = [[1, 1.0]]
            # 入学後の評判が変わっても、確定済み年度を書き換えない。
            old = f[1].coaches['C-FAKE-A']
            f[1].coaches[old.coach_id] = replace(old, reputation=20)
            annual(f, 2028)
        repo, coaches, rep, saved = delayed
        loaded = pickle.loads(pickle.dumps(saved))
        loaded.bind(repo.team)
        self.assertEqual(expected, abilities(loaded, freshmen(loaded, 2027)))
        self.assertEqual(('C-FAKE-A', 80, .12), loaded.coaches.intake_for('FAKE-A', 2027))
        self.assertEqual(2, len(loaded.coaches.intake_ratings['C-FAKE-A']))
        destination = coaches.coaches['C-FAKE-A'].school_id
        self.assertEqual(('C-FAKE-A', 20, -.12), loaded.coaches.intake_for(destination, 2028))
        self.assertFalse(loaded.coaches.finalize_intake(2028))

    def test_fixed_school_reputation_remains_independent(self):
        high, low = books(80, fixed=True), books(20, fixed=True)
        for f in (high, low):
            annual(f, 2027)
        self.assertEqual(high[2].__dict__, low[2].__dict__)
        a = abilities(high[3], freshmen(high[3], 2027))
        b = abilities(low[3], freshmen(low[3], 2027))
        self.assertGreater(sum(x.contact for x in a), sum(x.contact for x in b))
        self.assertEqual(0.0, high[2].values['FAKE-A'])

    def test_generation_order_does_not_change_players_and_ratings_are_not_copied_each_year(self):
        f, g = books(), books()
        for year in (2027, 2028, 2029):
            annual(f, year)
            annual(g, year)
            for sid in f[0].schools:
                f[3].roster(year, sid)
            for sid in reversed(g[0].schools):
                g[3].roster(year, sid)
        for sid in f[0].schools:
            a, b = f[3].roster(2029, sid), g[3].roster(2029, sid)
            self.assertEqual(a, b)
            self.assertEqual(abilities(f[3], a.players), abilities(g[3], b.players))
        self.assertEqual(f[1].intake_ratings, g[1].intake_ratings)
        self.assertTrue(all(len(v) == 1 for v in f[1].intake_ratings.values()))

    def test_ability_edit_and_growth_do_not_add_the_coach_bonus_again(self):
        high, low = books(80), books(20)
        for f in (high, low):
            annual(f, 2027)
        a, b = freshmen(high[3], 2027)[0], freshmen(low[3], 2027)[0]
        edited = replace(low[3].base_ability(b), contact=75, power=73)
        for f, player in ((high, a), (low, b)):
            f[3].edit_abilities([player], [edited], day='2027-04-02', source='test')
            self.assertEqual(75, f[3].base_ability(player).contact)
            f[3].grow(date(2027, 4, 30))
        self.assertEqual(high[3].state(a).values, low[3].state(b).values)
        self.assertEqual(high[3].state(a).potential, low[3].state(b).potential)
        saved = pickle.loads(pickle.dumps(high[3]))
        saved.bind(high[0].team)
        self.assertEqual(high[3].state(a).values, saved.state(a).values)

    def test_unfinalized_future_is_rejected_and_combined_clip_is_unchanged(self):
        f = books(100)
        with self.assertRaisesRegex(ValueError, 'not finalized'):
            f[1].intake_for('FAKE-A', 2027)
        with self.assertRaises(ValueError):
            f[1].finalize_intake(2027)
        annual(f, 2027)
        model = f[3].ability_generator.intake_model
        model.params = deepcopy(model.params)
        model.params['quality_model']['program_component']['weight'] = 1000
        f[2].intake_by_year[2027]['FAKE-A'] = 2.0
        profile = model.profile(school_id='FAKE-A', entry_year=2027, base_seed=7)
        self.assertEqual(3.5, profile.intake_quality_z)
        self.assertEqual(.2, profile.coach_quality_z)
        f[2].intake_by_year[2027]['FAKE-A'] = -2.0
        self.assertEqual(-3.5, model.profile(school_id='FAKE-A', entry_year=2027, base_seed=7).intake_quality_z)


if __name__ == '__main__':
    unittest.main()
