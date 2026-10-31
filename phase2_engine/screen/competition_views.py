"""大会の一覧・トーナメント表・試合の詳細を画面用にまとめる（game_definition.md §9）。

トーナメント表の配置（校名の行・試合の交点・線）はここで計算し、画面は
その座標どおりに描くだけにする。
"""
from __future__ import annotations

from dataclasses import replace

from game_core.match_state import (TeamMatchParticipation, ChangeMoment, CompletedPlateAppearanceMoment,
                                  apply_lineup_change, replay_team_participation)

from .match_summary import called_label, home_runs, pitchers_of_record
from ..competition_schedule_runtime import SCHEDULE_PENDING
from ..tournament_runtime import MATCH_BYE, MainTournamentRuntimeState
from ..competition_history import result_main as main_runtime


SEGMENT_LABELS = {"spring": "春", "summer": "夏", "autumn": "秋"}
LEVEL_LABELS = {"national": "全国", "regional": "地区", "local": "都道府県"}
STATUS_LABELS = {
    "upcoming": "これから",
    "active": "開催中",
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
    'DH': 'DH', 'P_DH': '投・DH',
    "P": "投", "C": "捕", "1B": "一", "2B": "二", "3B": "三",
    "SS": "遊", "LF": "左", "CF": "中", "RF": "右",
}
HALF_LABELS = {"t": "表", "b": "裏", "top": "表", "bottom": "裏"}


def _level(competition: dict) -> str:
    level = competition.get("competition_level", "")
    return "local" if level not in ("national", "regional") else level


def has_started(scheduled, today: str) -> bool:
    """最初の試合日を迎えたか、1試合でも終わっていれば始まっている。
    日程だけ組まれて最初の試合日より前の大会は「これから」。"""
    return any(
        match.status != SCHEDULE_PENDING or match.match_date <= today
        for match in scheduled.matches.values()
    )


def _first_day(season, competition_id: str, calendar: dict, scheduled) -> str:
    """大会の期間の初日。地区予選など本大会より前の段階があれば、その最初の試合日。"""
    days = [calendar.get("start_date", "")]
    days += [
        dates[0]
        for dates in (getattr(season, "stage_date_lists", {}) or {}).get(competition_id, {}).values()
        if dates
    ]
    if scheduled is not None:
        days += [m.match_date for m in scheduled.matches.values() if m.match_date]
    days = [day for day in days if day]
    return min(days) if days else ""


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
            if scheduled is not None and scheduled.is_complete:
                status = "completed"
            elif scheduled is not None and has_started(
                scheduled, season.current_date.isoformat()
            ):
                status = "active"
            else:
                status = "upcoming"
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
                "start_date": _first_day(season, cid, calendar, scheduled),
                "end_date": calendar.get("end_date", ""),
                "status": status,
                "status_label": STATUS_LABELS[status],
                "champion_id": champion,
                "champion_name": names(champion) if champion else "",
            })
    # 開催中 → これから → 終了の順。その中は始まる日の順
    level_order = {"national": 0, "regional": 1, "local": 2}
    status_order = {"active": 0, "upcoming": 1, "completed": 2}
    return sorted(rows, key=lambda row: (
        row["school_year"], status_order[row["status"]], row["start_date"] or "9",
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

    # 準々決勝などを前の回戦のあとに抽選する大会（夏の甲子園）は、抽選の前の
    # 回戦までを線でつなぎ、そこから先は抽選が済んだ対戦だけを別に出す
    redraw = sorted(getattr(main, "redraw_rounds", {}) or {})
    tree_rounds = redraw[0] - 1 if redraw else main.total_rounds
    final = None
    if tree_rounds == main.total_rounds and main.total_rounds:
        final = node(main._match_id(main.total_rounds, 1))
    elif tree_rounds:
        for match_id in main.match_ids_by_round[tree_rounds]:
            node(match_id)
    round_names = {
        match["round"]: match["round_name"] for match in drawn
    }
    later = [
        {
            "round": round_no,
            "round_name": _round_name_of(main, round_no),
            "drawn": main.is_drawn(round_no),
            "matches": [
                _later_match(main.matches[match_id], scheduled_matches.get(match_id))
                for match_id in main.match_ids_by_round[round_no]
            ],
        }
        for round_no in range(tree_rounds + 1, main.total_rounds + 1)
    ]
    return {
        "total_rounds": tree_rounds,
        "rows": rows,
        "matches": sorted(drawn, key=lambda m: (m["round"], m["y"])),
        "round_names": [
            round_names.get(number, f"{number}回戦")
            for number in range(1, tree_rounds + 1)
        ],
        "final_y": final["y"] if final else 0.0,
        "champion_id": main.champion_school_id if final else "",
        "later_rounds": later,
        "champion_after_draw": main.champion_school_id if not final else "",
    }


def _round_name_of(main, round_no: int) -> str:
    ids = main.match_ids_by_round.get(round_no) or []
    return main.matches[ids[0]].round_name if ids else f"{round_no}回戦"


def _later_match(bracket_match, row) -> dict:
    """抽選で決める回戦の試合（抽選前は学校が空）。"""
    return {
        "match_id": bracket_match.match_id,
        "team1_id": bracket_match.team1,
        "team2_id": bracket_match.team2,
        "winner_id": bracket_match.winner,
        "team1_score": getattr(row, "team1_score", None),
        "team2_score": getattr(row, "team2_score", None),
        "match_date": getattr(row, "match_date", ""),
        "status": bracket_match.status,
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


def _dh_match_lineups(detail, teams, names, player_name, year):
    """DHも同じ状態操作で再生。内部規則通知は選手交代の表示に混ぜない。"""
    lineups, changes = {}, []
    positions, orders = {t: {} for t in teams}, {t: {} for t in teams}
    exited, fielding = {}, {}
    halves = []
    next_pa = 1
    for row in detail['inning_scores']:
        if row['plate_appearances']:
            halves.append((next_pa, next_pa+row['plate_appearances']-1, row['half']))
        next_pa += row['plate_appearances']

    def person(team, pid):
        return dict(player_id=pid, name=player_name(team, pid))

    def roles(state):
        result = {a.player_id: a.defensive_position for a in state.defensive_alignment}
        if state.designated_hitter_id:
            result[state.designated_hitter_id] = ('P_DH' if state.current_pitcher_id == state.designated_hitter_id else 'DH')
        return result

    for raw in detail['team_participation']:
        record = TeamMatchParticipation.from_dict(raw)
        team = record.school_id
        final = replay_team_participation(record, year)
        state = replay_team_participation(replace(record, changes=(), fielding_player_ids=()), year,
                                          registered=final.registered_player_ids)
        exited[team], fielding[team] = final.exited_player_ids, set(record.fielding_player_ids)
        dh = record.starting_designated_hitter_id
        lineups[team] = dict(starting_pitcher_id=record.starting_pitcher_id, players=[
            {**person(team, s.player_id), 'batting_order': s.batting_order,
             'position_code': 'P_DH' if s.player_id == dh == record.starting_pitcher_id else s.defensive_position,
             'position': POSITION_LABELS['P_DH' if s.player_id == dh == record.starting_pitcher_id else s.defensive_position]}
            for s in sorted(record.starting_lineup, key=lambda s: s.batting_order)])
        lineups[team]['designated_hitter_id'] = dh
        lineups[team]['retired_roles'] = ({dh: sorted(final.retired_two_way_roles)}
                                         if dh == record.starting_pitcher_id else {})
        if dh is not None and dh != record.starting_pitcher_id:
            lineups[team]['pitcher'] = {**person(team, record.starting_pitcher_id), 'batting_order': None,
                                      'position_code': 'P', 'position': '投（打順外）'}
        orders[team].update((s.player_id, s.batting_order) for s in state.batting_order)

        def apply(change):
            before_roles = roles(state)
            before_bats = state.batting_order
            old_dh, old_p = state.designated_hitter_id, state.current_pitcher_id
            old_exited, old_retired = state.exited_player_ids, state.retired_two_way_roles
            apply_lineup_change(state, change)
            if change.kind in ('dh_plate_appearance', 'dh_opponent_pitcher'):
                return
            after_roles = roles(state)
            batting = [dict(batting_order=b.batting_order, outgoing=person(team, a.player_id),
                            incoming=person(team, b.player_id))
                       for a, b in zip(before_bats, state.batting_order, strict=True) if a.player_id != b.player_id]
            orders[team].update((b.player_id, b.batting_order) for b in state.batting_order)
            dh_lost = old_dh is not None and state.designated_hitter_id is None
            p_changed = old_p != state.current_pitcher_id
            labels = (['DH解除'] if dh_lost else []) + (['投手交代'] if p_changed else [])
            if not labels:
                labels = ['DH交代' if old_dh != state.designated_hitter_id else '選手交代' if batting else '守備変更']
            changes.append(dict(
                sequence=change.sequence, school_id=team, school_name=names(team),
                inning=change.moment.inning, half=HALF_LABELS[change.moment.half],
                next_plate_appearance_no=change.moment.next_plate_appearance_no, order=change.moment.order,
                kind=change.kind, label='・'.join(labels), outgoing=None, incoming=None, batting_order=None,
                moves=[{**person(team, pid), 'before': POSITION_LABELS[before_roles[pid]],
                        'after': POSITION_LABELS[after_roles[pid]]} for pid in sorted(before_roles.keys() & after_roles.keys())
                       if before_roles[pid] != after_roles[pid]],
                batting_changes=batting, dh_ended=dh_lost,
                pitcher_change=(dict(outgoing=person(team, old_p), incoming=person(team, state.current_pitcher_id)) if p_changed else None),
                fully_exited=[person(team, pid) for pid in sorted(state.exited_player_ids-old_exited)],
                roles_ended=[{**person(team, dh), 'role': '投手' if role == 'pitcher' else '打撃'}
                             for role in sorted(state.retired_two_way_roles-old_retired)]))

        def note(pid, role):
            history = positions[team].setdefault(pid, [])
            if not history or history[-1] != role:
                history.append(role)

        cursor = 0
        for first, last, half in halves:
            defense = teams[1] if half == 'top' else teams[0]
            for pa in range(first, last+1):
                while cursor < len(record.changes):
                    change = record.changes[cursor]
                    if not isinstance(change.moment, ChangeMoment) or change.moment.next_plate_appearance_no != pa:
                        break
                    apply(change)
                    cursor += 1
                actual_roles = roles(state)
                if defense == team:
                    for a in state.defensive_alignment:
                        if a.player_id in fielding[team]:
                            note(a.player_id, actual_roles[a.player_id])
                elif state.designated_hitter_id:
                    note(state.designated_hitter_id, actual_roles[state.designated_hitter_id])
                while cursor < len(record.changes):
                    change = record.changes[cursor]
                    if not isinstance(change.moment, CompletedPlateAppearanceMoment) or change.moment.completed_plate_appearance_no != pa:
                        break
                    apply(change)
                    cursor += 1
        if cursor != len(record.changes):
            raise ValueError('unplayed lineup change in screen record')
    changes.sort(key=lambda c: (c['next_plate_appearance_no'], c['order'], teams.index(c['school_id']), c['sequence']))
    return lineups, changes, positions, orders, exited, fielding


def _match_lineups(detail, teams, names, player_name, year):
    """保存済みの配置を既存の復元操作でたどり、表示用の行と守備履歴へ投影する。"""
    lineups = dict.fromkeys(teams)
    changes = []
    positions = {team: {} for team in teams}
    orders = {team: {} for team in teams}
    exited = {team: set() for team in teams}
    fielding = {team: set() for team in teams}
    if not detail.get("team_participation"):
        return lineups, changes, positions, orders, exited, fielding
    if any(r.get('starting_designated_hitter_id') is not None
           or any(c.get('dh_action') is not None for c in r['changes']) for r in detail['team_participation']):
        return _dh_match_lineups(detail, teams, names, player_name, year)

    spans = []
    next_pa = 1
    for half in detail["inning_scores"]:
        count = half["plate_appearances"]
        if count:
            defense = teams[1] if half["half"] == "top" else teams[0]
            spans.append((next_pa, next_pa + count - 1, defense))
        next_pa += count

    def person(team, player_id):
        return {"player_id": player_id, "name": player_name(team, player_id)} if player_id else None

    for raw in detail["team_participation"]:
        record = TeamMatchParticipation.from_dict(raw)
        team = record.school_id
        final = replay_team_participation(record, year)
        state = replay_team_participation(replace(record, changes=(), fielding_player_ids=()), year,
                                          registered=final.registered_player_ids)
        exited[team] = final.exited_player_ids
        fielding[team] = set(record.fielding_player_ids)
        lineups[team] = {
            "starting_pitcher_id": record.starting_pitcher_id,
            "players": [
                {**person(team, slot.player_id), "batting_order": slot.batting_order,
                 "position_code": slot.defensive_position,
                 "position": POSITION_LABELS[slot.defensive_position]}
                for slot in sorted(record.starting_lineup, key=lambda slot: slot.batting_order)
            ],
        }
        orders[team].update((slot.player_id, slot.batting_order) for slot in record.starting_lineup)
        checkpoints = sorted({first for first, _, defense in spans if defense == team}
                             | {change.moment.next_plate_appearance_no for change in record.changes})
        cursor = span_index = 0
        for pa in checkpoints:
            while cursor < len(record.changes) and record.changes[cursor].moment.next_plate_appearance_no <= pa:
                change = record.changes[cursor]
                before = {a.player_id: a.defensive_position for a in state.defensive_alignment}
                apply_lineup_change(state, change)
                moves = [
                    {**person(team, a.player_id), "before": POSITION_LABELS[before[a.player_id]],
                     "after": POSITION_LABELS[a.defensive_position]}
                    for a in state.defensive_alignment
                    if a.player_id in before and before[a.player_id] != a.defensive_position
                ]
                changes.append({
                    "sequence": change.sequence, "school_id": team, "school_name": names(team),
                    "inning": change.moment.inning, "half": HALF_LABELS[change.moment.half],
                    "next_plate_appearance_no": change.moment.next_plate_appearance_no,
                    "kind": change.kind,
                    "label": {"pitcher_change": "投手交代", "position_change": "守備変更",
                              "substitution": "選手交代"}[change.kind],
                    "outgoing": person(team, change.outgoing_player_id),
                    "incoming": person(team, change.incoming_player_id),
                    "batting_order": change.batting_order, "moves": moves,
                })
                if change.incoming_player_id is not None:
                    orders[team][change.incoming_player_id] = change.batting_order
                cursor += 1
            while pa > spans[span_index][1]:
                span_index += 1
            if spans[span_index][2] == team:
                for assignment in state.defensive_alignment:
                    if assignment.player_id not in fielding[team]:
                        continue
                    history = positions[team].setdefault(assignment.player_id, [])
                    if not history or history[-1] != assignment.defensive_position:
                        history.append(assignment.defensive_position)
    changes.sort(key=lambda c: (c["next_plate_appearance_no"], teams.index(c["school_id"]), c["sequence"]))
    return lineups, changes, positions, orders, exited, fielding


def match_detail(row: dict, detail: dict | None, names, players, *, school_year=None,
                 mercy=()) -> dict:
    """試合の画面：得点板、試合の要点、両チームの個人成績。

    ``players(school_id)`` は選手ID → 選手。名前の解決にだけ使い、本職を実配置にしない。
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
        # 「7回コールド」など（mercy はコールドの規則 [回, 点差]）
        "called": called_label(detail, mercy),
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
        return player.display_name if player is not None else "名前不明"

    year = school_year or detail.get("reference_year") or detail.get("year")
    lineups, changes, positions, orders, exited, fielding = _match_lineups(
        detail, (team1, team2), names, player_name, year,
    )
    out["lineups"] = lineups
    out["lineup_changes"] = changes
    out["has_lineup_record"] = all(lineups.values())

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
    # 勝利投手・敗戦投手（決められないときは None）と本塁打
    record = pitchers_of_record(detail)
    out["decisions"] = {
        key: {"school_id": school, "name": player_name(school, pid)}
        for key, (school, pid) in record.items()
    } if record else None
    out["home_runs"] = [
        {**hr, "name": player_name(hr["school_id"], hr["player_id"])}
        for hr in home_runs(detail)
    ]

    def position(school_id, player_id):
        if lineups[school_id] is None:
            return "配置記録なし"
        return "→".join(POSITION_LABELS[pos] for pos in positions[school_id].get(player_id, ())) or "守備出場なし"

    out["batting"] = {
        team: [
            {
                "player_id": stat["player_id"],
                "name": player_name(team, stat["player_id"]),
                "position": position(team, stat["player_id"]),
                "batting_order": orders[team].get(stat["player_id"]),
                "exited": stat["player_id"] in exited[team],
                "fielded": stat["player_id"] in fielding[team],
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
                "player_id": stat["player_id"],
                "name": player_name(team, stat["player_id"]),
                "innings": _outs_to_innings(stat.get("outs_recorded", 0)),
                **{key: stat.get(key, 0) for key in (
                    "batters_faced", "hits_allowed", "runs_allowed",
                    "earned_runs", "walks", "strikeouts",
                    "home_runs_allowed", "pitches",
                )},
            }
            for stat in detail.get("pitcher_stats") or ()
            if stat.get("school_id") == team
        ]
        for team in (team1, team2)
    }
    for team in (team1, team2):
        lineup = lineups[team]
        if not lineup or lineup.get('designated_hitter_id') is None:
            continue
        endings = lineup['retired_roles']
        batting_ids = {b['player_id'] for b in out['batting'][team]}
        for table in ('batting', 'pitching'):
            for stat in out[table][team]:
                pid = stat['player_id']
                ended = endings.get(pid, ())
                labels = [('投手役終了' if role == 'pitcher' else '打撃役終了') for role in ended]
                if not labels:
                    if pid not in batting_ids:
                        labels = ['守備専任']
                    elif pid not in fielding[team]:
                        labels = ['打撃専任']
                stat['role_label'] = '・'.join(labels)
                if table == 'pitching':
                    stat['position'] = position(team, pid)
                    stat['exited'] = pid in exited[team]
    return out
