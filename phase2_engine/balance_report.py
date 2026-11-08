"""バランスの物差し：新しく始めて指定した日まで進め、試合と選手の指標を出す。

試合の中身を変えるPRと最後の調整で使う集計（CIには入れない。結果のファイルはリポジトリに置かない）。

    python -m phase2_engine.balance_report --seeds 20261022,20261026 --until 2027-08-31

出す指標（年度ごと・シードごと。シードが2つ以上なら平均も）

- §11：地方大会の1チーム1試合の得点・コールドの割合・完封の割合、
  夏の甲子園の初出場の学校の数（割合）・2年続けて出る学校の数
- 先発の平均球数・完投の割合、盗塁・併殺の1試合あたりの数（両チームの合計）
- 個人成績の上位（打率・本塁打・防御率。規定は ``config/stats/player_rankings_v1.json``。
  少ない試合の選手で埋まらないよう、チームの試合数が ``--min-team-games`` 以上の選手だけ）
- 3年の投手の球速の分布、能力ごとのSの人数（7月1日の名簿。7月1日がなければ最後の日）
- 作戦（犠打・スクイズ・エンドラン）の1試合あたりの数と犠打の成功率。試合の要点の作戦の記録
  （``game_core/highlights.py`` の ``T``）と打者の犠打から数え、監督の小技・機動力の傾向
  （低い〜40・中・61〜高い）ごとの1チーム1試合あたりの数も出す
- 場面ごとの作戦の試み（無死一塁・無死二塁・無死一二塁・一死一塁で、送りバント・エンドランを
  試みた打席の割合。全試合と夏の甲子園）。試合の計算の作戦の判断（``_choose_tactic``）を数える
- 交代（段階F2）：代打・代走・守備固めの1試合あたりの数（交代の記録の理由から）、代打の打率、
  監督の交代の積極性（低い〜40・中・61〜高い）ごとの1チーム1試合あたりの交代の数
- 左右別の打率（打者の左右は名簿から）：同じ側どうし・逆の側、右対右・左対左・両打ち
- 暴投・捕逸・重盗・本盗の1試合あたりの数、1打席・1チーム1試合（9回あたり）の球数（段階H1）
- 度胸（段階G）：投手の度胸の帯（〜44・45〜59・60〜）ごとの、ピンチ・終盤の接戦とそれ以外の被打率
- 守備（段階H2）：失策の1試合あたりの数（地方大会・夏の甲子園）、守備位置ごとの打球・失策の割合、
  守った選手の守備の値の帯（〜44・45〜54・55〜）ごとの単打・失策の割合、本職でない位置（適性60未満）の失策の割合
- §11 の調整：地方大会の点差（0〜2・3〜5・6〜9・10以上）と延長の割合、夏の甲子園の直前10年の夏の出場回数
  （0・1・2・3回以上。実在の出場とゲームの年度）、夏の甲子園の1試合あたり（両チーム）の本塁打・盗塁・犠打・
  失策・四死球・三振とチーム打率・出塁率、甲子園の先発の球数・完投、甲子園の大会の個人成績の上位、
  同じ打者の対右・対左の打率の差（起用の偏りを除く）
- 部員の人数（4月1日の名簿）：全国の1校あたりの学年ごとの人数、1校の部員数の分布、私立・公立と
  評判の帯（z）ごとの平均、新入部員を最低人数まで増やした学校の数、退部した人数
- 連合チーム（11月1日の年度の状態）：大会の種類ごとの連合チームの数・構成校の数・出なかった学校の数
- 夏の地方大会のシード（8月31日の年度の状態）：シードのある大会の数・シード校の数、シード校どうしが
  準々決勝より前に当たった数（16校・32校のシードはベスト16・32で当たるので、
  ブロックを分けた回戦より前に当たった数も）、シード校のベスト8・ベスト4に残った割合。シードを入れていない版で
  比べるときは、同じ決まり（``competition_seed_rules.csv``）で選んだはずの学校を数える（``applied``＝0）
- ``--ability-table``：打者・守備・投手が全部50の相手に、能力を30・80・95にしたときの三振・四球・打率・長打率・本塁打
  （打席の結果の重みから計算する。試合は進めない）
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from datetime import date, timedelta
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LOCAL = "summer_local_qualifier"
KOSHIEN = "national_championship"
VELOCITY_BANDS = ((0, "〜129"), (130, "130〜134"), (135, "135〜139"),
                  (140, "140〜144"), (145, "145〜149"), (150, "150〜"))
TOP = 5
TENDENCY_BANDS = ((0, "低"), (41, "中"), (61, "高"))
COMPOSURE_BANDS = ((0, "〜44"), (45, "45〜59"), (60, "60〜"))
FIELDING_BANDS = ((0, "〜44"), (45, "45〜54"), (55, "55〜"))
FIELDING_POSITIONS = ("P", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
HITS = ("single", "double", "triple", "home_run")


def tendency_band(value) -> str | None:
    if value is None:
        return None
    return next(label for low, label in reversed(TENDENCY_BANDS) if value >= low)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def summer_history(path: Path = ROOT / "historical_data" / "koshien_entrants.csv") -> dict[str, set[int]]:
    """実在の夏の甲子園の出場年（学校ID → 年）。初出場・2年続けての判定に使う。"""
    out: dict[str, set[int]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["kind"] == "summer" and row["school_id"]:
                out[row["school_id"]].add(int(row["year"]))
    return out


class BalanceTally:
    """1つのシードの試合と名簿を集める（年度ごと）。"""

    def __init__(self, kind_of, history: dict[str, set[int]], rankings: dict,
                 min_team_games: int = 1):
        self.kind_of = kind_of
        self.min_team_games = min_team_games
        self.history = history
        self.rankings = rankings
        self.games = defaultdict(list)          # (年度, 大会の種類) → (得点1, 得点2, 最終回)
        self.starts = defaultdict(lambda: [0, 0, 0])  # 年度 → [先発数, 球数の合計, 完投]
        self.running = defaultdict(Counter)      # 年度 → 試合・盗塁・併殺・暴投・捕逸・球数・打者・アウト
        self.koshien = defaultdict(set)          # 年度 → 夏の甲子園に出た学校
        self.koshien_play = defaultdict(Counter)  # 年度 → 夏の甲子園の試合の打撃・投手の合計
        self.koshien_starts = defaultdict(lambda: [0, 0, 0])  # 年度 → 甲子園の [先発数, 球数, 完投]
        self.koshien_batters = defaultdict(lambda: defaultdict(Counter))  # 年度 → 選手 → 甲子園の成績
        self.koshien_pitchers = defaultdict(lambda: defaultdict(Counter))
        self.platoon = defaultdict(lambda: defaultdict(Counter))  # 年度 → (学校, 選手) → 対右・対左
        self.platoon_side = defaultdict(dict)    # 年度 → (学校, 選手) → 打つ側
        self.batters = defaultdict(lambda: defaultdict(Counter))   # 年度 → 選手 → 成績
        self.pitchers = defaultdict(lambda: defaultdict(Counter))
        self.team_games = defaultdict(Counter)   # 年度 → 学校 → 試合数
        self.rosters = {}                        # 年度 → 名簿の集計
        self.sizes = {}                          # 年度 → 部員の人数の集計（4月1日）
        self.unions = {}                         # 年度 → 大会の種類 → 連合チームの集計
        self.summer_seeds = {}                   # 年度 → 夏の地方大会のシードの集計
        self.tactics = defaultdict(Counter)      # 年度 → 作戦の数（全試合）
        self.tactics_koshien = defaultdict(Counter)  # 年度 → 作戦の数（夏の甲子園）
        self.substitutions = defaultdict(Counter)   # 年度 → 交代の数・代打の成績
        self.substitutions_by_band = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # 年度 → 帯 → [チーム試合, 交代]
        self.splits = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # 年度 → 組み合わせ → [打数, 安打]
        # 年度 → (小技／機動力, 傾向の帯) → [チーム試合, 犠打の試み, スクイズ, エンドラン, 盗塁の試み]
        self.by_tendency = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))

    def add_match(self, competition_id: str, detail: dict, coach_of=None, bats_of=None) -> None:
        """``coach_of(学校ID)`` はその試合の監督（小技・機動力・交代の傾向を見る。なければ None）。
        ``bats_of(学校ID, 選手ID)`` は打者の打つ側（R・L・S。左右別の打率に使う）。"""
        year = int(detail["reference_year"])
        kind = self.kind_of(competition_id)
        self.games[(year, kind)].append(
            (int(detail["team1_score"]), int(detail["team2_score"]), int(detail["last_inning"])))
        if kind == KOSHIEN:
            self.koshien[year].update((detail["team1_school_id"], detail["team2_school_id"]))
        for school in (detail["team1_school_id"], detail["team2_school_id"]):
            self.team_games[year][school] += 1
        pitchers = detail.get("pitcher_stats") or []
        for part in detail.get("team_participation") or []:
            mine = [p for p in pitchers if p["school_id"] == part["school_id"] and p["batters_faced"] > 0]
            starter = next((p for p in mine if p["player_id"] == part["starting_pitcher_id"]), None)
            if starter is None:
                continue
            for row in (self.starts[year], *((self.koshien_starts[year],) if kind == KOSHIEN else ())):
                row[0] += 1
                row[1] += int(starter["pitches"])
                row[2] += len(mine) == 1
        batters = detail.get("batter_stats") or []
        run = self.running[year]
        run["games"] += 1
        run["stolen_bases"] += sum(int(b.get("stolen_bases", 0)) for b in batters)
        run["double_plays"] += sum(int(b.get("grounded_into_double_plays", 0)) for b in batters)
        run["passed_balls"] += sum(int(b.get("passed_balls", 0)) for b in batters)
        errors = sum(int(t.get("errors", 0)) for t in detail.get("team_stats") or ())
        run["errors"] += errors
        if kind in (LOCAL, KOSHIEN):
            run[f"games_{kind}"] += 1
            run[f"errors_{kind}"] += errors
        for key in ("wild_pitches", "pitches", "batters_faced", "outs_recorded"):
            run[key] += sum(int(p.get(key, 0)) for p in pitchers)
        for b in batters:
            self.batters[year][(b["school_id"], b["player_id"])].update(
                {k: int(b.get(k, 0)) for k in ("plate_appearances", "at_bats", "hits", "home_runs")})
            self.platoon[year][(b["school_id"], b["player_id"])].update(
                {k: int(b.get(k, 0)) for k in ("vs_rhp_at_bats", "vs_rhp_hits", "vs_lhp_at_bats", "vs_lhp_hits")})
        if kind == KOSHIEN:
            play = self.koshien_play[year]
            play["games"] += 1
            for b in batters:
                for k in ("plate_appearances", "at_bats", "hits", "home_runs", "walks", "hit_by_pitch",
                          "strikeouts", "stolen_bases", "sacrifice_bunts", "sacrifice_flies"):
                    play[k] += int(b.get(k, 0))
                self.koshien_batters[year][(b["school_id"], b["player_id"])].update(
                    {k: int(b.get(k, 0)) for k in ("plate_appearances", "at_bats", "hits", "home_runs")})
            play["errors"] += sum(int(t.get("errors", 0)) for t in detail.get("team_stats") or ())
            for p in pitchers:
                self.koshien_pitchers[year][(p["school_id"], p["player_id"])].update(
                    {k: int(p.get(k, 0)) for k in ("outs_recorded", "earned_runs")})
        for p in pitchers:
            self.pitchers[year][(p["school_id"], p["player_id"])].update(
                {k: int(p.get(k, 0)) for k in ("outs_recorded", "earned_runs")})
        self._add_tactics(year, detail, batters, coach_of, kind == KOSHIEN)
        self._add_substitutions(year, detail, batters, coach_of)
        if bats_of is not None:
            self._add_splits(year, batters, bats_of)
            for b in batters:
                key = (b["school_id"], b["player_id"])
                if key not in self.platoon_side[year]:
                    self.platoon_side[year][key] = bats_of(*key)

    def _add_substitutions(self, year, detail, batters, coach_of) -> None:
        tally = self.substitutions[year]
        tally["games"] += 1
        for b in batters:
            tally["pinch_hit_at_bats"] += int(b.get("pinch_hit_at_bats", 0))
            tally["pinch_hit_hits"] += int(b.get("pinch_hit_hits", 0))
        for part in detail.get("team_participation") or []:
            reasons = Counter(c.get("reason") for c in part.get("changes") or () if c.get("reason"))
            tally.update(reasons)
            coach = coach_of(part["school_id"]) if coach_of else None
            band = tendency_band(getattr(coach, "substitutions", None)) if coach is not None else None
            if band is not None:
                cell = self.substitutions_by_band[year][band]
                cell[0] += 1
                cell[1] += sum(reasons.values())

    def _add_splits(self, year, batters, bats_of) -> None:
        cells = self.splits[year]
        for b in batters:
            bats = bats_of(b["school_id"], b["player_id"])
            if bats is None:
                continue
            for hand in ("R", "L"):
                at_bats = int(b.get(f"vs_{hand.lower()}hp_at_bats", 0))
                hits = int(b.get(f"vs_{hand.lower()}hp_hits", 0))
                if not at_bats:
                    continue
                kind = "switch" if bats == "S" else ("same" if bats == hand else "opposite")
                for key in (kind, f"{bats}v{hand}"):
                    cells[key][0] += at_bats
                    cells[key][1] += hits

    def _substitution_summary(self, year) -> dict:
        t = self.substitutions.get(year)
        if not t or not t["games"]:
            return {}
        games = t["games"]
        return {
            "games": games,
            "pinch_hitters": round(t["pinch_hitter"] / games, 3),
            "pinch_runners": round(t["pinch_runner"] / games, 3),
            "defensive_replacements": round(t["defensive_replacement"] / games, 3),
            "pinch_hit_average": (round(t["pinch_hit_hits"] / t["pinch_hit_at_bats"], 3)
                                  if t["pinch_hit_at_bats"] else None),
            "pinch_hit_at_bats": t["pinch_hit_at_bats"],
            "by_tendency": {band: {"team_games": cell[0], "substitutions": round(cell[1] / cell[0], 3)}
                            for band, cell in sorted(self.substitutions_by_band.get(year, {}).items())
                            if cell[0]},
        }

    def _add_tactics(self, year, detail, batters, coach_of, koshien=False) -> None:
        offense = {"t": detail["team1_school_id"], "b": detail["team2_school_id"]}
        per_team = defaultdict(Counter)
        for b in batters:
            per_team[b["school_id"]]["sacrifice_bunts"] += int(b.get("sacrifice_bunts", 0))
            per_team[b["school_id"]]["steal_attempts"] += (
                int(b.get("stolen_bases", 0)) + int(b.get("caught_stealing", 0)))
        for item in detail.get("highlights") or []:
            if item[0] != "T":
                continue
            _, _, half, _, tactic, outcome = item
            per_team[offense[half]][f"{tactic}:{outcome}"] += 1
            per_team[offense[half]][tactic] += 1
        tallies = [self.tactics[year]] + ([self.tactics_koshien[year]] if koshien else [])
        for tally in tallies:
            tally["games"] += 1
        for school in offense.values():
            row = per_team[school]
            for tally in tallies:
                tally.update(row)
            coach = coach_of(school) if coach_of else None
            if coach is None:
                continue
            squeezes = row["squeeze"]
            bunts = row["sacrifice_bunts"] - row["squeeze:ok"] + row["bunt"]
            for field, index_values in (("small_ball", (1, 2)), ("mobility", (3, 4))):
                band = tendency_band(getattr(coach, field, None))
                if band is None:
                    continue
                cell = self.by_tendency[year][(field, band)]
                cell[0] += 1
                if field == "small_ball":
                    cell[1] += bunts
                    cell[2] += squeezes
                else:
                    cell[3] += row["hit_and_run"]
                    cell[4] += row["steal_attempts"]

    def _tactics_summary(self, year, source=None) -> dict:
        t = (source if source is not None else self.tactics).get(year)
        if not t or not t["games"]:
            return {}
        games = t["games"]
        bunt_ok = t["sacrifice_bunts"] - t["squeeze:ok"]
        bunt_tries = bunt_ok + t["bunt"]
        out = {
            "games": games,
            "sacrifice_bunts": round(t["sacrifice_bunts"] / games, 2),
            "bunt_attempts": round(bunt_tries / games, 2),
            "bunt_success": round(bunt_ok / bunt_tries, 3) if bunt_tries else None,
            "bunt_failures": {k.split(":")[1]: t[k] for k in sorted(t) if k.startswith("bunt:")},
            "squeezes": round(t["squeeze"] / games, 3),
            "squeeze_success": round(t["squeeze:ok"] / t["squeeze"], 3) if t["squeeze"] else None,
            "hit_and_runs": round(t["hit_and_run"] / games, 3),
            "steal_attempts": round(t["steal_attempts"] / games, 2),
        }
        if source is not None:
            return out
        bands = self.by_tendency.get(year, {})
        out["by_tendency"] = {
            f"{field}:{band}": {
                "team_games": cell[0],
                **({"bunt_attempts": round(cell[1] / cell[0], 3), "squeezes": round(cell[2] / cell[0], 3)}
                   if field == "small_ball" else
                   {"hit_and_runs": round(cell[3] / cell[0], 3), "steal_attempts": round(cell[4] / cell[0], 3)}),
            }
            for (field, band), cell in sorted(bands.items()) if cell[0]
        }
        return out

    def add_rosters(self, year: int, players) -> None:
        """``players`` は (学年, 投手か, {能力: 値}) の並び。"""
        velocity = Counter()
        speeds = []
        s_count = Counter()
        total = 0
        for grade, pitcher, values in players:
            total += 1
            for name, value in values.items():
                if name != "velocity_kmh" and value and value >= 90:
                    s_count[name] += 1
            speed = values.get("velocity_kmh")
            if grade == 3 and pitcher and speed:
                speeds.append(speed)
                velocity[next(label for low, label in reversed(VELOCITY_BANDS) if speed >= low)] += 1
        self.rosters[year] = {
            "players": total,
            "third_year_pitchers": len(speeds),
            "velocity_mean": round(statistics.mean(speeds), 1) if speeds else None,
            "velocity_max": max(speeds) if speeds else None,
            "velocity_bands": {label: velocity[label] for _, label in VELOCITY_BANDS},
            "s_count": dict(sorted(s_count.items())),
        }

    def add_unions(self, year: int, season, kind_of) -> None:
        """その年度の連合チーム（大会の種類ごとに合計）。"""
        out = defaultdict(Counter)
        for cid, plan in (getattr(season, "union_plans", None) or {}).items():
            row = out[kind_of(cid)]
            row["teams"] += len(plan.teams)
            row["schools"] += sum(len(team.schools) for team in plan.teams)
            row["absent"] += len(plan.absent)
        self.unions[year] = {kind: dict(row) for kind, row in sorted(out.items())}

    def add_summer_seeds(self, year: int, season) -> None:
        """その年度の夏の地方大会のシード校と勝ち上がり（``summer_seed_rows``）。"""
        rows = summer_seed_rows(season)
        if not rows:
            return
        seeds = sum(r["seeds"] for r in rows)
        out = {
            "competitions": len(rows),
            "applied": sum(r["applied"] for r in rows),
            "seeded_competitions": sum(1 for r in rows if r["seeds"]),
            "seed_schools": seeds,
            "seed_meetings_before_qf": sum(r["meetings_before_qf"] for r in rows),
            "seed_meetings_inside_blocks": sum(r["meetings_inside_blocks"] for r in rows),
        }
        if seeds:
            out["best8_share"] = round(sum(r["best8"] for r in rows) / seeds, 3)
            out["best4_share"] = round(sum(r["best4"] for r in rows) / seeds, 3)
        self.summer_seeds[year] = out

    def add_sizes(self, year: int, schools, floor_hits: int = 0) -> None:
        """``schools`` は (設置者, 評判のランク S〜E, 学年ごとの人数 {1: 人, 2: 人, 3: 人}) の並び。"""
        totals, grades = [], Counter()
        groups = defaultdict(list)
        by_rank = defaultdict(list)
        for ownership, rank, counts in schools:
            total = sum(counts.values())
            totals.append(total)
            grades.update(counts)
            owner = "私立" if ownership == "private" else "公立"
            groups[owner].append(total)
            if rank:
                by_rank[f"{owner}{rank}"].append(total)
        if not totals:
            return
        n = len(totals)
        q = statistics.quantiles(totals, n=20)
        self.sizes[year] = {
            "schools": n,
            "per_school": {str(g): round(grades[g] / n, 2) for g in (1, 2, 3)},
            "total_mean": round(statistics.mean(totals), 1),
            "total_quantiles": {"p5": q[0], "p25": q[4], "p50": q[9], "p75": q[14], "p95": q[18],
                                "max": max(totals)},
            "group_mean": {k: round(statistics.mean(v), 1) for k, v in sorted(groups.items())},
            # 私立・公立 × 評判のランクごとの部員数（平均・10%点・90%点・学校の数）
            "by_rank": {k: _spread(v) for k, v in sorted(by_rank.items(), key=lambda kv: _rank_key(kv[0]))},
            # 評判Sの私立で部員が50人に届かない学校
            "private_s_under_50": sum(total < 50 for total in by_rank.get("私立S", ())),
            "floor_hits": floor_hits,
            "grade_totals": {str(g): grades[g] for g in (1, 2, 3)},
        }
        before = self.sizes.get(year - 1)
        if before:
            # 前の年度の1・2年生のうち、進級しなかった（退部した）人数
            stayed = grades[2] + grades[3]
            moved = before["grade_totals"]["1"] + before["grade_totals"]["2"]
            self.sizes[year]["withdrawn_share"] = round(1 - stayed / moved, 4) if moved else None

    def _leaders(self, year: int) -> dict:
        games = self.team_games[year]
        bq = self.rankings["batter_qualification"]
        pq = self.rankings["pitcher_qualification"]
        avg, hr, era = [], [], []
        enough = max(self.min_team_games, int(bq["minimum_team_games"]))
        for (school, pid), row in self.batters[year].items():
            g = games[school]
            if g < self.min_team_games:
                continue
            hr.append((row["home_runs"], pid, school))
            if g >= enough and row["plate_appearances"] >= math.ceil(
                    g * float(bq["plate_appearances_per_team_game"])) and row["at_bats"]:
                avg.append((round(row["hits"] / row["at_bats"], 3), pid, school, row["at_bats"]))
        for (school, pid), row in self.pitchers[year].items():
            g = games[school]
            if g >= max(self.min_team_games, int(pq["minimum_team_games"])) and row["outs_recorded"] >= math.ceil(
                    g * float(pq["outs_recorded_per_team_game"])) and row["outs_recorded"]:
                era.append((round(row["earned_runs"] * 27 / row["outs_recorded"], 2), pid, school,
                            row["outs_recorded"]))
        return {
            "batting_average": sorted(avg, key=lambda r: (-r[0], -r[3], r[1]))[:TOP],
            "home_runs": sorted(hr, key=lambda r: (-r[0], r[1]))[:TOP],
            "earned_run_average": sorted(era, key=lambda r: (r[0], -r[3], r[1]))[:TOP],
        }

    def _previous_koshien(self, year: int) -> set[str]:
        if year - 1 in self.koshien:
            return self.koshien[year - 1]
        return {sid for sid, years in self.history.items() if year - 1 in years}

    def _appearances(self, school: str, year: int) -> int:
        """直前10年（year−10〜year−1）の夏の甲子園の出場回数（ゲームの年度はゲームの出場、それ以前は実在）。"""
        return sum((school in self.koshien[y]) if y in self.koshien else (y in self.history.get(school, ()))
                   for y in range(year - 10, year))

    def _koshien_leaders(self, year: int) -> dict:
        """夏の甲子園の大会の個人成績の上位（打率は10打席以上、防御率は9回以上）。"""
        avg = sorted(((round(r["hits"] / r["at_bats"], 3), r["at_bats"]) for r in self.koshien_batters[year].values()
                      if r["plate_appearances"] >= 10 and r["at_bats"]), key=lambda x: (-x[0], -x[1]))[:TOP]
        hr = sorted((r["home_runs"] for r in self.koshien_batters[year].values()), reverse=True)[:TOP]
        era = sorted((round(r["earned_runs"] * 27 / r["outs_recorded"], 2), r["outs_recorded"])
                     for r in self.koshien_pitchers[year].values() if r["outs_recorded"] >= 27)[:TOP]
        return {"batting_average": avg, "home_runs": hr, "earned_run_average": era}

    def _platoon_within(self, year: int) -> dict:
        """同じ打者の、逆の側の投手と同じ側の投手に対する打率の差（右打ち・左打ちごと。起用の偏りを除く）。

        両方の投手に10打数以上の打者だけ。打者ごとの差を、2つの打数の調和平均で重み付けして平均する。"""
        out = {}
        for side in ("R", "L"):
            num = den = 0.0
            for key, row in self.platoon[year].items():
                if self.platoon_side[year].get(key) != side:
                    continue
                same, opposite = ("rhp", "lhp") if side == "R" else ("lhp", "rhp")
                s_ab, o_ab = row[f"vs_{same}_at_bats"], row[f"vs_{opposite}_at_bats"]
                if s_ab < 10 or o_ab < 10:
                    continue
                weight = 2 * s_ab * o_ab / (s_ab + o_ab)
                num += weight * (row[f"vs_{opposite}_hits"] / o_ab - row[f"vs_{same}_hits"] / s_ab)
                den += weight
            if den:
                out[side] = {"weight": round(den, 1), "opposite_minus_same": round(num / den, 4)}
        return out

    def summary(self) -> dict:
        years = sorted({y for y, _ in self.games} | set(self.rosters) | set(self.sizes)
                       | set(self.unions) | set(self.summer_seeds))
        out = {}
        for year in years:
            local = self.games.get((year, LOCAL), [])
            row = {"local": _game_metrics(local)}
            teams = self.koshien.get(year, set())
            if teams:
                first = {t for t in teams
                         if not any(y < year for y in self.history.get(t, ()))
                         and not any(t in self.koshien[y] for y in self.koshien if y < year)}
                prior = Counter(min(3, self._appearances(t, year)) for t in teams)
                row["koshien"] = {
                    "teams": len(teams),
                    "first_time": len(first),
                    "first_time_share": round(len(first) / len(teams), 3),
                    "repeat": len(teams & self._previous_koshien(year)),
                    "prior10": {str(n): round(prior[n] / len(teams), 3) for n in range(4)},
                }
            play = self.koshien_play.get(year)
            if play and play["games"]:
                g = play["games"]
                row["koshien_per_game"] = {
                    "games": g,
                    **{k: round(play[k] / g, 3) for k in ("home_runs", "stolen_bases", "sacrifice_bunts",
                                                           "errors", "strikeouts")},
                    "walks_hbp": round((play["walks"] + play["hit_by_pitch"]) / g, 3),
                    "batting_average": round(play["hits"] / play["at_bats"], 3) if play["at_bats"] else None,
                    "on_base": round((play["hits"] + play["walks"] + play["hit_by_pitch"])
                                     / (play["at_bats"] + play["walks"] + play["hit_by_pitch"]
                                        + play["sacrifice_flies"]), 3) if play["at_bats"] else None,
                }
                ks = self.koshien_starts[year]
                if ks[0]:
                    row["koshien_starters"] = {"starts": ks[0], "pitches_mean": round(ks[1] / ks[0], 1),
                                               "complete_game_share": round(ks[2] / ks[0], 3)}
                row["koshien_leaders"] = self._koshien_leaders(year)
            platoon = self._platoon_within(year)
            if platoon:
                row["platoon_within"] = platoon
            starts = self.starts.get(year)
            if starts and starts[0]:
                row["starters"] = {"starts": starts[0],
                                   "pitches_mean": round(starts[1] / starts[0], 1),
                                   "complete_game_share": round(starts[2] / starts[0], 3)}
            run = self.running.get(year)
            if run and run["games"]:
                games = run["games"]
                row["per_game"] = {"games": games, **{key: round(run[key] / games, 3) for key in (
                    "stolen_bases", "double_plays", "wild_pitches", "passed_balls", "errors")}}
                for kind, label in ((LOCAL, "errors_local"), (KOSHIEN, "errors_koshien")):
                    if run[f"games_{kind}"]:
                        row["per_game"][label] = round(run[f"errors_{kind}"] / run[f"games_{kind}"], 3)
                if run["batters_faced"] and run["outs_recorded"]:
                    row["pitch_counts"] = {
                        "per_plate_appearance": round(run["pitches"] / run["batters_faced"], 2),
                        "per_team_game": round(run["pitches"] / (2 * games), 1),
                        "per_nine_innings": round(run["pitches"] * 27 / run["outs_recorded"], 1),
                    }
            tactics = self._tactics_summary(year)
            if tactics:
                row["tactics"] = tactics
                koshien_tactics = self._tactics_summary(year, self.tactics_koshien)
                if koshien_tactics:
                    row["tactics_koshien"] = koshien_tactics
            subs = self._substitution_summary(year)
            if subs:
                row["substitutions"] = subs
            splits = self.splits.get(year)
            if splits:
                row["splits"] = {key: {"at_bats": ab, "average": round(h / ab, 3)}
                                 for key, (ab, h) in sorted(splits.items()) if ab}
            row["leaders"] = self._leaders(year)
            if year in self.rosters:
                row["rosters"] = self.rosters[year]
            if year in self.sizes:
                row["sizes"] = self.sizes[year]
            if year in self.unions:
                row["unions"] = self.unions[year]
            if year in self.summer_seeds:
                row["summer_seeds"] = self.summer_seeds[year]
            out[year] = row
        return out


def _game_metrics(games) -> dict:
    if not games:
        return {}
    runs = [x for a, b, _ in games for x in (a, b)]
    margins = [abs(a - b) for a, b, _ in games]
    return {
        "games": len(games),
        "runs_per_team": round(statistics.mean(runs), 2),
        "called_share": round(sum(inning < 9 for *_, inning in games) / len(games), 3),
        "shutout_share": round(sum(min(a, b) == 0 for a, b, _ in games) / len(games), 3),
        "extra_share": round(sum(inning >= 10 for *_, inning in games) / len(games), 3),
        "margin": {label: round(sum(low <= m <= high for m in margins) / len(games), 3)
                   for label, low, high in (("0-2", 0, 2), ("3-5", 3, 5), ("6-9", 6, 9), ("10+", 10, 999))},
    }


def summer_seed_rows(season) -> list[dict]:
    """夏の地方大会ごとのシード校と勝ち上がり。シードを入れていない大会は、
    ``competition_seed_rules.csv`` の決まりで選んだはずの学校を数える（比べるため）。"""
    from .seed_draw import choose_seeds, seed_sources, summer_seed_rules

    repo = season.repo
    out = []
    for cid, scheduled in sorted(season.competitions.items()):
        competition = repo.competitions.get(cid, {})
        rules = summer_seed_rules(repo, cid)
        if competition.get("competition_type") != LOCAL or not rules or not scheduled.is_complete:
            continue
        runtime = scheduled.runtime
        seeds = list(getattr(runtime, "annual_seed_order", ()) or ())
        applied = bool(seeds)
        if not seeds:
            prefecture = competition.get("prefecture_code", "")
            rankings = {}
            for kind, offset in seed_sources(rules):
                if offset < 0:
                    ranking = (getattr(season, "prior_autumn_rankings", None) or {}).get(prefecture)
                    if ranking:
                        rankings[kind] = ranking
                    continue
                for source_id, source in season.competitions.items():
                    row = repo.competitions.get(source_id, {})
                    if (row.get("competition_type") == kind and row.get("prefecture_code") == prefecture
                            and source.is_complete):
                        rankings[kind] = source.to_competition_run().outcome.final_ranking_school_ids
            seeds = choose_seeds(rules, rankings, runtime.entrant_school_ids,
                                 base_seed=season.rng_seed, namespace=cid)
        seed_set = set(seeds)
        total = runtime.total_rounds
        # シード校が別々のブロックにいる回戦（それより前に当たれば決まりに反する）。
        # 途中で抽選し直す回戦からは数えない
        separated = total - (len(seeds) - 1).bit_length() + 1 if seeds else 0
        redraw = getattr(runtime, "redraw_rounds", {}) or {}
        if redraw:
            separated = min(separated, min(redraw))
        reached = defaultdict(set)
        meetings = inside = 0
        for match in runtime.matches.values():
            teams = {match.team1, match.team2} - {""}
            reached[match.round_no] |= teams
            if len(teams & seed_set) == 2:
                meetings += match.round_no < total - 2
                inside += match.round_no < separated
        out.append({
            "competition_id": cid,
            "applied": applied,
            "seeds": len(seeds),
            "meetings_before_qf": meetings,
            "meetings_inside_blocks": inside,
            "best8": len(seed_set & reached.get(total - 2, set())),
            "best4": len(seed_set & reached.get(total - 1, set())),
        })
    return out


def competition_kinds(repo):
    """大会IDから大会の種類（年度の付いたIDは元の大会の種類）。"""
    types = {cid: c.get("competition_type") for cid, c in repo.competitions.items()}
    cache = {}

    def kind_of(cid: str) -> str:
        if cid not in cache:
            cache[cid] = types.get(cid) or next(
                (t for key, t in types.items() if cid.startswith(key)), "?")
        return cache[cid]
    return kind_of


def roster_rows(book, year: int):
    from game_core.roster_book import SCALARS

    for school in book.schools(year):
        for player in book.roster(year, school).players:
            values = book.state(player).values
            yield (player.academic_year, player.primary_position == "P",
                   {name: values[i] for i, name in enumerate(SCALARS)})


RANK_ORDER = "SABCDE"


def _rank_key(label: str):
    return (label[:2], RANK_ORDER.index(label[2:]) if label[2:] in RANK_ORDER else 9)


def _spread(values) -> dict:
    ordered = sorted(values)

    def at(share):
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))]

    return {"n": len(ordered), "mean": round(statistics.mean(ordered), 1),
            "p10": at(0.1), "p90": at(0.9)}


def size_rows(book, year: int, repo):
    """4月1日の全校の (設置者, 評判のランク, 学年ごとの人数)。ランクはその日の評判（画面と同じ）。"""
    reputation = getattr(book, "reputation", None)
    for school in book.school_ids:
        counts = Counter(p.academic_year for p in book.roster(year, school).players)
        rank = reputation.rank(school) if reputation is not None else ""
        yield (repo.ownership_type(school), rank, {g: counts.get(g, 0) for g in (1, 2, 3)})


SITUATIONS = {
    (0, "first"): "無死一塁", (0, "second"): "無死二塁", (0, "first_second"): "無死一二塁",
    (1, "first"): "一死一塁",
}


def composure_band(value) -> str:
    value = 50 if value is None else value
    return next(label for low, label in reversed(COMPOSURE_BANDS) if value >= low)


class SituationCounter:
    """作戦の判断を場面ごとに数える（このコマンドの中だけで試合の計算を包む）。

    あわせて、重盗・本盗の数（盗塁の判断の結果から）と、投手の度胸の帯ごとのピンチ・終盤の接戦と
    それ以外の被打率（打席の場面の判断と、打席の結果の球数の計算から）を数える。"""

    def __init__(self, kind_of):
        self.kind_of = kind_of
        self.year = None
        self.kind = None
        self.counts = defaultdict(Counter)   # (年度, 全試合／夏の甲子園, 場面) → 打席・作戦
        self.steals = defaultdict(Counter)   # 年度 → 重盗・本盗（試み・成功）
        self.pressure = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # 年度 → (場面, 帯) → [打数, 安打]
        self.pressed = False
        self.fielding = defaultdict(Counter)  # 年度 → 守備位置・帯ごとの打球・単打・失策

    @contextmanager
    def watching(self):
        from game_core.match_simulator import MatchSimulator

        simulate, choose = MatchSimulator.simulate, MatchSimulator._choose_tactic
        attempt, under, pitches = (MatchSimulator._attempt_steal,
                                   getattr(MatchSimulator, "_under_pressure", None), MatchSimulator._pitches)
        field = getattr(MatchSimulator, "_field_ball", None)
        counter = self

        def watched_attempt(sim, *, bases, **kwargs):
            result = attempt(sim, bases=bases, **kwargs)
            if result:
                row = counter.steals[counter.year]
                lead = result[0]
                kind = ("home_steal" if lead[1] == 2 else
                        "double_steal" if lead[1] == 1 and bases[0] is not None else None)
                if kind is not None:
                    row[kind] += 1
                    row[f"{kind}_success"] += lead[2] == "sb"
            return result

        def watched_under(sim, bases, inning, margin):
            counter.pressed = under(sim, bases, inning, margin)
            return counter.pressed

        def watched_pitches(sim, event_type, rng, pitcher=None, batter=None):
            if pitcher is not None and bool(sim.event_catalog[event_type]["counts_as_at_bat"]):
                cell = counter.pressure[counter.year][
                    ("pressure" if counter.pressed else "other", composure_band(pitcher.composure))]
                cell[0] += 1
                cell[1] += event_type in HITS
            return pitches(sim, event_type, rng, pitcher, batter)

        def watched_simulate(sim, match_input, *args, **kwargs):
            counter.year = match_input.reference_year
            counter.kind = counter.kind_of(match_input.competition_id)
            return simulate(sim, match_input, *args, **kwargs)

        def watched_choose(sim, *, bases, outs, **kwargs):
            tactic = choose(sim, bases=bases, outs=outs, **kwargs)
            name = SITUATIONS.get((outs, MatchSimulator._runner_shape(bases))) if bases[2] is None else None
            if name is not None:
                for scope in ("all", "koshien") if counter.kind == KOSHIEN else ("all",):
                    row = counter.counts[(counter.year, scope, name)]
                    row["plate_appearances"] += 1
                    row[tactic or "none"] += 1
            return tactic

        MatchSimulator.simulate, MatchSimulator._choose_tactic = watched_simulate, watched_choose
        def watched_field(sim, event_type, **kwargs):
            result, fielded = field(sim, event_type, **kwargs)
            if fielded is not None and result in ("single", "field_out", "reached_on_error"):
                row = counter.fielding[counter.year]
                band = next(label for low, label in reversed(FIELDING_BANDS) if fielded.skill >= low)
                primary = "primary" if fielded.aptitude >= 60 else "out_of_position"
                for key in (f"pos:{fielded.position}", f"band:{band}", f"apt:{primary}", "all"):
                    row[f"{key}:balls"] += 1
                    row[f"{key}:single"] += result == "single"
                    row[f"{key}:error"] += result == "reached_on_error"
            return result, fielded

        # 変更の前の版（度胸・重盗・守備のない版）と比べるときは、ないものを包まない
        h1 = under is not None
        if h1:
            MatchSimulator._attempt_steal, MatchSimulator._under_pressure = watched_attempt, watched_under
            MatchSimulator._pitches = watched_pitches
        if field is not None:
            MatchSimulator._field_ball = watched_field
        try:
            yield self
        finally:
            MatchSimulator.simulate, MatchSimulator._choose_tactic = simulate, choose
            if field is not None:
                MatchSimulator._field_ball = field
            if h1:
                MatchSimulator._attempt_steal, MatchSimulator._under_pressure = attempt, under
                MatchSimulator._pitches = pitches

    def play_summary(self) -> dict:
        """年度 → 重盗・本盗の数と、度胸の帯ごとの被打率。"""
        out = defaultdict(dict)
        for year, row in self.steals.items():
            out[year]["steals"] = dict(sorted(row.items()))
        for year, row in self.fielding.items():
            total_errors = row["all:error"]
            out[year]["fielding"] = {
                key: {"balls": row[f"{key}:balls"],
                      "single_rate": round(row[f"{key}:single"] / row[f"{key}:balls"], 4),
                      "error_rate": round(row[f"{key}:error"] / row[f"{key}:balls"], 4),
                      **({"error_share": round(row[f"{key}:error"] / total_errors, 3)}
                         if key.startswith("pos:") and total_errors else {})}
                for key in ([f"pos:{p}" for p in FIELDING_POSITIONS]
                            + [f"band:{label}" for _, label in FIELDING_BANDS]
                            + ["apt:primary", "apt:out_of_position", "all"])
                if row[f"{key}:balls"]
            }
        for year, cells in self.pressure.items():
            out[year]["composure"] = {f"{scene}:{band}": {"at_bats": ab, "average": round(h / ab, 3)}
                                      for (scene, band), (ab, h) in sorted(cells.items()) if ab}
        return dict(out)

    def summary(self) -> dict:
        out = defaultdict(dict)
        for (year, scope, name), row in sorted(self.counts.items()):
            n = row["plate_appearances"]
            out[year].setdefault(scope, {})[name] = {
                "plate_appearances": n,
                "bunt": round(row["bunt"] / n, 3),
                "hit_and_run": round(row["hit_and_run"] / n, 3),
            }
        return dict(out)


class HandLookup:
    """選手ID → 打つ側（名簿から。学校・年度ごとに1回だけ引く）。"""

    def __init__(self):
        self.bats: dict[str, str] = {}
        self.loaded: set[tuple[int, str]] = set()

    def lookup(self, book, year: int, school_id: str, player_id: str) -> str | None:
        if player_id not in self.bats:
            for each in (year, year - 1):
                if (each, school_id) in self.loaded:
                    continue
                self.loaded.add((each, school_id))
                try:
                    players = book.roster(each, school_id).players
                except (KeyError, ValueError):
                    continue
                self.bats.update({p.player_id: p.bats for p in players})
                if player_id in self.bats:
                    break
        return self.bats.get(player_id)


def run_seed(seed: int, until: date, *, min_team_games: int = 1, progress=None) -> dict:
    from .live_game_service import LiveGameService
    from .live_season_save import PLAYER_RESOLVER_CONTRACT
    from .repository import DataRepository
    from .school_year import school_year_of

    repo = DataRepository(ROOT / "data")
    tally = BalanceTally(competition_kinds(repo), summer_history(),
                         _load_json(ROOT / "config" / "stats" / "player_rankings_v1.json"),
                         min_team_games)
    situations = SituationCounter(tally.kind_of)
    hands = HandLookup()
    with tempfile.TemporaryDirectory() as saves, situations.watching():
        service = LiveGameService(repo, ROOT / "data", save_root=saves,
                                  resolver_contract=PLAYER_RESOLVER_CONTRACT,
                                  autosave_after_action=False)
        session = service.new_game("balance", rng_seed=seed, save_initial=False)
        state = session.state
        last_snapshot = None
        while True:
            # 試合の記録は保存の前に状態に置かれる。集めたら手放す（このコマンドは保存しない）
            today = state.current_date
            played_on = max(today - timedelta(days=1), date(state.rosters.first_year, 4, 1))
            coaches = getattr(state, "coaches", None)

            def coach_of(school_id, on=played_on):
                return coaches.for_school(school_id, on=on) if coaches is not None else None

            def bats_of(school_id, player_id, on=played_on):
                return hands.lookup(state.rosters, school_year_of(on), school_id, player_id)

            for season in state.seasons.values():
                pending = season.pending_match_details
                for key in list(pending):
                    tally.add_match(key.split(":", 1)[0], pending.pop(key), coach_of, bats_of)
            if (today.month, today.day) == (4, 1):
                sizes = list(size_rows(state.rosters, today.year, repo))
                tally.add_sizes(today.year, sizes, state.rosters.floor_hits.get(today.year, 0))
            if (today.month, today.day) == (11, 1) and today.year in state.seasons:
                tally.add_unions(today.year, state.seasons[today.year], tally.kind_of)
            if (today.month, today.day) == (8, 31) and today.year in state.seasons:
                tally.add_summer_seeds(today.year, state.seasons[today.year])
            if (today.month, today.day) == (7, 1):
                tally.add_rosters(today.year, roster_rows(state.rosters, today.year))
                last_snapshot = today.year
            if today >= until:
                break
            service.next_day(session, autosave=False)
            if progress and today.day == 1:
                progress(seed, today)
        from .school_year import school_year_of

        year = school_year_of(state.current_date)
        if last_snapshot is None or last_snapshot < year:
            tally.add_rosters(year, roster_rows(state.rosters, year))
    report = tally.summary()
    for year, scopes in situations.summary().items():
        if year in report:
            report[year]["situations"] = scopes
    for year, extra in situations.play_summary().items():
        if year in report:
            if "steals" in extra and report[year].get("per_game"):
                games = report[year]["per_game"]["games"]
                report[year]["per_game"].update({
                    key: round(extra["steals"].get(key, 0) / games, 4)
                    for key in ("double_steal", "home_steal")})
                report[year]["steal_kinds"] = extra["steals"]
            if "composure" in extra:
                report[year]["composure"] = extra["composure"]
            if "fielding" in extra:
                report[year]["fielding"] = extra["fielding"]
    return report


def average(reports: list[dict]) -> dict:
    """シードごとの数値の平均（年度・項目がそろっているものだけ。上位の選手は出さない）。"""
    def merge(values):
        if all(isinstance(v, dict) for v in values):
            keys = set.intersection(*(set(v) for v in values))
            return {k: merge([v[k] for v in values]) for k in sorted(keys)
                    if k not in ("leaders", "koshien_leaders")}
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            return round(statistics.mean(values), 3)
        return None
    years = set.intersection(*(set(r) for r in reports))
    return {year: merge([r[year] for r in reports]) for year in sorted(years)}


def format_report(seed_label: str, report: dict) -> str:
    lines = [f"== {seed_label}"]
    for year, row in sorted(report.items()):
        lines.append(f"-- {year}年度")
        local = row.get("local") or {}
        if local:
            lines.append(f"  地方大会 {local['games']}試合: 得点 {local['runs_per_team']} / "
                         f"コールド {local['called_share']:.1%} / 完封 {local['shutout_share']:.1%}")
            if local.get("margin"):
                lines.append(f"  地方大会 点差 0〜2／3〜5／6〜9／10以上: " + "／".join(
                    f"{local['margin'][k]:.1%}" for k in ("0-2", "3-5", "6-9", "10+"))
                    + f" / 延長 {local['extra_share']:.1%}")
        ko = row.get("koshien")
        if ko:
            lines.append(f"  夏の甲子園 {ko['teams']}校: 初出場 {ko['first_time']}校"
                         f"（{ko['first_time_share']:.1%}） / 2年続けて {ko['repeat']}校")
        if ko and ko.get("prior10"):
            lines.append("  夏の甲子園 直前10年の出場 0回／1回／2回／3回以上: " + "／".join(
                f"{ko['prior10'][k]:.1%}" for k in ("0", "1", "2", "3")))
        kp = row.get("koshien_per_game")
        if kp:
            lines.append(f"  夏の甲子園 1試合あたり（{kp['games']}試合）: 本塁打 {kp['home_runs']} / 盗塁 {kp['stolen_bases']}"
                         f" / 犠打 {kp['sacrifice_bunts']} / 失策 {kp['errors']} / 四死球 {kp['walks_hbp']}"
                         f" / 三振 {kp['strikeouts']} / 打率 {kp['batting_average']} / 出塁率 {kp['on_base']}")
        kst = row.get("koshien_starters")
        if kst:
            lines.append(f"  夏の甲子園 先発 {kst['starts']}: 平均 {kst['pitches_mean']}球 / 完投 {kst['complete_game_share']:.1%}")
        kl = row.get("koshien_leaders")
        if kl:
            lines.append("  夏の甲子園の個人（10打席以上の打率・本塁打・9回以上の防御率）: "
                         + ", ".join(f"{a:.3f}({n})" for a, n in kl["batting_average"]) + " / "
                         + ", ".join(str(h) for h in kl["home_runs"]) + " / "
                         + ", ".join(f"{e:.2f}({o // 3}回)" for e, o in kl["earned_run_average"]))
        pw = row.get("platoon_within")
        if pw:
            lines.append("  同じ打者の左右の差（逆の側−同じ側の打率）: " + " / ".join(
                f"{side}打ち {v['opposite_minus_same']:+.3f}" for side, v in pw.items()))
        st = row.get("starters")
        if st:
            lines.append(f"  先発 {st['starts']}: 平均 {st['pitches_mean']}球 / 完投 {st['complete_game_share']:.1%}")
        pg = row.get("per_game")
        if pg:
            lines.append(f"  1試合あたり（{pg['games']}試合）: 盗塁 {pg['stolen_bases']} / 併殺 {pg['double_plays']}"
                         f" / 暴投 {pg.get('wild_pitches')} / 捕逸 {pg.get('passed_balls')}"
                         f" / 重盗 {pg.get('double_steal', '−')} / 本盗 {pg.get('home_steal', '−')}")
        if pg and pg.get("errors") is not None:
            lines.append(f"  失策（1試合あたり）: 全試合 {pg['errors']} / 地方大会 {pg.get('errors_local', '−')}"
                         f" / 夏の甲子園 {pg.get('errors_koshien', '−')}")
        fd = row.get("fielding")
        if fd:
            lines.append("  守備位置ごと（打球・単打・失策の割合・失策の内訳）: " + " / ".join(
                f"{k[4:]} {v['balls']}・{v['single_rate']:.3f}・{v['error_rate']:.4f}・{v.get('error_share', 0):.1%}"
                for k, v in fd.items() if k.startswith("pos:")))
            lines.append("  守った選手の守備の値の帯・適性（単打・失策の割合）: " + " / ".join(
                f"{k} {v['single_rate']:.3f}・{v['error_rate']:.4f}（{v['balls']}）"
                for k, v in fd.items() if not k.startswith("pos:")))
        sk = row.get("steal_kinds")
        if sk:
            lines.append("  重盗・本盗（試み・成功）: " + " ".join(f"{k}:{v}" for k, v in sk.items()))
        pc = row.get("pitch_counts")
        if pc:
            lines.append(f"  球数: 1打席 {pc['per_plate_appearance']} / 1チーム1試合 {pc['per_team_game']}"
                         f" / 9回あたり {pc['per_nine_innings']}")
        co = row.get("composure")
        if co:
            lines.append("  度胸の帯ごとの被打率（ピンチ・終盤の接戦 pressure／それ以外 other）: " + " / ".join(
                f"{key} {v['average']:.3f}（{v['at_bats']}）" for key, v in co.items()))
        ta = row.get("tactics")
        rate = lambda v: "−" if v is None else f"{v:.1%}"
        for label, tk in (("全試合", ta), ("夏の甲子園", row.get("tactics_koshien"))):
            if tk:
                lines.append(f"  作戦（{label}・1試合あたり）: 犠打 {tk['sacrifice_bunts']}（試み {tk['bunt_attempts']}・成功 "
                             f"{rate(tk['bunt_success'])}）/ スクイズ {tk['squeezes']}（成功 {rate(tk['squeeze_success'])}）"
                             f" / エンドラン {tk['hit_and_runs']} / 盗塁の試み {tk['steal_attempts']}")
        if ta:
            if ta.get("bunt_failures"):
                lines.append("  犠打の失敗: " + " ".join(f"{k}:{v}" for k, v in ta["bunt_failures"].items()))
            for key, cell in (ta.get("by_tendency") or {}).items():
                lines.append(f"  監督 {key}（{cell['team_games']}チーム試合）: " + " ".join(
                    f"{k} {v}" for k, v in cell.items() if k != "team_games"))
        for scope, label in (("all", "全試合"), ("koshien", "夏の甲子園")):
            rows = (row.get("situations") or {}).get(scope)
            if rows:
                lines.append(f"  場面ごとの作戦（{label}・試みた打席の割合）: " + " / ".join(
                    f"{name} {v['plate_appearances']}打席 バント{v['bunt']:.1%}・エンドラン{v['hit_and_run']:.1%}"
                    for name, v in rows.items()))
        su = row.get("substitutions")
        if su:
            average = "−" if su["pinch_hit_average"] is None else f"{su['pinch_hit_average']:.3f}"
            lines.append(f"  交代（1試合あたり）: 代打 {su['pinch_hitters']} / 代走 {su['pinch_runners']} / "
                         f"守備固め {su['defensive_replacements']} / 代打の打率 {average}（{su['pinch_hit_at_bats']}打数）")
            if su.get("by_tendency"):
                lines.append("  監督 交代の積極性（1チーム1試合あたりの交代）: " + " / ".join(
                    f"{band} {cell['substitutions']}（{cell['team_games']}）" for band, cell in su["by_tendency"].items()))
        sp = row.get("splits")
        if sp:
            lines.append("  左右別の打率: " + " / ".join(
                f"{key} {v['average']:.3f}（{v['at_bats']}）" for key, v in sp.items()))
        leaders = row.get("leaders") or {}
        if leaders.get("batting_average"):
            lines.append("  打率: " + ", ".join(f"{r[0]:.3f}({r[3]}打数)" for r in leaders["batting_average"]))
        if leaders.get("home_runs"):
            lines.append("  本塁打: " + ", ".join(str(r[0]) for r in leaders["home_runs"]))
        if leaders.get("earned_run_average"):
            lines.append("  防御率: " + ", ".join(f"{r[0]:.2f}({r[3] // 3}回)" for r in leaders["earned_run_average"]))
        sz = row.get("sizes")
        if sz:
            q = sz["total_quantiles"]
            lines.append(f"  部員（4月1日、{sz['schools']}校）: 1校あたり 1年 {sz['per_school']['1']} / "
                         f"2年 {sz['per_school']['2']} / 3年 {sz['per_school']['3']} / 計 {sz['total_mean']}人、"
                         f"最低人数で補った {sz['floor_hits']}校"
                         + (f"、退部 {sz['withdrawn_share']:.1%}" if sz.get("withdrawn_share") is not None else ""))
            lines.append("  部員数の分布 p5/25/50/75/95/最大: " + "/".join(
                str(q[k]) for k in ("p5", "p25", "p50", "p75", "p95", "max")))
            lines.append("  帯ごとの平均: " + " ".join(f"{k}:{v}" for k, v in sz["group_mean"].items()))
            if sz.get("by_rank"):
                lines.append("  私立・公立×評判 平均（10%点〜90%点、校数）: " + " ".join(
                    f"{k}:{v['mean']}({v['p10']}〜{v['p90']},{v['n']})" for k, v in sz["by_rank"].items()))
                lines.append(f"  評判Sの私立で50人未満: {sz['private_s_under_50']}校")
        un = row.get("unions")
        if un:
            lines.append("  連合チーム（チーム／構成校／出ない学校）: " + " ".join(
                f"{k}:{v.get('teams', 0)}／{v.get('schools', 0)}／{v.get('absent', 0)}"
                for k, v in un.items()))
        ss = row.get("summer_seeds")
        if ss:
            lines.append(
                f"  夏の地方大会のシード: シードのある大会 {ss.get('seeded_competitions')}"
                f"（入れた大会 {ss.get('applied')}）／{ss.get('competitions')}、シード校 {ss.get('seed_schools')}校、"
                f"準々決勝より前のシード校どうし {ss.get('seed_meetings_before_qf')}試合"
                f"（うちブロックを分けた回戦より前 {ss.get('seed_meetings_inside_blocks')}）、"
                f"ベスト8に残った {ss.get('best8_share')}、ベスト4 {ss.get('best4_share')}")
        ro = row.get("rosters")
        if ro:
            lines.append(f"  3年の投手 {ro['third_year_pitchers']}人: 平均 {ro['velocity_mean']}km/h / "
                         f"最速 {ro['velocity_max']} / " + " ".join(
                             f"{k}:{v}" for k, v in ro["velocity_bands"].items()))
            lines.append(f"  Sの人数（全{ro['players']}人）: " + " ".join(
                f"{k}:{v}" for k, v in ro["s_count"].items()))
    return "\n".join(lines)


ABILITY_TABLE_LEVELS = (30, 50, 80, 95)
ABILITY_TABLE_BATTER = ("contact", "power", "plate_discipline", "strikeout_resistance", "speed")
ABILITY_TABLE_PITCHER = ("velocity_kmh", "stuff", "control", "strikeout")


def ability_table() -> dict:
    """打者・守備・投手が全部50（球速は140km/h）の相手に、1つの能力だけを変えたときの打席の結果の割合。

    打席の結果の重みから計算する（左右の差・疲れ・度胸・作戦・守った選手の効きは入れない）。"""
    from dataclasses import replace

    from game_core.match_simulator import MatchSimulator

    import copy

    sim = MatchSimulator()
    # 左右の差を入れない（同じ側・逆の側の点を0にした写しで計算する）
    sim.params = copy.deepcopy(sim.params)
    platoon = sim.params["platoon"]
    platoon["same_side_points"] = {side: 0 for side in platoon["same_side_points"]}
    platoon["opposite_side_points"] = 0
    base = _neutral_player()
    batter, pitcher = replace(base, bats="R"), replace(base, throws="L", bats="L")

    def rates(b, p, defense=50.0):
        w = sim._event_weights(b, p, defense)
        total = sum(w.values())
        pa = {k: v / total for k, v in w.items()}
        walks = pa.get("walk", 0) + pa.get("hit_by_pitch", 0)
        at_bats = 1.0 - walks - pa.get("sacrifice_fly", 0)
        hits = sum(pa.get(k, 0) for k in ("single", "double", "triple", "home_run"))
        bases = pa.get("single", 0) + 2 * pa.get("double", 0) + 3 * pa.get("triple", 0) + 4 * pa.get("home_run", 0)
        return {"strikeout": round(pa.get("strikeout", 0), 3), "walk": round(walks, 3),
                "average": round(hits / at_bats, 3), "slugging": round(bases / at_bats, 3),
                "home_run": round(pa.get("home_run", 0), 4)}

    out = {}
    for key in ABILITY_TABLE_BATTER:
        out[f"打者 {key}"] = {lv: rates(replace(batter, **{key: lv}), pitcher) for lv in ABILITY_TABLE_LEVELS}
    for key in ABILITY_TABLE_PITCHER:
        levels = {30: 125, 50: 140, 80: 150, 95: 155} if key == "velocity_kmh" else {lv: lv for lv in ABILITY_TABLE_LEVELS}
        out[f"投手 {key}"] = {lv: rates(batter, replace(pitcher, **{key: value})) for lv, value in levels.items()}
    out["守備（チームの守備力）"] = {lv: rates(batter, pitcher, float(lv)) for lv in ABILITY_TABLE_LEVELS}
    return out


def _neutral_player():
    """能力が全部50の架空の選手（投手の能力も持つ。変化球なし）。"""
    from dataclasses import fields, replace

    from game_core.abilities import PlayerAbilitySnapshot

    values = {}
    for f in fields(PlayerAbilitySnapshot):
        if f.name in ("player_id", "school_id"):
            values[f.name] = "FAKE-NEUTRAL"
        elif f.name == "primary_position":
            values[f.name] = "P"
        elif f.name == "pitch_repertoire":
            values[f.name] = ()
        elif f.name == "position_aptitude":
            values[f.name] = tuple((pos, 50) for pos in ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"))
        elif f.name == "velocity_kmh":
            values[f.name] = 140
        elif f.name in ("bats", "throws"):
            values[f.name] = "R"
        elif f.type in ("int", "int | None", "float", "float | None"):
            values[f.name] = 50
        else:
            values[f.name] = None
    return PlayerAbilitySnapshot(**values)


def format_ability_table(table: dict) -> str:
    lines = ["能力ごとの効き（相手は全部50。三振・四死球は打席あたり、打率・長打率は打数あたり、本塁打は打席あたり）"]
    for name, by_level in table.items():
        lines.append(f"  {name}: " + " / ".join(
            f"{lv}→三振{r['strikeout']:.3f} 四死球{r['walk']:.3f} 打率{r['average']:.3f} 長打率{r['slugging']:.3f} "
            f"本塁打{r['home_run']:.4f}" for lv, r in by_level.items()))
    return "\n".join(lines)


def _run_one(args):
    seed, until, min_team_games = args
    return seed, run_seed(seed, until, min_team_games=min_team_games,
                          progress=lambda s, d: print(f"[{s}] {d}", file=sys.stderr, flush=True))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="新しく始めて進め、バランスの指標を出す")
    parser.add_argument("--seeds", help="カンマ区切りの乱数の種")
    parser.add_argument("--until", help="進める日（YYYY-MM-DD）")
    parser.add_argument("--workers", type=int, default=1, help="乱数の種を並べて進めるプロセスの数")
    parser.add_argument("--ability-table", action="store_true",
                        help="能力ごとの効きの表だけを出す（試合は進めない）")
    parser.add_argument("--min-team-games", type=int, default=8,
                        help="個人成績の上位に入れる選手のチームの最少試合数（年度ごと）")
    parser.add_argument("--json", type=Path, help="結果をJSONで書く先（リポジトリの外に置く）")
    args = parser.parse_args(argv)
    if args.ability_table:
        print(format_ability_table(ability_table()))
        return 0
    if not args.seeds or not args.until:
        parser.error("--seeds と --until が必要です（--ability-table のときは不要）")
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    until = date.fromisoformat(args.until)
    started = time.time()

    def progress(seed, day):
        print(f"[{seed}] {day} {time.time() - started:.0f}秒", file=sys.stderr, flush=True)

    reports = {}
    if args.workers > 1 and len(seeds) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for seed, report in pool.map(_run_one, [(s, until, args.min_team_games) for s in seeds]):
                reports[seed] = report
        for seed in seeds:
            print(format_report(f"seed {seed}", reports[seed]), flush=True)
    else:
        for seed in seeds:
            reports[seed] = run_seed(seed, until, min_team_games=args.min_team_games, progress=progress)
            print(format_report(f"seed {seed}", reports[seed]), flush=True)
    if args.json:
        args.json.write_text(json.dumps({str(k): v for k, v in reports.items()},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
    if len(seeds) > 1:
        print(format_report("平均", average(list(reports.values()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
