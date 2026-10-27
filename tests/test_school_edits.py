"""学校の編集（docs/design/school_edits.md）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from game_core.membership import RosterBook
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
        with tempfile.TemporaryDirectory() as tmp:
            edits.save(tmp)
            loaded = SchoolEdits.load(tmp)
            self.assertEqual({}, SchoolEdits.load(Path(tmp) / "none").schools)
        self.assertEqual(edits.schools, loaded.schools)


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
            with self.assertRaises(ValueError):
                data.edit_school(school_id, {**form, "short_name": " "})

            data.advance("day")
            detail = data.edit_school(school_id, {
                "display_name": "架空学園高等学校", "short_name": "架空学園",
                "ownership_type": "private",
            })
            self.assertEqual("架空学園", detail["name"])
            self.assertEqual("私立", detail["ownership"])
            self.assertEqual(1, len(detail["edit"]["history"]))
            # 変える前の日の試合は当時の名前、マスターは変えない
            self.assertEqual(old_name, data.names(school_id, "2026-04-01"))
            self.assertEqual("prefectural", repo.schools[school_id]["ownership_type"])
            self.assertEqual("private", repo.ownership_type(school_id))

            # 読み込み直しても残る。新しく始めたセーブには残らない
            service.save_game(session)
            reloaded = service.load_game("edit")
            self.assertEqual("架空学園", GameScreenData(service, reloaded).names(school_id))
            service.new_game("other", rng_seed=6, save_initial=False)
            self.assertEqual("prefectural", repo.ownership_type(school_id))


if __name__ == "__main__":
    unittest.main()
