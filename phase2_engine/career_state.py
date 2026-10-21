"""年度の重なり：いくつかの年度を同じ日付で進める（game_definition.md §8）。

- ゲームの日付は1つ。進行中の年度（``LiveSeasonDependencyRuntimeState``）を
  年度順に同じ日付で進める
- その年度の秋の大会の最後の日が過ぎたら、翌年度の大会表をつくって開く。
  翌年度の3月の試合（春季県大会）は、前の年度の選抜と同じ日に行う
- 年度の最後の日（3月31日）を進めたら、その年度は終わり（``finished_years``）。
  履歴の封印と取り除きはゲームサービスが行う

今の年度（日付が属する年度）の状態は、そのまま ``CareerState`` の属性として
読める（``competitions`` など）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from .school_year import school_year_end, school_year_of


AUTUMN = "autumn"

# (年度, 開く日, 学校ごとの試合の日) → (計画, 状態)
SeasonOpener = Callable[[int, date, dict], tuple[object, object]]


def autumn_end(state) -> date | None:
    """その年度の秋の大会の最後の日（日程の終わりの日）。"""
    ends = [
        date.fromisoformat(row["end_date"])
        for cid, row in state.calendar_rows.items()
        if cid in state.annual_templates
        and row.get("end_date")
        and state.repo.competitions.get(cid, {}).get("season_segment")
        == AUTUMN
    ]
    return max(ends) if ends else None


class CareerState:
    def __init__(
        self,
        seasons: dict[int, object],
        *,
        current_date: date,
        open_season: SeasonOpener | None = None,
        plans: dict[int, object] | None = None,
    ):
        if not seasons:
            raise ValueError("career needs at least one season")
        self.seasons = dict(sorted(seasons.items()))
        self.current_date = current_date
        self.start_date = min(
            state.start_date for state in self.seasons.values()
        )
        # 進めた日（セーブの processed_dates の元）
        self.history: list[dict] = []
        # 翌年度をつくる関数と年度ごとの計画（データ・engine を使うので
        # 書き出さない。読込時につなぎ直す）
        self.open_season = open_season
        self.plans = dict(plans or {})

    # セーブには年度の状態と日付だけを書き出す
    def __getstate__(self):
        return {
            "seasons": self.seasons,
            "current_date": self.current_date,
            "start_date": self.start_date,
            "history": self.history,
        }

    def __setstate__(self, data):
        self.__dict__.update(data)
        self.open_season = None
        self.plans = {}

    @property
    def school_year(self) -> int:
        return school_year_of(self.current_date)

    @property
    def primary(self):
        """今の年度の状態。まだ開いていなければ最新の年度。"""
        year = self.school_year
        if year in self.seasons:
            return self.seasons[year]
        earlier = [y for y in self.seasons if y <= year]
        return self.seasons[max(earlier) if earlier else min(self.seasons)]

    def __getattr__(self, name):
        if name.startswith("__") or name in (
            "seasons", "current_date", "plans", "open_season", "history",
        ):
            raise AttributeError(name)
        return getattr(self.primary, name)

    @property
    def year(self) -> int:
        return self.primary.year

    @property
    def rng_seed(self) -> int:
        return self.primary.rng_seed

    def finished_years(self) -> list[int]:
        return [
            year for year in self.seasons
            if self.current_date > school_year_end(year)
        ]

    def drop(self, year: int) -> object:
        if year not in self.finished_years():
            raise ValueError(f"season {year} has not finished")
        if len(self.seasons) == 1:
            raise ValueError("cannot drop the only season")
        self.plans.pop(year, None)
        return self.seasons.pop(year)

    def _open_next_season(self) -> list[int]:
        latest = max(self.seasons)
        state = self.seasons[latest]
        end = autumn_end(state)
        if (
            latest + 1 in self.seasons
            or end is None
            or self.current_date <= end
        ):
            return []
        if self.open_season is None:
            raise ValueError("career cannot open the next season")
        # 前の年度と同じ「学校ごとの試合の日」を使い、3月の選抜と新しい
        # 年度の春季県大会が同じ学校で同じ日に重ならないようにする
        plan, state = self.open_season(
            latest + 1, self.current_date, state.school_days,
        )
        self.seasons[latest + 1] = state
        self.plans[latest + 1] = plan
        return [latest + 1]

    def _record_day(self, played: int) -> None:
        self.history.append({
            "action": "play_today",
            "date": self.current_date.isoformat(),
            "match_count": played,
        })

    def play_today(self) -> list[dict]:
        results: list[dict] = []
        for year, state in self.seasons.items():
            if state.current_date == self.current_date:
                results.extend(state.play_today())
        self._record_day(len(results))
        return results

    def next_day(self) -> dict:
        played = 0
        for year, state in self.seasons.items():
            if state.current_date != self.current_date:
                continue
            if self.current_date >= school_year_end(year):
                played += len(state.play_today())
            else:
                played += state.next_day()["played_match_count"]
        self._record_day(played)
        previous = self.current_date
        self.current_date = previous + timedelta(days=1)
        opened = self._open_next_season()
        return {
            "from_date": previous.isoformat(),
            "to_date": self.current_date.isoformat(),
            "played_match_count": played,
            "opened_years": opened,
            "finished_years": self.finished_years(),
        }

    def advance_to(self, target: str | date) -> dict:
        target_date = (
            target if isinstance(target, date)
            else date.fromisoformat(target)
        )
        if target_date < self.current_date:
            raise ValueError("career cannot move backward")
        days = 0
        played = 0
        while self.current_date < target_date:
            played += self.next_day()["played_match_count"]
            days += 1
        return {
            "current_date": self.current_date.isoformat(),
            "advanced_days": days,
            "played_match_count": played,
        }

    def advance_through(self, target: str | date) -> dict:
        result = self.advance_to(target)
        result["played_match_count"] += len(self.play_today())
        result["processed_through"] = self.current_date.isoformat()
        return result
