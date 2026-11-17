"""正式な画面：セーブの管理（game_definition.md §9）。"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from game_core.match_simulator import MatchSimulator
from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.app import ScreenApi, main as screen_main
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

            self.assertIn("error", api.new_save("x", "slot01"))
            self.assertIn("error", api.new_save("x", "だめ"))
            self.assertIn("error", api.new_save("x", "", "abc"))
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

    def test_closing_the_screen_saves_only_when_days_are_unsaved(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(repo, DATA_ROOT, save_root=tmp)
            session = service.new_game("slot01", rng_seed=11, title="はじめ")
            data = GameScreenData(service, session)
            api = ScreenApi(data)
            slot = Path(tmp) / "slot01"

            def files():
                return {path.name: path.read_bytes() for path in slot.rglob("*.json")}

            # 新しく始めて保存したまま：閉じても何も書かない
            before = files()
            self.assertIsNone(api.save_on_close())
            self.assertEqual(before, files())

            # 試合のない日を1日ずつ進めると保存されない → 閉じるときに保存する
            for _ in range(400):
                moved = data.advance("day")
                if not moved["played_match_count"]:
                    break
            self.assertEqual(0, moved["played_match_count"])
            quiet_day = moved["to_date"]
            self.assertNotEqual(
                quiet_day, service.slots.inspect("slot01")["current_date"])
            saved = api.save_on_close()
            self.assertEqual("autosave", saved["kind"])
            self.assertEqual(quiet_day, saved["current_date"])
            self.assertEqual(quiet_day, service.slots.inspect("slot01")["current_date"])
            self.assertEqual(quiet_day, service.load_game("slot01").state.current_date.isoformat())

            # 保存したあとは、もう一度閉じても書かない
            before = files()
            self.assertIsNone(api.save_on_close())
            self.assertEqual(before, files())

            # 試合のある日はその日に保存されるので、閉じるときは書かない
            for _ in range(400):
                moved = data.advance("day")
                if moved["played_match_count"]:
                    break
            self.assertGreater(moved["played_match_count"], 0)
            self.assertEqual(moved["to_date"], service.slots.inspect("slot01")["current_date"])
            before = files()
            self.assertIsNone(api.save_on_close())
            self.assertEqual(before, files())

            # 日付を進めている途中で閉じたら保存しない
            session.unsaved_progress = True
            api._advancing = True
            self.assertIsNone(api.save_on_close())
            self.assertEqual(before, files())
            api._advancing = False
            self.assertIsNotNone(api.save_on_close())

    def test_closing_without_a_save_chosen_does_nothing(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(repo, DATA_ROOT, save_root=tmp)
            self.assertIsNone(ScreenApi(GameScreenData(service)).save_on_close())
            self.assertEqual([], list(Path(tmp).iterdir()))

    def test_choose_save_at_startup(self):
        repo = DataRepository(DATA_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            service = LiveGameService(
                repo, DATA_ROOT, save_root=tmp, autosave_after_action=False,
            )
            api = ScreenApi(GameScreenData(service))
            self.assertIsNone(api.shell()["header"])
            self.assertEqual([], api.saves()["slots"])
            self.assertTrue(api.today().get("no_session"))
            self.assertTrue(api.advance({"mode": "day"}).get("no_session"))
            created = api.new_save("はじめ", "mine", "42")
            self.assertEqual("mine", created["current_slot"])
            self.assertEqual(42, api._data.session.plan.rng_seed)
            self.assertNotIn("error", api.today())



class StartupCheckTests(unittest.TestCase):
    """EXE を作ったあとに使う ``--check``：画面を出さずに起動の手前まで確かめて終わる。"""

    def test_check_reads_saves_and_never_opens_a_window(self):
        def no_window(*args, **kwargs):
            raise AssertionError("--check でウィンドウを開いた")

        fake = types.SimpleNamespace(create_window=no_window, start=no_window)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules, {"webview": fake}), \
                contextlib.redirect_stdout(out), \
                patch("os.chdir"), \
                patch.object(MatchSimulator, "check_results", True):
            screen_main(["--check", "--save-root", tmp])
            # 遊ぶときの入口では、終わった試合の結果の検査を省く
            self.assertFalse(MatchSimulator.check_results)
        self.assertIn("起動の確認", out.getvalue())
        self.assertIn("'slots': 0", out.getvalue())


if __name__ == "__main__":
    unittest.main()
