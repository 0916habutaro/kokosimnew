"""正式な画面のウィンドウ（pywebview、ADR-044）。

    python -m phase2_engine.screen --save-root out/saves --slot slot01

スロットのセーブがあれば読み込み、なければ新しく始める。画面のファイルは
``phase2_engine/screen/web/``。JavaScript からは ``ScreenApi`` のメソッドだけを呼ぶ。
"""
from __future__ import annotations

import argparse
from pathlib import Path
import threading
import traceback

from .. import PLAYER_RESOLVER_CONTRACT, DataRepository, LiveGameService
from .data import GameScreenData


WEB_DIR = Path(__file__).resolve().parent / "web"
TITLE = "ココシミュNew"
BUSY = "日付を進めている途中です"


class ScreenApi:
    """JavaScript から呼ぶ入口（pywebview の js_api）。中身はデータの層に任せる。

    pywebview は呼び出しごとに別のスレッドで動かす。状態を読む・進める処理は
    ``_state_lock`` で1つずつにし、日付を進めている間は ``progress`` 以外を
    断る（進めている途中の状態を読まない）。
    """

    def __init__(self, data: GameScreenData):
        self._data = data
        self._state_lock = threading.Lock()
        self._advance_lock = threading.Lock()
        self._advancing = False
        self._progress = {"running": False}

    def shell(self) -> dict:
        return self._read(self._data.shell)

    def header(self) -> dict:
        return self._read(self._data.header)

    def competitions(self) -> dict:
        return self._read(self._data.competitions)

    def bracket(self, school_year, competition_id) -> dict:
        return self._read(self._data.bracket, school_year, competition_id)

    def match(self, school_year, competition_id, match_id) -> dict:
        return self._read(
            self._data.match, school_year, competition_id, match_id,
        )

    def matches_on(self, day="") -> dict:
        return self._read(self._data.matches_on, day)

    def progress(self) -> dict:
        return dict(self._progress)

    def _read(self, function, *args) -> dict:
        if self._advancing:
            return {"error": BUSY, "busy": True}
        with self._state_lock:
            return self._call(function, *args)

    def advance(self, options: dict) -> dict:
        if not self._advance_lock.acquire(blocking=False):
            return {"error": BUSY, "busy": True}
        self._advancing = True
        try:
            with self._state_lock:
                return self._advance(options)
        finally:
            self._progress = {"running": False}
            self._advancing = False
            self._advance_lock.release()

    def _advance(self, options: dict) -> dict:
        start = self._data.state.current_date
        self._progress = {
            "running": True,
            "from_date": start.isoformat(),
            "current_date": start.isoformat(),
            "target_date": options.get("target_date", ""),
            "advanced_days": 0,
            "played_match_count": 0,
        }

        def on_day(step: dict) -> None:
            self._progress = {
                **self._progress,
                "current_date": step.get("to_date", ""),
                "advanced_days": self._progress["advanced_days"] + 1,
                "played_match_count": self._progress["played_match_count"]
                + int(step.get("played_match_count", 0)),
            }

        return self._call(
            self._data.advance,
            options.get("mode", ""),
            target_date=options.get("target_date", ""),
            competition_id=options.get("competition_id", ""),
            school_year=options.get("school_year"),
            stop_at_big_scene=bool(options.get("stop_at_big_scene")),
            on_day=on_day,
        )

    @staticmethod
    def _call(function, *args, **kwargs) -> dict:
        try:
            return function(*args, **kwargs)
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # 画面には短い説明だけ返し、詳細はコンソールへ
            traceback.print_exc()
            return {"error": f"{type(exc).__name__}: {exc}"}


def open_session(service: LiveGameService, slot: str, seed: int, title: str):
    names = {row.get("slot_id") for row in service.list_games()}
    if slot in names:
        return service.load_game(slot)
    return service.new_game(slot, rng_seed=seed, title=title)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ココシミュNew の画面を開く")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--save-root", default="out/saves")
    parser.add_argument("--slot", default="slot01")
    parser.add_argument("--seed", type=int, default=2026100801)
    parser.add_argument("--title", default="2026年シーズン")
    return parser


def main(argv=None) -> None:
    import webview  # pywebview（requirements.txt）

    args = build_parser().parse_args(argv)
    repo = DataRepository(args.data_dir)
    service = LiveGameService(
        repo, args.data_dir, save_root=args.save_root,
        resolver_contract=PLAYER_RESOLVER_CONTRACT,
    )
    session = open_session(service, args.slot, args.seed, args.title)
    api = ScreenApi(GameScreenData(service, session))
    webview.create_window(
        TITLE, str(WEB_DIR / "index.html"), js_api=api,
        width=1400, height=900, min_size=(1100, 700),
        background_color="#0b1730",
    )
    webview.start()
