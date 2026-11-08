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
from .joint_teams import JointTeam, UnionPlan, form_unions, joint_team_config
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
        self.types = {cid: entry.competition_type for cid, entry in plan.entries.items()}
        self._areas = None
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
        lead = self._summer_lead(school_id)
        return self._summer_ends.get(lead or school_id)

    # ---- 連合チーム（game_core/joint_teams.py） ----

    def _plans(self) -> dict:
        return getattr(self.state, "union_plans", None) or {}

    def union_for(self, competition_id: str, school_id: str, *,
                  chain_only: bool = False) -> JointTeam | None:
        """その大会で ``school_id`` が代表校の連合チーム。連合を組んだ大会から進んだ大会
        （地区大会・甲子園など）は、同じ年度の同じつながり（``chains``）の連合を使う。"""
        plans = self._plans()
        if competition_id in plans and not chain_only:
            team = plans[competition_id].team_of(school_id)
            if team is not None:
                return team
            # この大会の計画（新しく組んだ連合・出ない学校）にない学校は、つながりの連合を見る
        chains = joint_team_config()["chains"]
        chain = chains.get(self.types.get(competition_id, ""))
        if chain is None:
            return None
        for cid, plan in plans.items():
            if cid != competition_id and chains.get(self.types.get(cid, "")) == chain:
                team = plan.team_of(school_id)
                if team is not None:
                    return team
        return None

    def _summer_lead(self, school_id: str) -> str | None:
        """夏の連合のほかの学校なら、代表校（夏の終わりは代表校の負けた日）。"""
        plans = self._plans()
        key = tuple(id(plan) for plan in plans.values())
        if key != getattr(self, "_summer_leads_key", None):
            chains = joint_team_config()["chains"]
            self._summer_leads = {
                partner: team.lead
                for cid, plan in plans.items()
                if chains.get(self.types.get(cid, "")) == SUMMER
                for team in plan.teams for partner in team.partners
            }
            self._summer_leads_key = key
        return self._summer_leads.get(school_id)

    def plan_unions(self, competition_id: str, annual) -> UnionPlan | None:
        """大会の連合チーム。その大会の部員の名簿がまだつくれないときは None
        （4月1日に組み直す）。連合を組まない種類の大会は空の計画。"""
        rule = joint_team_config()
        rosters = self.members.rosters
        if rosters is None or self.types.get(competition_id) not in rule["competition_types"]:
            return UnionPlan()
        start = self.starts.get(competition_id)
        if start is None or not rosters.can_build(school_year_of(start)):
            return None
        def count(school_id):
            # 同じつながりの大会ですでに連合の代表校なら、連合の部員で数える
            team = self.union_for(competition_id, school_id, chain_only=True)
            return sum(
                len(self.members.competition_members(
                    competition_id, member, start_date=start,
                    season_segment=self.segments[competition_id]).players)
                for member in (team.schools if team is not None else (school_id,))
            )

        players = {school_id: count(school_id) for school_id in annual.entrant_school_ids}
        branch, town = self._area_lookup()
        preferred = {
            *annual.direct_main_entry_school_ids, *annual.seed_event_bypass_school_ids,
            *annual.main_seed_school_ids, *annual.koshien_exempt_school_ids,
        }
        return form_unions(
            f"{self.plan.year}:{competition_id}", annual.entrant_school_ids, players,
            seed=self.plan.rng_seed, branch_of=branch, municipality_of=town, preferred=preferred,
        )

    def _area_lookup(self):
        """学校 → 支部・地区（data/areas の federation_branch）と市町村。"""
        if self._areas is None:
            import csv

            from phase2_engine.paths import resolve_data_file

            repo = self.plan.repo
            path = resolve_data_file(repo.data_dir, "area_schemes.csv")
            with path.open(encoding="utf-8-sig", newline="") as handle:
                schemes = {row["scheme_id"] for row in csv.DictReader(handle)
                           if row["scheme_type"] == "federation_branch"}
            branch = {}
            for (_, scheme_id), schools in repo.school_areas_by_scheme.items():
                if scheme_id in schemes:
                    for school_id, areas in schools.items():
                        branch[school_id] = min(areas)
            town = {sid: row.get("municipality", "") for sid, row in repo.schools.items()}
            self._areas = (branch, town)
        branch, town = self._areas
        return (lambda sid: branch.get(sid, "")), (lambda sid: town.get(sid, ""))

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
            team = self.union_for(competition_id, school_id)
            if team is not None:
                # 連合チーム：構成校それぞれの大会開始日の部員をまとめる（選手の学校は変えない）
                fixed = replace(fixed, players=tuple(
                    player for member in team.schools
                    for player in self.members.competition_members(
                        competition_id, member, start_date=self.starts[competition_id],
                        season_segment=self.segments[competition_id]).players
                ))
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
