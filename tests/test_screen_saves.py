"""正式な画面：セーブの管理（game_definition.md §9）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.app import ScreenApi
from phase2_engine.screen.data import GameScreenData
from phase2_engine.screen.save_views import next_slot_id, slot_rows, source_label


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class SaveViewTests(unittest.TestCase):
    def test_labels_and_slot_ids(self):
        self.assertEqual("手動セーブ", source_label("manual"))
        self.assertEqual("自動セーブ（2つ前）", source_label("autosave_backup_2"))
        self.assertEqual("slot01", next_slot_id([]))
        self.assertEqual("slot03", next_slot_id(["slot01", "slot02", "other"]))

    def test_slot_rows(self):
        missing = {"exists": False}
        rows = slot_rows([{
            "slot_id": "slot01", "latest_source": "manual",
            "manual": {"exists": True, "status": "valid", "path": "",
                       "metadata": {"current_date": "2026-05-03"}},
            "autosave": missing,
            "user_metadata": {"title": "テストの年"},
        }], "slot01")
        self.assertEqual("テストの年", rows[0]["title"])
        self.assertEqual("2026年5月3日", rows[0]["date_label"])
        self.assertTrue(rows[0]["current"] and rows[0]["loadable"])


class SaveScreenTests(unittest.TestCase):
    def test_save_rename_switch_and_delete(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                repo, DATA_ROOT, save_root=tmp, autosave_after_action=False,
            )
            session = service.new_game("slot01", rng_seed=11, title="はじめ")
            data = GameScreenData(service, session)
            api = ScreenApi(data)
            data.advance("day")
            saved = api.save_now()
            self.assertEqual("2026年4月2日", saved["slots"][0]["date_label"])
            self.assertEqual(
                "名前", api.rename_save("slot01", "名前")["slots"][0]["title"]
            )
            self.assertIn("error", api.rename_save("slot01", " "))
            self.assertIn("error", api.delete_save("slot01"))

            created = api.new_save("ふたつめ")
            self.assertEqual("slot02", created["current_slot"])
            self.assertEqual("2026-04-01", created["header"]["date"])
            self.assertEqual(2, len(created["slots"]))

            sources = [row["source"] for row in api.recovery("slot01")["sources"]]
            self.assertIn("manual", sources)
            opened = api.open_save("slot01", "manual")
            self.assertEqual("slot01", opened["current_slot"])
            self.assertEqual("2026-04-02", opened["header"]["date"])
            self.assertEqual(
                ["slot01"],
                [row["slot_id"] for row in api.delete_save("slot02")["slots"]],
            )
            self.assertEqual({"running": False}, api.progress())


if __name__ == "__main__":
    unittest.main()
