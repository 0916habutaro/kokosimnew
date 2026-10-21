"""部員：年度ごとの名簿、3年生の引退、大会ごとの出場メンバー。

game_definition.md §8：

- 入学は4月1日、卒業は3月31日。年度 ``Y`` の名簿は ``Y`` 年4月1日から
  翌年3月31日までの部員（1〜3年生）
- 3年生は自分の学校の夏の大会が終わった時点で引退する
- 各大会の出場メンバーは、その大会が始まった時点の部員から選び、途中で
  入れ替えない。3月に始まる大会は前の年度の名簿（新入生は入らない）
- 秋の大会と1〜3月に始まる大会は新チーム（1・2年生）で戦う。甲子園に
  出ている学校の秋の県大会が甲子園の途中で始まっても、3年生は出ない
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Callable, Mapping

from phase2_engine.models import Team
from phase2_engine.school_year import school_year_of

from .career_rosters import advance_school_roster
from .players import Player, PlayerRosterGenerator, SchoolRoster


NEW_TEAM_SEGMENTS = frozenset({"autumn"})


class RosterBook:
    """年度ごとの名簿。最初の年度は生成し、以降は前の年度から進級・入学でつくる。"""

    def __init__(
        self,
        team_for: Callable[[str], Team],
        *,
        first_year: int,
        career_seed: int,
        generator: PlayerRosterGenerator | None = None,
    ):
        self.team_for = team_for
        self.first_year = first_year
        self.career_seed = career_seed
        self.generator = generator or PlayerRosterGenerator()
        self._rosters: dict[tuple[int, str], SchoolRoster] = {}

    def roster(self, year: int, school_id: str) -> SchoolRoster:
        key = (year, school_id)
        cached = self._rosters.get(key)
        if cached is not None:
            return cached
        if year < self.first_year - 1:
            raise ValueError(f"no roster before {self.first_year - 1}: {year}")
        team = self.team_for(school_id)
        if year == self.first_year - 1:
            roster = self._before_first_year(school_id)
        elif year == self.first_year:
            roster = self.generator.generate_school(
                team, year, self.career_seed
            )
        else:
            roster = advance_school_roster(
                self.roster(year - 1, school_id),
                team,
                next_year=year,
                career_seed=self.career_seed,
                generator=self.generator,
            ).roster
        self._rosters[key] = roster
        return roster

    def _before_first_year(self, school_id: str) -> SchoolRoster:
        """ゲーム開始の前の年度（3月に始まる大会用）。

        最初の年度の2・3年生を1学年戻したもの。卒業した3年生と、まだ
        入学していない新入生はいない。
        """
        first = self.roster(self.first_year, school_id)
        return replace(
            first,
            reference_year=self.first_year - 1,
            players=[
                replace(player, academic_year=player.academic_year - 1)
                for player in first.players
                if player.academic_year >= 2
            ],
        )


@dataclass(frozen=True)
class CompetitionMembers:
    competition_id: str
    school_id: str
    start_date: date
    roster_year: int
    players: tuple[Player, ...]


class SchoolMembers:
    """日付ごとの部員と、大会ごとの出場メンバー。

    ``summer_end(year, school_id)`` は年度 ``year`` に、その学校の夏の大会が
    終わった日（まだなら ``None``）を返す。
    """

    def __init__(
        self,
        rosters: RosterBook,
        summer_end: Callable[[int, str], date | None],
    ):
        self.rosters = rosters
        self.summer_end = summer_end

    def retired(self, year: int, school_id: str, on: date) -> bool:
        end = self.summer_end(year, school_id)
        return end is not None and on > end

    def members_on(self, school_id: str, on: date) -> tuple[Player, ...]:
        year = school_year_of(on)
        roster = self.rosters.roster(year, school_id)
        retired = self.retired(year, school_id, on)
        return tuple(
            player for player in roster.players
            if not (player.academic_year == 3 and retired)
        )

    def competition_members(
        self,
        competition_id: str,
        school_id: str,
        *,
        start_date: date,
        season_segment: str,
    ) -> CompetitionMembers:
        players = self.members_on(school_id, start_date)
        # 秋の大会と、1〜3月に始まる大会（選抜・新しい年度の春季県大会）は
        # 新チーム。夏が終わった3年生は出ない。
        if (
            season_segment in NEW_TEAM_SEGMENTS
            or start_date.month <= 3
        ):
            players = tuple(p for p in players if p.academic_year != 3)
        return CompetitionMembers(
            competition_id=competition_id,
            school_id=school_id,
            start_date=start_date,
            roster_year=school_year_of(start_date),
            players=players,
        )


def summer_end_dates(
    results: Mapping[str, Mapping[str, object]],
    summer_competition_ids: set[str],
    completed_final_ids: set[str] = frozenset(),
) -> dict[str, date]:
    """夏の大会の試合結果から、学校ごとに夏が終わった日を求める。

    負けた日が夏の終わり。最後まで負けなかった全国大会の優勝校は、その
    大会が終わった（``completed_final_ids`` に入った）とき、最後の試合の日で
    終わる。``results`` は ``completed_results()`` の形。
    """
    ended: dict[str, date] = {}
    last_played: dict[tuple[str, str], date] = {}
    for row in results.values():
        competition_id = str(row.get("competition_id"))
        if competition_id not in summer_competition_ids:
            continue
        played = date.fromisoformat(str(row["match_date"]))
        for key in ("team1_id", "team2_id"):
            school = row.get(key)
            if school:
                slot = (competition_id, str(school))
                last_played[slot] = max(
                    played, last_played.get(slot, played)
                )
        loser = row.get("loser_id")
        if loser:
            ended[str(loser)] = min(played, ended.get(str(loser), played))
    for (competition_id, school), played in last_played.items():
        if competition_id in completed_final_ids and school not in ended:
            ended[school] = played
    return ended
