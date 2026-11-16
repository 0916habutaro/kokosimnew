"""記録の画面の「ランキング」：学校別・都道府県別の甲子園などの回数（game_definition.md §9）。

ゲームの記録は年度ごとに数えておき（``year_tally``）、表示のときに期間の年度を足す。
甲子園の実際の記録（``koshien_records.load_actual``。#451 と同じ数え方）は保存では混ぜず、
期間「通算（実際＋ゲーム）」のときに表示のときだけ足す。「ゲーム開始後の通算」と直近◯年は
ゲームの記録だけ（実際の記録は年ごとの勝敗がそろっていないため）。

学校別は、並べ替えの項目（``basis``）と甲子園の種類で記録のある学校だけを出す（``has_record``）。

- 甲子園（夏・選抜）：出場・勝利・敗戦・優勝の回数と勝率（勝ち÷（勝ち＋負け）。引き分けは数えない）
- 明治神宮大会・地区大会（春・秋）・都道府県大会（春・秋の県大会と夏の地方大会）：優勝の回数（ゲームだけ）
"""
from __future__ import annotations

import json
import math
import zlib

TALLY_VERSION = 1
KOSHIEN = {"national_championship": "summer", "national_invitational": "spring"}
TITLES = {
    "national_autumn_championship": "jingu",
    "spring_regional": "regional", "autumn_regional": "regional",
    "spring_prefectural": "prefectural", "autumn_prefectural": "prefectural",
    "summer_local_qualifier": "prefectural",
}
TITLE_KEYS = ("jingu", "regional", "prefectural")
COUNT_KEYS = ("appearances", "wins", "losses", "championships")


# 期間：通算（実際＋ゲーム）・ゲーム開始後の通算・直近◯年（ゲームだけ）
PERIODS = (("all", "通算（実際＋ゲーム）"), ("game", "ゲーム開始後の通算"),
           ("5", "直近5年"), ("10", "直近10年"), ("20", "直近20年"))
KIND_LABELS = {"koshien": "夏か選抜の甲子園", "summer": "夏の甲子園", "spring": "選抜"}
TITLE_LABELS = {"jingu": "神宮大会", "regional": "地区大会", "prefectural": "県大会"}


def period_years(period: str, current: int):
    """期間の年度（None は全年度）と、甲子園の実際の記録を足すか。"""
    if period in ("all", "game"):
        return None, period == "all"
    return set(range(current - int(period) + 1, current + 1)), False


def basis(sort_key: str | None) -> str:
    """学校別に出す学校の基準。神宮・地区・県大会の優勝で並べているときはその大会、
    ほか（甲子園の項目・校名・都道府県）は甲子園（``"koshien"``）。"""
    return sort_key if sort_key in TITLE_KEYS else "koshien"


def has_record(total: dict, kind: str, basis_key: str) -> bool:
    """学校別に出すか：甲子園なら選んだ種類（``kind``）に1回でも出場、ほかはその優勝が1回以上。"""
    if basis_key == "koshien":
        return total[kind]["appearances"] > 0
    return total[basis_key] > 0


def basis_note(kind: str, basis_key: str) -> str:
    if basis_key == "koshien":
        return f"{KIND_LABELS[kind]}に出場した学校だけを出しています。"
    return f"{TITLE_LABELS[basis_key]}で優勝した学校だけを出しています。"


def year_tally(results: dict[str, list[dict]], finished=None) -> dict[str, dict]:
    """1年度の成績（学校ID → 大会ごとの成績。``school_views.year_results`` の形）から、
    学校ID → {"summer"/"spring": [出場, 勝, 敗, 優勝], "jingu"/"regional"/"prefectural": 優勝}。

    ``finished(大会ID)`` が偽の大会（まだ終わっていない）は数えない。回数のない学校は入れない。"""
    out: dict[str, dict] = {}
    for school_id, rows in results.items():
        entry: dict = {}
        for row in rows:
            if finished is not None and not finished(row["competition_id"]):
                continue
            won = row.get("finish") == "優勝"
            kind = KOSHIEN.get(row.get("type"))
            if kind:
                counts = entry.setdefault(kind, [0, 0, 0, 0])
                counts[0] += 1
                counts[1] += int(row.get("wins") or 0)
                counts[2] += int(row.get("losses") or 0)
                counts[3] += int(won)
            title = TITLES.get(row.get("type"))
            if title and won:
                entry[title] = entry.get(title, 0) + 1
        if entry:
            out[school_id] = entry
    return out


def to_blob(tally: dict) -> bytes:
    data = {"version": TALLY_VERSION, "schools": tally}
    return zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)


def from_blob(blob: bytes) -> dict:
    data = json.loads(zlib.decompress(blob))
    if data.get("version") != TALLY_VERSION:
        raise ValueError("ランキングの集計の形が違います")
    return data["schools"]


def empty() -> dict:
    return {kind: dict.fromkeys(COUNT_KEYS, 0) for kind in ("summer", "spring")} | dict.fromkeys(TITLE_KEYS, 0)


def school_totals(tallies: dict[int, dict], years=None, actual: dict | None = None) -> dict[str, dict]:
    """学校ID → 回数の合計。``years`` は足す年度（None なら全期間）。

    ``actual`` を渡すと甲子園の実際の記録（学校ID → {"summer"/"spring": 通算}）を足す
    （実際＋ゲーム）。渡さなければゲームの記録だけ。"""
    out: dict[str, dict] = {}
    for year, tally in tallies.items():
        if years is not None and year not in years:
            continue
        for school_id, entry in tally.items():
            total = out.setdefault(school_id, empty())
            for kind in ("summer", "spring"):
                for key, value in zip(COUNT_KEYS, entry.get(kind, (0, 0, 0, 0))):
                    total[kind][key] += value
            for key in TITLE_KEYS:
                total[key] += entry.get(key, 0)
    for school_id, record in (actual or {}).items():
        for kind in ("summer", "spring"):
            part = record.get(kind)
            if not part:
                continue
            total = out.setdefault(school_id, empty())
            for key in COUNT_KEYS:
                total[kind][key] += int(part.get(key) or 0)
    for total in out.values():
        finish(total)
    return out


def finish(total: dict) -> dict:
    """夏＋春の甲子園の合計と、勝率（勝ち÷（勝ち＋負け）。試合がなければ None）を付ける。"""
    total["koshien"] = {key: total["summer"][key] + total["spring"][key] for key in COUNT_KEYS}
    for kind in ("summer", "spring", "koshien"):
        part = total[kind]
        games = part["wins"] + part["losses"]
        part["rate"] = part["wins"] / games if games else None
    return total


def prefecture_totals(schools: dict[str, dict], prefecture_of) -> dict[str, dict]:
    """都道府県コード → 回数の合計（学校の合計を所在地の都道府県ごとに足す）。"""
    out: dict[str, dict] = {}
    for school_id, total in schools.items():
        code = prefecture_of(school_id)
        if not code:
            continue
        sums = out.setdefault(code, empty())
        for kind in ("summer", "spring"):
            for key in COUNT_KEYS:
                sums[kind][key] += total[kind][key]
        for key in TITLE_KEYS:
            sums[key] += total[key]
    for sums in out.values():
        finish(sums)
    return out


def color_steps(values: dict[str, float | None], steps: int = 5) -> dict:
    """色の段階分け（1系統の色の濃さ）。0 と値なし（None）は塗らない（段階 None）。

    値のある中の最小〜最大を ``steps`` 段に等分する。整数の値は段の幅を整数にする（最小74・
    最大275・5段なら幅41：74〜114、115〜155、…）。小数（勝率）はそのまま等分する。
    戻り値は ``classes``（キー → 段階 0〜 か None）と ``bounds``（段ごとの [下, 上]。
    整数なら両端を含む）。値が1種類だけなら1段。"""
    shown = [v for v in values.values() if v]
    if not shown:
        return {"classes": dict.fromkeys(values), "bounds": [], "integer": True}
    low, top = min(shown), max(shown)
    integer = all(float(v).is_integer() for v in shown)
    if integer:
        low, top = int(low), int(top)
        width = max(1, math.ceil((top - low + 1) / steps))
        count = math.ceil((top - low + 1) / width)
        bounds = [[low + width * i, min(top, low + width * (i + 1) - 1)] for i in range(count)]
        classes = {key: (None if not v else (int(v) - low) // width) for key, v in values.items()}
    else:
        if top == low:
            return {"classes": {k: (None if not v else 0) for k, v in values.items()},
                    "bounds": [[low, top]], "integer": False}
        width = (top - low) / steps
        bounds = [[low + width * i, low + width * (i + 1)] for i in range(steps)]
        classes = {key: (None if not v else min(steps - 1, int((v - low) / width))) for key, v in values.items()}
    return {"classes": classes, "bounds": bounds, "integer": integer}


# ---- 都道府県別の対戦成績（甲子園。ゲーム開始後の試合だけ） ----

MATCHUP_PERIODS = (("game", "ゲーム開始後の通算"), ("5", "直近5年"), ("10", "直近10年"), ("20", "直近20年"))


def koshien_games(rows: list[dict], competitions: dict, finished=None) -> list[dict]:
    """1年度の試合の要約（``school_views.normalized_rows`` の形）から甲子園（夏・選抜）の試合だけ。

    数え方は学校の通算の勝敗（``year_results``）と同じ：勝ちの決まった試合だけ（引き分けは
    数えず、再試合はその試合を1試合、不戦勝は勝ち・負けに数える）。``finished(大会ID)`` が偽の
    大会（まだ終わっていない）は数えない（ランキングと同じ）。回戦名は本大会の回戦の数から。"""
    games = [row for row in rows
             if KOSHIEN.get(competitions.get(row["competition_id"], {}).get("competition_type"))
             and (finished is None or finished(row["competition_id"]))]
    rounds: dict[str, int] = {}
    for row in games:
        if row["main"]:
            rounds[row["competition_id"]] = max(rounds.get(row["competition_id"], 0), row["round_no"])
    out = []
    for row in games:
        cid = row["competition_id"]
        if row.get("third_place"):
            round_name = "3位決定戦"
        elif row["main"]:
            round_name = {0: "決勝", 1: "準決勝", 2: "準々決勝"}.get(
                rounds[cid] - row["round_no"], f"{row['round_no']}回戦")
        else:
            round_name = ""
        out.append({
            "competition_id": cid, "match_id": row["match_id"], "match_date": row["match_date"],
            "kind": KOSHIEN[competitions[cid]["competition_type"]], "round_name": round_name,
            "team1_id": row["team1_id"], "team2_id": row["team2_id"],
            "team1_score": row["team1_score"], "team2_score": row["team2_score"],
            "winner_id": row["winner_id"],
        })
    return out


def _picked(games_by_year: dict[int, list[dict]], years, kind: str):
    for year, games in sorted(games_by_year.items()):
        if years is not None and year not in years:
            continue
        for game in games:
            if kind == "koshien" or game["kind"] == kind:
                yield year, game


def matchups(games_by_year: dict[int, list[dict]], years, kind: str, area_of) -> dict[str, dict]:
    """地域 → {"wins", "losses", "rate", "opponents": {相手の地域: [勝, 敗]}}。

    同じ地域どうしの試合は、その地域に1勝1敗（相手の欄は自分の地域）。地域の分からない学校の
    試合は数えない。"""
    out: dict[str, dict] = {}
    for _, game in _picked(games_by_year, years, kind):
        one, two = area_of(game["team1_id"]), area_of(game["team2_id"])
        if not one or not two:
            continue
        for me, other, won in ((one, two, game["winner_id"] == game["team1_id"]),
                               (two, one, game["winner_id"] == game["team2_id"])):
            entry = out.setdefault(me, {"wins": 0, "losses": 0, "opponents": {}})
            entry["wins" if won else "losses"] += 1
            entry["opponents"].setdefault(other, [0, 0])[0 if won else 1] += 1
    for entry in out.values():
        games = entry["wins"] + entry["losses"]
        entry["rate"] = entry["wins"] / games if games else None
    return out


def best_and_worst(opponents: dict[str, list[int]], order: dict[str, int]):
    """いちばん勝ち越している相手と、いちばん負け越している相手（勝ち越し・負け越しがなければ None）。

    差が同じなら試合の多い方、それも同じなら地図の並びの順。"""
    def pick(sign):
        rows = [(sign * (w - l), w + l, -order.get(a, 99), a) for a, (w, l) in opponents.items() if sign * (w - l) > 0]
        if not rows:
            return None
        area = max(rows)[3]
        return {"area": area, "wins": opponents[area][0], "losses": opponents[area][1]}
    return pick(1), pick(-1)


def area_games(games_by_year: dict[int, list[dict]], years, kind: str, area_of, area: str) -> list[dict]:
    """その地域の学校が出た試合（新しい順）。``side`` はその地域の学校の側（1か2。両方なら1）。"""
    out = []
    for year, game in _picked(games_by_year, years, kind):
        one, two = area_of(game["team1_id"]), area_of(game["team2_id"])
        if area not in (one, two) or not one or not two:
            continue
        out.append({**game, "school_year": year, "side": 1 if one == area else 2,
                    "team1_area": one, "team2_area": two})
    out.sort(key=lambda g: (g["match_date"], g["match_id"]), reverse=True)
    return out
