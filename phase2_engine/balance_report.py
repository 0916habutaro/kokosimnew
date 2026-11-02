"""バランスの物差し：新しく始めて指定した日まで進め、試合と選手の指標を出す。

試合の中身を変えるPRと最後の調整で使う集計（CIには入れない。結果のファイルはリポジトリに置かない）。

    python -m phase2_engine.balance_report --seeds 20261022,20261026 --until 2027-08-31

出す指標（年度ごと・シードごと。シードが2つ以上なら平均も）

- §11：地方大会の1チーム1試合の得点・コールドの割合・完封の割合、
  夏の甲子園の初出場の学校の数（割合）・2年続けて出る学校の数
- 先発の平均球数・完投の割合、盗塁・併殺の1試合あたりの数（両チームの合計）
- 個人成績の上位（打率・本塁打・防御率。規定は ``config/stats/player_rankings_v1.json``）
- 3年の投手の球速の分布、能力ごとのSの人数（7月1日の名簿。7月1日がなければ最後の日）
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
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

    def __init__(self, kind_of, history: dict[str, set[int]], rankings: dict):
        self.kind_of = kind_of
        self.history = history
        self.rankings = rankings
        self.games = defaultdict(list)          # (年度, 大会の種類) → (得点1, 得点2, 最終回)
        self.starts = defaultdict(lambda: [0, 0, 0])  # 年度 → [先発数, 球数の合計, 完投]
        self.running = defaultdict(lambda: [0, 0, 0])  # 年度 → [試合, 盗塁, 併殺]
        self.koshien = defaultdict(set)          # 年度 → 夏の甲子園に出た学校
        self.batters = defaultdict(lambda: defaultdict(Counter))   # 年度 → 選手 → 成績
        self.pitchers = defaultdict(lambda: defaultdict(Counter))
        self.team_games = defaultdict(Counter)   # 年度 → 学校 → 試合数
        self.rosters = {}                        # 年度 → 名簿の集計

    def add_match(self, competition_id: str, detail: dict) -> None:
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
            row = self.starts[year]
            row[0] += 1
            row[1] += int(starter["pitches"])
            row[2] += len(mine) == 1
        batters = detail.get("batter_stats") or []
        run = self.running[year]
        run[0] += 1
        run[1] += sum(int(b.get("stolen_bases", 0)) for b in batters)
        run[2] += sum(int(b.get("grounded_into_double_plays", 0)) for b in batters)
        for b in batters:
            self.batters[year][(b["school_id"], b["player_id"])].update(
                {k: int(b.get(k, 0)) for k in ("plate_appearances", "at_bats", "hits", "home_runs")})
        for p in pitchers:
            self.pitchers[year][(p["school_id"], p["player_id"])].update(
                {k: int(p.get(k, 0)) for k in ("outs_recorded", "earned_runs")})

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

    def _leaders(self, year: int) -> dict:
        games = self.team_games[year]
        bq = self.rankings["batter_qualification"]
        pq = self.rankings["pitcher_qualification"]
        avg, hr, era = [], [], []
        for (school, pid), row in self.batters[year].items():
            hr.append((row["home_runs"], pid, school))
            g = games[school]
            if g >= int(bq["minimum_team_games"]) and row["plate_appearances"] >= math.ceil(
                    g * float(bq["plate_appearances_per_team_game"])) and row["at_bats"]:
                avg.append((round(row["hits"] / row["at_bats"], 3), pid, school, row["at_bats"]))
        for (school, pid), row in self.pitchers[year].items():
            g = games[school]
            if g >= int(pq["minimum_team_games"]) and row["outs_recorded"] >= math.ceil(
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

    def summary(self) -> dict:
        years = sorted({y for y, _ in self.games} | set(self.rosters))
        out = {}
        for year in years:
            local = self.games.get((year, LOCAL), [])
            row = {"local": _game_metrics(local)}
            teams = self.koshien.get(year, set())
            if teams:
                first = {t for t in teams
                         if not any(y < year for y in self.history.get(t, ()))
                         and not any(t in self.koshien[y] for y in self.koshien if y < year)}
                row["koshien"] = {
                    "teams": len(teams),
                    "first_time": len(first),
                    "first_time_share": round(len(first) / len(teams), 3),
                    "repeat": len(teams & self._previous_koshien(year)),
                }
            starts = self.starts.get(year)
            if starts and starts[0]:
                row["starters"] = {"starts": starts[0],
                                   "pitches_mean": round(starts[1] / starts[0], 1),
                                   "complete_game_share": round(starts[2] / starts[0], 3)}
            run = self.running.get(year)
            if run and run[0]:
                row["per_game"] = {"games": run[0], "stolen_bases": round(run[1] / run[0], 2),
                                   "double_plays": round(run[2] / run[0], 2)}
            row["leaders"] = self._leaders(year)
            if year in self.rosters:
                row["rosters"] = self.rosters[year]
            out[year] = row
        return out


def _game_metrics(games) -> dict:
    if not games:
        return {}
    runs = [x for a, b, _ in games for x in (a, b)]
    return {
        "games": len(games),
        "runs_per_team": round(statistics.mean(runs), 2),
        "called_share": round(sum(inning < 9 for *_, inning in games) / len(games), 3),
        "shutout_share": round(sum(min(a, b) == 0 for a, b, _ in games) / len(games), 3),
    }


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


def run_seed(seed: int, until: date, *, progress=None) -> dict:
    from .live_game_service import LiveGameService
    from .live_season_save import PLAYER_RESOLVER_CONTRACT
    from .repository import DataRepository

    repo = DataRepository(ROOT / "data")
    tally = BalanceTally(competition_kinds(repo), summer_history(),
                         _load_json(ROOT / "config" / "stats" / "player_rankings_v1.json"))
    with tempfile.TemporaryDirectory() as saves:
        service = LiveGameService(repo, ROOT / "data", save_root=saves,
                                  resolver_contract=PLAYER_RESOLVER_CONTRACT,
                                  autosave_after_action=False)
        session = service.new_game("balance", rng_seed=seed, save_initial=False)
        state = session.state
        last_snapshot = None
        while True:
            # 試合の記録は保存の前に状態に置かれる。集めたら手放す（このコマンドは保存しない）
            for season in state.seasons.values():
                pending = season.pending_match_details
                for key in list(pending):
                    tally.add_match(key.split(":", 1)[0], pending.pop(key))
            today = state.current_date
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
    return tally.summary()


def average(reports: list[dict]) -> dict:
    """シードごとの数値の平均（年度・項目がそろっているものだけ。上位の選手は出さない）。"""
    def merge(values):
        if all(isinstance(v, dict) for v in values):
            keys = set.intersection(*(set(v) for v in values))
            return {k: merge([v[k] for v in values]) for k in sorted(keys) if k != "leaders"}
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
        ko = row.get("koshien")
        if ko:
            lines.append(f"  夏の甲子園 {ko['teams']}校: 初出場 {ko['first_time']}校"
                         f"（{ko['first_time_share']:.1%}） / 2年続けて {ko['repeat']}校")
        st = row.get("starters")
        if st:
            lines.append(f"  先発 {st['starts']}: 平均 {st['pitches_mean']}球 / 完投 {st['complete_game_share']:.1%}")
        pg = row.get("per_game")
        if pg:
            lines.append(f"  1試合あたり（{pg['games']}試合）: 盗塁 {pg['stolen_bases']} / 併殺 {pg['double_plays']}")
        leaders = row.get("leaders") or {}
        if leaders.get("batting_average"):
            lines.append("  打率: " + ", ".join(f"{r[0]:.3f}({r[3]}打数)" for r in leaders["batting_average"]))
        if leaders.get("home_runs"):
            lines.append("  本塁打: " + ", ".join(str(r[0]) for r in leaders["home_runs"]))
        if leaders.get("earned_run_average"):
            lines.append("  防御率: " + ", ".join(f"{r[0]:.2f}({r[3] // 3}回)" for r in leaders["earned_run_average"]))
        ro = row.get("rosters")
        if ro:
            lines.append(f"  3年の投手 {ro['third_year_pitchers']}人: 平均 {ro['velocity_mean']}km/h / "
                         f"最速 {ro['velocity_max']} / " + " ".join(
                             f"{k}:{v}" for k, v in ro["velocity_bands"].items()))
            lines.append(f"  Sの人数（全{ro['players']}人）: " + " ".join(
                f"{k}:{v}" for k, v in ro["s_count"].items()))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="新しく始めて進め、バランスの指標を出す")
    parser.add_argument("--seeds", required=True, help="カンマ区切りの乱数の種")
    parser.add_argument("--until", required=True, help="進める日（YYYY-MM-DD）")
    parser.add_argument("--json", type=Path, help="結果をJSONで書く先（リポジトリの外に置く）")
    args = parser.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    until = date.fromisoformat(args.until)
    started = time.time()

    def progress(seed, day):
        print(f"[{seed}] {day} {time.time() - started:.0f}秒", file=sys.stderr, flush=True)

    reports = {}
    for seed in seeds:
        reports[seed] = run_seed(seed, until, progress=progress)
        print(format_report(f"seed {seed}", reports[seed]), flush=True)
    if len(seeds) > 1:
        print(format_report("平均", average(list(reports.values()))))
    if args.json:
        args.json.write_text(json.dumps({str(k): v for k, v in reports.items()},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
