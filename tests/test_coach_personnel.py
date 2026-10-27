"""監督人事：全国配置、所属イベント、日付参照、再開と乱数分離。"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
import pickle
import random
import statistics
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from game_core.coaches import Coach, CoachBook
from phase2_engine import DataRepository, LiveGameService
from phase2_engine.career_state import CareerState
from phase2_engine.models import Team
from phase2_engine.screen.data import GameScreenData

ROOT = Path(__file__).resolve().parents[1]


class FakeRepository:
    def __init__(self, specifications):
        self.schools = {sid: {"ownership_type": owner, "prefecture_code": pref}
                        for sid, pref, owner in specifications}

    def team(self, sid):
        return Team(sid, "FAKE-P-" + sid, "架空高校" + sid, self.schools[sid]["prefecture_code"])

    def ownership_type(self, sid):
        return self.schools[sid]["ownership_type"]


def fixture(specifications=None):
    specifications = specifications or [(s, "13", "prefectural") for s in ("A", "B", "C")]
    repo = FakeRepository(specifications)
    coaches = [Coach("COACH-" + sid, "架空 監督" + sid, 1976, sid, 2016, 50, 40, 60, 30)
               for sid in repo.schools]
    book = CoachBook(coaches, seed=7)
    # 退任を抑え、異動だけを必ず発生させる。年齢上限は別のテストで確認する。
    book.config = deepcopy(book.config)
    book.config["retirement"]["age_probabilities"] = [[40, 0.0]]
    for group in ("public", "private"):
        book.config["retirement"][group]["maximum_bonus"] = 0.0
        book.config["transfer"][group] = [[1, 1.0]]
    return repo, book


def identity(coach):
    return (coach.coach_id, coach.display_name, coach.birth_year, coach.reputation,
            coach.development, coach.pitching_change, coach.player_selection)


class CoachPersonnelTests(unittest.TestCase):
    def test_batch_transfers_preserve_identity_and_date_specific_tenure(self):
        repo, book = fixture()
        before = dict(book.coaches)
        self.assertFalse(book.update(date(2026, 4, 1), repo))
        self.assertFalse(book.update(date(2027, 3, 31), repo))
        self.assertTrue(book.update(date(2027, 4, 1), repo))
        book.validate_coverage(repo.schools)
        self.assertEqual(3, len(book.coaches))
        self.assertEqual(3, sum(e.kind == "transfer" for e in book.events))
        for sid in repo.schools:
            old = before["COACH-" + sid]
            current = book.for_school(sid)
            self.assertNotEqual(old.coach_id, current.coach_id)
            self.assertEqual(old, book.for_school(sid, date(2027, 3, 31)))
            self.assertEqual(current, book.for_school(sid, date(2027, 4, 1)))
            self.assertEqual(1, current.view(date(2027, 4, 1))["tenure_years"])
            self.assertEqual(identity(before[current.coach_id]), identity(current))
        for event in book.events[3:]:
            self.assertEqual("2016-04-01", event.previous_appointment_date)
            self.assertEqual(11, event.completed_tenure_years)
            self.assertNotEqual(event.from_school_id, event.to_school_id)
        saved = pickle.dumps(book.__getstate__())
        self.assertFalse(book.update(date(2027, 4, 1), repo))
        self.assertFalse(book.update(date(2027, 4, 2), repo))
        self.assertEqual(saved, pickle.dumps(book.__getstate__()))

    def test_retirement_keeps_person_and_successor_has_new_id_and_configured_age(self):
        repo, book = fixture()
        old = replace(book.coaches["COACH-A"], birth_year=1947)
        book.coaches[old.coach_id] = old
        book.update(date(2027, 4, 1), repo)
        book.validate_coverage(repo.schools)
        self.assertEqual(identity(old), identity(book.coaches[old.coach_id]))
        self.assertEqual("2027-04-01", book.coaches[old.coach_id].retired_on)
        self.assertEqual("", book.coaches[old.coach_id].school_id)
        self.assertNotIn(old.coach_id, book.active_by_school.values())
        self.assertEqual(old, book.for_school("A", date(2027, 3, 31)))
        self.assertEqual({"initial", "transfer", "retirement", "appointment"},
                         {e.kind for e in book.events})
        new_ids = set(book.coaches) - {"COACH-A", "COACH-B", "COACH-C"}
        self.assertEqual(1, len(new_ids))
        new = book.coaches[new_ids.pop()]
        self.assertEqual(2027, new.appointment_year)
        age = 2027 - new.birth_year
        self.assertTrue(book.config["successor_age"]["min"] <= age <= book.config["successor_age"]["max"])
        self.assertTrue(all(1 <= x <= 100 for x in identity(new)[3:]))

    def test_matching_is_confined_to_same_prefecture_and_ownership_and_cancels_singletons(self):
        repo, book = fixture([("A", "13", "prefectural"), ("B", "13", "prefectural"),
                              ("C", "14", "prefectural"), ("D", "13", "private"),
                              ("E", "13", "private"), ("F", "13", "municipal"),
                              ("G", "13", "unknown")])
        book.update(date(2027, 4, 1), repo)
        moves = [e for e in book.events if e.kind == "transfer"]
        self.assertEqual(4, len(moves))
        for e in moves:
            self.assertEqual(repo.schools[e.from_school_id], repo.schools[e.to_school_id])
        for sid in ("C", "F", "G"):
            self.assertEqual("COACH-" + sid, book.for_school(sid).coach_id)
        book.validate_coverage(repo.schools)

    def test_age_and_tenure_probabilities_and_private_long_tenure(self):
        _, book = fixture()
        config = CoachBook([], root=ROOT).config
        book.config = config
        base = book.coaches["COACH-A"]
        probs = [book.retirement_probability(replace(base, birth_year=2027 - age), 2027, "public")
                 for age in (30, 40, 50, 60, 65, 70, 75, 80)]
        self.assertEqual(sorted(probs), probs)
        self.assertEqual(0, probs[0])
        self.assertEqual(1, probs[-1])
        long = replace(base, appointment_year=1990)
        for group in ("public", "private"):
            self.assertGreater(book.retirement_probability(long, 2027, group),
                               book.retirement_probability(base, 2027, group))
        repo, book = fixture()
        book.config = config
        # 24歳・在任1年では退任も異動もしない。
        book.coaches = {cid: replace(c, birth_year=2003, appointment_year=2026)
                        for cid, c in book.coaches.items()}
        before = dict(book.coaches)
        book.update(date(2027, 4, 1), repo)
        self.assertEqual(before, book.coaches)

    def test_update_is_atomic_and_rejects_missing_or_duplicate_assignments(self):
        repo, book = fixture()
        book.coaches["COACH-A"] = replace(book.coaches["COACH-A"], birth_year=1947)
        before = pickle.dumps(book.__getstate__())
        with patch("game_core.coaches._draw_coach", side_effect=ValueError("generation failed")):
            with self.assertRaises(ValueError):
                book.update(date(2027, 4, 1), repo)
        self.assertEqual(before, pickle.dumps(book.__getstate__()))
        with self.assertRaises(ValueError):
            book.update(date(2028, 4, 1), repo)
        book.coaches["COACH-B"] = replace(book.coaches["COACH-B"], school_id="A")
        with self.assertRaises(ValueError):
            book.validate_coverage(repo.schools)

    def test_personnel_runs_before_reputation_growth_and_april_rosters(self):
        repo, book = fixture()
        observed = []
        old = date(2027, 3, 31)
        season = SimpleNamespace(start_date=old, current_date=old, play_today=lambda: [],
                                 calendar_rows={}, annual_templates={}, repo=repo)
        reputation = SimpleNamespace(collect=lambda _: None,
                                     update=lambda _: observed.append(("reputation", book.updated_year)))
        rosters = SimpleNamespace(grow=lambda _: observed.append(("grow", book.updated_year)),
                                  set_today=lambda _: observed.append(("rosters", book.updated_year)))
        career = CareerState({2026: season}, current_date=old, coaches=book,
                             reputation=reputation, rosters=rosters)
        career.next_day()
        self.assertEqual([("reputation", 2027), ("grow", 2027), ("rosters", 2027)], observed)

    def test_thirty_year_national_coverage_distributions_and_resume_reproducibility(self):
        repo = DataRepository(ROOT / "data")
        teams = [repo.team(sid) for sid in repo.schools]
        reversed_repo = DataRepository(ROOT / "data")
        reversed_repo.schools = dict(reversed(list(reversed_repo.schools.items())))
        random_state = random.getstate()
        for seed in (7, 20261027):
            book = CoachBook.generate(ROOT, teams, seed)
            resumed = CoachBook.generate(ROOT, reversed(teams), seed)
            counts = Counter()
            tenure = {"public": [], "private": []}
            for year in range(2027, 2057):
                n = len(book.events)
                previous_people = dict(book.coaches)
                book.update(date(year, 4, 1), repo)
                resumed = pickle.loads(pickle.dumps(resumed))
                resumed.update(date(year, 4, 1), reversed_repo)
                self.assertEqual(book.coaches, resumed.coaches)
                self.assertEqual(book.events, resumed.events)
                self.assertEqual(book.active_by_school, resumed.active_by_school)
                book.validate_coverage(repo.schools)
                self.assertEqual(len(repo.schools), len(book.active_by_school))
                self.assertLessEqual(set(previous_people), set(book.coaches))
                arrivals = [e for e in book.events[n:] if e.kind == "appointment"]
                self.assertEqual(len(arrivals), len(book.coaches) - len(previous_people))
                self.assertTrue(all(e.coach_id not in previous_people for e in arrivals))
                for e in book.events[n:]:
                    counts[e.kind] += 1
                    if e.kind in ("retirement", "transfer"):
                        self.assertEqual(identity(previous_people[e.coach_id]), identity(book.coaches[e.coach_id]))
                    if e.kind == "transfer":
                        self.assertEqual(repo.team(e.from_school_id).prefecture_code,
                                         repo.team(e.to_school_id).prefecture_code)
                        self.assertEqual(repo.ownership_type(e.from_school_id), repo.ownership_type(e.to_school_id))
                self.assertFalse(book.update(date(year, 4, 1), repo))
                for sid in repo.schools:
                    coach = book.for_school(sid)
                    age = year - coach.birth_year
                    self.assertTrue(25 <= age < book.config["retirement"]["maximum_age"])
                    group = "public" if repo.ownership_type(sid) in book.config["public_ownership_types"] else "private"
                    tenure[group].append(year - coach.appointment_year + 1)
            self.assertTrue(all(counts[k] > 0 for k in ("retirement", "transfer", "appointment")))
            self.assertGreater(statistics.mean(tenure["private"]), statistics.mean(tenure["public"]))
            ages = [2056 - book.coaches[cid].birth_year for cid in book.active_by_school.values()]
            print("人事30年", seed, dict(counts), "平均在任年数",
                  {k: round(statistics.mean(v), 2) for k, v in tenure.items()},
                  "最終年の年齢（最小/平均/最大）", min(ages), round(statistics.mean(ages), 2), max(ages), "欠員0")
        self.assertEqual(random_state, random.getstate())


class CoachPersonnelServiceTests(unittest.TestCase):
    def test_multiple_years_real_save_resume_current_display_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = ROOT / "data"
            def service():
                return LiveGameService(DataRepository(data), data, save_root=tmp, autosave_after_action=False)
            game = service()
            session = game.new_game("personnel", rng_seed=7, save_initial=False)
            initial = dict(session.state.coaches.coaches)
            game.advance_through(session, "2027-03-31")
            self.assertEqual(initial, session.state.coaches.coaches)
            game.save_game(session)
            resumed_game = service()
            resumed = resumed_game.load_game("personnel")
            for current_game, current in ((game, session), (resumed_game, resumed)):
                current_game.advance_to(current, "2027-04-01")
                current.state.coaches.validate_coverage(current_game.repo.schools)
            self.assertEqual(session.state.coaches.events, resumed.state.coaches.events)
            sid = next(e.from_school_id for e in session.state.coaches.events if e.kind == "transfer")
            self.assertNotEqual(initial[session.state.coaches.for_school(sid, date(2027, 3, 31)).coach_id].coach_id,
                                session.state.coaches.for_school(sid).coach_id)
            game.edit_school(session, sid, info={"display_name": "架空新高校", "short_name": "架空新"})
            game.save_game(session)
            reloaded = service().load_game("personnel")
            shown = GameScreenData(game, reloaded).school(sid)
            self.assertEqual("架空新", shown["name"])
            self.assertEqual(session.state.coaches.for_school(sid).view(date(2027, 4, 1)), shown["coach"])
            for current_game, current in ((game, session), (resumed_game, resumed)):
                current_game.advance_through(current, "2028-04-02")
            left, right = session.state.coaches, resumed.state.coaches
            self.assertEqual(2028, left.updated_year)
            self.assertEqual(left.coaches, right.coaches)
            self.assertEqual(left.events, right.events)
            self.assertEqual(session.state.completed_results(), resumed.state.completed_results())
            game.save_game(session)
            loaded = service().load_game("personnel")
            self.assertEqual(left.coaches, loaded.state.coaches.coaches)
            self.assertEqual(left.events, loaded.state.coaches.events)


if __name__ == "__main__":
    unittest.main()
