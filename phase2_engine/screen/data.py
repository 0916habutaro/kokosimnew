"""画面に出すデータをまとめて返す層（game_definition.md §9、ADR-044）。

画面（JavaScript）はここが返す dict / list だけを読む。値は JSON にできる
形（文字列・数・真偽・リスト・dict）にする。日付を進める処理もここを通す。
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Callable

from ..career_state import CareerState


CONFIG_PATH = Path("screen") / "screen_v1.json"
WEEKDAYS = "月火水木金土日"

ADVANCE_DAY = "day"
ADVANCE_NEXT_MATCH_DAY = "next_match_day"
ADVANCE_COMPETITION_END = "competition_end"
ADVANCE_DATE = "date"
ADVANCE_MODES = (
    ADVANCE_DAY, ADVANCE_NEXT_MATCH_DAY, ADVANCE_COMPETITION_END, ADVANCE_DATE,
)

STOP_BIG_SCENE = "big_scene"
STOP_MATCH_DAY = "match_day"
STOP_COMPETITION_END = "competition_end"

MENU = (
    {"id": "today", "label": "今日"},
    {"id": "competitions", "label": "大会"},
    {"id": "matches", "label": "試合"},
    {"id": "schools", "label": "学校"},
    {"id": "records", "label": "記録"},
    {"id": "saves", "label": "セーブ"},
)


def load_screen_config(config_root: str | Path) -> dict:
    path = Path(config_root) / CONFIG_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_id") != "screen_v1":
        raise ValueError("screen config_id mismatch")
    return data


def date_label(day: date) -> str:
    return f"{day.year}年{day.month}月{day.day}日（{WEEKDAYS[day.weekday()]}）"


def _seasons(state) -> dict[int, object]:
    if isinstance(state, CareerState):
        return state.seasons
    return {state.year: state}


class GameScreenData:
    """遊んでいるセーブ（``LiveGameService`` のセッション）を画面用に読む。"""

    def __init__(self, service, session, *, config: dict | None = None):
        self.service = service
        self.session = session
        self.config = config or load_screen_config(
            Path(service.data_dir).parent / "config"
        )

    @property
    def state(self):
        return self.session.state

    # ---- 上の帯・メニュー ----

    def shell(self) -> dict:
        return {"menu": list(MENU), "header": self.header()}

    def header(self) -> dict:
        today = self.state.current_date
        return {
            "slot_id": self.session.slot_id,
            "date": today.isoformat(),
            "date_label": date_label(today),
            "school_year": self.state.school_year
            if isinstance(self.state, CareerState) else self.state.year,
            "today_match_count": len(self.today_matches()),
            "active_competitions": self.active_competitions(),
        }

    # ---- 今日の試合 ----

    def today_matches(self) -> list[dict]:
        today = self.state.current_date
        return [
            {**row, "school_year": year}
            for year, season in _seasons(self.state).items()
            if season.current_date == today
            for row in season.today_matches()
        ]

    def big_scene_matches(self) -> list[dict]:
        rule = self.config["big_scene"]
        competitions = self.service.repo.competitions
        return [
            row for row in self.today_matches()
            if row.get("stage_code") in rule["stage_codes"]
            and row.get("round_name") in rule["round_names"]
            and competitions.get(row["competition_id"], {}).get(
                "competition_type"
            ) in rule["competition_types"]
        ]

    def active_competitions(self) -> list[dict]:
        """始まっていて、まだ終わっていない大会（「大会が終わるまで」の候補）。"""
        rows = []
        for year, season in _seasons(self.state).items():
            for cid, scheduled in season.competitions.items():
                if scheduled.is_complete:
                    continue
                rows.append({
                    "school_year": year,
                    "competition_id": cid,
                    "name": scheduled.competition_name,
                    "next_date": scheduled.next_scheduled_date() or "",
                })
        return sorted(
            rows, key=lambda row: (row["next_date"] or "9", row["name"])
        )

    # ---- 日付を進める ----

    def advance(
        self,
        mode: str,
        *,
        target_date: str = "",
        competition_id: str = "",
        school_year: int | None = None,
        stop_at_big_scene: bool = False,
        on_day: Callable[[dict], None] | None = None,
    ) -> dict:
        """日付を進めて、進めた結果と新しい上の帯を返す。

        ``mode`` は 1日（day）／次の試合日まで（next_match_day）／大会が
        終わるまで（competition_end）／指定日まで（date）。まとめて進めるとき
        ``stop_at_big_scene`` なら、大きな場面（決勝・代表決定）の日の前で止まる。
        """
        if mode not in ADVANCE_MODES:
            raise ValueError(f"unknown advance mode: {mode}")
        start = self.state.current_date
        if mode == ADVANCE_DAY:
            result = self.service.next_day(self.session)
            if on_day is not None:
                on_day(result)
            return self._advanced(start, result, "")

        checks: list[Callable[[object], str]] = []
        if mode == ADVANCE_DATE:
            target = date.fromisoformat(target_date)
            if target <= start:
                raise ValueError("指定日は今日より後にしてください")
        else:
            target = start + timedelta(
                days=int(self.config["advance"]["max_days"])
            )
        if mode == ADVANCE_NEXT_MATCH_DAY:
            checks.append(
                lambda _: STOP_MATCH_DAY if self.today_matches() else ""
            )
        if mode == ADVANCE_COMPETITION_END:
            season = _seasons(self.state).get(
                int(school_year) if school_year is not None
                else self.header()["school_year"]
            )
            if season is None or competition_id not in season.competitions:
                raise ValueError("その大会は進行中ではありません")
            checks.append(
                lambda _: STOP_COMPETITION_END
                if season.competitions[competition_id].is_complete else ""
            )
        if stop_at_big_scene:
            checks.append(
                lambda _: STOP_BIG_SCENE if self.big_scene_matches() else ""
            )

        def stop_before(state) -> str:
            for check in checks:
                reason = check(state)
                if reason:
                    return reason
            return ""

        result = self.service.advance_to(
            self.session,
            target.isoformat(),
            stop_before=stop_before if checks else None,
            on_day=on_day,
        )
        return self._advanced(start, result, result.get("stopped_reason", ""))

    def _advanced(self, start: date, result: dict, stopped: str) -> dict:
        header = self.header()
        return {
            "from_date": start.isoformat(),
            "to_date": header["date"],
            "played_match_count": int(result.get("played_match_count", 0)),
            "stopped_reason": stopped,
            "big_scene_matches": (
                self.big_scene_matches()
                if stopped == STOP_BIG_SCENE else []
            ),
            "header": header,
        }
