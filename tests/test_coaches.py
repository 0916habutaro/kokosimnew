"""監督の全国配置、本番保存、表示と、選手・試合の乱数からの分離。"""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from game_core.coaches import CoachBook
from phase2_engine import DataRepository, LiveGameService, PLAYER_RESOLVER_CONTRACT
from phase2_engine.models import Team
from phase2_engine.screen.data import GameScreenData

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class CoachGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = DataRepository(DATA)
        cls.teams = [cls.repo.team(sid) for sid in cls.repo.schools]

    def test_national_assignment_unique_ids_and_balanced_distributions(self):
        config = json.loads((ROOT / "config/coaches/coach_generation_v1.json").read_text(encoding="utf-8"))
        for seed in (7, 20261027):
            book = CoachBook.generate(ROOT, self.teams, seed)
            coaches = list(book.coaches.values())
            self.assertEqual(set(self.repo.schools), {c.school_id for c in coaches})
            self.assertEqual(len(self.repo.schools), len(coaches))
            self.assertTrue(set(book.coaches).isdisjoint(self.repo.schools))
            for coach in coaches:
                self.assertEqual(coach, book.for_school(coach.school_id))
                self.assertIn(" ", coach.display_name)
                view = coach.view(date(2026, 4, 1))
                self.assertTrue(config["age"]["min"] <= view["age"] <= config["age"]["max"])
                self.assertTrue(1 <= view["tenure_years"] <= config["tenure"]["max"])
                self.assertGreaterEqual(coach.appointment_year - coach.birth_year,
                                        config["minimum_appointment_age"])
            for field in ("reputation", "development", "pitching_change", "player_selection"):
                values = [getattr(c, field) for c in coaches]
                spec = config[field]
                self.assertTrue(all(spec["min"] <= v <= spec["max"] for v in values))
                self.assertAlmostEqual(spec["mean"], statistics.mean(values), delta=2)
                self.assertGreater(statistics.pstdev(values), spec["stddev"] * .8)
                self.assertLess(sum(v < 20 or v > 80 for v in values) / len(values), .15)

    def test_seed_reproducibility_order_and_global_random_isolation(self):
        state = random.getstate()
        left = CoachBook.generate(ROOT, self.teams, 7)
        right = CoachBook.generate(ROOT, reversed(self.teams), 7)
        self.assertEqual(left.coaches, right.coaches)
        self.assertNotEqual(left.coaches, CoachBook.generate(ROOT, self.teams, 8).coaches)
        self.assertEqual(state, random.getstate())

    def test_identity_independent_of_assignment_and_names(self):
        teams = [Team("FAKE-A", "FAKE-P", "架空高校", "13")]
        original = CoachBook.generate(ROOT, teams, 8)
        coach = original.for_school("FAKE-A")
        renamed = CoachBook.generate(ROOT, [replace(teams[0], display_name="架空新高校")], 8)
        self.assertEqual(original.coaches, renamed.coaches)
        # 所属を変えても人物IDはそのまま保存できる（異動処理は6-2）。
        reassigned = CoachBook([replace(coach, school_id="FAKE-B")])
        self.assertIsNone(reassigned.for_school("FAKE-A"))
        self.assertEqual(coach.coach_id, reassigned.for_school("FAKE-B").coach_id)
        self.assertIsNone(original.for_school("missing"))
        with self.assertRaises(ValueError):
            CoachBook([coach, coach])
        with self.assertRaises(ValueError):
            CoachBook([coach, replace(coach, coach_id="another")])

    def test_age_and_tenure_follow_school_year_without_regenerating(self):
        coach = CoachBook.generate(ROOT, self.teams[:1], 8).for_school(self.teams[0].school_id)
        initial = coach.view(date(2026, 4, 1))
        self.assertEqual(initial, coach.view(date(2027, 3, 31)))
        following = coach.view(date(2027, 4, 1))
        self.assertEqual(initial["age"] + 1, following["age"])
        self.assertEqual(initial["tenure_years"] + 1, following["tenure_years"])
        self.assertEqual(initial["coach_id"], following["coach_id"])


def service(save_root, players=False):
    options = {"resolver_contract": PLAYER_RESOLVER_CONTRACT} if players else {}
    return LiveGameService(DataRepository(DATA), DATA, save_root=save_root,
                           autosave_after_action=False, **options)


class CoachPersistenceTests(unittest.TestCase):
    def test_real_save_restart_resume_rename_and_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = service(tmp)
            session = game.new_game("coach", rng_seed=7, save_initial=False)
            before = dict(session.state.coaches.coaches)
            sid = next(iter(game.repo.schools))
            initial = GameScreenData(game, session).school(sid)["coach"]
            self.assertEqual(before[initial["coach_id"]].view(session.state.current_date), initial)
            game.edit_school(session, sid, info={"display_name": "架空新高校", "short_name": "架空新"})
            game.save_game(session)
            # 別プロセスで本番のスロットをロード。再生成されれば失敗させる。
            script = '''
import json, sys
from unittest.mock import patch
from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.data import GameScreenData
game = LiveGameService(DataRepository(sys.argv[1]), sys.argv[1], save_root=sys.argv[2], autosave_after_action=False)
with patch("game_core.coaches.CoachBook.generate", side_effect=AssertionError("regenerated")):
    session = game.load_game("coach")
print(json.dumps(GameScreenData(game, session).school(sys.argv[3])["coach"], ensure_ascii=False))
'''
            restarted = subprocess.run([sys.executable, "-c", script, str(DATA), tmp, sid],
                                       cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(initial, json.loads(restarted.stdout))
            fresh = service(tmp)
            with patch.object(CoachBook, "generate", side_effect=AssertionError("regenerated")):
                loaded = fresh.load_game("coach")
            self.assertEqual(before, loaded.state.coaches.coaches)
            detail = GameScreenData(fresh, loaded).school(sid)
            self.assertEqual("架空新", detail["name"])
            self.assertEqual(initial, detail["coach"])
            session.state.advance_through("2026-04-04")
            loaded.state.advance_through("2026-04-04")
            self.assertEqual(session.state.completed_results(), loaded.state.completed_results())
            self.assertEqual(before, loaded.state.coaches.coaches)
            fresh.save_game(loaded)
            self.assertEqual(before, service(tmp).load_game("coach").state.coaches.coaches)

    def test_generation_does_not_change_players_abilities_or_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = service(tmp, players=True)
            with patch.object(CoachBook, "generate", return_value=None):
                control = game.new_game("without", rng_seed=17, save_initial=False)
            actual = game.new_game("with", rng_seed=17, save_initial=False)
            self.assertTrue(actual.state.coaches.coaches)
            # 起動時に行う3月の試合、4月の試合・個人成績・球数まで比較。
            for day in ("2026-04-01", "2026-04-04"):
                control.state.advance_through(day)
                actual.state.advance_through(day)
                self.assertEqual(control.state.completed_results(), actual.state.completed_results())
                self.assertEqual(control.state.pending_match_details, actual.state.pending_match_details)
                self.assertEqual(control.state.primary.pitch_log, actual.state.primary.pitch_log)
                left, right = control.state.rosters, actual.state.rosters
                self.assertEqual(left.schools(2026), right.schools(2026))
                for sid in left.schools(2026):
                    a, b = left.roster(2026, sid), right.roster(2026, sid)
                    self.assertEqual(a, b)
                    self.assertEqual([left.ability(p) for p in a.players],
                                     [right.ability(p) for p in b.players])
            game.save_game(actual)
            loaded = service(tmp, players=True).load_game("with")
            self.assertEqual(actual.state.coaches.coaches, loaded.state.coaches.coaches)
            actual.state.advance_through("2026-04-06")
            loaded.state.advance_through("2026-04-06")
            self.assertEqual(actual.state.completed_results(), loaded.state.completed_results())


if __name__ == "__main__":
    unittest.main()
