"""全国大会の日ごとの試合数と、準々決勝以降の抽選（game_definition.md §8）。

設定は ``config/schedule/national_day_plans_v1.json``。第N日は大会の試合日
（``season_calendar.csv`` の ``game_date_list``）の N 番目の日。試合はどの回戦も
組み合わせ表の上から順に入れる。
"""
from __future__ import annotations

import json
from pathlib import Path


CONFIG_PATH = Path("schedule") / "national_day_plans_v1.json"


def load_plans(data_dir: str | Path) -> dict[str, dict]:
    path = Path(data_dir).resolve().parent / "config" / CONFIG_PATH
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_id") != "national_day_plans_v1":
        raise ValueError("national day plan config_id mismatch")
    return data["plans"]


def round_number(key: str, total_rounds: int) -> int:
    """「R2」「QF」「SF」「F」→ 回戦の番号。"""
    from_end = {"QF": 2, "SF": 1, "F": 0}
    if key in from_end:
        return total_rounds - from_end[key]
    return int(key.lstrip("R"))


def plan_for(data_dir, competition_type: str, entrant_count: int) -> dict | None:
    """その大会の計画。出場校の数が計画と違う年は使わない（None）。"""
    plan = load_plans(data_dir).get(competition_type)
    if plan is None or int(plan.get("entrants", 0)) != entrant_count:
        return None
    return plan


def redraw_rounds(plan: dict | None, total_rounds: int) -> dict[int, int]:
    if not plan:
        return {}
    return {
        round_number(key, total_rounds): int(groups)
        for key, groups in (plan.get("redraw") or {}).items()
    }


def match_dates(plan: dict, main, calendar_dates: list[str]) -> dict[str, str]:
    """試合ID → 試合日。各回戦の試合（不戦勝を除く）を上から順に日へ入れる。

    計画の試合数・日数が組み合わせ表や日程と合わなければ空（いつもの割り当て）。"""
    days = plan.get("days") or []
    if len(days) > len(calendar_dates):
        return {}
    queues: dict[int, list[str]] = {}
    for round_no in range(1, main.total_rounds + 1):
        queues[round_no] = [
            match_id for match_id in main.match_ids_by_round[round_no]
            if not main.matches[match_id].is_bye
            and main.matches[match_id].status != "bye"
        ]
    out: dict[str, str] = {}
    for day, entries in zip(calendar_dates, days):
        for key, count in entries:
            queue = queues.get(round_number(key, main.total_rounds), [])
            if len(queue) < int(count):
                return {}
            for _ in range(int(count)):
                out[queue.pop(0)] = day
    if any(queues.values()):
        return {}
    return out
