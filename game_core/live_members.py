"""進行中の年度の大会ごとの出場メンバー（部員の決まりは membership.py）。

大会の開始日（予選を含む最初の試合日）と夏の大会の結果を、年度の計画と
進行中の状態から取り出して ``SchoolMembers`` に渡す。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from phase2_engine.school_year import school_year_of

from .membership import (
    CompetitionMembers,
    RosterBook,
    SchoolMembers,
    summer_end_dates,
)
from .roster_size import bench_score, roster_size_model, select_bench


SUMMER = "summer"
# ベンチ入りの記録で「その大会の出場メンバー全員」（部員が20人以下）
ALL_MEMBERS: tuple[str, ...] = ()
SUMMER_FINAL_TYPE = "national_championship"


def competition_start_dates(plan) -> dict[str, date]:
    """大会ごとの最初の試合日（予選の日程を含む）。"""
    starts: dict[str, list[str]] = {}
    for row in plan.calendar_rows:
        values = [
            value
            for value in (
                row.get("start_date", ""),
                *(row.get("game_date_list") or "").split(";"),
            )
            if value
        ]
        starts.setdefault(row["competition_id"], []).extend(values)
    for row in plan.stage_calendar_rows:
        if row["competition_id"] in starts:
            starts[row["competition_id"]].extend(
                value for value in (row.get("date_list") or "").split(";")
                if value
            )
    return {
        cid: date.fromisoformat(min(values))
        for cid, values in starts.items()
        if values
    }


class LiveSeasonMembers:
    """``AbilityMatchResolver(member_provider=...)`` に渡す出場メンバー。

    進行中の状態（``attach``）から夏の大会の結果を読み、大会ごとの
    メンバーを最初に必要になったときに決めて固定する。
    """

    def __init__(self, plan, rosters: RosterBook | None):
        self.plan = plan
        self.starts = competition_start_dates(plan)
        self.segments = {
            cid: entry.season_segment
            for cid, entry in plan.entries.items()
        }
        self.summer_ids = {
            cid for cid, segment in self.segments.items()
            if segment == SUMMER
        }
        self.final_ids = {
            cid for cid, entry in plan.entries.items()
            if entry.competition_type == SUMMER_FINAL_TYPE
        }
        self.members = SchoolMembers(rosters, self._summer_end)
        self.state = None
        self._fixed: dict[tuple[str, str], CompetitionMembers] = {}
        self._unsaved: dict[str, tuple[str, ...]] = {}
        self._summer_ends: dict[str, date] = {}
        self._summer_ends_as_of: tuple | None = None

    def attach(self, state) -> None:
        self.state = state
        # 状態ができる前（開始前の試合）に選んだベンチ入りも状態に入れる
        saved = getattr(state, "bench_members", None)
        if saved is not None:
            for slot, ids in self._unsaved.items():
                saved.setdefault(slot, ids)
        self._unsaved = {}

    def _summer_end(self, year: int, school_id: str) -> date | None:
        if self.state is None or year != self.plan.year:
            return None
        marker = (
            self.state.current_date,
            len(self.state.history),
        )
        if marker != self._summer_ends_as_of:
            completed = {
                cid for cid in self.final_ids
                if cid in self.state.competitions
                and self.state.competitions[cid].is_complete
            }
            self._summer_ends = summer_end_dates(
                {
                    f"{cid}:{match_id}": {
                        "competition_id": cid,
                        "match_date": match.match_date,
                        "team1_id": match.team1_id,
                        "team2_id": match.team2_id,
                        "loser_id": match.loser_id,
                    }
                    for cid in self.summer_ids
                    if cid in self.state.competitions
                    for match_id, match in self.state.competitions[
                        cid
                    ].matches.items()
                    if match.status == "completed"
                },
                self.summer_ids,
                completed,
            )
            self._summer_ends_as_of = marker
        return self._summer_ends.get(school_id)

    def __call__(
        self,
        competition_id: str,
        school_id: str,
    ) -> CompetitionMembers:
        key = (competition_id, school_id)
        fixed = self._fixed.get(key)
        if fixed is None:
            fixed = self.members.competition_members(
                competition_id,
                school_id,
                start_date=self.starts[competition_id],
                season_segment=self.segments[competition_id],
            )
            fixed = self._bench(fixed)
            self._fixed[key] = fixed
        return fixed

    def _bench(self, members: CompetitionMembers) -> CompetitionMembers:
        """ベンチ入り（roster_size_v1 の bench）。最初に必要になった日（その学校の最初の
        試合の日）の能力で選び、進行中の状態に入れて固定する（セーブの読込で選び直さない）。

        部員が ``size`` 人以下で全員が入るときも、大会ごとに ``ALL_MEMBERS``（空の並び）を
        入れる（画面が前の大会のベンチ入りを出さないように。選手IDは持たずセーブを小さく）。"""
        rosters = self.members.rosters
        if rosters is None:
            return members
        bench = roster_size_model().config["bench"]
        saved = getattr(self.state, "bench_members", None)
        slot = f"{members.competition_id}:{members.school_id}"
        ids = saved.get(slot) if saved is not None else None
        if ids is None:
            if len(members.players) <= int(bench["size"]):
                ids = ALL_MEMBERS
            else:
                chosen = select_bench(members.players, lambda p: bench_score(rosters.ability(p)))
                ids = tuple(p.player_id for p in chosen)
            if saved is not None:
                saved[slot] = ids
            else:
                self._unsaved[slot] = ids
        if ids == ALL_MEMBERS:
            return members
        keep = set(ids)
        return replace(members, players=tuple(p for p in members.players if p.player_id in keep))

    def members_on(self, school_id: str, on: date):
        if school_year_of(on) != self.plan.year:
            raise ValueError("date outside this season's school year")
        return self.members.members_on(school_id, on)


class PlayerSeason:
    """選手で試合をする engine と、それにつなぐ出場メンバー・試合記録の置き場。"""

    def __init__(self, engine, members, resolver):
        self.engine = engine
        self.members = members
        self.resolver = resolver
        # 状態ができる前（開始前の試合）の試合記録
        self.resolver.detail_sink = {}

    def attach(self, state, rosters) -> None:
        """進行中の年度の状態と、セーブに入った名簿（``CareerState.rosters``）をつなぐ。"""
        self.members.attach(state)
        self.members.members.rosters = rosters
        self.resolver.ability_generator.source = rosters
        pending = state.pending_match_details
        pending.update(self.resolver.detail_sink)
        self.resolver.detail_sink = pending
        # 試合の規定（コールドを使わない決勝など）を決めるのに大会の進行を見る
        self.resolver.season_state = state


def new_roster_book(repo, rng_seed: int) -> RosterBook:
    """新規開始の名簿（最初の年度の部員は使うときに乱数の種からつくる）。"""
    from phase2_engine.season_catalog import TEMPLATE_YEAR

    return RosterBook(
        repo.team, first_year=TEMPLATE_YEAR, career_seed=rng_seed,
        school_ids=sorted(sid for sid in repo.schools if sid in repo.school_to_program),
    )


def player_engine(repo, plan) -> PlayerSeason:
    """選手で試合をする engine。進行中の状態ができたら ``attach`` する。"""
    from phase2_engine.engine import TournamentEngine

    from .tournament_bridge import AbilityMatchResolver

    # 名簿は attach でつなぐ（セーブに入っている。new_roster_book でつくる）
    members = LiveSeasonMembers(plan, None)
    resolver = AbilityMatchResolver(
        repo,
        team_generation_seed=plan.rng_seed,
        member_provider=members,
    )
    engine = TournamentEngine(
        repo,
        main_match_resolver=resolver,
        pre_main_match_resolver=resolver,
    )
    return PlayerSeason(engine, members, resolver)
