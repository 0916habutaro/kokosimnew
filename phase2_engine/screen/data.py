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
from .competition_views import (
    bracket_layout,
    competition_list,
    main_runtime,
    match_detail,
    other_stage_matches,
)
from .competition_names import CompetitionNames
from .school_names import SchoolNames


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
        config_root = Path(service.data_dir).parent / "config"
        self.config = config or load_screen_config(config_root)
        self.names = SchoolNames(service.repo, config_root)
        self.competition_names = CompetitionNames(config_root)

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
                name = self._competition_name(
                    season, cid, scheduled.competition_name,
                )
                rows.append({
                    "school_year": year,
                    "competition_id": cid,
                    "name": name,
                    "short_name": self.competition_names(cid, name),
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

    # ---- 大会・トーナメント表・試合 ----

    def _plans(self) -> dict:
        plans = getattr(self.state, "plans", None)
        if isinstance(self.state, CareerState) and plans:
            return plans
        return {self.session.plan.year: self.session.plan}

    def _season(self, school_year) -> object:
        season = _seasons(self.state).get(int(school_year))
        if season is None:
            raise ValueError("その年度は進行中ではありません")
        return season

    def competitions(self) -> dict:
        rows = competition_list(
            _seasons(self.state), self._plans(), self.service.repo,
            self.names, self.competition_names,
        )
        return {
            "competitions": rows,
            "school_years": sorted({row["school_year"] for row in rows}),
        }

    def bracket(self, school_year, competition_id: str) -> dict:
        season = self._season(school_year)
        names = self.names
        listing = {
            row["competition_id"]: row
            for row in competition_list(
                {int(school_year): season}, self._plans(),
                self.service.repo, names, self.competition_names,
            )
        }
        if competition_id not in listing:
            raise ValueError("その大会はありません")
        out = {"competition": listing[competition_id]}
        scheduled = season.competitions.get(competition_id)
        if scheduled is None:
            return {**out, "main": None, "other_matches": [], "names": {}}
        main = main_runtime(scheduled)
        layout = (
            bracket_layout(main, scheduled) if main is not None else None
        )
        others = other_stage_matches(scheduled)
        ids = {
            team
            for match in others for team in (match["team1_id"], match["team2_id"])
        }
        if layout is not None:
            ids |= {row["school_id"] for row in layout["rows"]}
        return {
            **out,
            "main": layout,
            "other_matches": others,
            "names": {school_id: names(school_id) for school_id in ids if school_id},
        }

    def match(self, school_year, competition_id: str, match_id: str) -> dict:
        season = self._season(school_year)
        scheduled = season.competitions.get(competition_id)
        row = (
            scheduled.matches.get(match_id) if scheduled is not None else None
        )
        if row is None:
            raise ValueError("その試合はありません")
        data = row.public_dict()
        data["competition_id"] = competition_id
        detail = None
        if data.get("status") == "completed":
            detail = season.pending_match_details.get(
                f"{competition_id}:{match_id}"
            )
            if detail is None:
                try:
                    detail = self.service.historical_match(
                        self.session.slot_id, int(school_year),
                        competition_id, match_id,
                    )
                except (KeyError, ValueError, OSError):
                    detail = None
        out = match_detail(
            data, detail, self.names,
            lambda school_id: self._players(season, competition_id, school_id),
        )
        out["school_year"] = int(school_year)
        out["competition_name"] = self._competition_name(
            season, competition_id, out.get("competition_name") or "",
        )
        return out

    def matches_on(self, day: str = "") -> dict:
        """その日の全国の試合（試合の画面の一覧）。日を省くと直近の試合日。"""
        rows = []
        for year, season in _seasons(self.state).items():
            for cid, scheduled in season.competitions.items():
                for row in scheduled.matches.values():
                    if row.match_date and row.team1_id and row.team2_id:
                        rows.append((year, cid, row))
        played = sorted({
            row.match_date for _, _, row in rows if row.status == "completed"
        })
        target = day or (played[-1] if played else self.state.current_date.isoformat())
        names = self.names
        items = [
            {
                "school_year": year,
                "competition_id": cid,
                "competition_name": self.competition_names(
                    cid,
                    self._competition_name(
                        _seasons(self.state)[year], cid, row.competition_name,
                    ),
                ),
                **{key: value for key, value in _match_fields(row).items()},
                "team1_name": names(row.team1_id),
                "team2_name": names(row.team2_id),
            }
            for year, cid, row in rows
            if row.match_date == target
        ]
        items.sort(key=lambda m: (m["competition_name"], m["match_id"]))
        return {
            "date": target,
            "match_dates": played[-60:],
            "matches": items,
        }

    def _competition_name(self, season, competition_id: str, fallback: str) -> str:
        plan = self._plans().get(season.year)
        entry = plan.entries.get(competition_id) if plan is not None else None
        return (entry.display_name if entry is not None else "") or fallback

    @staticmethod
    def _players(season, competition_id: str, school_id: str) -> dict:
        """その大会の出場メンバー（選手で試合をしているとき）。"""
        resolver = getattr(season.engine, "main_match_resolver", None)
        provider = getattr(resolver, "member_provider", None)
        if provider is None:
            return {}
        members = provider(competition_id, school_id)
        return {player.player_id: player for player in members.players}


def _match_fields(row) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "match_id", "match_date", "stage_code", "round_name",
            "group_name", "team1_id", "team2_id", "team1_score",
            "team2_score", "winner_id", "status",
        )
    }
