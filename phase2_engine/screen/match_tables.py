"""試合の画面の「成績」の表（打撃・投手）を組み立てる（game_definition.md §9）。

画面（JavaScript）は、ここで並べた行・守備の印・計の行をそのまま描く。

- 打撃：打順1〜9の順。各打順の中は先発 → 出た順の交代選手（交代選手は打順の数字を出さず字下げ）
- 守備の印：新聞の書き方。代打は「打」、代走は「走」、守備から出た選手は「守」で始め、守った位置を
  つなげる（「打一」「走中」「投一投」）。DH は「DH」、投手と打撃の兼任は「投・DH」
- 計の行：打者・投手の行の合計（投手の回はアウトの合計から書き直す）
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

# 交代の理由 → 守備の印の頭（game_core/match_state.py の LineupChange.reason）
ENTRY_MARKS = {"pinch_hitter": "打", "pinch_runner": "走"}
DEFENSIVE_ENTRY = "守"
BATTING_KEYS = ("at_bats", "runs", "hits", "rbi", "home_runs", "walks_hbp", "strikeouts")
BATTING_DETAIL_KEYS = ("doubles", "triples", "sacrifice_bunts", "stolen_bases", "caught_stealing",
                       "picked_off", "grounded_into_double_plays", "errors", "passed_balls")
PITCHING_KEYS = ("pitches", "batters_faced", "hits_allowed", "home_runs_allowed", "walks_hbp",
                 "strikeouts", "runs_allowed", "earned_runs")
PITCHING_DETAIL_KEYS = ("wild_pitches", "errors")


def innings_label(outs: int) -> str:
    """アウトの数 → 投球回（「8 1/3」「2/3」「3」）。"""
    whole, rest = divmod(int(outs or 0), 3)
    if not rest:
        return f"{whole}"
    return f"{whole} {rest}/3" if whole else f"{rest}/3"


def slot_entries(lineup: Mapping | None, changes: Iterable[Mapping], team: str) -> dict[int, list[tuple]]:
    """打順 → [(選手ID, 交代の理由, 交代の種類)]（先発 → 出た順）。先発の理由は None。"""
    slots: dict[int, list[tuple]] = {}
    for player in (lineup or {}).get("players") or ():
        if player.get("batting_order"):
            slots.setdefault(int(player["batting_order"]), []).append((player["player_id"], None, None))
    for change in changes:
        if change.get("school_id") != team:
            continue
        batting = change.get("batting_changes")
        if batting is None:
            batting = ([{"batting_order": change["batting_order"], "incoming": change["incoming"]}]
                       if change.get("incoming") and change.get("batting_order") else [])
        for entry in batting:
            incoming = (entry.get("incoming") or {}).get("player_id")
            if incoming and entry.get("batting_order"):
                slot = slots.setdefault(int(entry["batting_order"]), [])
                if all(pid != incoming for pid, *_ in slot):
                    slot.append((incoming, change.get("reason"), change.get("kind")))
    return slots


TWO_WAY = "投・DH"
# 頭に「守」を付けない最初の位置（救援の投手・DHの役で出た選手）
NO_ENTRY_MARK = ("投", "DH", TWO_WAY)


def position_mark(reason: str | None, kind: str | None, starter: bool, history: Sequence[str]) -> str:
    """守備の印。``history`` は守った位置（「投」「一」「DH」「投・DH」…）の並び。

    投手とDHの兼任（投・DH）のあとDHだけになったときは「投・DH」のまま。"""
    places = list(history)
    if places[:1] == [TWO_WAY]:
        places = [TWO_WAY] + [p for p in places[1:] if p not in ("DH", TWO_WAY)]
    text = "".join(places)
    if starter or kind == "pitcher_change":
        return text
    if reason in ENTRY_MARKS:
        return ENTRY_MARKS[reason] + text
    return text if places[:1] and places[0] in NO_ENTRY_MARK else DEFENSIVE_ENTRY + text


def _with_sums(row: Mapping) -> dict:
    out = dict(row)
    # 四死球：打者は死球（hit_by_pitch）、投手は与死球（hit_batters）
    out["walks_hbp"] = (int(row.get("walks") or 0) + int(row.get("hit_by_pitch") or 0)
                        + int(row.get("hit_batters") or 0))
    return out


def batting_table(rows: Sequence[Mapping], lineup: Mapping | None, changes: Iterable[Mapping], team: str,
                  history: Mapping[str, Sequence[str]]) -> dict:
    """打撃の表：{rows: [{…成績, slot, sub, mark}], total: {…}}。

    ``rows`` は打者の成績の行（``player_id`` と成績）。``history`` は選手 → 守った位置の並び（表示の文字）。
    配置の記録がなければ（``lineup`` が None）記録の順のまま、守備の印は「−」。"""
    by_id = {row["player_id"]: _with_sums(row) for row in rows}
    out: list[dict] = []
    if lineup is None:
        out = [{**row, "slot": row.get("batting_order"), "sub": False, "mark": "−"} for row in by_id.values()]
    else:
        placed = set()
        for slot, entries in sorted(slot_entries(lineup, changes, team).items()):
            for index, (pid, reason, kind) in enumerate(entries):
                if pid not in by_id or pid in placed:
                    continue
                placed.add(pid)
                out.append({**by_id[pid], "slot": slot if index == 0 else None, "sub": index > 0,
                            "mark": position_mark(reason, kind, index == 0, history.get(pid, ()))})
        out += [{**row, "slot": None, "sub": True, "mark": "".join(history.get(pid, ()))}
                for pid, row in by_id.items() if pid not in placed]
    total = {key: sum(int(row.get(key) or 0) for row in out) for key in (*BATTING_KEYS, *BATTING_DETAIL_KEYS)}
    return {"rows": out, "total": total}


def pitching_table(rows: Sequence[Mapping], two_way: Iterable[str] = ()) -> dict:
    """投手の表：{rows: [{…成績, innings, mark}], total: {…, innings}}。``two_way`` は投手と打撃の
    兼任（投・DH）の選手。印はその選手だけ「投・DH」。"""
    two_way = set(two_way)
    out = [{**_with_sums(row), "innings": innings_label(row.get("outs", 0)),
            "mark": "投・DH" if row["player_id"] in two_way else ""} for row in rows]
    total = {key: sum(int(row.get(key) or 0) for row in out) for key in (*PITCHING_KEYS, *PITCHING_DETAIL_KEYS)}
    total["innings"] = innings_label(sum(int(row.get("outs") or 0) for row in out))
    return {"rows": out, "total": total}
