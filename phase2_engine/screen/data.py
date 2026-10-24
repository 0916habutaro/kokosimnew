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
from ..save_slots import SAVE_KIND_MANUAL
from .competition_views import (
    POSITION_LABELS,
    bracket_layout,
    competition_list,
    main_runtime,
    match_detail,
    other_stage_matches,
)
from .competition_names import CompetitionNames
from .save_views import next_slot_id, recovery_rows, slot_rows
from .school_names import SchoolNames, prefecture_names
from .school_views import (
    SchoolAbilities,
    best_result,
    koshien_summary,
    normalized_rows,
    year_results,
)


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

    def __init__(self, service, session=None, *, config: dict | None = None):
        self.service = service
        self.session = session
        config_root = Path(service.data_dir).parent / "config"
        self.config_root = config_root
        self.config = config or load_screen_config(config_root)
        self.names = SchoolNames(service.repo, config_root)
        self.competition_names = CompetitionNames(config_root)
        self.prefectures = prefecture_names(service.repo.data_dir)
        self.abilities = SchoolAbilities(
            config_root, self.config["school_overall_weights"],
        )
        self._closed_years: dict[int, dict] = {}
        self._stage_names = {
            stage["stage_id"]: stage.get("stage_name", "")
            for cid in service.repo.competitions
            for stage in service.repo.stages(cid)
        }

    @property
    def state(self):
        return self.session.state

    # ---- 上の帯・メニュー ----

    def shell(self) -> dict:
        """メニューと上の帯。セーブを選ぶ前は上の帯がない（None）。"""
        header = self.header() if self.session is not None else None
        return {"menu": list(MENU), "header": header}

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
        others = [
            {**row, "round_name": self.stage_label(row["match_id"], row["group_name"])}
            for row in other_stage_matches(scheduled)
        ]
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
        if int(school_year) not in _seasons(self.state):
            return self._closed_match(int(school_year), competition_id, match_id)
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
                "round_name": row.round_name if row.stage_code == "MAIN"
                else self.stage_label(row.match_id, row.group_name),
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

    def stage_label(self, match_id: str, group_name: str = "") -> str:
        """MAIN 以外の試合の段階（「地区予選　川崎・横浜北地区」など）。"""
        stage = self._stage_names.get(match_id.split("-", 1)[0], "") or "予選"
        return f"{stage}　{group_name}" if group_name else stage

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


    def _closed_match(self, year: int, competition_id: str, match_id: str) -> dict:
        """閉じた年度の試合（試合の履歴から）。"""
        detail = self.service.historical_match(
            self.session.slot_id, year, competition_id, match_id,
        )
        if detail is None:
            raise ValueError("その試合はありません")
        row = {**detail, "status": "completed"}
        out = match_detail(row, detail, self.names, lambda _: {})
        out["school_year"] = year
        out["competition_name"] = self.competition_names(
            competition_id, detail.get("competition_name") or competition_id,
        )
        return out

    # ---- 今日 ----

    def today(self) -> dict:
        """今日の画面：今日の試合数、注目の試合、進行中の大会、直近の大きな結果。"""
        return {
            "header": self.header(),
            "featured": self.featured_matches(),
            "recent_results": self.recent_results(),
        }

    def featured_matches(self) -> list[dict]:
        rule = self.config["featured_match"]
        competitions = self.service.repo.competitions
        members = None
        abilities: dict = {}
        if self.abilities is not None:
            members = self._today_members()
            if members is not None:
                abilities = self.abilities.get(members, self._current_year())[0]
        scored = []
        for row in self.today_matches():
            if not (row.get("team1_id") and row.get("team2_id")):
                continue
            ctype = competitions.get(row["competition_id"], {}).get(
                "competition_type", ""
            )
            points = rule["competition_points"].get(
                ctype, rule["other_competition_points"]
            )
            if row.get("stage_code") == "MAIN":
                points += rule["round_points"].get(row.get("round_name", ""), 0)
            overall = [
                abilities[team]["overall"]
                for team in (row["team1_id"], row["team2_id"])
                if abilities.get(team)
            ]
            if len(overall) == 2:
                points += sum(overall) / 2 * float(rule["ability_weight"])
            scored.append((points, row))
        scored.sort(key=lambda item: -item[0])
        # 同じ大会ばかりにならないよう、1つの大会からは max_per_competition 試合まで
        picked, per_competition = [], {}
        for _, row in scored:
            key = (row.get("school_year"), row["competition_id"])
            if per_competition.get(key, 0) >= int(rule["max_per_competition"]):
                continue
            per_competition[key] = per_competition.get(key, 0) + 1
            picked.append(row)
            if len(picked) >= int(rule["count"]):
                break
        return [self._match_summary(row) for row in picked]

    def recent_results(self) -> list[dict]:
        rule = self.config["recent_results"]
        big = self.config["big_scene"]
        competitions = self.service.repo.competitions
        since = (
            self.state.current_date - timedelta(days=int(rule["days"]))
        ).isoformat()
        rows = []
        for year, season in _seasons(self.state).items():
            for cid, scheduled in season.competitions.items():
                if competitions.get(cid, {}).get("competition_type") not in big["competition_types"]:
                    continue
                for row in scheduled.matches.values():
                    if (
                        row.status == "completed"
                        and row.stage_code in big["stage_codes"]
                        and row.round_name in big["round_names"]
                        and row.match_date >= since
                    ):
                        rows.append({**row.public_dict(), "competition_id": cid,
                                     "school_year": year})
        rows.sort(key=lambda r: (r["match_date"], r["competition_id"]), reverse=True)
        return [self._match_summary(row) for row in rows[: int(rule["count"])]]

    def _match_summary(self, row: dict) -> dict:
        cid = row["competition_id"]
        year = row.get("school_year") or self._current_year()
        season = _seasons(self.state).get(year)
        name = (
            self._competition_name(season, cid, row.get("competition_name", ""))
            if season is not None else row.get("competition_name", "")
        )
        return {
            "school_year": year,
            "competition_id": cid,
            "competition_name": self.competition_names(cid, name),
            "match_id": row["match_id"],
            "match_date": row.get("match_date", ""),
            "round_name": row.get("round_name", "") if row.get("stage_code") == "MAIN"
            else self.stage_label(row["match_id"], row.get("group_name", "")),
            "team1_id": row["team1_id"], "team2_id": row["team2_id"],
            "team1_name": self.names(row["team1_id"]),
            "team2_name": self.names(row["team2_id"]),
            "team1_score": row.get("team1_score"),
            "team2_score": row.get("team2_score"),
            "winner_id": row.get("winner_id", ""),
            "status": row.get("status", ""),
        }

    # ---- 記録 ----

    def records(self, school_year=None) -> dict:
        """年度ごとの甲子園・選抜・神宮の上位校と、都道府県の代表校。"""
        years = self._years()
        year = int(school_year) if school_year else self._current_year()
        if year not in years:
            raise ValueError("その年度の記録はありません")
        results = self._results(year)
        by_competition: dict[str, list[tuple[str, dict]]] = {}
        for school_id, rows in results.items():
            for row in rows:
                by_competition.setdefault(row["competition_id"], []).append(
                    (school_id, row)
                )
        competitions = self.service.repo.competitions

        def entry(school_id, row):
            return {
                "school_id": school_id,
                "name": self.names(school_id),
                "prefecture": self.prefectures.get(
                    self.service.repo.schools.get(school_id, {}).get("prefecture_code"), ""
                ),
                "finish": row["finish"],
                "wins": row["wins"], "losses": row["losses"],
            }

        nationals = []
        for ctype, label in NATIONAL_TYPES:
            cids = [cid for cid, c in competitions.items() if c.get("competition_type") == ctype]
            rows = [item for cid in cids for item in by_competition.get(cid, [])]
            groups = {
                finish: [entry(sid, row) for sid, row in rows if row["finish"] == finish]
                for finish in FINISH_GROUPS
            }
            season = _seasons(self.state).get(year)
            started = bool(rows) or any(
                cid in season.competitions for cid in cids
            ) if season is not None else bool(rows)
            nationals.append({
                "type": ctype, "label": label,
                "competition_name": rows[0][1]["competition_name"] if rows else label,
                "played": bool(rows),
                "started": started,
                "finished": bool(groups["優勝"]),
                "entrants": len(rows),
                "groups": groups,
            })
        koshien = {
            sid: row["finish"]
            for cid, items in by_competition.items()
            if competitions.get(cid, {}).get("competition_type") == "national_championship"
            for sid, row in items
        }
        senbatsu = {
            sid: row["finish"]
            for cid, items in by_competition.items()
            if competitions.get(cid, {}).get("competition_type") == "national_invitational"
            for sid, row in items
        }
        representatives = []
        for cid, competition in sorted(
            competitions.items(),
            key=lambda item: (item[1].get("prefecture_code", ""), item[0]),
        ):
            if competition.get("competition_type") != "summer_local_qualifier":
                continue
            champion = next(
                (sid for sid, row in by_competition.get(cid, []) if row["finish"] == "優勝"),
                "",
            )
            representatives.append({
                "competition_id": cid,
                "area": self.competition_names(
                    cid, competition.get("competition_name", cid)
                ).replace("夏・", ""),
                "prefecture": self.prefectures.get(competition.get("prefecture_code"), ""),
                "school_id": champion,
                "name": self.names(champion) if champion else "",
                "koshien": koshien.get(champion, "") if champion else "",
            })
        schools = self.service.repo.schools
        senbatsu_rows = sorted(
            (
                {
                    "school_id": sid, "name": self.names(sid),
                    "prefecture": self.prefectures.get(
                        schools.get(sid, {}).get("prefecture_code"), ""
                    ),
                    "prefecture_code": schools.get(sid, {}).get("prefecture_code", ""),
                    "finish": finish,
                }
                for sid, finish in senbatsu.items()
            ),
            key=lambda row: (row["prefecture_code"], row["name"]),
        )
        return {
            "school_year": year,
            "years": sorted(years, reverse=True),
            "nationals": nationals,
            "representatives": representatives,
            "senbatsu": senbatsu_rows,
        }

    # ---- 学校 ----

    def _today_members(self) -> dict | None:
        """学校ID → 今日の部員（選手で試合をしているとき）。"""
        season = self.state.primary if isinstance(self.state, CareerState) else self.state
        resolver = getattr(season.engine, "main_match_resolver", None)
        provider = getattr(resolver, "member_provider", None)
        if provider is None:
            return None
        today = self.state.current_date
        return {
            school_id: provider.members_on(school_id, today)
            for school_id in self.service.repo.schools
        }

    def compute_abilities(self) -> bool:
        """学校の能力を計算しておく。"""
        job = self.ability_job()
        if job is None:
            return False
        job()
        return True

    def ability_job(self) -> Callable[[], None] | None:
        """今のセーブの能力を計算する処理（別のスレッドで呼ぶ）。

        部員・年度・乱数の種はここで読んでおくので、計算の途中で日付が進んだり
        セーブが切り替わったりしても、読んだ時点のセーブの分だけを計算する。
        """
        if self.session is None:
            return None
        members = self._today_members()
        if members is None:
            return None
        abilities, year = self.abilities, self._current_year()
        seed = self.session.plan.rng_seed
        return lambda: abilities.compute(members, year, seed)

    def _current_year(self) -> int:
        return (
            self.state.school_year if isinstance(self.state, CareerState)
            else self.state.year
        )

    def _year_rows(self, year: int) -> tuple[list[dict], dict]:
        """その年度の試合の要約と、大会ごとの MAIN の回戦数。"""
        seasons = _seasons(self.state)
        if year in seasons:
            season = seasons[year]
            rows = []
            rounds = {}
            for cid, scheduled in season.competitions.items():
                rows.extend(
                    {**row.public_dict(), "competition_id": cid}
                    for row in scheduled.matches.values()
                )
                main = main_runtime(scheduled)
                if main is not None:
                    rounds[cid] = main.total_rounds
            return normalized_rows(rows), rounds
        return normalized_rows(
            self.service.historical_match_index(self.session.slot_id, year)
        ), {}

    def _results(self, year: int) -> dict[str, list[dict]]:
        if year in self._closed_years and year not in _seasons(self.state):
            return self._closed_years[year]
        rows, rounds = self._year_rows(year)
        results = year_results(
            rows, self.service.repo.competitions, rounds,
            self.competition_names,
        )
        if year not in _seasons(self.state):
            self._closed_years[year] = results
        return results

    def _years(self) -> list[int]:
        archived = {
            int(row["year"])
            for row in self.service.career_history_years(self.session.slot_id)
        }
        return sorted(archived | set(_seasons(self.state)))

    def _ownership(self, school: dict) -> str:
        kind = school.get("ownership_type", "")
        if kind == "prefectural":
            prefecture = self.prefectures.get(school.get("prefecture_code"), "")
            return (prefecture[-1:] or "県") + "立"
        return {
            "municipal": "市立", "private": "私立", "national": "国立",
            "public_university_corporation": "公立大学法人",
        }.get(kind, "不明")

    def schools(self) -> dict:
        """学校の一覧（全校）。能力の計算が終わっていない学校は能力が空。"""
        year = self._current_year()
        members = self._today_members()
        if members is None:
            abilities, status = {}, "unavailable"
        else:
            abilities, ready = self.abilities.get(members, year)
            status = "ready" if ready else "computing"
        results = self._results(year)
        rows = []
        for school_id, school in self.service.repo.schools.items():
            mine = results.get(school_id, [])
            best = best_result(mine)
            rows.append({
                "school_id": school_id,
                "name": self.names(school_id),
                "official_name": school.get("official_name") or school.get("display_name", ""),
                "prefecture_code": school.get("prefecture_code", ""),
                "prefecture": self.prefectures.get(school.get("prefecture_code"), ""),
                "ownership": self._ownership(school),
                "abilities": abilities.get(school_id),
                "wins": sum(r["wins"] for r in mine),
                "losses": sum(r["losses"] for r in mine),
                "best": best["label"] if best else "",
                "best_score": best["score"] if best else 0,
            })
        return {"school_year": year, "abilities_status": status, "schools": rows}

    def school(self, school_id: str) -> dict:
        repo = self.service.repo
        if school_id not in repo.schools:
            raise ValueError("その学校はありません")
        school = repo.schools[school_id]
        year = self._current_year()
        members = self._today_members()
        abilities = None
        roster = []
        if members is not None:
            self.abilities.compute({school_id: members[school_id]}, year,
                                   self.session.plan.rng_seed)
            abilities = self.abilities.get(
                {school_id: members[school_id]}, year,
            )[0].get(school_id)
            roster = [
                {
                    "name": player.display_name,
                    "grade": player.academic_year,
                    "position": POSITION_LABELS.get(player.primary_position, ""),
                    "bats": player.bats, "throws": player.throws,
                }
                for player in sorted(
                    members[school_id],
                    key=lambda p: (-p.academic_year, p.roster_no),
                )
            ]
        by_year = {}
        for each in self._years():
            results = self._results(each).get(school_id, [])
            by_year[each] = results
        yearly = []
        for each, results in sorted(by_year.items(), reverse=True):
            row = {
                "school_year": each,
                "wins": sum(r["wins"] for r in results),
                "losses": sum(r["losses"] for r in results),
            }
            for segment in ("spring", "summer", "autumn"):
                part = [r for r in results if r["segment"] == segment]
                best = best_result(part)
                row[segment] = {
                    "best": best["label"] if best else "",
                    "wins": sum(r["wins"] for r in part),
                    "losses": sum(r["losses"] for r in part),
                }
            yearly.append(row)
        game_koshien = koshien_summary(by_year)
        return {
            "school_id": school_id,
            "name": self.names(school_id),
            "official_name": school.get("official_name") or school.get("display_name", ""),
            "prefecture": self.prefectures.get(school.get("prefecture_code"), ""),
            "ownership": self._ownership(school),
            "school_year": year,
            "abilities": abilities,
            "this_year": by_year.get(year, []),
            "yearly": yearly,
            # 甲子園：ゲーム開始前の実際の記録（historical_data 側。収集中）と
            # ゲーム内の記録を混ぜずに並べる。実際の記録がない学校は None
            "koshien": {"game": game_koshien, "actual": None},
            "members": roster,
            "years": sorted(by_year, reverse=True),
        }

    def school_matches(self, school_id: str, school_year) -> dict:
        year = int(school_year)
        seasons = _seasons(self.state)
        if year in seasons:
            rows = [
                {**row.public_dict(), "competition_id": cid}
                for cid, scheduled in seasons[year].competitions.items()
                for row in scheduled.matches.values()
                if school_id in (row.team1_id, row.team2_id)
            ]
        else:
            rows = self.service.historical_match_index(self.session.slot_id, year)
            rows = [
                row for row in rows if school_id in (row["team1_id"], row["team2_id"])
            ]
        all_rows, rounds = self._year_rows(year)
        for row in all_rows:
            if row["main"]:
                cid = row["competition_id"]
                rounds.setdefault(cid, 0)
                if year not in seasons:
                    rounds[cid] = max(rounds[cid], row["round_no"])
        out = []
        for row in normalized_rows(rows):
            mine = 1 if row["team1_id"] == school_id else 2
            other = row["team2_id"] if mine == 1 else row["team1_id"]
            competition = self.service.repo.competitions.get(row["competition_id"], {})
            original = next(
                (r for r in rows if r["match_id"] == row["match_id"]
                 and r["competition_id"] == row["competition_id"]), {},
            )
            out.append({
                "school_year": year,
                "competition_id": row["competition_id"],
                "competition_name": self.competition_names(
                    row["competition_id"],
                    competition.get("competition_name", row["competition_id"]),
                ),
                "match_id": row["match_id"],
                "match_date": row["match_date"],
                "round_name": (
                    original.get("round_name") or round_label(
                        row["round_no"], rounds.get(row["competition_id"], 0),
                    )
                ) if row["main"] else self.stage_label(
                    row["match_id"], original.get("group_name", ""),
                ),
                "opponent_id": other,
                "opponent_name": self.names(other),
                "won": row["winner_id"] == school_id,
                "score": row[f"team{mine}_score"],
                "opponent_score": row[f"team{3 - mine}_score"],
            })
        out.sort(key=lambda m: (m["match_date"], m["match_id"]))
        return {"school_id": school_id, "school_year": year, "matches": out}

    # ---- セーブ ----

    def use_session(self, session) -> None:
        """別のセーブに切り替える。前のセーブの集計は捨てる。"""
        self.session = session
        self._closed_years = {}
        self.abilities = SchoolAbilities(
            self.config_root, self.config["school_overall_weights"],
        )

    def saves(self) -> dict:
        current = self.session.slot_id if self.session is not None else ""
        return {
            "current_slot": current,
            "slots": slot_rows(self.service.list_games(), current),
        }

    def save_now(self) -> dict:
        self.service.save_game(self.session, kind=SAVE_KIND_MANUAL)
        return self.saves()

    def rename_save(self, slot_id: str, title: str) -> dict:
        title = str(title).strip()
        if not title:
            raise ValueError("名前を入れてください")
        self.service.rename_game(slot_id, title)
        return self.saves()

    def delete_save(self, slot_id: str) -> dict:
        if self.session is not None and slot_id == self.session.slot_id:
            raise ValueError("遊んでいるセーブは削除できません")
        self.service.delete_game(slot_id)
        return self.saves()

    def recovery(self, slot_id: str) -> dict:
        return {
            "slot_id": slot_id,
            "sources": recovery_rows(self.service.recovery_sources(slot_id)),
        }

    def open_save(self, slot_id: str, source: str = "latest") -> dict:
        """セーブを読み込んで遊ぶセーブにする。古いセーブからは手動セーブに戻す。"""
        if source == "latest":
            session = self.service.load_game(slot_id)
        else:
            session = self.service.recover_game(slot_id, source=source)
        self.use_session(session)
        return {**self.saves(), "header": self.header()}

    def new_save(self, title: str, rng_seed: int, slot_id: str = "") -> dict:
        """新しく始める。スロット名が空なら ``slot01`` の形で空いているものにする。"""
        title = str(title).strip()
        if not title:
            raise ValueError("名前を入れてください")
        root = self.service.slots.root_dir
        used = [path.name for path in root.iterdir()] if root.exists() else []
        slot_id = str(slot_id).strip() or next_slot_id(used)
        try:
            self.service.slots.validate_slot_id(slot_id)
        except ValueError:
            raise ValueError(
                "スロット名は半角の英数字・「-」・「_」で入れてください"
            ) from None
        if slot_id in used:
            raise ValueError("そのスロット名はもう使われています")
        session = self.service.new_game(
            slot_id, rng_seed=int(rng_seed), title=title,
        )
        self.use_session(session)
        return {**self.saves(), "header": self.header()}


NATIONAL_TYPES = (
    ("national_championship", "夏の甲子園"),
    ("national_invitational", "選抜"),
    ("national_autumn_championship", "明治神宮大会"),
)
FINISH_GROUPS = ("優勝", "準優勝", "ベスト4", "ベスト8")


def round_label(round_no: int, total_rounds: int) -> str:
    """MAIN の回戦名（履歴の試合は回戦名を持たないので番号から）。"""
    return {0: "決勝", 1: "準決勝", 2: "準々決勝"}.get(
        total_rounds - round_no, f"{round_no}回戦"
    )


def _match_fields(row) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "match_id", "match_date", "stage_code", "round_name",
            "group_name", "team1_id", "team2_id", "team1_score",
            "team2_score", "winner_id", "status",
        )
    }
