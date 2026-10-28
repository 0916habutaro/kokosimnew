"""画面に出すデータをまとめて返す層（game_definition.md §9、ADR-044）。

画面（JavaScript）はここが返す dict / list だけを読む。値は JSON にできる
形（文字列・数・真偽・リスト・dict）にする。日付を進める処理もここを通す。
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from game_core.players import Player
from game_core.school_reputation import reputation_for

from ..career_state import CareerState
from ..paths import resolve_data_file
from ..save_slots import SAVE_KIND_MANUAL
from ..school_edits import SchoolEdits
from .competition_views import (
    POSITION_LABELS,
    bracket_layout,
    competition_list,
    has_started,
    main_runtime,
    match_detail,
    other_stage_matches,
)
from .competition_names import CompetitionNames
from .coach_views import CoachHistory, official_record, tournament_record
from ..competition_records import competition_records
from .koshien_records import (
    KINDS as KOSHIEN_KINDS,
    RECORDS_PATH as KOSHIEN_RECORDS_PATH,
    appearance_label,
    combined as koshien_combined,
    count_label,
    load_actual as load_actual_koshien,
)
from .player_views import (
    GROWTH_LABELS,
    injury_row,
    ability_rows,
    ability_values,
    rank,
    season_stats,
    snapshot_values,
    trend_keys,
)
from .save_views import next_slot_id, recovery_rows, slot_rows
from .school_names import EditedNames, SchoolNames, prefecture_names
from .school_views import (
    SchoolAbilities,
    team_totals,
    best_result,
    koshien_summary,
    normalized_rows,
    year_results,
)


CONFIG_PATH = Path("screen") / "screen_v1.json"
BASIS_LABELS = {"century": "21世紀枠", "jingu": "神宮枠"}
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


def _csv_rows(data_dir, name: str) -> list[dict]:
    with resolve_data_file(data_dir, name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


PLAYER_FIELDS = tuple(Player.__dataclass_fields__)


def _prefecture_short(name: str) -> str:
    """都道府県名から「都・府・県」を除く（東京都→東京、京都府→京都）。北海道はそのまま。"""
    return name[:-1] if name.endswith(("都", "府", "県")) else name


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
        self.names = EditedNames(
            SchoolNames(service.repo, config_root), self._load_edits(),
        )
        self.competition_names = CompetitionNames(config_root)
        # ゲーム開始前の甲子園の実際の記録（ゲームの記録とは混ぜずに並べる）
        self.actual_koshien = load_actual_koshien(
            config_root.parent / KOSHIEN_RECORDS_PATH
        )
        self.prefectures = prefecture_names(service.repo.data_dir)
        # 地区大会の校名に添える「石川1位」（都道府県大会の順位から）
        self._feeder_rules: dict[str, list[dict]] = {}
        for row in _csv_rows(service.repo.data_dir, "regional_feeder_rules.csv"):
            if row.get("source_type") == "prefectural_result":
                self._feeder_rules.setdefault(row["destination_competition_id"], []).append(row)
        self._entry_tags: dict[tuple, dict[str, str]] = {}
        # 都道府県 → 地区（秋の地区割り。出場校一覧の札の色）
        self._regions = {
            row["prefecture_code"]: row["region_id"]
            for row in sorted(
                _csv_rows(service.repo.data_dir, "prefecture_region_memberships.csv"),
                key=lambda row: row.get("effective_year", ""),
            )
            if row.get("season_segment") == "autumn"
        }
        self.abilities = self._new_abilities()
        self._closed_years: dict[int, dict] = {}
        self._coach_history = None
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
        return {
            "menu": list(MENU), "header": header,
            "ability_ranks": dict(self.config["ability_ranks"]),
        }

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
            today = season.current_date.isoformat()
            for cid, scheduled in season.competitions.items():
                if scheduled.is_complete or not has_started(scheduled, today):
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
        season = self._season_of(int(school_year))
        if season is None:
            raise ValueError("その年度の大会の記録はありません")
        return season

    def _season_of(self, year: int):
        """進行中の年度の状態、なければ閉じた年度の状態（見るだけ）。どちらもなければ None。"""
        season = _seasons(self.state).get(year)
        if season is not None:
            return season
        closed = self.service.closed_season(
            self.session.slot_id, year, self.session.plan.rng_seed,
        )
        return closed[0] if closed is not None else None

    def _plan_of(self, year: int):
        """その年度の大会の表示名（閉じた年度は閉じたときに残した名前）。"""
        plan = self._plans().get(year)
        if plan is not None:
            return plan
        closed = self.service.closed_season(
            self.session.slot_id, year, self.session.plan.rng_seed,
        )
        names = closed[1] if closed is not None else {}
        return SimpleNamespace(entries={
            cid: SimpleNamespace(display_name=name) for cid, name in names.items()
        })

    def competitions(self, school_year=None) -> dict:
        """その年度（省くと今の年度）の大会。閉じた年度は見るだけ。"""
        year = int(school_year) if school_year else self._current_year()
        season = self._season_of(year)
        rows = competition_list(
            {year: season}, {year: self._plan_of(year)}, self.service.repo,
            self.names, self.competition_names,
        ) if season is not None else []
        return {
            "school_year": year,
            "competitions": rows,
            "school_years": self._years(),
        }

    def bracket(self, school_year, competition_id: str) -> dict:
        season = self._season(school_year)
        names = self.names
        listing = {
            row["competition_id"]: row
            for row in competition_list(
                {int(school_year): season}, {int(school_year): self._plan_of(int(school_year))},
                self.service.repo, names, self.competition_names,
            )
        }
        if competition_id not in listing:
            raise ValueError("その大会はありません")
        out = {"competition": listing[competition_id]}
        scheduled = season.competitions.get(competition_id)
        if scheduled is None:
            return {**out, "main": None, "entrants": [], "other_matches": [], "names": {}}
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
        first_day = min(
            (m.match_date for m in scheduled.matches.values() if m.match_date),
            default="",
        )
        return {
            **out,
            "main": layout,
            "entrants": self._national_entrants(
                int(school_year), competition_id, main,
            ),
            "other_matches": others,
            # 大会の最初の試合の日の名前
            "names": {
                school_id: self.team_name(
                    school_id, competition_id, first_day, int(school_year),
                )
                for school_id in ids if school_id
            },
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
            data, detail,
            lambda school_id: self.team_name(
                school_id, competition_id, data.get("match_date", ""), int(school_year),
            ),
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
                "team1_name": self.team_name(row.team1_id, cid, row.match_date, year),
                "team2_name": self.team_name(row.team2_id, cid, row.match_date, year),
            }
            for year, cid, row in rows
            if row.match_date == target
        ]
        items.sort(key=lambda m: (m["competition_name"], m["match_id"]))
        # 前後の試合日（見ている日が試合日でなくても、その前後の日）
        return {
            "date": target,
            "prev_date": next((d for d in reversed(played) if d < target), ""),
            "next_date": next((d for d in played if d > target), ""),
            "matches": items,
        }

    def _national_entrants(self, year: int, competition_id: str, main) -> list[dict]:
        """全国大会の出場校（都道府県順）。夏・春は甲子園の通算〇回目つき。"""
        competition = self.service.repo.competitions.get(competition_id, {})
        if competition.get("competition_level") != "national" or main is None:
            return []
        kind = {"national_championship": "summer",
                "national_invitational": "spring"}.get(competition.get("competition_type"))
        before = self._koshien_counts(year - 1) if kind else None
        # この大会の暦の年（選抜は年度の翌年の3月）
        this_year = year + 1 if kind == "spring" else year
        areas = self._summer_areas(year) if kind == "summer" else {}
        basis = self._selection_basis(year, competition_id)
        schools = self.service.repo.schools
        rows = []
        for school_id in main.entrant_school_ids:
            row = {
                "school_id": school_id,
                "name": self.names(school_id),
                "prefecture": self.prefectures.get(
                    schools.get(school_id, {}).get("prefecture_code"), ""
                ),
                "prefecture_code": schools.get(school_id, {}).get("prefecture_code", ""),
                # 地区名：夏は代表の大会（北北海道・東東京など）、ほかは都道府県
                "area": areas.get(school_id) or self.prefecture_short(school_id),
                # 地区名の札の色（地方ごと）
                "region_id": self._regions.get(
                    schools.get(school_id, {}).get("prefecture_code"), ""
                ),
                # 選抜の21世紀枠・神宮枠
                "basis_label": BASIS_LABELS.get(basis.get(school_id, ""), ""),
                "appearance": None,
                "appearance_label": "",
            }
            if kind:
                actual = self.actual_koshien.get(school_id, {}).get(kind, {})
                row["appearance"] = count_label(
                    actual.get("appearances", 0),
                    before[kind]["appearances"].get(school_id, 0) + 1,
                )
                row["appearance_label"] = appearance_label(
                    actual, before[kind]["years"].get(school_id, set()),
                    this_year, row["appearance"]["total"],
                )
            rows.append(row)
        return sorted(rows, key=lambda row: (row["prefecture_code"], row["name"]))

    def _selection_basis(self, year: int, competition_id: str) -> dict[str, str]:
        """選抜の出場校 → 選ばれた枠（jingu・century）。選考の記録から。"""
        season = self._season_of(year)
        for entry in getattr(season, "history", None) or ():
            if (
                entry.get("action") == "select_invitational"
                and entry.get("competition_id") == competition_id
            ):
                return dict(entry.get("selection_basis") or {})
        return {}

    def entrant(self, school_year, competition_id: str, school_id: str) -> dict:
        """出場校一覧の右の詳細：総合ランク・レーダー・予選の成績と勝ち上がり。

        予選は、夏の甲子園なら夏の地方大会、選抜・神宮なら秋の都道府県大会と地区大会。"""
        year = int(school_year)
        competition = self.service.repo.competitions.get(competition_id, {})
        segment = (
            "summer" if competition.get("competition_type") == "national_championship"
            else "autumn"
        )
        results = sorted(
            (
                r for r in self._results(year).get(school_id, [])
                if r["segment"] == segment and r["level"] in ("local", "regional")
            ),
            key=lambda r: r["first_date"],
        )
        ids = {r["competition_id"] for r in results}
        games = [
            m for m in self.school_matches(school_id, year)["matches"]
            if m["competition_id"] in ids
        ]
        totals = team_totals(
            school_id,
            (self._match_record(year, m["competition_id"], m["match_id"]) for m in games),
        )
        return {
            "school_id": school_id,
            "name": self.names(school_id),
            "prefecture": self.prefectures.get(
                self.service.repo.schools.get(school_id, {}).get("prefecture_code"), ""
            ),
            "abilities": self._entrant_abilities(year, [school_id]).get(school_id),
            "stats": totals,
            "results": [
                {
                    "competition_name": r["competition_name"],
                    "finish": r["finish"],
                    "wins": r["wins"],
                    "losses": r["losses"],
                    "games": [
                        {key: m[key] for key in (
                            "match_id", "match_date", "round_name", "won",
                            "score", "opponent_score", "opponent_name",
                        )} | {"competition_id": m["competition_id"]}
                        for m in games if m["competition_id"] == r["competition_id"]
                    ],
                }
                for r in results
            ],
        }

    def _match_record(self, year: int, competition_id: str, match_id: str) -> dict | None:
        """試合の個人成績（終わった試合）。まだ書き出していない試合はセーブの中から。"""
        season = _seasons(self.state).get(year)
        if season is not None:
            detail = season.pending_match_details.get(f"{competition_id}:{match_id}")
            if detail is not None:
                return detail
        try:
            return self.service.historical_match(
                self.session.slot_id, year, competition_id, match_id,
            )
        except (KeyError, ValueError, OSError):
            return None

    def _entrant_abilities(self, year: int, school_ids) -> dict:
        """出場校の能力。能力は今の部員から出すので、前の年度の大会には出さない。"""
        members = self._today_members()
        if year != self._current_year() or members is None:
            return {}
        chosen = {sid: members[sid] for sid in school_ids if sid in members}
        self.abilities.compute(chosen, year, self.session.plan.rng_seed)
        return self.abilities.get(chosen, year)[0]

    def _summer_areas(self, year: int) -> dict[str, str]:
        """夏の代表校 → 代表になった大会の地区名（北北海道・東東京・青森…）。"""
        season = self._season_of(year)
        if season is None:
            return {}
        out = {}
        for cid, scheduled in season.competitions.items():
            competition = self.service.repo.competitions.get(cid, {})
            if competition.get("competition_type") != "summer_local_qualifier":
                continue
            main = main_runtime(scheduled)
            if main is None or not main.champion_school_id:
                continue
            short = self.competition_names(cid, competition.get("competition_name", cid))
            out[main.champion_school_id] = short.replace("夏・", "").removesuffix("大会")
        return out

    def team_name(
        self, school_id: str, competition_id: str, day: str = "", year: int | None = None,
    ) -> str:
        """試合に出す校名。全国大会・地区大会では都道府県を添える（横浜（神奈川））。
        夏の甲子園は代表の地区名（東東京など）、地区大会は都道府県大会の順位
        （金沢商（石川1位））。日を渡すと、その日の名前（学校の編集で名前を変える前の
        試合は当時の名前）。``year`` は大会の年度（省くと今の年度）。"""
        name = self.names(school_id, day)
        level = self.service.repo.competitions.get(competition_id, {}).get(
            "competition_level", ""
        )
        if not name or level not in ("national", "regional"):
            return name
        tag = self.entry_tags(competition_id, year).get(school_id)
        return f"{name}（{tag or self.prefecture_short(school_id)}）"

    def entry_tags(self, competition_id: str, year: int | None = None) -> dict[str, str]:
        """学校 → 校名に添える札（夏の甲子園の地区名・地区大会の都道府県の順位）。"""
        year = year or self._current_year()
        key = (year, competition_id, self.state.current_date)
        if key not in self._entry_tags:
            competition = self.service.repo.competitions.get(competition_id, {})
            if competition.get("competition_type") == "national_championship":
                tags = self._summer_areas(year)
            elif competition.get("competition_level") == "regional":
                tags = self._feeder_ranks(year, competition_id)
            else:
                tags = {}
            self._entry_tags = {
                k: v for k, v in self._entry_tags.items() if k[2] == key[2]
            }
            self._entry_tags[key] = tags
        return self._entry_tags[key]

    def _feeder_ranks(self, year: int, competition_id: str) -> dict[str, str]:
        """地区大会に出た学校 → 「石川1位」（その都道府県大会の順位）。"""
        season = self._season_of(year)
        if season is None:
            return {}
        out: dict[str, str] = {}
        for rule in self._feeder_rules.get(competition_id, ()):
            scheduled = season.competitions.get(rule["source_competition_id"])
            if scheduled is None or not scheduled.is_complete:
                continue
            outcome = scheduled.to_competition_run().outcome
            if outcome is None:
                continue
            limit = max(int(rule.get("rank_to") or 0), int(rule.get("quota") or 0))
            prefecture = _prefecture_short(
                self.prefectures.get(rule.get("source_prefecture_code"), "")
            )
            for index, school_id in enumerate(outcome.final_ranking_school_ids[:limit]):
                out.setdefault(school_id, f"{prefecture}{index + 1}位")
        return out

    def prefecture_short(self, school_id: str) -> str:
        """「神奈川」「東京」「京都」「北海道」（都・府・県を除く）。"""
        code = self.service.repo.schools.get(school_id, {}).get("prefecture_code")
        return _prefecture_short(self.prefectures.get(code, ""))

    def stage_label(self, match_id: str, group_name: str = "") -> str:
        """MAIN 以外の試合の段階（「地区予選　川崎・横浜北地区」など）。"""
        stage = self._stage_names.get(match_id.split("-", 1)[0], "") or "予選"
        return f"{stage}　{group_name}" if group_name else stage

    def _competition_name(self, season, competition_id: str, fallback: str) -> str:
        plan = self._plan_of(season.year)
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


    def _roster_players(self, year: int, school_id: str) -> dict:
        """閉じた年度の試合の選手名。名簿（年度ごと、選手IDは変わらない）から。
        3月の大会もあるので前後の年度の名簿も見る。閉じた年度の名簿は試合の履歴に
        書き出してある。選手で試合をしないときは空。"""
        rosters = getattr(self.state, "rosters", None)
        if rosters is None:
            return {}
        players = {}
        for roster_year in (year - 1, year, year + 1):
            if roster_year <= rosters.closed_through:
                rows = self.service.closed_roster(
                    self.session.slot_id, roster_year, school_id,
                ) or []
                players.update({
                    row["player_id"]: Player(**{key: row[key] for key in PLAYER_FIELDS})
                    for row in rows
                })
                continue
            try:
                roster = rosters.roster(roster_year, school_id)
            except ValueError:
                continue
            players.update({player.player_id: player for player in roster.players})
        return players

    def _closed_match(self, year: int, competition_id: str, match_id: str) -> dict:
        """閉じた年度の試合（試合の履歴から）。"""
        detail = self.service.historical_match(
            self.session.slot_id, year, competition_id, match_id,
        )
        if detail is None:
            raise ValueError("その試合はありません")
        row = {**detail, "status": "completed"}
        out = match_detail(
            row, detail,
            lambda school_id: self.team_name(
                school_id, competition_id, row.get("match_date", ""), year,
            ),
            lambda school_id: self._roster_players(year, school_id),
        )
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
            "team1_name": self.team_name(row["team1_id"], cid, row.get("match_date", ""), year),
            "team2_name": self.team_name(row["team2_id"], cid, row.get("match_date", ""), year),
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
        counts = self._koshien_counts(year)

        def koshien_count(school_id: str, kind: str, key: str = "appearances") -> dict:
            actual = self.actual_koshien.get(school_id, {}).get(kind, {})
            return count_label(actual.get(key, 0), counts[kind][key].get(school_id, 0))

        for national in nationals:
            kind = {"national_championship": "summer",
                    "national_invitational": "spring"}.get(national["type"])
            if kind:
                for champion in national["groups"]["優勝"]:
                    champion["championship_count"] = koshien_count(
                        champion["school_id"], kind, "championships"
                    )
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
                "appearance": koshien_count(champion, "summer") if champion else None,
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
                    "appearance": koshien_count(sid, "spring"),
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

    def _koshien_counts(self, year: int) -> dict:
        """その年度までのゲーム内の甲子園（夏・春）の出場・優勝の回数。"""
        counts = {
            kind: {"appearances": {}, "championships": {}, "years": {}}
            for kind in KOSHIEN_KINDS
        }
        kinds = {"national_championship": "summer", "national_invitational": "spring"}
        for each in self._years():
            if each > year:
                continue
            for school_id, rows in self._results(each).items():
                for row in rows:
                    kind = kinds.get(row["type"])
                    if not kind:
                        continue
                    # 出場した年（暦の年。選抜は年度の翌年の3月）
                    counts[kind]["years"].setdefault(school_id, set()).add(
                        int(row["first_date"][:4])
                    )
                    for key, hit in (("appearances", True),
                                     ("championships", row["finish"] == "優勝")):
                        if hit:
                            bucket = counts[kind][key]
                            bucket[school_id] = bucket.get(school_id, 0) + 1
        return counts

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

    def _ownership(self, school_id: str) -> str:
        return self._ownership_label(
            self.service.repo.ownership_type(school_id),
            self.service.repo.schools.get(school_id, {}),
        )

    # ---- 学校の編集 ----

    OWNERSHIP_TYPES = (
        "prefectural", "municipal", "national", "public_university_corporation", "private",
    )

    def _edit_form(self, school_id: str) -> dict:
        """学校の編集の画面に出す今の値・選べる値・変更の記録。"""
        edits = self.names.edits
        school = self.service.repo.schools.get(school_id, {})
        history = [
            {"date": entry["date"], "kind": "info",
             "changes": {k: v for k, v in entry.items() if k != "date"}}
            for entry in edits.info_history(school_id)
        ]
        state = self.state
        book = getattr(state, "rosters", None)
        rep = state.reputation if isinstance(state, CareerState) else None
        reputation = None
        if rep is not None and school_id in rep.values:
            setting = rep.edits.get(school_id)
            limits = self.service._ability_editor().config["reputation"]
            reputation = {"current": rep.values[school_id], "rank": rep.rank(school_id),
                          "setting": dict(setting) if setting else None,
                          "minimum": limits["minimum_z"], "maximum": limits["maximum_z"]}
        return {
            "display_name": self._official_name(school_id),
            "short_name": self.names(school_id),
            "ownership_type": self.service.repo.ownership_type(school_id),
            "ownership_options": [
                {"value": kind, "label": self._ownership_label(kind, school)}
                for kind in self.OWNERSHIP_TYPES
            ],
            "team_editable": book is not None,
            "team_ranks": list(self.config["ability_ranks"]) + ["G"],
            "team_history": [row for row in (book.team_edits if book else [])
                             if row["school_id"] == school_id],
            "reputation": reputation,
            "history": sorted(history, key=lambda row: row["date"]),
        }

    def edit_school(self, school_id: str, payload: dict) -> dict:
        """学校の情報を変える（そのセーブの中だけ。data/master は変えない）。"""
        if self.session is None:
            raise ValueError("遊ぶセーブを選んでください")
        if not isinstance(payload, dict):
            raise ValueError("編集内容が不正です")
        operation = payload.get("operation", "info")
        if operation == "team":
            result = self.service.edit_team(self.session, school_id, payload.get("target"))
            if not result["reached"]:
                return {"error": result["reason"], "result": result}
            self.abilities = self._new_abilities()
            return {"school": self.school(school_id), "result": result}
        if operation == "reputation":
            self.service.edit_reputation(self.session, school_id, payload.get("value"), payload.get("mode"))
            return {"school": self.school(school_id)}
        if operation != "info":
            raise ValueError("編集方法が不正です")
        info = {}
        for key in ("display_name", "short_name"):
            value = str(payload.get(key, "")).strip()
            if not value:
                raise ValueError("名前を入れてください")
            info[key] = value
        ownership = str(payload.get("ownership_type", ""))
        if ownership not in self.OWNERSHIP_TYPES:
            raise ValueError("設置者を選んでください")
        info["ownership_type"] = ownership
        # 元と同じ値は変更として残さない
        school = self.service.repo.schools.get(school_id, {})
        base = {
            "display_name": school.get("official_name") or school.get("display_name", ""),
            "short_name": self.names._base(school_id),
            "ownership_type": school.get("ownership_type", ""),
        }
        current = self.names.edits.info_on(school_id)
        info = {
            key: value for key, value in info.items()
            if value != current.get(key, base[key])
        }
        self.service.edit_school(
            self.session, school_id, info=info,
        )
        self.names.edits = self._load_edits()
        self.abilities = self._new_abilities()
        return self.school(school_id)

    def preview_team(self, school_id, target):
        return self.service.edit_team(self.session, school_id, target, preview=True)

    def edit_player(self, school_id, player_id, payload):
        self.service.edit_player(self.session, school_id, player_id, payload)
        self.abilities = self._new_abilities()
        return self.player(school_id, player_id)

    def _player_edit_form(self, rosters, player):
        from .player_views import BATTER_LABELS, CATCHER_LABELS, PITCHER_LABELS, PITCH_LABELS
        from game_core.abilities import FIELD_POSITIONS

        snapshot = rosters.base_ability(player)
        return {
            "fields": [{"key": key, "label": label, "value": getattr(snapshot, key),
                        "minimum": 100 if key == "velocity_kmh" else 1,
                        "maximum": 165 if key == "velocity_kmh" else 100}
                       for key, label in BATTER_LABELS + CATCHER_LABELS + PITCHER_LABELS
                       if getattr(snapshot, key) is not None],
            "aptitudes": [{"key": key, "label": POSITION_LABELS.get(key, key),
                           "value": snapshot.aptitude(key),
                           "minimum": 60 if key == player.primary_position else 1, "maximum": 100}
                          for key in FIELD_POSITIONS],
            "pitches": [pitch.to_dict() for pitch in snapshot.pitch_repertoire],
            "pitch_types": [{"key": key, "label": PITCH_LABELS.get(key, key)} for key in rosters.pitch_types()],
            "history": rosters.ability_edits.get(player.player_id, []),
        }

    def _ownership_label(self, kind: str, school: dict) -> str:
        if kind == "prefectural":
            prefecture = self.prefectures.get(school.get("prefecture_code"), "")
            return (prefecture[-1:] or "県") + "立"
        return {
            "municipal": "市立", "private": "私立", "national": "国立",
            "public_university_corporation": "公立大学法人",
        }.get(kind, "不明")

    def _official_name(self, school_id: str) -> str:
        """学校の詳細に出す名前（編集した表示名を優先）。"""
        school = self.service.repo.schools.get(school_id, {})
        return (
            self.names.edits.info_on(school_id).get("display_name")
            or school.get("official_name") or school.get("display_name", "")
        )

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
                "official_name": self._official_name(school_id),
                "prefecture_code": school.get("prefecture_code", ""),
                "prefecture": self.prefectures.get(school.get("prefecture_code"), ""),
                "ownership": self._ownership(school_id),
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
                    "player_id": player.player_id,
                    "name": player.display_name,
                    "hometown": self.prefectures.get(player.hometown_prefecture_code, ""),
                    "grade": player.academic_year,
                    "position": POSITION_LABELS.get(player.primary_position, ""),
                    "bats": player.bats, "throws": player.throws,
                    "injury": self._injury_now(player),
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
        coaches = self.state.coaches if isinstance(self.state, CareerState) else None
        coach = coaches.for_school(school_id, on=self.state.current_date) if coaches is not None else None
        return {
            "school_id": school_id,
            "coach": coach.view(self.state.current_date) if coach else None,
            "name": self.names(school_id),
            "official_name": self._official_name(school_id),
            "prefecture": self.prefectures.get(school.get("prefecture_code"), ""),
            "ownership": self._ownership(school_id),
            # 学校の評判は進行中のセーブに保存した最新値。
            "reputation_rank": (
                self.state.reputation.rank(school_id)
                if isinstance(self.state, CareerState) and self.state.reputation is not None
                else reputation_for(str(self.config_root.parent)).rank(
                    school_id, self.session.plan.rng_seed,
                )
            ),
            "school_year": year,
            "abilities": abilities,
            "edit": self._edit_form(school_id),
            "this_year": by_year.get(year, []),
            "yearly": yearly,
            # 甲子園：ゲーム開始前の実際の記録（historical_data）とゲーム内の
            # 記録を混ぜずに持ち、合計と内訳を並べる。実際の記録がない学校は None
            "koshien": {
                kind: koshien_combined(
                    self.actual_koshien.get(school_id, {}).get(kind),
                    game_koshien[kind],
                )
                for kind in KOSHIEN_KINDS
            },
            "members": roster,
            "years": sorted(by_year, reverse=True),
        }

    # ---- 監督（読み取り専用） ----

    def _coach_index(self):
        book = getattr(self.state, 'coaches', None)
        if book is None:
            raise ValueError('このセーブには監督の記録がありません')
        cached = self._coach_history
        if cached is None or cached.book is not book or cached.event_count != len(book.events):
            self._coach_history = CoachHistory(book)
        return self._coach_history

    def school_coaches(self, school_id: str) -> dict:
        if school_id not in self.service.repo.schools:
            raise ValueError('その学校はありません')
        index = self._coach_index()
        return {'school_id': school_id, 'name': self.names(school_id, self.state.current_date.isoformat()),
                'as_of': self.state.current_date.isoformat(),
                'simulation_start': f'{index.book.first_year}-04-01',
                'coaches': index.school(school_id, self.state.current_date, self.names)}

    def coach(self, coach_id: str) -> dict:
        index = self._coach_index()
        today = self.state.current_date
        result = index.coach(coach_id, today, self.names)
        first = result['simulation_start']
        # 特定の学校の索引だけを読み、全年度の大会スナップショットは開かない。
        schools = {p['school_id'] for p in result['periods']}
        archive = self.service._history_archive(self.session.slot_id)
        facts = {}
        for sid in schools:
            for row in archive.school_match_facts(sid, first, today.isoformat()):
                facts[(row['year'], row['competition_id'], row['match_id'])] = row
        # 進行中の試合は保存前の状態を優先する。履歴との二重計上を避ける。
        for year, season in _seasons(self.state).items():
            for cid, scheduled in season.competitions.items():
                for mid, match in scheduled.matches.items():
                    if not schools.intersection((match.team1_id, match.team2_id)):
                        continue
                    key = (year, cid, mid)
                    facts.pop(key, None)
                    if match.status == 'completed':
                        facts[key] = match.public_dict()
        result['official_record'] = official_record(facts.values(), index.book, coach_id, today)
        result['tournament_record'] = self._coach_tournaments(result, index.book, today, schools, archive)
        return result

    def _coach_tournaments(self, person, book, today, schools, archive):
        live = _seasons(self.state)
        records = {(r['year'], r['competition_id'], r['school_id']): r
                   for sid in schools for r in archive.school_competition_records(sid)
                   if r['year'] not in live}
        competitions = getattr(self.service.repo, 'competitions', {})
        for year, season in live.items():
            plan = getattr(self.state, 'plans', {}).get(year)
            entries = plan.entries if plan is not None else {}
            for cid, scheduled in season.competitions.items():
                for row in competition_records(year, cid, scheduled, competitions.get(cid, {}),
                        getattr(season, 'calendar_rows', {}).get(cid, {}),
                        name=entries[cid].display_name if cid in entries else '',
                        confirmed_on=today.isoformat(), school_ids=schools):
                    if row['school_id'] in schools:
                        records[(year, cid, row['school_id'])] = row
        return tournament_record(records.values(), book, person['coach_id'], today,
                                 person['periods'], self.names)

    # ---- 選手 ----

    def player(self, school_id: str, player_id: str) -> dict:
        """選手の画面：名前・出身・学年・成長の型、今の能力、学年ごとの能力の推移
        （年度末の能力。閉じた年度は試合履歴の名簿から）、年度ごとの成績。"""
        rosters = getattr(self.state, "rosters", None) if self.session else None
        if rosters is None:
            raise ValueError("選手は選手で試合をしているときに出ます")
        bands = json.loads(
            (self.config_root / "abilities" / "ability_scale_v1.json").read_text(encoding="utf-8")
        )["display_bands"]
        pitch_types = rosters.pitch_types()
        current = self._current_year()
        entries = []  # (年度, 選手, 年度末の能力の並び or None, 成長の型)
        for year in range(current - 3, current + 1):
            row = None
            if year < current:
                for item in self.service.closed_roster(self.session.slot_id, year, school_id) or ():
                    if item["player_id"] == player_id:
                        row = item
            if row is None and year > rosters.closed_through:
                try:
                    roster = rosters.roster(year, school_id)
                except ValueError:
                    roster = None
                found = next(
                    (p for p in (roster.players if roster else ()) if p.player_id == player_id),
                    None,
                )
                if found is not None:
                    row = {**found.to_dict(), "abilities": None, "growth_type": None}
            if row is not None:
                entries.append((year, row))
        if not entries:
            raise ValueError("その選手はいません")
        last_year, last = entries[-1]
        player = Player(**{key: last[key] for key in PLAYER_FIELDS})
        enrolled = last_year == current
        now = None
        growth_type = next(
            (row["growth_type"] for _, row in reversed(entries) if row["growth_type"]), None,
        )
        injuries = [
            injury_row(i["start"], i["days"], i["severity"])
            for i in next((row.get("injuries") or [] for _, row in reversed(entries)
                           if row.get("injuries")), [])
        ]
        if enrolled:
            state = rosters.state(player)
            from game_core.player_growth import TYPES

            growth_type = TYPES[state.growth_type]
            now = snapshot_values(rosters.ability(player))
            injuries = [
                injury_row(i.start.isoformat(), i.days, i.severity) for i in state.injuries
            ]
        trend = [
            {
                "school_year": year, "grade": row["academic_year"], "label": "年度末",
                "values": ability_values(row["abilities"], pitch_types),
            }
            for year, row in entries if row["abilities"]
        ]
        if now is not None:
            trend.append({
                "school_year": current, "grade": player.academic_year, "label": "今",
                "values": now,
            })
        position = player.primary_position
        return {
            "edit": self._player_edit_form(rosters, player) if enrolled else None,
            "player_id": player.player_id,
            "school_id": school_id,
            "school_name": self.names(school_id),
            "name": player.display_name,
            "hometown": self.prefectures.get(player.hometown_prefecture_code, ""),
            "grade": player.academic_year,
            "status": "在学" if enrolled else "卒業",
            "entry_year": player.entry_year,
            "position": POSITION_LABELS.get(position, ""),
            "bats": player.bats, "throws": player.throws,
            "growth_type": GROWTH_LABELS.get(growth_type or "", ""),
            "injury": self._injury_now(player) if enrolled else None,
            # 怪我の履歴（新しい順）
            "injuries": list(reversed(injuries)),
            "abilities": ability_rows(now, position, bands) if now else [],
            "pitches": now["pitches"] if now else [],
            "trend_keys": [
                {"key": key, "label": label} for key, label in trend_keys(position)
            ],
            "trend": [
                {
                    **item,
                    "values": {
                        key: {
                            "value": item["values"].get(key),
                            "rank": "" if key == "velocity_kmh" else rank(item["values"].get(key), bands),
                        }
                        for key, _ in trend_keys(position)
                    },
                }
                for item in trend
            ],
            "seasons": [
                {"school_year": year, "grade": row["academic_year"],
                 **season_stats(self._school_details(school_id, year), player.player_id)}
                for year, row in entries
            ],
        }

    def _injury_now(self, player) -> dict | None:
        """今日、怪我で休んでいれば重さと復帰の見込みの日。"""
        rosters = getattr(self.state, "rosters", None)
        injury = rosters.injury(player, self.state.current_date) if rosters is not None else None
        if injury is None:
            return None
        return injury_row(injury.start.isoformat(), injury.days, injury.severity)

    def _school_details(self, school_id: str, year: int) -> list[dict]:
        """その学校の、その学校年度（4月〜翌3月）の試合の記録（個人成績つき）。"""
        from ..school_year import school_year_of

        seasons = _seasons(self.state)
        details = []
        for season_year in (year, year + 1):
            if season_year in seasons:
                season = seasons[season_year]
                rows = [
                    (cid, row.match_id, row.match_date)
                    for cid, scheduled in season.competitions.items()
                    for row in scheduled.matches.values()
                    if row.status == "completed" and school_id in (row.team1_id, row.team2_id)
                ]
            else:
                season = None
                rows = [
                    (row["competition_id"], row["match_id"], row["match_date"])
                    for row in self.service.historical_match_index(self.session.slot_id, season_year)
                    if school_id in (row["team1_id"], row["team2_id"])
                ]
            for cid, match_id, day in rows:
                if not day or school_year_of(date.fromisoformat(day)) != year:
                    continue
                detail = (
                    season.pending_match_details.get(f"{cid}:{match_id}")
                    if season is not None else None
                )
                if detail is None:
                    try:
                        detail = self.service.historical_match(
                            self.session.slot_id, season_year, cid, match_id,
                        )
                    except (KeyError, ValueError, OSError):
                        detail = None
                if detail:
                    details.append(detail)
        return details

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
                "opponent_name": self.names(other, row["match_date"]),
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
        self._coach_history = None
        self.service.forget_closed_seasons()
        self.names.edits = self._load_edits()
        self.abilities = self._new_abilities()

    def _load_edits(self) -> SchoolEdits:
        if self.session is None:
            return SchoolEdits()
        return self.service.school_edits(self.session)

    def _new_abilities(self) -> SchoolAbilities:
        return SchoolAbilities(
            self.config_root, self.config["school_overall_weights"],
            # 選手の能力はセーブに入った名簿から
            rosters=getattr(self.state, "rosters", None) if self.session else None,
        )

    def saves(self) -> dict:
        current = self.session.slot_id if self.session is not None else ""
        return {
            "current_slot": current,
            "slots": slot_rows(self.service.list_games(), current),
            "injury": self.injury_levels(),
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

    def injury_levels(self) -> dict:
        """怪我の頻度の選択肢と、遊んでいるセーブの設定。"""
        from game_core.injuries import injury_model

        model = injury_model()
        rosters = getattr(self.state, "rosters", None) if self.session else None
        return {
            "levels": [
                {"id": key, "label": value["label_ja"]} for key, value in model.levels.items()
            ],
            "default": model.config["default_level"],
            "current": rosters.injury_level if rosters is not None else "",
        }

    def set_injury_level(self, level: str) -> dict:
        """遊んでいるセーブの怪我の頻度を変える（セーブの中だけに残す）。"""
        from game_core.injuries import injury_model

        rosters = getattr(self.state, "rosters", None) if self.session else None
        if rosters is None:
            raise ValueError("選手で試合をしているセーブだけ変えられます")
        if level not in injury_model().levels:
            raise ValueError("その設定はありません")
        rosters.injury_level = level
        self.service.save_game(self.session, kind=SAVE_KIND_MANUAL)
        return {**self.saves(), "injury": self.injury_levels()}

    def new_save(self, title: str, rng_seed: int, slot_id: str = "",
                 injury_level: str = "") -> dict:
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
            injury_level=str(injury_level) or None,
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
