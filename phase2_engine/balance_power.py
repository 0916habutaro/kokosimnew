"""バランスの物差しのうち、年をまたいで見る指標（``balance_report`` の「通し」の節）。

- 番狂わせ：評判のランクの差（0・1・2・3段以上）ごとの、上のランクの学校の勝率。大会の格ごと
- 強豪の続き方（夏の甲子園）：連続出場・出場回数の分布、都道府県ごとの出場校の数
- 都道府県の強弱：甲子園（春夏）の勝率の散らばり
- 優勝校の顔ぶれ：夏・選抜の優勝校の評判のランク、連覇・初優勝
- 投手の使われ方：準決勝・決勝でのエースの登板の間隔、7日間の球数の上限に届いた投手、1試合の球数
- 監督：在任年数・勇退の年齢、甲子園で勝った監督が勇退したあとの学校の評判

実際の値は ``historical_data`` から同じ関数（``dynasty_metrics``・``spread_by_prefecture``）で計算する。
結果のファイルはリポジトリに置かない。
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from pathlib import Path
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


def _rows(name: str) -> list[dict]:
    with (HISTORY / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def actual_metrics(repo, tournaments: int = 10, rank_of=None) -> dict:
    """実際の値（``historical_data``）。ゲームと同じ関数で数える。

    - 強豪の続き方：出場校一覧の直近 ``tournaments`` 回の夏（中止の2020年は大会がないので飛ばす）。
      学校IDのない行は都道府県と当時の校名で1校とみなす
    - 都道府県の強弱：通算の記録（開始前の全期間の春夏の勝敗）を学校の今の都道府県で合計する
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
        self.champions = defaultdict(dict)              # 夏・選抜 → 年 → (学校, ランク)
        self.coach_wins: Counter = Counter()            # 監督 → 甲子園（春夏）の勝数
        self.coach_wins_by_year: dict[str, Counter] = defaultdict(Counter)  # 監督 → 年度 → 勝数
        self.pitch_days = defaultdict(dict)             # 選手 → 試合の日 → 球数（上限の日数分だけ）
        self.limit_reached = defaultdict(set)           # 場面 → (年度, 選手)
        self.starter_pitches = defaultdict(Counter)     # 場面 → 球数の帯 → 先発の数
        self.starter_max = Counter()
        self.tournament_pitches = defaultdict(lambda: defaultdict(dict))  # (大会, 学校) → 選手 → 日 → 球数
        self.ace = defaultdict(Counter)                 # 場面 → 数

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
        if kind in KOSHIEN_NAMES:
            name = KOSHIEN_NAMES[kind]
            self.entrants[name][day.year].update((winner, loser))
            self.records[name][self.repo.team(winner).prefecture_code][0] += 1
            self.records[name][self.repo.team(loser).prefecture_code][1] += 1
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
            "champions": {name: self._champion_summary(name) for name in KOSHIEN_NAMES.values()
                          if self.champions[name]},
            "starter_pitches": pitching,
            "ace": ace,
            "pitch_limit": {scope: len(rows) for scope, rows in sorted(self.limit_reached.items())},
            "coaches": self._coach_summary(coaches),
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
