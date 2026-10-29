"""正式な画面のウィンドウ（pywebview、ADR-044）。

    python -m phase2_engine.screen               （セーブを画面で選ぶ）
    python -m phase2_engine.screen --slot slot01 （slot01 を開く）

``--slot`` のセーブがあれば読み込み、なければ新しく始める。画面のファイルは
``phase2_engine/screen/web/``。JavaScript からは ``ScreenApi`` のメソッドだけを呼ぶ。

``--slot`` を付けないときは、セーブの画面から遊ぶセーブを選ぶ（新しく始める
こともできる）。EXE（``kokosimnew.spec``）では、データと設定は EXE の中、
セーブは ``config/screen/screen_v1.json`` の ``save_root`` に置く（そのドライブが
なければユーザーのフォルダ ``%LOCALAPPDATA%\\KokosimNew\\saves``）。
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import random
import sys
import threading
import traceback

from .. import PLAYER_RESOLVER_CONTRACT, DataRepository, LiveGameService
from .data import GameScreenData, load_screen_config


WEB_DIR = Path(__file__).resolve().parent / "web"
TITLE = "ココシミュNew"
BUSY = "日付を進めている途中です"
NO_SESSION = "遊ぶセーブを選んでください"
# セーブを選ぶ前でも呼べるもの
WITHOUT_SESSION = (
    "shell", "saves", "rename_save", "delete_save", "recovery",
)


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

    def competitions(self, school_year=None) -> dict:
        return self._read(self._data.competitions, school_year)

    def bracket(self, school_year, competition_id) -> dict:
        return self._read(self._data.bracket, school_year, competition_id)

    def entrant(self, school_year, competition_id, school_id) -> dict:
        return self._read(self._data.entrant, school_year, competition_id, school_id)

    def match(self, school_year, competition_id, match_id) -> dict:
        return self._read(
            self._data.match, school_year, competition_id, match_id,
        )

    def matches_on(self, day="") -> dict:
        return self._read(self._data.matches_on, day)

    def today(self) -> dict:
        return self._read(self._data.today)

    def records_entrants(self, filters=None) -> dict:
        return self._read(self._data.records_entrants, filters)

    def records_best8(self, filters=None) -> dict:
        return self._read(self._data.records_best8, filters)

    def records(self, school_year=None) -> dict:
        return self._read(self._data.records, school_year)

    def schools(self) -> dict:
        return self._read(self._data.schools)

    def school(self, school_id) -> dict:
        return self._read(self._data.school, school_id)

    def coach(self, coach_id) -> dict:
        return self._read(self._data.coach, coach_id)

    def school_coaches(self, school_id) -> dict:
        return self._read(self._data.school_coaches, school_id)

    def school_matches(self, school_id, school_year) -> dict:
        return self._read(self._data.school_matches, school_id, school_year)

    def player(self, school_id, player_id, reference_year=None) -> dict:
        if reference_year is None:
            return self._read(self._data.player, school_id, player_id)
        return self._read(self._data.player, school_id, player_id, reference_year)

    def warm_up(self) -> None:
        """学校の能力を別のスレッドで計算しておく（一覧を開いたときに待たない）。"""
        threading.Thread(target=self._warm_up, daemon=True).start()

    def _warm_up(self) -> None:
        with self._state_lock:
            job = self._data.ability_job()
        if job is not None:
            self._call(job)

    def edit_school(self, school_id, payload) -> dict:
        result = self._read(self._data.edit_school, school_id, payload)
        # 名簿の能力を変えたら一覧も計算し直しておく
        if not result.get("error"):
            self.warm_up()
        return result

    def preview_team(self, school_id, target) -> dict:
        return self._read(self._data.preview_team, school_id, target)

    def edit_player(self, school_id, player_id, payload) -> dict:
        result = self._read(self._data.edit_player, school_id, player_id, payload)
        if not result.get("error"):
            self.warm_up()
        return result

    def saves(self) -> dict:
        return self._read(self._data.saves)

    def save_now(self) -> dict:
        return self._read(self._data.save_now)

    def rename_save(self, slot_id, title) -> dict:
        return self._read(self._data.rename_save, slot_id, title)

    def delete_save(self, slot_id) -> dict:
        return self._read(self._data.delete_save, slot_id)

    def recovery(self, slot_id) -> dict:
        return self._read(self._data.recovery, slot_id)

    def open_save(self, slot_id, source="latest") -> dict:
        return self._exclusive(self._data.open_save, slot_id, source)

    def new_save(self, title, slot_id="", seed="", injury_level="") -> dict:
        """新しく始める。スロット名・シードが空なら、空いている名前・乱数にする。"""
        seed = str(seed).strip()
        if not seed:
            seed = random.SystemRandom().randrange(1, 2**31)
        elif not seed.isdigit():
            return {"error": "シードは数字で入れてください"}
        return self._exclusive(self._data.new_save, title, int(seed), slot_id, injury_level)

    def set_injury_level(self, level) -> dict:
        """遊んでいるセーブの怪我の頻度を変える。"""
        return self._exclusive(self._data.set_injury_level, level)

    def progress(self) -> dict:
        return dict(self._progress)

    def _read(self, function, *args) -> dict:
        if self._advancing:
            return {"error": BUSY, "busy": True}
        if self._data.session is None and function.__name__ not in WITHOUT_SESSION:
            return {"error": NO_SESSION, "no_session": True}
        with self._state_lock:
            return self._call(function, *args)

    def advance(self, options: dict) -> dict:
        if self._data.session is None:
            return {"error": NO_SESSION, "no_session": True}
        return self._exclusive(self._advance, options)

    def _exclusive(self, function, *args) -> dict:
        """日付を進める・セーブを切り替えるなど、状態を書き換える処理。

        その間は ``progress`` 以外の呼び出しを断る。
        """
        if not self._advance_lock.acquire(blocking=False):
            return {"error": BUSY, "busy": True}
        self._advancing = True
        self._progress = {"running": True}
        try:
            with self._state_lock:
                return self._call(function, *args)
        finally:
            self._progress = {"running": False}
            self._advancing = False
            self._advance_lock.release()
            # 部員が変わる日（4月1日・夏の大会の後）や別のセーブに備えて
            # 能力を計算しておく
            self.warm_up()

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

        return self._data.advance(
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


def app_root() -> Path:
    """data/ と config/ があるフォルダ（EXE なら展開先、それ以外はリポジトリ）。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def default_save_root() -> Path:
    """``config/screen/screen_v1.json`` の ``save_root``（Windows でそのドライブが
    あるとき）。なければ EXE はユーザーのフォルダ、それ以外はリポジトリの out/saves。"""
    path = load_screen_config(app_root() / "config")["save_root"]["windows_path"]
    if os.name == "nt" and path and Path(Path(path).anchor).exists():
        return Path(path)
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "KokosimNew" / "saves"
    return app_root() / "out" / "saves"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ココシミュNew の画面を開く")
    parser.add_argument("--data-dir", default=str(app_root() / "data"))
    parser.add_argument("--save-root", default=str(default_save_root()))
    parser.add_argument("--slot", default="", help="付けないときは画面で選ぶ")
    parser.add_argument("--seed", type=int, default=2026100801)
    parser.add_argument("--title", default="2026年シーズン")
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    save_root = Path(args.save_root).resolve()
    if sys.stdout is None or sys.stderr is None:
        # コンソールのない EXE では、エラーの詳細をセーブの隣のログに書く
        save_root.mkdir(parents=True, exist_ok=True)
        log = open(save_root / "kokosimnew.log", "a", encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    # 能力・試合の設定（config/）はいまの作業フォルダから読むので、そろえておく
    os.chdir(app_root())
    repo = DataRepository(data_dir)
    service = LiveGameService(
        repo, data_dir, save_root=save_root,
        resolver_contract=PLAYER_RESOLVER_CONTRACT,
    )
    session = (
        open_session(service, args.slot, args.seed, args.title)
        if args.slot else None
    )
    api = ScreenApi(GameScreenData(service, session))
    api.warm_up()
    import webview  # pywebview（requirements.txt）

    webview.create_window(
        TITLE, str(WEB_DIR / "index.html"), js_api=api,
        width=1400, height=900, min_size=(1100, 700),
        background_color="#0b1730",
    )
    webview.start()
