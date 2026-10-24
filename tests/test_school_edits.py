"""学校の編集（docs/design/school_edits.md）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from game_core.membership import RosterBook
from game_core.school_edits import SchoolAdjustmentModel
from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine import DataRepository, LiveGameService
from phase2_engine.school_edits import SchoolEdits
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
CONFIG = ROOT / "config"


class SchoolEditStoreTests(unittest.TestCase):
    def test_info_by_date_and_round_trip(self):
        edits = SchoolEdits()
        self.assertTrue(edits.set_info("SCHX1", "2026-05-01", {"short_name": "新名"}))
        self.assertFalse(edits.set_info("SCHX1", "2026-05-02", {"short_name": "新名"}))
        edits.set_info("SCHX1", "2027-04-01", {"ownership_type": "private"})
        self.assertEqual({}, edits.info_on("SCHX1", "2026-04-30"))
        self.assertEqual({"short_name": "新名"}, edits.info_on("SCHX1", "2026-05-01"))
        self.assertEqual("private", edits.info_on("SCHX1")["ownership_type"])
        self.assertEqual({"SCHX1": "private"}, edits.ownership_overrides())
        edits.set_ability("SCHX1", "2026-05-01", {"batting": 2})
        with tempfile.TemporaryDirectory() as tmp:
            edits.save(tmp)
            loaded = SchoolEdits.load(tmp)
            self.assertEqual({}, SchoolEdits.load(Path(tmp) / "none").schools)
        self.assertEqual(edits.schools, loaded.schools)
        self.assertEqual({"SCHX1": {"batting": 2}}, loaded.adjustments())


class AdjustmentTests(unittest.TestCase):
    def test_steps_change_player_abilities_and_team_strength(self):
        model = SchoolAdjustmentModel(CONFIG)
        with self.assertRaises(ValueError):
            model.normalize({"batting": model.step_range + 1})
        self.assertEqual({"pitching": -1}, model.normalize({"batting": 0, "pitching": "-1"}))

        repo = DataRepository(DATA_ROOT)
        school_id = next(iter(repo.schools))
        players = RosterBook(repo.team, first_year=2026, career_seed=3).roster(
            2026, school_id,
        ).players
        generator = SchoolAwarePlayerAbilityGenerator(CONFIG / "abilities")
        teams = TeamStrengthGenerator(CONFIG / "abilities")
        before = [generator.generate(p, 2026, 3) for p in players]
        generator.school_adjustments = {school_id: {"batting": 2, "running": -1}}
        after = [generator.generate(p, 2026, 3) for p in players]
        points = model.categories["batting"]["points"] * 2
        for old, new in zip(before, after):
            self.assertEqual(min(100, old.contact + points), new.contact)
            self.assertEqual(old.control, new.control)  # 投手は変えていない
        # 学校の強さは補正した選手から計算する
        old_team, new_team = teams.generate(tuple(before)), teams.generate(tuple(after))
        self.assertGreater(new_team.batting_strength, old_team.batting_strength)
        self.assertLess(new_team.running_strength, old_team.running_strength)


class ScreenEditTests(unittest.TestCase):
    def test_edit_rename_ownership_and_reload(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                repo, DATA_ROOT, save_root=tmp, autosave_after_action=False,
            )
            session = service.new_game("edit", rng_seed=5)
            data = GameScreenData(service, session)
            school_id = next(
                sid for sid, row in repo.schools.items()
                if row.get("ownership_type") == "prefectural"
            )
            old_name = data.names(school_id)
            form = data.school(school_id)["edit"]
            self.assertEqual("prefectural", form["ownership_type"])
            self.assertEqual({}, form["ability"])
            with self.assertRaises(ValueError):
                data.edit_school(school_id, {**form, "short_name": " "})

            data.advance("day")
            detail = data.edit_school(school_id, {
                "display_name": "架空学園高等学校", "short_name": "架空学園",
                "ownership_type": "private", "ability": {"pitching": 1},
            })
            self.assertEqual("架空学園", detail["name"])
            self.assertEqual("私立", detail["ownership"])
            self.assertEqual({"pitching": 1}, detail["edit"]["ability"])
            self.assertEqual(2, len(detail["edit"]["history"]))
            # 変える前の日の試合は当時の名前、マスターは変えない
            self.assertEqual(old_name, data.names(school_id, "2026-04-01"))
            self.assertEqual("prefectural", repo.schools[school_id]["ownership_type"])
            self.assertEqual("private", repo.ownership_type(school_id))
            self.assertEqual({school_id: {"pitching": 1}}, service.school_adjustments)

            # 読み込み直しても残る。新しく始めたセーブには残らない
            service.save_game(session)
            reloaded = service.load_game("edit")
            self.assertEqual({school_id: {"pitching": 1}}, service.school_adjustments)
            self.assertEqual("架空学園", GameScreenData(service, reloaded).names(school_id))
            service.new_game("other", rng_seed=6, save_initial=False)
            self.assertEqual({}, service.school_adjustments)
            self.assertEqual("prefectural", repo.ownership_type(school_id))


if __name__ == "__main__":
    unittest.main()
