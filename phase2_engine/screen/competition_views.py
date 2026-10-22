"""大会の一覧・トーナメント表・試合の詳細を画面用にまとめる（game_definition.md §9）。

トーナメント表の配置（校名の行・試合の交点・線）はここで計算し、画面は
その座標どおりに描くだけにする。
"""
from __future__ import annotations

from ..tournament_runtime import MATCH_BYE, MainTournamentRuntimeState


SEGMENT_LABELS = {"spring": "春", "summer": "夏", "autumn": "秋"}
LEVEL_LABELS = {"national": "全国", "regional": "地区", "local": "都道府県"}
STATUS_LABELS = {
    "upcoming": "これから",
    "active": "進行中",
    "completed": "終了",
}
EVENT_LABELS = {
    "single": "安打",
    "double": "二塁打",
    "triple": "三塁打",
    "home_run": "本塁打",
    "walk": "四球",
    "hit_by_pitch": "死球",
    "field_out": "凡打",
    "fielder_choice": "野選",
    "reached_on_error": "失策",
    "sacrifice_bunt": "犠打",
    "sacrifice_fly": "犠飛",
    "strikeout": "三振",
}
POSITION_LABELS = {
    "P": "投", "C": "捕", "1B": "一", "2B": "二", "3B": "三",
    "SS": "遊", "LF": "左", "CF": "中", "RF": "右",
}
HALF_LABELS = {"t": "表", "b": "裏", "top": "表", "bottom": "裏"}


def main_runtime(scheduled) -> MainTournamentRuntimeState | None:
    runtime = scheduled.runtime
    if isinstance(runtime, MainTournamentRuntimeState):
        return runtime
    return getattr(runtime, "main_runtime", None)


def _level(competition: dict) -> str:
    level = competition.get("competition_level", "")
    return "local" if level not in ("national", "regional") else level


def competition_list(
    seasons: dict, plans: dict, repo, names, short_names,
) -> list[dict]:
    """進行中の年度の大会（始まっていない大会も含む）。"""
    rows = []
    for year, season in seasons.items():
        plan = plans.get(year)
        for cid in season.annual_templates:
            competition = repo.competitions.get(cid, {})
            entry = plan.entries.get(cid) if plan is not None else None
            calendar = season.calendar_rows.get(cid, {})
            scheduled = season.competitions.get(cid)
            if scheduled is None:
                status = "upcoming"
            elif scheduled.is_complete:
                status = "completed"
            else:
                status = "active"
            main = main_runtime(scheduled) if scheduled is not None else None
            champion = main.champion_school_id if main is not None else ""
            name = (
                entry.display_name if entry is not None else ""
            ) or competition.get("competition_name", cid)
            rows.append({
                "school_year": year,
                "competition_id": cid,
                "name": name,
                "short_name": short_names(cid, name),
                "segment": competition.get("season_segment", ""),
                "segment_label": SEGMENT_LABELS.get(
                    competition.get("season_segment", ""), ""
                ),
                "level": _level(competition),
                "level_label": LEVEL_LABELS[_level(competition)],
                "prefecture_code": competition.get("prefecture_code", ""),
                "start_date": calendar.get("start_date", ""),
                "end_date": calendar.get("end_date", ""),
                "status": status,
                "status_label": STATUS_LABELS[status],
                "champion_id": champion,
                "champion_name": names(champion) if champion else "",
            })
    level_order = {"national": 0, "regional": 1, "local": 2}
    return sorted(rows, key=lambda row: (
        row["school_year"], row["start_date"] or "9",
        level_order[row["level"]], row["prefecture_code"], row["name"],
    ))


def bracket_layout(main: MainTournamentRuntimeState, scheduled) -> dict:
    """MAIN の組み合わせを、行（校名）と交点（試合）の座標にする。

    行は最初の枠の順に、空き枠（不戦勝）を詰めて並べる。試合の交点の y は
    2つの子（行または下の回戦の試合）の y の中ほど。不戦勝の試合は描かず、
    勝ち上がる学校の行をそのまま上の回戦へつなぐ。
    """
    rows: list[dict] = []
    leaf_y: dict[int, float] = {}
    for index, school_id in enumerate(main.initial_slots):
        if school_id:
            leaf_y[index] = float(len(rows))
            rows.append({"school_id": school_id, "y": float(len(rows))})

    scheduled_matches = scheduled.matches
    nodes: dict[str, dict] = {}
    drawn: list[dict] = []

    def source(round_no: int, match_no: int, side: int) -> dict | None:
        """試合（round_no, match_no）の side 側の子。"""
        if round_no == 1:
            index = (match_no - 1) * 2 + side
            if index not in leaf_y:
                return None
            return {"y": leaf_y[index], "round": 0, "match_id": ""}
        child_no = (match_no - 1) * 2 + side + 1
        child_id = main._match_id(round_no - 1, child_no)
        return node(child_id)

    def node(match_id: str) -> dict | None:
        if match_id in nodes:
            return nodes[match_id]
        bracket_match = main.matches[match_id]
        children = [
            source(bracket_match.round_no, bracket_match.match_no_in_round, side)
            for side in (0, 1)
        ]
        present = [child for child in children if child is not None]
        if bracket_match.status == MATCH_BYE or len(present) < 2:
            # 不戦勝：子をそのまま上へつなぐ
            result = present[0] if present else None
        else:
            result = {
                "y": (present[0]["y"] + present[1]["y"]) / 2,
                "round": bracket_match.round_no,
                "match_id": match_id,
            }
            row = scheduled_matches.get(match_id)
            teams = (bracket_match.team1, bracket_match.team2)
            scores = (
                getattr(row, "team1_score", None),
                getattr(row, "team2_score", None),
            )
            drawn.append({
                "match_id": match_id,
                "round": bracket_match.round_no,
                "round_name": bracket_match.round_name,
                "y": result["y"],
                # 左右の子（行または下の回戦の試合）と、そこから来る学校・得点
                "children": [
                    {
                        "y": child["y"], "round": child["round"],
                        "school_id": teams[side], "score": scores[side],
                    }
                    for side, child in enumerate(children)
                    if child is not None
                ],
                "team1_id": bracket_match.team1,
                "team2_id": bracket_match.team2,
                "winner_id": bracket_match.winner,
                "team1_score": getattr(row, "team1_score", None),
                "team2_score": getattr(row, "team2_score", None),
                "match_date": getattr(row, "match_date", ""),
                "status": bracket_match.status,
            })
        nodes[match_id] = result
        return result

    if main.total_rounds:
        final_id = main._match_id(main.total_rounds, 1)
        final = node(final_id)
    else:
        final = None
    round_names = {
        match["round"]: match["round_name"] for match in drawn
    }
    return {
        "total_rounds": main.total_rounds,
        "rows": rows,
        "matches": sorted(drawn, key=lambda m: (m["round"], m["y"])),
        "round_names": [
            round_names.get(number, f"{number}回戦")
            for number in range(1, main.total_rounds + 1)
        ],
        "final_y": final["y"] if final else 0.0,
        "champion_id": main.champion_school_id,
    }


def other_stage_matches(scheduled) -> list[dict]:
    """MAIN 以外（予選・シード決め）の試合。"""
    return [
        _match_row(row)
        for row in sorted(
            scheduled.matches.values(),
            key=lambda m: (m.match_date or "9", m.stage_code, m.match_id),
        )
        if row.stage_code != "MAIN" and row.team1_id and row.team2_id
    ]


def _match_row(row) -> dict:
    return {
        "match_id": row.match_id,
        "stage_code": row.stage_code,
        "round_name": row.round_name,
        "group_name": row.group_name,
        "match_date": row.match_date,
        "team1_id": row.team1_id,
        "team2_id": row.team2_id,
        "team1_score": row.team1_score,
        "team2_score": row.team2_score,
        "winner_id": row.winner_id,
        "status": row.status,
    }


def _innings(detail: dict, team1: str, team2: str) -> tuple[list, list]:
    by_team: dict[str, dict[int, int | None]] = {team1: {}, team2: {}}
    for half in detail.get("inning_scores") or ():
        team = half.get("batting_team_id")
        if team in by_team:
            by_team[team][int(half["inning"])] = (
                int(half.get("runs") or 0) if half.get("was_played", True)
                else None
            )
    innings = max(
        [9] + [number for team in by_team.values() for number in team]
    )

    def line(team):
        return [by_team[team].get(number, None) for number in range(1, innings + 1)]

    return line(team1), line(team2)


def _outs_to_innings(outs: int) -> str:
    whole, rest = divmod(int(outs or 0), 3)
    return f"{whole}" + (f" {rest}/3" if rest else "")


def match_detail(row: dict, detail: dict | None, names, players) -> dict:
    """試合の画面：得点板、試合の要点、両チームの個人成績。

    ``players(school_id)`` は選手ID → 選手（名前・守備位置）。
    """
    team1, team2 = row["team1_id"], row["team2_id"]
    out = {
        **{key: row.get(key) for key in (
            "competition_id", "competition_name", "match_id", "match_date",
            "stage_code", "round_name", "group_name", "team1_id", "team2_id",
            "team1_score", "team2_score", "winner_id", "status",
        )},
        "team1_name": names(team1),
        "team2_name": names(team2),
        "has_detail": detail is not None,
    }
    if detail is None:
        return out
    line1, line2 = _innings(detail, team1, team2)
    team_stats = {
        stat["school_id"]: stat for stat in detail.get("team_stats") or ()
    }
    out["board"] = [
        {
            "school_id": team, "name": names(team), "innings": line,
            "runs": row.get(f"team{number}_score"),
            "hits": team_stats.get(team, {}).get("hits"),
            "errors": team_stats.get(team, {}).get("errors"),
        }
        for number, team, line in ((1, team1, line1), (2, team2, line2))
    ]
    lookup = {team: players(team) for team in (team1, team2)}

    def player_name(school_id, player_id):
        player = lookup.get(school_id, {}).get(player_id)
        return player.display_name if player is not None else ""

    batting_team = {"t": team1, "b": team2}
    highlights = []
    for item in detail.get("highlights") or ():
        kind, inning, half = item[0], item[1], item[2]
        if kind == "S":
            school = batting_team[half]
            highlights.append({
                "kind": "score", "inning": inning,
                "half": HALF_LABELS[half], "school_id": school,
                "school_name": names(school),
                "player_name": player_name(school, item[3]),
                "event": EVENT_LABELS.get(item[4], item[4]),
                "is_home_run": item[4] == "home_run",
                "runs": item[5],
            })
        else:
            school = item[3]
            highlights.append({
                "kind": "pitching_change", "inning": inning,
                "half": HALF_LABELS[half], "school_id": school,
                "school_name": names(school),
                "player_name": player_name(school, item[4]),
            })
    out["highlights"] = highlights

    def position(school_id, player_id):
        player = lookup.get(school_id, {}).get(player_id)
        return (
            POSITION_LABELS.get(player.primary_position, "")
            if player is not None else ""
        )

    out["batting"] = {
        team: [
            {
                "name": player_name(team, stat["player_id"]),
                "position": position(team, stat["player_id"]),
                **{key: stat.get(key, 0) for key in (
                    "at_bats", "hits", "runs", "rbi", "home_runs",
                    "walks", "strikeouts", "stolen_bases",
                )},
            }
            for stat in detail.get("batter_stats") or ()
            if stat.get("school_id") == team
        ]
        for team in (team1, team2)
    }
    out["pitching"] = {
        team: [
            {
                "name": player_name(team, stat["player_id"]),
                "innings": _outs_to_innings(stat.get("outs_recorded", 0)),
                **{key: stat.get(key, 0) for key in (
                    "batters_faced", "hits_allowed", "runs_allowed",
                    "earned_runs", "walks", "strikeouts",
                    "home_runs_allowed",
                )},
            }
            for stat in detail.get("pitcher_stats") or ()
            if stat.get("school_id") == team
        ]
        for team in (team1, team2)
    }
    return out
