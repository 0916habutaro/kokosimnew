"""今日の画面の「今日の見出し」：前の試合日の出来事を、新聞の見出しのように並べる。

見出しは、その日の試合の記録（``batter_stats``・``pitcher_stats``・``inning_scores``）と大会の
結果から、その場で作る（保存の形は変えない）。判定の値と並べ方は
``config/screen/headlines_v1.json``。

ここには学校・選手の名前や過去の出場を読む処理はなく、``data.GameScreenData`` が1日分を
まとめて読んで渡す。

1行は {kind, label, text, tier, level, round_weight, target}。``target`` は押したときに開く画面
（試合なら {"type": "match", school_year, competition_id, match_id}、学校なら
{"type": "school", school_id}）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .player_records import CYCLE, NO_HITTER, PERFECT, PlayerTally

CONFIG_PATH = Path("screen") / "headlines_v1.json"
FEAT_KINDS = (PERFECT, NO_HITTER, CYCLE)


def load_config(config_root: str | Path) -> dict:
    data = json.loads((Path(config_root) / CONFIG_PATH).read_text(encoding="utf-8"))
    if data.get("config_id") != "headlines_v1":
        raise ValueError("headlines config_id mismatch")
    return data


# ---- 1行をつくる ----


def headline(config: dict, kind: str, text: str, match: dict, *, target: dict | None = None,
             years: int | None = None) -> dict:
    """見出しの1行。``match`` はその出来事の試合（大会の格・回戦の重さに使う）。"""
    label = config["labels"][kind].format(years=years)
    return {
        "kind": kind,
        "label": label,
        "text": text,
        "tier": int(config["tiers"][kind]),
        "level": match.get("level", ""),
        "round_weight": round_weight(config, match),
        "target": target or match_target(match),
        "key": f"{kind}:{match.get('competition_id')}:{match.get('match_id')}",
    }


def match_target(match: dict) -> dict:
    return {"type": "match", "school_year": match["school_year"],
            "competition_id": match["competition_id"], "match_id": match["match_id"]}


def school_target(school_id: str) -> dict:
    return {"type": "school", "school_id": school_id}


def round_weight(config: dict, match: dict) -> int:
    if match.get("stage_code") != "MAIN":
        return 0
    return int(config["round_weights"].get(match.get("round_name", ""), 0))


def where(match: dict) -> str:
    """「夏・東京大会 3回戦」。"""
    return f"{match['competition_name']} {match['round_name']}".strip()


def arrange(config: dict, items: list[dict]) -> dict:
    """大事な順（順位 → 大会の格 → 回戦の重さ → 種類の順）に並べ、同じ見出しは1つにする。

    ``shown`` は最初に出す行数（残りは「ほか◯件」）。"""
    levels = {level: i for i, level in enumerate(config["level_order"])}
    kinds = {kind: i for i, kind in enumerate(config["tiers"])}
    seen, unique = set(), []
    for item in items:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        unique.append(item)
    unique.sort(key=lambda h: (
        h["tier"], levels.get(h["level"], len(levels)), -h["round_weight"],
        kinds.get(h["kind"], len(kinds)), h["key"],
    ))
    return {"items": unique, "shown": min(len(unique), int(config["max_lines"]))}


# ---- 試合の出来事 ----


def _int(value) -> int:
    return int(value or 0)


def _sides(match: dict) -> tuple[str, str]:
    """（勝った学校, 負けた学校）。"""
    winner = match["winner_id"]
    loser = match["team2_id"] if winner == match["team1_id"] else match["team1_id"]
    return winner, loser


def _score(match: dict) -> str:
    """勝った学校から見たスコア「5-4」。"""
    one, two = _int(match.get("team1_score")), _int(match.get("team2_score"))
    return f"{one}-{two}" if match["winner_id"] == match["team1_id"] else f"{two}-{one}"


def _halves(detail: dict) -> list[dict]:
    return [h for h in (detail.get("inning_scores") or ()) if h.get("was_played", True)]


def game_flow(match: dict, detail: dict) -> dict:
    """勝った学校の最大のビハインド・サヨナラか・最後の回。"""
    winner = match["winner_id"]
    runs = {match["team1_id"]: 0, match["team2_id"]: 0}
    behind = 0
    halves = _halves(detail)
    for half in halves:
        team = half.get("batting_team_id")
        if team in runs:
            runs[team] += _int(half.get("runs"))
        other = sum(v for k, v in runs.items() if k != winner)
        behind = max(behind, other - runs.get(winner, 0))
    last = halves[-1] if halves else {}
    last_inning = _int(detail.get("last_inning")) or _int(last.get("inning"))
    walk_off = (
        last.get("half") == "bottom" and last.get("batting_team_id") == winner
        and last_inning >= 9 and _int(last.get("runs")) > 0
    )
    return {"behind": behind, "walk_off": walk_off, "last_inning": last_inning}


def _drama_scope(config: dict, match: dict) -> bool:
    rule = config["drama"]
    if match.get("stage_code") != "MAIN":
        return False
    return match.get("level") in rule["levels"] or match.get("round_name") in rule["local_round_names"]


def drama_headline(config: dict, match: dict, detail: dict, names: dict) -> dict | None:
    """大逆転・サヨナラ・延長（1試合に1行。重なれば添える）。"""
    flow = game_flow(match, detail)
    winner, loser = _sides(match)
    extra = flow["last_inning"] >= 10
    notes = []
    if extra:
        notes.append(f"延長{flow['last_inning']}回タイブレーク")
    if flow["walk_off"]:
        notes.append("サヨナラ")
    note = f"（{'・'.join(notes)}）" if notes else ""
    rule = config["drama"]
    scoped = _drama_scope(config, match)
    if flow["behind"] >= int(rule["comeback_runs" if scoped else "comeback_runs_elsewhere"]):
        return headline(config, "comeback",
                        f"{names[winner]}、{flow['behind']}点差をひっくり返し{names[loser]}に{_score(match)}{note} ― {where(match)}",
                        match)
    if not scoped:
        return None
    if flow["walk_off"]:
        lead = f"延長{flow['last_inning']}回、" if extra else ""
        return headline(config, "walk_off",
                        f"{names[winner]}、{lead}{names[loser]}にサヨナラ勝ち（{_score(match)}） ― {where(match)}",
                        match)
    if extra:
        return headline(config, "extra_innings",
                        f"{names[winner]}、延長{flow['last_inning']}回タイブレークの末{names[loser]}を{_score(match)}で破る ― {where(match)}",
                        match)
    return None


def _player_label(names: dict, team: str, person: tuple[str, int] | None) -> str:
    """「青葉台・佐藤（3年）」。名前が分からなければ校名だけ。"""
    if not person or not person[0]:
        return names[team]
    surname = person[0].split()[0]
    grade = f"（{person[1]}年）" if person[1] else ""
    return f"{names[team]}・{surname}{grade}"


def _may_have_feat(detail: dict, min_outs: int) -> bool:
    """見出しになるノーヒットノーラン・サイクル安打があり得るか（集計を通す前の軽い絞り込み）。"""
    return any(
        not _int(row.get("hits_allowed")) and not _int(row.get("runs_allowed"))
        and _int(row.get("outs_recorded")) >= min_outs
        for row in detail.get("pitcher_stats") or ()
    ) or any(
        _int(row.get("doubles")) and _int(row.get("triples")) and _int(row.get("home_runs"))
        for row in detail.get("batter_stats") or ()
    )


def feat_headlines(config: dict, match: dict, detail: dict, names: dict, player) -> list[dict]:
    """完全試合・ノーヒットノーラン・サイクル安打（``player_records`` の判定）。

    ``player(学校ID, 選手ID)`` は（名前, 学年）か None。ノーヒットノーラン・完全試合は
    ``feat_min_outs`` アウト以上投げ切った試合だけ（コールドの試合は見出しにしない）。"""
    if not _may_have_feat(detail, int(config["feat_min_outs"])):
        return []
    tally = PlayerTally(year=match["school_year"])
    tally.add(match["competition_id"], match["match_id"],
              {**detail, "match_date": detail.get("match_date") or match.get("match_date")})
    out = []
    for feat in tally.feats:
        if feat["kind"] != CYCLE and feat.get("outs", 0) < int(config["feat_min_outs"]):
            continue
        team = match["team1_id"] if feat["opponent_id"] == match["team2_id"] else match["team2_id"]
        who = _player_label(names, team, player(team, feat["player_id"]))
        out.append({**headline(config, feat["kind"], f"{who}、{where(match)}で達成", match),
                    "player_id": feat["player_id"]})
    return out


def record_headlines(config: dict, match: dict, detail: dict, names: dict, player,
                     skip_pitchers=frozenset()) -> list[dict]:
    """1試合の奪三振・本塁打・得点の記録。``skip_pitchers`` はノーヒットノーランなどで見出しに
    なった投手（同じ投手の奪三振は重ねて出さない）。"""
    rule = config["records"]
    out = []
    for row in detail.get("pitcher_stats") or ():
        k = _int(row.get("strikeouts"))
        if k >= int(rule["strikeouts"]) and row["player_id"] not in skip_pitchers:
            who = _player_label(names, row["school_id"], player(row["school_id"], row["player_id"]))
            out.append({**headline(config, "strikeouts", f"{who}、1試合{k}奪三振 ― {where(match)}", match),
                        "key": f"strikeouts:{match['competition_id']}:{match['match_id']}:{row['player_id']}"})
    for row in detail.get("batter_stats") or ():
        hr = _int(row.get("home_runs"))
        if hr >= int(rule["home_runs"]):
            who = _player_label(names, row["school_id"], player(row["school_id"], row["player_id"]))
            out.append({**headline(config, "home_runs", f"{who}、1試合{hr}本塁打 ― {where(match)}", match),
                        "key": f"home_runs:{match['competition_id']}:{match['match_id']}:{row['player_id']}"})
    winner, loser = _sides(match)
    runs = max(_int(match.get("team1_score")), _int(match.get("team2_score")))
    if runs >= int(rule["runs"]) and _drama_scope(config, match):
        out.append(headline(config, "big_score",
                            f"{names[winner]}、{names[loser]}から{runs}点（{_score(match)}） ― {where(match)}", match))
    return out


def rank_gap(rank_order: list[str], winner_rank: str, loser_rank: str) -> int:
    """評判のランクの差（負けた学校が何段上か）。分からなければ0。"""
    if winner_rank not in rank_order or loser_rank not in rank_order:
        return 0
    return rank_order.index(winner_rank) - rank_order.index(loser_rank)


def upset_headline(config: dict, match: dict, names: dict, ranks: dict, rank_order: list[str]) -> dict | None:
    """評判のランクの差が大きい勝利。大会の格・回戦で基準を変える（config の upset.rules）。"""
    winner, loser = _sides(match)
    win_rank, lose_rank = ranks.get(winner, ""), ranks.get(loser, "")
    for rule in config["upset"]["rules"]:
        if match.get("level") not in rule["levels"]:
            continue
        if "round_names" in rule and not (
            match.get("stage_code") == "MAIN" and match.get("round_name") in rule["round_names"]
        ):
            continue
        if lose_rank in rule["loser_ranks"] and rank_gap(rank_order, win_rank, lose_rank) >= int(rule["min_gap"]):
            return headline(config, "upset",
                            f"評判{win_rank}の{names[winner]}、評判{lose_rank}の{names[loser]}を破る ― {where(match)}",
                            match)
        return None
    return None


def match_headlines(config: dict, match: dict, detail: dict | None, names: dict, ranks: dict,
                    rank_order: list[str], player) -> list[dict]:
    """1試合の出来事（記録・番狂わせ・大逆転・サヨナラ・延長・大量得点）。"""
    if not match.get("winner_id"):
        return []
    out = []
    upset = upset_headline(config, match, names, ranks, rank_order)
    if upset:
        out.append(upset)
    if detail:
        feats = feat_headlines(config, match, detail, names, player)
        out += feats
        drama = drama_headline(config, match, detail, names)
        if drama:
            out.append(drama)
        out += record_headlines(config, match, detail, names, player,
                                {f["player_id"] for f in feats if f["kind"] != CYCLE})
    else:
        out += record_headlines(config, match, {}, names, player)
    return out


# ---- 大会の出来事 ----


def koshien_streak(years, this_year: int, uncertain_until: int | None = None) -> int | None:
    """``this_year`` の前の年まで続いた連続出場の年数（前の年に出ていなければ0）。

    連続が欠けているかもしれない年（``uncertain_until`` まで）に届くときは None（数えられない）。"""
    years = set(years)
    streak = 0
    while this_year - streak - 1 in years:
        streak += 1
    if streak and uncertain_until is not None and this_year - streak <= uncertain_until:
        return None
    return streak


def koshien_gap(years, this_year: int, uncertain_until: int | None = None) -> int | None:
    """前回の出場から何年ぶりか（初めてなら0）。前回の年が欠けているかもしれないときは None。"""
    past = [y for y in years if y < this_year]
    if not past:
        return 0 if uncertain_until is None else None
    last = max(past)
    if uncertain_until is not None and (last <= uncertain_until or this_year - 1 <= uncertain_until):
        return None
    return this_year - last


def qualify_kind(config: dict, count_before: int, years, this_year: int,
                 uncertain_until: int | None = None) -> tuple[str, int | None]:
    """夏の甲子園の出場決定の見出しの種類：初出場・◯年ぶり・◯年連続・（どれでもない）。"""
    rule = config["koshien"]
    if count_before == 0:
        return "first_appearance", None
    streak = koshien_streak(years, this_year, uncertain_until)
    if streak is not None and streak + 1 >= int(rule["streak_years"]):
        return "streak", streak + 1
    gap = koshien_gap(years, this_year, uncertain_until)
    if gap is not None and gap >= int(rule["long_gap_years"]):
        return "long_gap", gap
    return "qualified", None


def qualify_headline(config: dict, match: dict, names: dict, winner: str, kind: str,
                     years: int | None, nth: str) -> dict:
    """夏の地方大会の優勝（夏の甲子園の出場決定）。``nth`` は「2年連続15回目」。"""
    if kind == "first_appearance":
        text = f"{names[winner]}、夏の甲子園へ ― {match['competition_name']}を制す"
    else:
        text = f"{names[winner]}、{nth}の夏の甲子園へ ― {match['competition_name']}を制す"
    return headline(config, kind, text, match, years=years)


def streak_broken_headline(config: dict, match: dict, names: dict, loser: str, streak: int) -> dict:
    winner = match["winner_id"]
    return headline(config, "streak_broken",
                    f"{names[loser]}、夏の甲子園の連続出場が{streak}で止まる ― {where(match)}で{names[winner]}に敗れる",
                    match, target=school_target(loser))


def early_exit_headline(config: dict, match: dict, names: dict, loser: str, rank: str) -> dict:
    winner = match["winner_id"]
    return headline(config, "early_exit",
                    f"評判{rank}の{names[loser]}、{where(match)}で{names[winner]}に敗れる",
                    match)


def champion_headline(config: dict, match: dict, names: dict, *, national: bool, nth: str = "") -> dict:
    """全国大会・地区大会の優勝。``nth`` は「初優勝」「2年連続3回目の優勝」（なければ添えない）。"""
    winner = match["winner_id"]
    note = f"（{nth}）" if nth else ""
    return headline(config, "national_champion" if national else "regional_champion",
                    f"{names[winner]}、{match['competition_name']}を制す{note}", match)


def coach_headline(config: dict, match: dict, names: dict, school_id: str, coach_name: str,
                   *, koshien: bool, wins: int) -> dict:
    what = f"甲子園{wins}勝目" if koshien else f"公式戦通算{wins}勝目"
    return {**headline(config, "coach_koshien_wins" if koshien else "coach_wins",
                       f"{names[school_id]}の{coach_name}監督、{what} ― {where(match)}",
                       match, target=school_target(school_id)),
            "key": f"coach:{'k' if koshien else 'w'}:{school_id}:{match['match_id']}"}
