"""バランスの物差しのうち、年をまたいで見る指標（``balance_report`` の「通し」の節）。

- 番狂わせ：評判のランクの差（0・1・2・3段以上）ごとの、上のランクの学校の勝率。大会の格ごと
- 強豪の続き方（夏の甲子園）：連続出場・出場回数の分布、都道府県ごとの出場校の数
- 都道府県の強弱：甲子園（春夏）の勝率の散らばり
- 優勝校の顔ぶれ：夏・選抜の優勝校の評判のランク、連覇・初優勝
- 投手の使われ方：準決勝・決勝でのエースの登板の間隔、7日間の球数の上限に届いた投手、1試合の球数
- 監督：在任年数・勇退の年齢、甲子園で勝った監督が勇退したあとの学校の評判
- 県内の勢力の入れ替わり：県ベスト4と代表校が直前3年の夏の成績で県内の何位から来たか、
  甲子園の新顔の公立校の割合、評判の県内順位とチームの強さの県内順位の結び付き（ゲームのみ）

実際の値は ``historical_data`` から同じ関数（``dynasty_metrics``・``spread_by_prefecture``・
``origin_metrics``・``newcomer_metrics``）で計算する。
結果のファイルはリポジトリに置かない。
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from pathlib import Path
import json
import re
import statistics

from .school_year import school_year_of

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "historical_data"
SUMMER, SENBATSU, LOCAL = "national_championship", "national_invitational", "summer_local_qualifier"
LEVELS = {
    LOCAL: "県大会", "spring_prefectural": "県大会", "autumn_prefectural": "県大会",
    "spring_regional": "地区大会", "autumn_regional": "地区大会",
    SUMMER: "甲子園", SENBATSU: "甲子園", "national_autumn_championship": "神宮",
}
KOSHIEN_NAMES = {SUMMER: "夏", SENBATSU: "選抜"}
# 夏の出場枠が2つの都道府県（独り勝ち・群雄割拠の数からは外す）
TWO_SLOT_PREFECTURES = ("01", "13")
STREAK_BANDS = ((2, 2, "2年"), (3, 4, "3〜4年"), (5, 9, "5〜9年"), (10, 999, "10年以上"))
COUNT_BANDS = ((1, 1, "1回"), (2, 3, "2〜3回"), (4, 6, "4〜6回"), (7, 999, "7回以上"))
PITCH_BANDS = ((0, "〜99"), (100, "100〜119"), (120, "120〜139"), (140, "140〜"))
TENURE_BANDS = ((0, 3, "〜3年"), (4, 6, "4〜6年"), (7, 10, "7〜10年"), (11, 20, "11〜20年"), (21, 999, "21年〜"))
AGE_BANDS = ((0, 54, "〜54歳"), (55, 59, "55〜59歳"), (60, 64, "60〜64歳"), (65, 69, "65〜69歳"), (70, 999, "70歳〜"))
# 名将とみなす甲子園（春夏）の勝数（ゲーム内で数えた分。開始前の勝数は監督が架空なのでない）
GREAT_COACH_WINS = (3, 5, 10)
REPUTATION_FOLLOW_YEARS = (1, 2, 3)
DOMINANT_SHARE = 0.7    # 1校がその県の出場のこの割合以上なら「独り勝ち」
CROWDED_SCHOOLS = 5     # 10大会でこの校数以上が出た県は「群雄割拠」
# 県内の勢力の入れ替わり（指標の定義。調整値ではないので config/ に置かない）
# 夏の地方大会の勝ち上がり（1＝優勝、2＝準優勝、4＝ベスト4 …。``summer_local.finishes`` と同じ）→ 点
FINISH_POINTS = {1: 5, 2: 4, 4: 3, 8: 2, 16: 1}
PRIOR_WEIGHTS = (1.0, 0.6, 0.3)     # 直前の年から1年前・2年前・3年前
RANK_BANDS = ((1, 1, "1位"), (2, 3, "2〜3位"), (4, 5, "4〜5位"), (6, 10, "6〜10位"), (11, 10 ** 6, "11位以下"))
NO_RECORD = "実績なし"
NEWCOMER_YEARS = 15                 # 新顔：その年の前の15年に（21世紀枠以外で）春夏の出場がない
SUMMER_KIND, SPRING_KIND = "夏", "春"


def _band(bands, value) -> str:
    return next(label for low, high, label in bands if low <= value <= high)


def _share(part, whole) -> float:
    return round(part / whole, 4) if whole else 0.0


def dynasty_metrics(by_year: dict[int, set], prefecture_of) -> dict:
    """夏の甲子園の出場校（大会の年 → 学校）から、強豪の続き方を数える。

    年は並べた順に「続き」とみなす（中止の年は飛ばして数える）。ゲームと実際で同じ関数を使う。"""
    years = sorted(by_year)
    longest: dict = {}
    count: Counter = Counter()
    run: dict = {}
    for year in years:
        run = {school: run.get(school, 0) + 1 for school in by_year[year]}
        for school, length in run.items():
            longest[school] = max(longest.get(school, 0), length)
            count[school] += 1
    by_prefecture: dict[str, Counter] = defaultdict(Counter)
    for school, times in count.items():
        by_prefecture[prefecture_of(school)][school] = times
    single = {p: c for p, c in by_prefecture.items() if p not in TWO_SLOT_PREFECTURES}
    return {
        "tournaments": len(years),
        "schools": len(count),
        "streaks": {label: sum(low <= v <= high for v in longest.values()) for low, high, label in STREAK_BANDS},
        "longest_streak": max(longest.values(), default=0),
        "appearances": {label: sum(low <= v <= high for v in count.values()) for low, high, label in COUNT_BANDS},
        "prefecture_school_counts": dict(sorted(Counter(len(c) for c in single.values()).items())),
        "prefecture_schools_mean": round(statistics.mean(len(c) for c in single.values()), 2) if single else 0,
        "dominant_prefectures": sum(max(c.values()) >= DOMINANT_SHARE * sum(c.values()) for c in single.values()),
        "crowded_prefectures": sum(len(c) >= CROWDED_SCHOOLS for c in single.values()),
        "by_prefecture": {p: {"schools": len(c), "top": max(c.values())} for p, c in sorted(by_prefecture.items())},
    }


def spread_by_prefecture(records: dict[str, list[int]], top: int = 5) -> dict:
    """都道府県 → [勝ち, 負け] から、勝率の散らばり（標準偏差・上位・下位）を出す。"""
    rates = {p: w / (w + l) for p, (w, l) in records.items() if w + l}
    order = sorted(rates, key=lambda p: (-rates[p], p))
    return {
        "prefectures": len(rates),
        "stdev": round(statistics.pstdev(rates.values()), 4) if rates else 0.0,
        "top": [(p, round(rates[p], 3)) for p in order[:top]],
        "bottom": [(p, round(rates[p], 3)) for p in order[-top:]],
        "rates": {p: round(r, 4) for p, r in sorted(rates.items())},
        "records": {p: list(records[p]) for p in sorted(records)},
    }


def prior_ranks(finishes: dict[int, dict[str, dict[str, int]]], year: int) -> dict[str, dict[str, int | None]] | None:
    """夏の地方大会の区分 → 学校 → 直前3年の成績による区分の中の順位（3年とも0点なら None＝実績なし）。

    ``finishes`` は 年 → 区分 → 学校 → 勝ち上がり（1＝優勝、2＝準優勝、4＝ベスト4 …、0＝それ以外）。
    その年の区分に出た学校に、前の3年の点（``FINISH_POINTS`` × ``PRIOR_WEIGHTS``）を付けて順位にする。
    前の年の区分は問わない（学校ごとに数える）。点が同じ学校は同じ順位。前の3年がそろわなければ None。"""
    if year not in finishes or any(year - back not in finishes for back in range(1, len(PRIOR_WEIGHTS) + 1)):
        return None
    points: dict[str, float] = defaultdict(float)
    for back, weight in enumerate(PRIOR_WEIGHTS, start=1):
        for schools in finishes[year - back].values():
            for school, reached in schools.items():
                points[school] += weight * FINISH_POINTS.get(reached, 0)
    out = {}
    for division, schools in finishes[year].items():
        scored = sorted((round(points.get(school, 0.0), 6) for school in schools), reverse=True)
        out[division] = {school: (scored.index(round(points.get(school, 0.0), 6)) + 1
                                  if points.get(school, 0.0) > 0 else None)
                         for school in schools}
    return out


def rank_band(rank: int | None) -> str:
    return NO_RECORD if rank is None else _band(RANK_BANDS, rank)


def _band_shares(counter: Counter) -> dict:
    total = sum(counter.values())
    labels = [label for _, _, label in RANK_BANDS] + [NO_RECORD]
    return {"slots": total, **{label: _share(counter[label], total) for label in labels}}


def origin_metrics(finishes: dict[int, dict[str, dict[str, int]]], years, group_of) -> dict:
    """指標A：県ベスト4（4強に入った学校）と代表校（優勝）が、直前の県内順位のどの帯から来たか。

    ``group_of(school)`` は "公立"・"私立"・None（どちらでもない。全体にだけ数える）。"""
    counts = {slot: defaultdict(Counter) for slot in ("best4", "champion")}
    used = []
    for year in years:
        ranks = prior_ranks(finishes, year)
        if ranks is None:
            continue
        used.append(year)
        for division, schools in finishes[year].items():
            for school, reached in schools.items():
                if not reached or reached > 4:
                    continue
                band = rank_band(ranks[division][school])
                for slot in ("best4",) + (("champion",) if reached == 1 else ()):
                    for group in ("全体", group_of(school)):
                        if group:
                            counts[slot][group][band] += 1
    out = {slot: {group: _band_shares(counts[slot][group]) for group in ("全体", "公立", "私立")
                  if counts[slot][group]} for slot in counts}
    return {"years": used, **out} if used else {}


def entry_rates(finishes: dict[int, dict[str, dict[str, int]]], years, group_of) -> dict:
    """直前の県内順位の帯 → 公立・私立 → 学校1校あたりの「県ベスト4に入る確率」と「代表校になる確率」。

    分母はその年の区分に出た学校（``prior_ranks`` と同じ）。"""
    cells: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])   # 学校, 4強, 優勝
    for year in years:
        ranks = prior_ranks(finishes, year)
        if ranks is None:
            continue
        for division, schools in finishes[year].items():
            for school, reached in schools.items():
                group = group_of(school)
                if not group:
                    continue
                cell = cells[(rank_band(ranks[division][school]), group)]
                cell[0] += 1
                cell[1] += bool(reached) and reached <= 4
                cell[2] += reached == 1
    out: dict = {}
    for band in [b for _, _, b in RANK_BANDS] + [NO_RECORD]:
        for group in ("公立", "私立"):
            schools, best4, champion = cells.get((band, group), (0, 0, 0))
            if schools:
                out.setdefault(band, {})[group] = {"schools": schools, "best4_rate": _share(best4, schools),
                                                   "champion_rate": _share(champion, schools)}
    return out


def ownership_gap(reputation: dict[int, dict[str, float]], intake: dict[int, dict[str, tuple]],
                  strength: dict[int, dict[str, float]], prefecture_of, group_of) -> dict:
    """（ゲームのみ）4月1日の評判の県内順位の帯 → 公立・私立 → 入部品質 z・有望な新入生の人数・
    新入生の平均能力・7月1日のチームの強さ（overall）の平均。

    ``intake`` は 年 → 学校 → (入部品質 z, 有望な新入生の人数, 新入生の平均能力 または None)。"""
    sums: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for year, values in reputation.items():
        rows = intake.get(year, {})
        ranks = _ranks_within({s: z for s, z in values.items() if s in rows}, prefecture_of)
        for school, rank in ranks.items():
            group = group_of(school)
            if not group:
                continue
            cell = sums[(_band(RANK_BANDS, rank), group)]
            z, prospects, ability = rows[school]
            cell["intake_z"].append(z)
            cell["prospects"].append(prospects)
            if ability is not None:
                cell["freshman_ability"].append(ability)
            if school in strength.get(year, {}):
                cell["strength"].append(strength[year][school])
    out: dict = {}
    for _, _, band in RANK_BANDS:
        for group in ("公立", "私立"):
            cell = sums.get((band, group))
            if cell:
                out.setdefault(band, {})[group] = {
                    "schools": len(cell["intake_z"]),
                    **{f"{name}_mean": round(statistics.mean(v), 3) for name, v in cell.items() if v}}
    return out


def newcomer_metrics(appearances: dict[str, dict[int, set]], century: set, years: dict[str, list[int]],
                     is_public) -> dict:
    """指標B：甲子園の出場校のうち「新顔の公立校」の割合（夏・春）。

    ``appearances`` は 夏・春 → 年 → 学校、``century`` は21世紀枠の (学校, 年)。
    新顔は、その年の前の ``NEWCOMER_YEARS`` 年に、21世紀枠以外での春夏の出場がない公立校。
    春は21世紀枠の出場校を数えない（分母にも入れない）。"""
    last: dict[str, list[int]] = defaultdict(list)
    for kind, by_year in appearances.items():
        for year, schools in by_year.items():
            for school in schools:
                if not (kind == SPRING_KIND and (school, year) in century):
                    last[school].append(year)
    out = {}
    for kind, chosen in years.items():
        entrants = public = new = 0
        for year in chosen:
            for school in appearances.get(kind, {}).get(year, ()):
                if kind == SPRING_KIND and (school, year) in century:
                    continue
                entrants += 1
                if not is_public(school):
                    continue
                public += 1
                new += not any(year - NEWCOMER_YEARS <= y < year for y in last[school])
        if entrants:
            out[kind] = {"tournaments": len([y for y in chosen if appearances.get(kind, {}).get(y)]),
                         "all_entrants": entrants, "public": public, "newcomers": new,
                         "newcomer_share": _share(new, entrants), "newcomer_public_share": _share(new, public)}
    return out


PERIOD_YEARS = 5


def period_metrics(appearances: dict[str, dict[int, set]], century: set, years: dict[str, list[int]],
                   is_public, prefecture_of, start: int) -> dict:
    """5年ごと（``start`` 年から）の、夏・選抜（21世紀枠を除く）の出場校に占める公立の割合と、
    初めて出る公立（直前15年に21世紀枠以外の出場がない公立。``newcomer_metrics`` と同じ）の割合。
    夏は、1校がその5年の夏に4回以上出た県の数（出場枠が2つの北海道・東京を除く）も数える。"""
    out = {}
    last = max((y for chosen in years.values() for y in chosen), default=start - 1)
    for first in range(start, last + 1, PERIOD_YEARS):
        block = range(first, first + PERIOD_YEARS)
        chosen = {kind: [y for y in ys if y in block] for kind, ys in years.items()}
        rows = newcomer_metrics(appearances, century, chosen, is_public)
        cell = {kind: {"tournaments": row["tournaments"], "all_entrants": row["all_entrants"],
                       "public_share": _share(row["public"], row["all_entrants"]),
                       "newcomer_share": row["newcomer_share"]} for kind, row in rows.items()}
        summers = Counter(school for y in chosen.get(SUMMER_KIND, ())
                          for school in appearances.get(SUMMER_KIND, {}).get(y, ()))
        cell["dominant_4of5"] = len({prefecture_of(school) for school, times in summers.items()
                                     if times >= 4 and prefecture_of(school) not in TWO_SLOT_PREFECTURES})
        if rows:
            out[f"{first}〜{first + PERIOD_YEARS - 1}"] = cell
    return out


def _ranks_within(values: dict[str, float], prefecture_of) -> dict[str, int]:
    """学校 → 県の中の順位（値の大きい順。同じ値は学校IDの順）。"""
    by_prefecture: dict[str, list[str]] = defaultdict(list)
    for school in values:
        by_prefecture[prefecture_of(school)].append(school)
    out = {}
    for schools in by_prefecture.values():
        for rank, school in enumerate(sorted(schools, key=lambda s: (-values[s], s)), start=1):
            out[school] = rank
    return out


def _spearman(pairs: list[tuple[int, int]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy)


def _average_ranks(values: dict[str, float]) -> dict[str, float]:
    """値の大きい順の順位（同じ値は順位の平均）。"""
    order = sorted(values, key=lambda key: -values[key])
    ranks, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for key in order[i:j + 1]:
            ranks[key] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def actual_prefecture_rates() -> dict[str, float]:
    """史実の都道府県の甲子園の勝率（``koshien_games.csv`` の県どうしの試合。初期の県の差と同じ年の範囲。
    5割に寄せない、そのままの勝率）。"""
    from game_core.school_reputation import koshien_game_records

    config = json.loads((ROOT / "config/abilities/school_reputation_v1.json").read_text(encoding="utf-8"))
    first, last = config["prefecture_strength"]["years"]
    return {code: wins / games for code, (wins, games) in koshien_game_records(HISTORY, first, last).items()
            if games}


def _prefecture_cell(by_year: dict[int, dict[str, list[int]]], years, actual: dict[str, float]) -> dict | None:
    totals = defaultdict(lambda: [0, 0])
    for year in years:
        for code, (wins, losses) in by_year.get(year, {}).items():
            totals[code][0] += wins
            totals[code][1] += losses
    game = {code: w / (w + l) for code, (w, l) in totals.items() if w + l and code in actual}
    if len(game) < 3:
        return None
    game_ranks = _average_ranks(game)
    actual_ranks = _average_ranks({code: actual[code] for code in game})
    value = _spearman([(game_ranks[code], actual_ranks[code]) for code in game])
    return {"history_correlation": round(value, 3) if value is not None else None,
            "prefectures": len(game), "games": sum(sum(v) for v in totals.values()) // 2,
            **true_spread({code: totals[code] for code in game}),
            "ranks": {code: game_ranks[code] for code in sorted(game)}}


def prefecture_correlation(by_year: dict[int, dict[str, list[int]]], actual: dict[str, float] | None = None) -> dict:
    """5年ごとと、すべての年をまとめた（``all_years``）、ゲームの甲子園（春夏）の都道府県の勝率と、
    史実（``actual_prefecture_rates``）の順位相関。

    ``by_year`` は 年 → 都道府県 → [勝ち, 負け]。両方に勝率のある都道府県で比べる。
    5年では試合数による揺れが大きいので、合否はすべての年をまとめた値で見る。"""
    if not by_year:
        return {}
    actual = actual_prefecture_rates() if actual is None else actual
    out = {}
    start, last = min(by_year), max(by_year)
    for first in range(start, last + 1, PERIOD_YEARS):
        cell = _prefecture_cell(by_year, range(first, first + PERIOD_YEARS), actual)
        if cell is not None:
            out[f"{first}〜{first + PERIOD_YEARS - 1}"] = cell
    spans = list(out)
    if len(spans) >= 2:
        first_ranks, last_ranks = out[spans[0]]["ranks"], out[spans[-1]]["ranks"]
        out["rank_rise"] = {"periods": len(spans), "risen_15": sum(
            1 for code in first_ranks if code in last_ranks and first_ranks[code] - last_ranks[code] >= 15)}
    for span in spans:
        del out[span]["ranks"]
    whole = _prefecture_cell(by_year, range(start, last + 1), actual)
    if whole is not None:
        del whole["ranks"]
        out["all_years"] = {**whole, "first_year": start, "last_year": last}
    return out


def true_spread(records: dict[str, list[int]]) -> dict:
    """都道府県 → [勝ち, 負け] の勝率の散らばり（標準偏差）と、試合数による揺れの見込み
    （各県の p(1−p)/試合 の平均の平方根。p は全体の勝率0.5）と、揺れを除いた真の差の見積もり
    （√(散らばり² − 揺れ²)。負なら0）。"""
    rates = {code: w / (w + l) for code, (w, l) in records.items() if w + l}
    if len(rates) < 2:
        return {}
    spread = statistics.pstdev(rates.values())
    noise = statistics.mean(0.25 / sum(records[code]) for code in rates) ** 0.5
    return {"stdev": round(spread, 4), "noise_stdev": round(noise, 4),
            "true_stdev": round(max(0.0, spread ** 2 - noise ** 2) ** 0.5, 4)}


def district_top_metrics(strength: dict[int, dict[str, float]],
                         local_finishes: dict[int, dict[str, dict[str, int]]]) -> dict:
    """5年ごとの、地区（夏の地方大会）で1番強い学校の強さ（7月1日の overall）。

    ``top_stdev`` は地区ごとに5年の平均を出してからの地区どうしの散らばり（標準偏差。年ごとの当たり外れを除いた
    地区の差）、``yearly_stdev`` は年ごとの散らばりの5年の平均。地区は大会に出た学校のうち学校IDの最も小さい学校で
    年をまたいで結ぶ。"""
    tops: dict[int, dict[str, float]] = {}
    for year, values in strength.items():
        for schools in local_finishes.get(year, {}).values():
            present = [s for s in schools if s in values]
            if present:
                tops.setdefault(year, {})[min(schools)] = max(values[s] for s in present)
    out = {}
    if tops:
        for first in range(min(tops), max(tops) + 1, PERIOD_YEARS):
            years = [y for y in range(first, first + PERIOD_YEARS) if len(tops.get(y, {})) >= 2]
            if not years:
                continue
            by_district: dict[str, list[float]] = defaultdict(list)
            for year in years:
                for district, value in tops[year].items():
                    by_district[district].append(value)
            means = [statistics.mean(v) for v in by_district.values()]
            out[f"{first}〜{first + PERIOD_YEARS - 1}"] = {
                "top_mean": round(statistics.mean(means), 2),
                "top_stdev": round(statistics.pstdev(means), 3),
                "yearly_stdev": round(statistics.mean(statistics.pstdev(tops[y].values()) for y in years), 3)}
    return out


def strength_metrics(reputation: dict[int, dict[str, float]], strength: dict[int, dict[str, float]],
                     prefecture_of) -> dict:
    """指標C（ゲームのみ）：7月1日の評判の県内順位の帯ごとの、チームの強さ（overall）の県内順位。

    順位は強さのある学校（9人以上）の中で付ける。変化は前の年の7月1日の強さの県内順位との差の絶対値。
    順位相関は県×年ごとのスピアマン（順位どうしの相関）の平均。"""
    cells: dict[str, list[int]] = defaultdict(list)
    moves: dict[str, list[int]] = defaultdict(list)
    correlations = []
    previous: dict[str, int] = {}
    for year in sorted(strength):
        values = strength[year]
        known = {s: z for s, z in reputation.get(year, {}).items() if s in values}
        if not known:
            continue
        rep_rank = _ranks_within(known, prefecture_of)
        str_rank = _ranks_within({s: values[s] for s in known}, prefecture_of)
        by_prefecture: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for school, rank in rep_rank.items():
            band = _band(RANK_BANDS, rank)
            cells[band].append(str_rank[school])
            if school in previous:
                moves[band].append(abs(str_rank[school] - previous[school]))
            by_prefecture[prefecture_of(school)].append((rank, str_rank[school]))
        correlations += [r for r in map(_spearman, by_prefecture.values()) if r is not None]
        previous = str_rank
    if not cells:
        return {}
    out = {"by_reputation_band": {}}
    for _, _, band in RANK_BANDS:
        ranks = cells.get(band)
        if ranks:
            out["by_reputation_band"][band] = {
                "schools": len(ranks), "strength_rank_mean": round(statistics.mean(ranks), 2),
                "strength_rank_stdev": round(statistics.pstdev(ranks), 2),
                **({"rank_change_mean": round(statistics.mean(moves[band]), 2)} if moves.get(band) else {})}
    out["rank_correlation"] = round(statistics.mean(correlations), 4) if correlations else 0.0
    return out


def public_ownership_types() -> set[str]:
    """公立とみなす設置者（21世紀枠の設定と同じ）。"""
    import json

    config = json.loads((ROOT / "config" / "selection" / "senbatsu_selection_v1.json").read_text(encoding="utf-8"))
    return set(config["century"]["public_ownership_types"])


def school_group(repo, public_types):
    """学校 → "公立"・"私立"・None（国立など。全体にだけ数える）。"""
    def group(school):
        ownership = repo.ownership_type(school)
        return "公立" if ownership in public_types else "私立" if ownership == "private" else None
    return group


def actual_finishes() -> dict[int, dict[str, dict[str, int]]]:
    """実際の夏の地方大会（``summer_local_games.csv``）：年 → 大会（区分）→ 学校 → 勝ち上がり（0＝それ以外）。
    学校IDのない校名（連合チームなど）は数えない。"""
    from historical_results.summer_local import finishes

    games = _rows("summer_local_games.csv")
    out: dict[int, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    school_of = {}
    for game in games:
        for side in ("top", "bottom"):
            school = game[f"{side}_school_id"]
            if school:
                school_of[(game["tournament"], game[f"{side}_team"])] = school
                out[int(game["year"])][game["tournament"]].setdefault(school, 0)
    for (tournament, team), reached in finishes(games).items():
        school = school_of.get((tournament, team))
        if school:
            out[int(tournament[:4])][tournament][school] = reached
    return {year: dict(divisions) for year, divisions in out.items()}


def actual_appearances() -> tuple[dict[str, dict[int, set]], set]:
    """実際の甲子園の出場（夏・春 → 年 → 学校）と21世紀枠の (学校, 年)。学校IDのない行は数えない。
    選出後の辞退は数えず、中止の大会（2020年の選抜）の選出は出場に数える（通算の数え方と同じ）。"""
    appearances: dict[str, dict[int, set]] = {SUMMER_KIND: defaultdict(set), SPRING_KIND: defaultdict(set)}
    for row in _rows("koshien_entrants.csv"):
        if row["school_id"] and row["status"] != "withdrawn" and row["kind"] in ("summer", "spring"):
            kind = SUMMER_KIND if row["kind"] == "summer" else SPRING_KIND
            appearances[kind][int(row["year"])].add(row["school_id"])
    century = {(row["school_id"], int(row["year"])) for row in _rows("senbatsu_century_entrants.csv")
               if row["school_id"]}
    return appearances, century


def _rows(name: str) -> list[dict]:
    with (HISTORY / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def actual_metrics(repo, tournaments: int = 10, rank_of=None) -> dict:
    """実際の値（``historical_data``）。ゲームと同じ関数で数える。

    - 強豪の続き方：出場校一覧の直近 ``tournaments`` 回の夏（中止の2020年は大会がないので飛ばす）。
      学校IDのない行は都道府県と当時の校名で1校とみなす
    - 都道府県の強弱：通算の記録（開始前の全期間の春夏の勝敗）を学校の今の都道府県で合計する
    - 県内の勢力の入れ替わり：直前3年の成績による順位は夏の地方大会（2021〜2025年）から出せる2024・2025年。
      新顔の公立校は直近の夏の年までの10年（春も同じ年）
    - 番狂わせ：夏の地方大会（``summer_local_games.csv``）を ``rank_of``（開始時の評判のランク）で分ける。
      開始時の評判はこの試合の結果からも作っているので、上のランクの勝率は高めに出る（参考）
    """
    entrants = [r for r in _rows("koshien_entrants.csv") if r["kind"] == "summer" and r["status"] == "played"]
    years = sorted({int(r["year"]) for r in entrants})[-tournaments:]
    by_year: dict[int, set] = defaultdict(set)
    prefecture = {}
    for row in entrants:
        if int(row["year"]) in years:
            key = row["school_id"] or (row["prefecture_code"], row["team_name"])
            by_year[int(row["year"])].add(key)
            prefecture[key] = row["prefecture_code"]
    records: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in _rows("koshien_records.csv"):
        if row["school_id"] in repo.schools:
            record = records[repo.team(row["school_id"]).prefecture_code]
            record[0] += int(row["wins"] or 0)
            record[1] += int(row["losses"] or 0)
    out = {"years": years, "dynasty": dynasty_metrics(by_year, prefecture.get),
           "prefecture_strength": spread_by_prefecture(records)}
    group_of = school_group(repo, public_ownership_types())
    finishes = actual_finishes()
    appearances, century = actual_appearances()
    newcomer_years = list(range(years[-1] - 9, years[-1] + 1)) if years else []
    out["turnover"] = {
        "origin": origin_metrics(finishes, sorted(finishes), group_of),
        "entry_rates": entry_rates(finishes, sorted(finishes), group_of),
        "newcomers": newcomer_metrics(appearances, century,
                                      {SUMMER_KIND: newcomer_years, SPRING_KIND: newcomer_years},
                                      lambda school: group_of(school) == "公立"),
        "periods": period_metrics(appearances, century,
                                  {SUMMER_KIND: newcomer_years, SPRING_KIND: newcomer_years},
                                  lambda school: group_of(school) == "公立",
                                  lambda school: repo.team(school).prefecture_code,
                                  newcomer_years[0] if newcomer_years else 0),
    }
    if rank_of is not None:
        upsets = UpsetCounter()
        for game in _rows("summer_local_games.csv"):
            if game["result_type"] == "decided" and game["top_school_id"] and game["bottom_school_id"]:
                sides = (game["top_school_id"], game["bottom_school_id"])
                winner = sides[game["winner"] != "top"]
                upsets.add("県大会", rank_of(winner), rank_of(sides[winner == sides[0]]))
        out["upsets"] = upsets.summary()
    return out


class UpsetCounter:
    """格 → ランクの差 → [試合, 上のランクの勝ち]。差0は数だけ（上のランクがない）。"""

    def __init__(self, labels: str = "SABCDE"):
        self.index = {label: i for i, label in enumerate(labels)}
        self.rows = defaultdict(lambda: [0, 0])

    def add(self, level: str, winner_rank: str, loser_rank: str) -> None:
        if winner_rank not in self.index or loser_rank not in self.index:
            return
        gap = self.index[loser_rank] - self.index[winner_rank]   # 正なら上のランクが勝った
        row = self.rows[(level, min(abs(gap), 3))]
        row[0] += 1
        row[1] += gap > 0

    def summary(self) -> dict:
        out: dict = defaultdict(dict)
        for (level, gap), (games, upper) in sorted(self.rows.items()):
            out[level][str(gap)] = {"games": games, **({"upper_win_rate": _share(upper, games)} if gap else {})}
        return dict(out)


def rank_map(reputation) -> dict[str, str]:
    """学校 → 評判のランク（全校の中の順位の割合とランクの境目から）。"""
    from game_core.annual_reputation import _shares

    labels = reputation.rank_labels
    return {school: next(label for label, low in labels if share >= float(low))
            for school, share in _shares(reputation.values).items()}


class PowerTally:
    """1つのシードの、年をまたぐ指標を集める。"""

    def __init__(self, repo, kind_of, pitch_limit: tuple[int, int] | None = None):
        self.repo = repo
        self.kind_of = kind_of
        self.pitch_limit = pitch_limit                  # (球数, 日数)
        self.ranks: dict[str, str] = {}                 # 学校 → 今の評判のランク
        self.reputation: dict[int, dict[str, float]] = {}   # 4月1日の年 → 学校 → 評判
        self.rank_history: dict[int, dict[str, str]] = {}
        self.upsets = UpsetCounter()
        self.entrants = defaultdict(lambda: defaultdict(set))       # 夏・選抜 → 年 → 学校
        self.records = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # 夏・選抜 → 都道府県 → [勝, 負]
        self.records_by_year = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # 年 → 都道府県 → [勝, 負]（春夏）
        self.champions = defaultdict(dict)              # 夏・選抜 → 年 → (学校, ランク)
        self.coach_wins: Counter = Counter()            # 監督 → 甲子園（春夏）の勝数
        self.coach_wins_by_year: dict[str, Counter] = defaultdict(Counter)  # 監督 → 年度 → 勝数
        self.pitch_days = defaultdict(dict)             # 選手 → 試合の日 → 球数（上限の日数分だけ）
        self.limit_reached = defaultdict(set)           # 場面 → (年度, 選手)
        self.starter_pitches = defaultdict(Counter)     # 場面 → 球数の帯 → 先発の数
        self.starter_max = Counter()
        self.tournament_pitches = defaultdict(lambda: defaultdict(dict))  # (大会, 学校) → 選手 → 日 → 球数
        self.ace = defaultdict(Counter)                 # 場面 → 数
        # 県内の勢力の入れ替わり
        self.local_finishes = defaultdict(lambda: defaultdict(dict))  # 年 → 夏の地方大会 → 学校 → 勝ち上がり
        self.century: set = set()                       # 21世紀枠の (学校, 選抜の年)
        self.july_reputation: dict[int, dict[str, float]] = {}       # 7月1日の年 → 学校 → 評判
        self.july_strength: dict[int, dict[str, float]] = {}         # 7月1日の年 → 学校 → 強さ（overall）
        self.april_reputation: dict[int, dict[str, float]] = {}      # 4月1日の年 → 学校 → 評判
        self.intake: dict[int, dict[str, tuple]] = {}               # 年 → 学校 → (入部品質 z, 有望, 新入生の能力)

    def set_reputation(self, year: int, reputation) -> None:
        """4月1日の評判の更新のあとに呼ぶ。その年度の試合のランクに使う。"""
        self.ranks = rank_map(reputation)
        self.reputation[year] = dict(reputation.values)
        self.rank_history[year] = dict(self.ranks)

    def add_match(self, competition_id: str, detail: dict, day: date, rounds_left: int | None,
                  coach_of=None) -> None:
        kind = self.kind_of(competition_id)
        level = LEVELS.get(kind)
        winner, loser = detail.get("winner_id"), detail.get("loser_id")
        if not level or not winner or not loser:
            return
        self.upsets.add(level, self.ranks.get(winner, ""), self.ranks.get(loser, ""))
        if kind == LOCAL:
            schools = self.local_finishes[day.year][competition_id]
            for school in (winner, loser):
                schools.setdefault(school, 0)
            if rounds_left is not None:
                reached = {loser: 2 ** (rounds_left + 1), **({winner: 1} if rounds_left == 0 else {})}
                for school, value in reached.items():
                    schools[school] = min(schools[school] or value, value)
        if kind in KOSHIEN_NAMES:
            name = KOSHIEN_NAMES[kind]
            self.entrants[name][day.year].update((winner, loser))
            self.records[name][self.repo.team(winner).prefecture_code][0] += 1
            self.records[name][self.repo.team(loser).prefecture_code][1] += 1
            by_year = self.records_by_year
            by_year[day.year][self.repo.team(winner).prefecture_code][0] += 1
            by_year[day.year][self.repo.team(loser).prefecture_code][1] += 1
            if rounds_left == 0:
                self.champions[name][day.year] = (winner, self.ranks.get(winner, ""))
            coach = coach_of(winner) if coach_of else None
            if coach is not None:
                self.coach_wins[coach.coach_id] += 1
                self.coach_wins_by_year[coach.coach_id][school_year_of(day)] += 1
        self._add_pitching(competition_id, kind, level, detail, day, rounds_left)

    def _add_pitching(self, competition_id, kind, level, detail, day, rounds_left) -> None:
        late = rounds_left in (0, 1)
        scopes = ["全試合"]
        if level == "甲子園":
            scopes.append("甲子園")
            if late:
                scopes.append("甲子園の準決勝・決勝")
        elif kind == LOCAL:
            scopes.append("夏の地方大会")
            if late:
                scopes.append("夏の地方大会の準決勝・決勝")
        pitched = [p for p in detail.get("pitcher_stats") or () if int(p.get("pitches", 0)) > 0]
        starters = {part["school_id"]: part.get("starting_pitcher_id") for part in detail.get("team_participation") or ()}
        year = day.year if day.month >= 4 else day.year - 1
        for p in pitched:
            pitches = int(p["pitches"])
            if starters.get(p["school_id"]) == p["player_id"]:
                label = next(name for low, name in reversed(PITCH_BANDS) if pitches >= low)
                for scope in scopes:
                    self.starter_pitches[scope][label] += 1
                    self.starter_pitches[scope]["starts"] += 1
                    self.starter_pitches[scope]["pitches"] += pitches
                    self.starter_max[scope] = max(self.starter_max[scope], pitches)
            if self.pitch_limit:
                limit, days = self.pitch_limit
                first = day - timedelta(days=days - 1)
                log = self.pitch_days[p["player_id"]]
                for old in [d for d in log if d < first]:
                    del log[old]
                log[day] = log.get(day, 0) + pitches
                total = sum(log.values())
                for scope in scopes[:2]:
                    if total >= limit:
                        self.limit_reached[scope].add((year, p["player_id"]))
                    if total >= limit * 0.8:
                        self.limit_reached[scope + "（8割以上）"].add((year, p["player_id"]))
        if level != "甲子園" and kind != LOCAL:
            return
        for school in (detail["team1_school_id"], detail["team2_school_id"]):
            log = self.tournament_pitches[(competition_id, day.year, school)]
            mine = {p["player_id"]: int(p["pitches"]) for p in pitched if p["school_id"] == school}
            if late and log:
                # エース：その大会でこの試合の前までに最も多く投げた投手
                ace = max(log, key=lambda player: (sum(log[player].values()), player))
                row = self.ace[scopes[-1]]
                row["team_games"] += 1
                if ace in mine:
                    gap = (day - max(log[ace])).days
                    row["pitched"] += 1
                    row["started"] += starters.get(school) == ace
                    row["pitches"] += mine[ace]
                    row[f"gap_{min(gap, 4)}"] += 1          # 1＝連投、2＝中1日、3＝中2日、4＝中3日以上
                    if gap == 1 and day - timedelta(days=2) in log[ace]:
                        row["three_days"] += 1
            for player, pitches in mine.items():
                log[player][day] = pitches
            if rounds_left == 0:
                del self.tournament_pitches[(competition_id, day.year, school)]

    def add_century(self, year: int, basis: dict) -> None:
        """選考の記録（``select_invitational`` の ``selection_basis``）。``year`` は選抜の行われる年。"""
        self.century |= {(school, year) for school, kind in (basis or {}).items() if kind == "century"}

    def add_strength(self, year: int, reputation: dict[str, float], strength: dict[str, float]) -> None:
        """7月1日の評判とチームの強さ（overall）。"""
        self.july_reputation[year] = dict(reputation)
        self.july_strength[year] = dict(strength)

    def add_intake(self, year: int, reputation: dict[str, float], rows: dict[str, tuple]) -> None:
        """4月1日の評判と、その年度の新入生（``intake_rows``）。"""
        self.april_reputation[year] = dict(reputation)
        self.intake[year] = dict(rows)

    def _turnover_summary(self, group_of) -> dict:
        """県内の勢力の入れ替わり。開始より前の年は実際の値（夏の地方大会・甲子園の出場）で補う。"""
        finishes = {year: dict(divisions) for year, divisions in actual_finishes().items()
                    if year not in self.local_finishes}
        game_years = sorted(self.local_finishes)
        finishes.update({year: {cid: dict(s) for cid, s in self.local_finishes[year].items()} for year in game_years})
        appearances, century = actual_appearances()
        game = {SUMMER_KIND: self.entrants["夏"], SPRING_KIND: self.entrants["選抜"]}
        for kind, by_year in game.items():
            for year, schools in by_year.items():
                appearances[kind][year] = set(schools)
        return {
            "origin": origin_metrics(finishes, game_years, group_of),
            "entry_rates": entry_rates(finishes, game_years, group_of),
            "ownership_gap": ownership_gap(self.april_reputation, self.intake, self.july_strength,
                                           lambda school: self.repo.team(school).prefecture_code, group_of),
            "newcomers": newcomer_metrics(appearances, century | self.century,
                                          {kind: sorted(by_year) for kind, by_year in game.items()},
                                          lambda school: group_of(school) == "公立"),
            "strength": strength_metrics(self.july_reputation, self.july_strength,
                                         lambda school: self.repo.team(school).prefecture_code),
            "periods": period_metrics(appearances, century | self.century,
                                      {kind: sorted(by_year) for kind, by_year in game.items()},
                                      lambda school: group_of(school) == "公立",
                                      lambda school: self.repo.team(school).prefecture_code,
                                      min(game[SUMMER_KIND], default=0)),
        }

    def _champion_summary(self, name: str) -> dict:
        champions = self.champions[name]
        past = {r["school_id"] for r in _rows("koshien_records.csv")
                if r["kind"] == ("summer" if name == "夏" else "spring") and int(r["championships"] or 0) > 0}
        seen, first, repeat = set(past), 0, 0
        for year in sorted(champions):
            school = champions[year][0]
            first += school not in seen
            seen.add(school)
            repeat += champions.get(year - 1, ("",))[0] == school
        return {"tournaments": len(champions), "ranks": dict(Counter(rank for _, rank in champions.values())),
                "first_time": first, "repeat": repeat,
                "list": {str(year): list(pair) for year, pair in sorted(champions.items())}}

    def _coach_summary(self, coaches) -> dict:
        if coaches is None:
            return {}
        public_types = set(coaches.config["public_ownership_types"])

        def group(school_id):
            return "公立" if self.repo.ownership_type(school_id) in public_types else "私立"

        first = coaches.first_year
        tenure, ages = defaultdict(Counter), defaultdict(Counter)
        tenure_sum, age_sum = defaultdict(list), defaultdict(list)
        changed = defaultdict(set)                      # 年 → 監督が替わった学校
        leaving, arriving = [], []
        for event in coaches.events:
            year = int(event.date[:4])
            if event.kind not in ("retirement", "transfer") or year <= first:
                continue
            changed[year].add(event.from_school_id)
            g = group(event.from_school_id)
            years = event.completed_tenure_years
            for key in (g, "全体"):
                tenure[key][_band(TENURE_BANDS, years)] += 1
                tenure_sum[key].append(years)
            if event.kind == "retirement":
                age = year - coaches.coaches[event.coach_id].birth_year
                for key in (g, "全体"):
                    ages[key][_band(AGE_BANDS, age)] += 1
                    age_sum[key].append(age)
            leaving.append((event.kind, year, event.coach_id, event.from_school_id))
            if event.kind == "transfer" and event.to_school_id:
                arriving.append((year, event.coach_id, event.to_school_id))
        last = max(self.reputation, default=first)
        # 在任年数は画面と同じ数え方（就任の年度を1年目とする。Coach.view の tenure_years）
        active = Counter(_band(TENURE_BANDS, last - c.appointment_year + 1)
                         for c in coaches.coaches.values() if c.retired_on is None)
        out = {
            "ended_tenure": {k: {**{label: v[label] for _, _, label in TENURE_BANDS},
                                 "mean": round(statistics.mean(tenure_sum[k]), 2)} for k, v in tenure.items()},
            "retirement_age": {k: {**{label: v[label] for _, _, label in AGE_BANDS},
                                   "mean": round(statistics.mean(age_sum[k]), 2)} for k, v in ages.items()},
            "active_tenure": {label: active[label] for _, _, label in TENURE_BANDS},
            "koshien_wins": {f"{n}勝以上": sum(w >= n for w in self.coach_wins.values()) for n in GREAT_COACH_WINS},
        }
        # 名将が去った・来た学校の評判（z）の変化と、同じ年・同じランクで監督が替わらなかった学校の変化。
        # 名将かどうかは、勇退・異動の前の年度までの甲子園の勝数で数える（そのあとの勝ちは数えない）

        def wins_before(coach_id, year):
            return sum(n for y, n in self.coach_wins_by_year[coach_id].items() if y < year)

        after = {}
        for wins in GREAT_COACH_WINS:
            groups = [(label, [(y, s) for k, y, c, s in leaving if k == kind and wins_before(c, y) >= wins])
                      for kind, label in (("retirement", "勇退"), ("transfer", "異動"))]
            groups.append(("着任", [(y, s) for y, c, s in arriving if wins_before(c, y) >= wins]))
            for label, rows in groups:
                entry = {"coaches": len(rows)}
                for ahead in REPUTATION_FOLLOW_YEARS:
                    moved, control = [], []
                    for year, school in rows:
                        now, later = self.reputation.get(year, {}), self.reputation.get(year + ahead, {})
                        if school not in now or school not in later:
                            continue
                        moved.append(later[school] - now[school])
                        rank = self.rank_history[year].get(school)
                        peers = [later[s] - now[s] for s, r in self.rank_history[year].items()
                                 if r == rank and s not in changed[year] and s in later]
                        if peers:
                            control.append(statistics.mean(peers))
                    if moved:
                        entry[f"{ahead}年後"] = {"schools": len(moved), "change_z": round(statistics.mean(moved), 3),
                                               "peers_change_z": round(statistics.mean(control), 3) if control else None}
                after[f"{wins}勝以上・{label}"] = entry
        out["after_great_coach"] = after
        return out

    def summary(self, coaches=None) -> dict:
        prefecture_of = lambda school: self.repo.team(school).prefecture_code  # noqa: E731
        both = defaultdict(lambda: [0, 0])
        for records in self.records.values():
            for prefecture, (wins, losses) in records.items():
                both[prefecture][0] += wins
                both[prefecture][1] += losses
        pitching = {}
        for scope, row in self.starter_pitches.items():
            starts = row["starts"]
            pitching[scope] = {"starts": starts, "mean": round(row["pitches"] / starts, 1),
                               "max": self.starter_max[scope],
                               **{label: _share(row[label], starts) for _, label in PITCH_BANDS}}
        ace = {}
        for scope, row in self.ace.items():
            pitched = row["pitched"]
            ace[scope] = {"team_games": row["team_games"], "pitched": _share(pitched, row["team_games"]),
                          "started": _share(row["started"], row["team_games"]),
                          "mean_pitches": round(row["pitches"] / pitched, 1) if pitched else 0.0,
                          "back_to_back": row["gap_1"], "three_days": row["three_days"],
                          "gap": {label: _share(row[f"gap_{n}"], pitched) for n, label in
                                  ((1, "連投"), (2, "中1日"), (3, "中2日"), (4, "中3日以上"))}}
        return {
            "upsets": self.upsets.summary(),
            "dynasty": dynasty_metrics(self.entrants["夏"], prefecture_of) if self.entrants["夏"] else {},
            "summer_entrants": {str(y): sorted(s) for y, s in sorted(self.entrants["夏"].items())},
            "prefecture_strength": spread_by_prefecture(both) if both else {},
            "prefecture_correlation": prefecture_correlation(self.records_by_year),
            "district_top": district_top_metrics(self.july_strength, self.local_finishes),
            "champions": {name: self._champion_summary(name) for name in KOSHIEN_NAMES.values()
                          if self.champions[name]},
            "starter_pitches": pitching,
            "ace": ace,
            "pitch_limit": {scope: len(rows) for scope, rows in sorted(self.limit_reached.items())},
            "coaches": self._coach_summary(coaches),
            "turnover": self._turnover_summary(school_group(self.repo, public_ownership_types())),
        }


def total_rounds(season, competition_id: str) -> int | None:
    """大会の本大会の回戦の数（本大会がまだなければ None）。"""
    runtime = getattr(season.competitions.get(competition_id), "runtime", None)
    return getattr(getattr(runtime, "main_runtime", runtime), "total_rounds", None)


def rounds_left(season, competition_id: str, match_id: str) -> int | None:
    """本大会の試合なら決勝まであと何回戦か（決勝は0）。``AbilityMatchResolver._rounds_left`` と同じ数え方。"""
    found = re.search(r"-MAIN-R(\d+)-", match_id)
    total = total_rounds(season, competition_id)
    if found is None or not total:
        return None
    return int(total) - int(found.group(1))


def merge_seeds(powers: list[dict]) -> dict:
    """乱数の種をまとめた値：都道府県の勝敗は足してから勝率にする（1つの種では試合が少なく散らばりが大きく出る）。"""
    both = defaultdict(lambda: [0, 0])
    for power in powers:
        for prefecture, (wins, losses) in (power.get("prefecture_strength") or {}).get("records", {}).items():
            both[prefecture][0] += wins
            both[prefecture][1] += losses
    return {"prefecture_strength": spread_by_prefecture(both)} if both else {}


def _pairs(mapping: dict, bands=()) -> str:
    """``bands`` があればその順（乱数の種の平均は項目名の順に並ぶので、帯の順に戻す）。"""
    order = [b[-1] for b in bands if b[-1] in mapping]
    keys = order + [k for k in mapping if k not in order]
    return "／".join(f"{k} {mapping[k]}" for k in keys)


def format_dynasty(label: str, d: dict) -> list[str]:
    if not d:
        return []
    return [
        f"  {label}（{d['tournaments']}大会・出場{d['schools']}校）",
        f"    連続出場の最長ごとの学校数 {_pairs(d['streaks'], STREAK_BANDS)}　最長 {d['longest_streak']}",
        f"    出場回数ごとの学校数 {_pairs(d['appearances'], COUNT_BANDS)}",
        f"    都道府県ごとの出場校の数（2枠の北海道・東京を除く）平均 {d['prefecture_schools_mean']}校　"
        f"分布 {_pairs({f'{k}校': v for k, v in d['prefecture_school_counts'].items()})}県　"
        f"独り勝ち（1校が7割以上）{d['dominant_prefectures']}県　群雄割拠（{CROWDED_SCHOOLS}校以上）{d['crowded_prefectures']}県",
    ]


def format_strength(label: str, s: dict) -> list[str]:
    if not s:
        return []
    return [f"  {label}：勝率の標準偏差 {s['stdev']:.3f}（{s['prefectures']}都道府県）",
            "    上位 " + "　".join(f"{p} {r:.3f}" for p, r in s["top"])
            + "　下位 " + "　".join(f"{p} {r:.3f}" for p, r in s["bottom"])]


def format_upsets(label: str, upsets: dict) -> list[str]:
    lines = []
    for level, rows in upsets.items():
        parts = [f"差{gap}{'段以上' if gap == '3' else '段'} "
                 + (f"{row['upper_win_rate']:.1%}" if "upper_win_rate" in row else "—") + f"（{row['games']}試合）"
                 for gap, row in rows.items()]
        lines.append(f"  {label}{level}：上のランクの勝率 " + "　".join(parts))
    return lines


def _origin_line(label: str, cell: dict) -> str:
    bands = [b for _, _, b in RANK_BANDS] + [NO_RECORD]
    return f"    {label}（{cell['slots']:.0f}枠）" + "／".join(f"{b} {cell.get(b, 0):.0%}" for b in bands)


def format_turnover(game: dict, actual: dict) -> list[str]:
    """県内の勢力の入れ替わり（短い1節）。"""
    if not game and not actual:
        return []
    lines = ["■ 県内の勢力の入れ替わり（直前3年の夏の地方大会の成績による区分の中の順位。重み1.0／0.6／0.3）"]
    for slot, name in (("best4", "県ベスト4"), ("champion", "代表校")):
        for label, origin in (("ゲーム", game.get("origin") or {}), ("実際", actual.get("origin") or {})):
            if origin.get(slot):
                years = origin.get("years")     # 乱数の種の平均では年の並びは残らない
                span = f" {years[0]}〜{years[-1]}年" if years else ""
                for group, cell in origin[slot].items():
                    lines.append(_origin_line(f"{name}・{label}{span}・{group}", cell))
    for label, rows in (("ゲーム", game.get("newcomers") or {}), ("実際", actual.get("newcomers") or {})):
        for kind, row in rows.items():
            lines.append(f"  新顔の公立校（直前{NEWCOMER_YEARS}年に21世紀枠以外の出場なし）{label}・{kind}："
                         f"{row['newcomer_share']:.1%}（{row['newcomers']:.4g}／出場{row['all_entrants']:.0f}校、"
                         f"公立のうち {row['newcomer_public_share']:.1%}、{row['tournaments']}大会"
                         + ("、21世紀枠を除く" if kind == SPRING_KIND else "") + "）")
    for label, rates in (("ゲーム", game.get("entry_rates") or {}), ("実際", actual.get("entry_rates") or {})):
        if rates:
            lines.append(f"  直前の県内順位の帯ごとの1校あたりの確率（{label}。県ベスト4・代表校、公立／私立）")
            for band in [b for _, _, b in RANK_BANDS] + [NO_RECORD]:
                cells = rates.get(band) or {}
                lines.append(f"    {band}：" + "　".join(
                    f"{group} {c['best4_rate']:.1%}・{c['champion_rate']:.1%}（{c['schools']:.0f}校年）"
                    for group, c in cells.items()))
    gap = game.get("ownership_gap") or {}
    if gap:
        lines.append("  評判の県内順位の帯ごとの公立／私立（ゲームのみ。入部品質z・有望な新入生・新入生の能力・強さ）")
        for band in [b for _, _, b in RANK_BANDS if b in gap]:
            lines.append(f"    {band}：" + "　".join(
                f"{group} z {c.get('intake_z_mean', 0):+.2f}・有望 {c.get('prospects_mean', 0):.2f}人・"
                f"能力 {c.get('freshman_ability_mean', 0):.1f}・強さ "
                + (f"{c['strength_mean']:.1f}" if "strength_mean" in c else "—")
                + f"（{c['schools']:.0f}校年）" for group, c in gap[band].items()))
    for label, periods in (("ゲーム", game.get("periods") or {}), ("実際", actual.get("periods") or {})):
        for span, cell in periods.items():
            parts = [f"{kind} 公立 {cell[kind]['public_share']:.1%}・初めて出る公立 {cell[kind]['newcomer_share']:.1%}"
                     f"（{cell[kind]['all_entrants']:.0f}校）" for kind in (SUMMER_KIND, SPRING_KIND) if kind in cell]
            lines.append(f"  5年ごと {label} {span}：" + "　".join(parts)
                         + f"　1校が4回以上の県 {cell.get('dominant_4of5', 0):.4g}")
    strength = game.get("strength") or {}
    if strength:
        lines.append(f"  評判の県内順位と強さ（overall）の県内順位（7月1日、ゲームのみ）：順位相関 {strength['rank_correlation']:.3f}")
        bands = strength["by_reputation_band"]
        for band in [b for _, _, b in RANK_BANDS if b in bands]:
            cell = bands[band]
            change = cell.get("rank_change_mean")
            lines.append(f"    評判 {band}：強さの順位 平均 {cell['strength_rank_mean']}・散らばり {cell['strength_rank_stdev']}"
                         + (f"・前の年からの変化 {change}" if change is not None else "") + f"（{cell['schools']:.0f}校年）")
    return lines


def format_power(power: dict, actual: dict | None = None) -> str:
    """通しの指標の表示。``actual`` があれば実際の値を並べる。"""
    lines = ["通しの指標（始めた日から進めた日まで）", "■ 番狂わせ（評判のランクの差ごと）"]
    lines += format_upsets("", power.get("upsets") or {})
    if actual and "upsets" in actual:
        lines += format_upsets("実際（夏の地方大会2021〜2025年・開始時のランク。参考）", actual["upsets"])
    lines.append("  実際の値なし：地区大会・甲子園（試合ごとの記録がない）")
    lines.append("■ 強豪の続き方（夏の甲子園）")
    lines += format_dynasty("ゲーム", power.get("dynasty") or {})
    if actual:
        years = actual["years"]
        lines += format_dynasty(f"実際 {years[0]}〜{years[-1]}年", actual["dynasty"])
    lines.append("■ 都道府県の強弱（甲子園の春夏の勝率）")
    lines += format_strength("ゲーム", power.get("prefecture_strength") or {})
    for span, cell in (power.get("prefecture_correlation") or {}).items():
        if span == "rank_rise":
            lines.append(f"  県の順位が最初の5年から最後の5年で15位以上上がった県：{cell['risen_15']:.1f}")
            continue
        value = cell.get("history_correlation")
        if span == "all_years":
            span = f"{cell['first_year']:.0f}〜{cell['last_year']:.0f}"
        lines.append(f"  {'まとめて' if 'first_year' in cell else '5年ごと'} {span}：史実（koshien_games の県別勝率）との順位相関 "
                     + (f"{value:.3f}" if value is not None else "—") + f"（{cell['games']:.0f}試合）"
                     + (f"　勝率の散らばり {cell['stdev']:.3f}・試合数による揺れ {cell['noise_stdev']:.3f}"
                        f"・真の差の見積もり {cell['true_stdev']:.3f}" if "stdev" in cell else ""))
    for span, cell in (power.get("district_top") or {}).items():
        lines.append(f"  5年ごと {span}：地区1位の強さ（7月1日）平均 {cell['top_mean']:.1f}・地区の差（5年の平均の散らばり）"
                     f" {cell['top_stdev']:.2f}・年ごとの散らばり {cell['yearly_stdev']:.2f}")
    if actual:
        lines += format_strength("実際（開始前の通算）", actual["prefecture_strength"])
    lines.append("■ 優勝校の顔ぶれ（実際の値なし：年ごとの優勝校の記録がない）")
    for name, c in (power.get("champions") or {}).items():
        lines.append(f"  {name} {c['tournaments']}大会：ランク {_pairs(c.get('ranks') or {})}　"
                     f"初優勝 {c['first_time']}　連覇 {c['repeat']}")
    lines.append("■ 投手の使われ方（実際の値なし：試合ごとの球数の記録がない）")
    for scope, row in (power.get("starter_pitches") or {}).items():
        lines.append(f"  先発の球数 {scope}：平均 {row['mean']}　最多 {row['max']}　"
                     + "　".join(f"{label} {row[label]:.1%}" for _, label in PITCH_BANDS) + f"（{row['starts']}先発）")
    for scope, row in (power.get("ace") or {}).items():
        lines.append(f"  エース {scope}：登板 {row['pitched']:.1%}　先発 {row['started']:.1%}　平均 {row['mean_pitches']}球　"
                     f"間隔 {_pairs({k: f'{v:.1%}' for k, v in row['gap'].items()})}　"
                     f"連投 {row['back_to_back']}回　3日続けて {row['three_days']}回（{row['team_games']}チーム試合）")
    if power.get("pitch_limit") is not None:
        lines.append(f"  7日間の球数の上限に届いた投手（年度ごとの延べ人数）：{_pairs(power['pitch_limit']) or '0'}")
    lines += format_turnover(power.get("turnover") or {}, (actual or {}).get("turnover") or {})
    coaches = power.get("coaches") or {}
    if coaches:
        lines.append("■ 監督（実際の値なし）")
        for key, row in coaches["ended_tenure"].items():
            lines.append(f"  終わった在任の年数 {key}：{_pairs(row, TENURE_BANDS)}")
        lines.append(f"  今の監督の在任年数：{_pairs(coaches['active_tenure'], TENURE_BANDS)}")
        for key, row in coaches["retirement_age"].items():
            lines.append(f"  勇退の年齢 {key}：{_pairs(row, AGE_BANDS)}")
        lines.append("  甲子園（春夏）で勝った監督の数："
                     + _pairs(coaches["koshien_wins"], [(f"{n}勝以上",) for n in GREAT_COACH_WINS]))
        for key, row in sorted(coaches["after_great_coach"].items(), key=lambda kv: int(kv[0].split("勝")[0])):
            steps = "　".join(
                f"{ahead} {v['change_z']:+.3f}（同じランクの学校 "
                + (f"{v['peers_change_z']:+.3f}" if v["peers_change_z"] is not None else "—") + f"、{v['schools']}校）"
                for ahead, v in row.items() if ahead != "coaches")
            lines.append(f"  名将（{key}）{row['coaches']}人：学校の評判（z）の変化 {steps or '—'}")
    return "\n".join(lines)
