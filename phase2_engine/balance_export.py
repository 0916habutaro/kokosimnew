"""balance_report の結果を表計算で開ける CSV に書く。2つの結果（--json）の前後の比較も出す。

結果のファイルはリポジトリに置かない（出力先の既定は ``out/``。.gitignore 済み）。CSV は Excel で
そのまま開けるよう UTF-8（BOM付き）で書く。

- 指標（``--csv``）：``metrics.csv``（1行1指標の縦長。種ごとの値と、種の平均・最小・最大）と
  ``conditions.csv``（種・期間・コミット・config の revision・日時）
- 前後の比較（``--compare 前.json 後.json``）：指標ごとの前・後・差・実際。Markdown の表を標準出力に出し、
  ``--csv`` があれば ``compare.csv`` も書く
- 試合ごとの一覧（``--matches-csv``）：``matches_<種>.csv``。1行1試合
- 学校×年度の一覧（``--schools-csv``）：``schools_<種>.csv``。1行＝1校の1年度。
  名簿・能力・学校の強さ・監督・評判はその年度の7月1日（夏の地方大会の前。7月1日まで進めていなければ
  最後の日）、到達点と甲子園の勝敗はその年度のシーズンの大会（3月に始まる春季県大会はその年の4月からの
  年度、3月の選抜は選んだ前の年度のシーズン。終わっていない大会は画面と同じく「勝ち残り」）

どちらの一覧も「年度」は大会を持つシーズンの年度（試合の日の年度ではない）。
"""
from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date, datetime
import json
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = Path("out")
ENCODING = "utf-8-sig"          # Excel でそのまま開ける
POWER_KEY = "通し"               # balance_report の年をまたぐ指標の鍵
ALL_YEARS = "全年度"             # 比較で年度ごとの指標を年度の平均にした行
AGGREGATES = ("平均", "最小", "最大")

# 指標の先頭 → 区分（長い方を先に見る）
CATEGORIES = (
    (("local", "blowout"), "大差"), (("blowout",), "大差"),
    (("local",), "§11"), (("koshien",), "§11"),
    (("koshien_per_game",), "甲子園"), (("koshien_starters",), "甲子園"),
    (("koshien_bench",), "甲子園"), (("tactics_koshien",), "甲子園"),
    (("upsets",), "番狂わせ"),
    (("dynasty",), "強豪の続き方"), (("prefecture_strength",), "強豪の続き方"), (("champions",), "強豪の続き方"),
    (("starters",), "投手"), (("pitch_counts",), "投手"), (("composure",), "投手"),
    (("pitcher_shuffle",), "投手"), (("starter_pitches",), "投手"), (("ace",), "投手"), (("pitch_limit",), "投手"),
    (("coaches",), "監督"),
    (("turnover",), "勢力の入れ替わり"),
    (("per_game",), "試合"), (("steal_kinds",), "試合"), (("fielding",), "守備"),
    (("tactics",), "作戦"), (("situations",), "作戦"),
    (("substitutions",), "采配"), (("lineup",), "采配"), (("lineup_changes",), "采配"),
    (("splits",), "打撃"), (("platoon_within",), "打撃"),
    (("rosters",), "選手"), (("recruitment",), "選手"), (("sizes",), "部員"), (("reputation_top50",), "評判"),
    (("unions",), "連合"), (("summer_union_history",), "連合"),
    (("prefectural_entry",), "大会の方式"), (("summer_seeds",), "大会の方式"), (("spring_seeds",), "大会の方式"),
    (("autumn_seeds",), "大会の方式"), (("selection",), "大会の方式"),
    (("spring_regionals",), "大会の方式"), (("autumn_regionals",), "大会の方式"),
)

CATEGORY_ORDER = ("§11", "大差", "番狂わせ", "強豪の続き方", "勢力の入れ替わり", "甲子園", "投手", "監督", "試合", "守備", "作戦",
                  "采配", "打撃", "選手", "部員", "評判", "連合", "大会の方式", "その他")

# 指標の名前（鍵ごとの言い換え。ないものは鍵のまま）
LABELS = {
    "local": "地方大会", "koshien": "夏の甲子園", "games": "試合", "runs_per_team": "1チームの得点",
    "called_share": "コールド", "shutout_share": "完封", "extra_share": "延長", "margin": "点差",
    "blowout": "大差", "teams": "出場校", "first_time": "初出場", "first_time_share": "初出場の割合",
    "repeat": "2年続けて出た学校", "prior10": "直前10年の出場回数",
    "koshien_per_game": "夏の甲子園の1試合", "home_runs": "本塁打", "stolen_bases": "盗塁",
    "sacrifice_bunts": "犠打", "errors": "失策", "strikeouts": "三振", "walks_hbp": "四死球",
    "batting_average": "打率", "on_base": "出塁率",
    "koshien_starters": "甲子園の先発", "starters": "先発", "starts": "先発の数",
    "pitches_mean": "球数の平均", "complete_game_share": "完投",
    "per_game": "1試合あたり", "double_plays": "併殺", "wild_pitches": "暴投", "passed_balls": "捕逸",
    "errors_local": "失策（地方大会）", "errors_koshien": "失策（夏の甲子園）",
    "double_steal": "重盗", "home_steal": "本盗",
    "pitch_counts": "球数", "per_plate_appearance": "1打席", "per_team_game": "1チーム1試合",
    "per_nine_innings": "9回あたり",
    "tactics": "作戦", "tactics_koshien": "作戦（夏の甲子園）", "bunt_attempts": "犠打の試み",
    "bunt_success": "犠打の成功率", "bunt_failures": "犠打の失敗", "squeezes": "スクイズ",
    "squeeze_success": "スクイズの成功率", "hit_and_runs": "エンドラン", "steal_attempts": "盗塁の試み",
    "by_tendency": "監督の傾向ごと",
    "substitutions": "交代", "pinch_hitters": "代打", "pinch_runners": "代走",
    "defensive_replacements": "守備固め", "pinch_hit_average": "代打の打率", "pinch_hit_at_bats": "代打の打数",
    "blowout_rest": "大差で休ませた", "blowout_rest_team_games": "大差で休ませたチーム試合",
    "pitcher_shuffle": "投手の配置転換", "lineup_changes": "顔ぶれ・打順の変更", "lineup": "打順",
    "splits": "左右別", "platoon_within": "対右・対左の差", "situations": "場面ごとの作戦",
    "steal_kinds": "重盗・本盗", "composure": "度胸", "fielding": "守備",
    "rosters": "名簿（7月1日）", "players": "選手", "third_year_pitchers": "3年の投手",
    "velocity_mean": "球速の平均", "velocity_max": "最速", "velocity_bands": "球速の帯",
    "s_count": "Sの人数", "by_grade": "学年ごと", "s_third_main": "3年の主な能力のS",
    "a_one": "主な能力のA以上1つ以上", "a_two": "主な能力のA以上2つ以上",
    "kmh145": "145km/h以上", "kmh150": "150km/h以上", "fastest": "最速",
    "koshien_bench": "夏の甲子園のベンチ入り（学年）",
    "recruitment": "新入生の配分（4月1日）", "freshmen": "新入生",
    "prospect_drawn": "有望選手の旧方式の抽選", "prospect_supply": "全国プールの候補者",
    "prospect_assigned": "有望選手の割当", "schools_with_prospects": "有望選手を獲得した学校",
    "sizes": "部員（4月1日）", "schools": "学校", "per_school": "1校あたり（学年）",
    "total_mean": "1校の部員の平均", "total_quantiles": "1校の部員の分布", "group_mean": "設置者ごとの平均",
    "by_rank": "評判のランクごと", "private_s_under_50": "評判Sの私立で50人未満", "floor_hits": "最低人数まで増やした学校",
    "grade_totals": "学年ごとの合計", "withdrawn_share": "退部の割合",
    "reputation_top50": "評判の上位50校の入れ替わり", "vs_previous": "前の年から", "vs_start": "始めの年から",
    "unions": "連合チーム", "summer_union_history": "夏の連合の続き方", "prefectural_entry": "県大会の出場",
    "summer_seeds": "夏の成績シード", "spring_seeds": "春の成績シード", "autumn_seeds": "秋の成績シード",
    "selection": "選抜の選考", "spring_regionals": "春の地区大会", "autumn_regionals": "秋の地区大会",
    "upsets": "番狂わせ（ランクの差ごと）", "upper_win_rate": "上のランクの勝率",
    "dynasty": "夏の甲子園の続き方", "tournaments": "大会", "streaks": "連続出場", "longest_streak": "最長の連続出場",
    "appearances": "出場回数", "prefecture_school_counts": "都道府県ごとの出場校の数",
    "prefecture_schools_mean": "都道府県の出場校の平均", "dominant_prefectures": "独り勝ちの県",
    "crowded_prefectures": "群雄割拠の県", "by_prefecture": "都道府県ごと",
    "prefecture_strength": "都道府県の甲子園の勝率", "prefectures": "都道府県", "stdev": "標準偏差",
    "rates": "勝率", "champions": "優勝校", "ranks": "評判のランク",
    "starter_pitches": "先発の球数", "mean": "平均", "max": "最大", "ace": "エース",
    "team_games": "チーム試合", "pitched": "登板", "started": "先発", "mean_pitches": "球数の平均",
    "back_to_back": "連投", "three_days": "3連投", "gap": "登板の間隔", "pitch_limit": "球数の上限に届いた投手",
    "coaches": "監督", "ended_tenure": "終わった在任", "retirement_age": "勇退の年齢",
    "active_tenure": "現役の在任年数", "koshien_wins": "甲子園の勝数", "after_great_coach": "名将が去った・来た学校",
    "change_z": "評判の変化（z）", "plate_appearances": "打席", "pitches": "球数", "at_bats": "打数",
    "hits": "安打", "regional_entrants": "秋季地区大会の出場校", "senbatsu_entrants": "選抜の出場校",
    "regional_seed_share": "地区大会の出場校のうち県大会のシード校", "senbatsu_seed_share": "選抜の出場校のうち県大会のシード校",
    "competitions": "大会", "applied": "シードを入れた大会", "seeded_competitions": "シードのある大会",
    "seed_schools": "シード校", "seed_meetings_before_qf": "準々決勝より前のシード校どうし",
    "seed_meetings_inside_blocks": "ブロック内のシード校どうし", "best8_share": "シード校のベスト8",
    "best4_share": "シード校のベスト4", "byes": "1回戦免除", "relaxed_regions": "決まりをゆるめた地区",
    "same_prefecture_first_games": "同じ県どうしの初戦", "rank1_first_games": "県1位どうしの初戦",
    "five_single": "5年続けて単独の学校のうち連合", "five_single_total": "5年続けて単独の学校",
    "five_single_share": "5年続けて単独の学校のうち連合の割合", "previous": "前の年に連合",
    "continued": "続けて連合", "continued_share": "続けて連合の割合",
    "turnover": "県内の勢力の入れ替わり", "origin": "直前の県内順位から", "best4": "県ベスト4",
    "champion": "代表校", "slots": "枠", "newcomers": "新顔の公立校", "all_entrants": "出場校", "public": "公立校",
    "newcomer_share": "新顔の公立校の割合", "newcomer_public_share": "公立校のうち新顔の割合",
    "strength": "評判と強さ（ゲームのみ）", "by_reputation_band": "評判の県内順位の帯ごと",
    "strength_rank_mean": "強さの県内順位の平均", "strength_rank_stdev": "強さの県内順位の散らばり",
    "rank_change_mean": "前の年からの強さの順位の変化", "rank_correlation": "評判と強さの順位相関",
    "entry_rates": "直前の県内順位の帯ごとの1校あたりの確率", "best4_rate": "県ベスト4に入る確率",
    "champion_rate": "代表校になる確率", "ownership_gap": "評判の県内順位の帯ごとの公立・私立（ゲームのみ）",
    "intake_z_mean": "入部品質zの平均", "prospects_mean": "有望な新入生の平均人数",
    "freshman_ability_mean": "新入生の主な能力の平均", "strength_mean": "強さ（overall）の平均",
}

# 都道府県・地区ごとの内訳。Markdown の比較には出さない（CSV には出す）
DETAIL_KEYS = frozenset(("by_prefecture", "rates", "prefectural_entry", "hosts", "entrants", "by_region",
                         "prefecture_school_counts"))
PREFECTURE_CODE = re.compile(r"\d{2}")
ROUND_RE = re.compile(r"-MAIN-R(\d+)-")
SUMMER_AREA_RE = re.compile(r"選手権(.+?)大会")
COMPETITION_COLUMNS = (
    ("spring_prefectural", "春の県大会"), ("spring_regional", "春の地区大会"),
    ("summer_local_qualifier", "夏の地方大会"), ("national_championship", "夏の甲子園"),
    ("autumn_prefectural", "秋の県大会"), ("autumn_regional", "秋の地区大会"),
    ("national_autumn_championship", "神宮"), ("national_invitational", "選抜"),
)
KOSHIEN_COLUMNS = (("national_championship", "夏の甲子園"), ("national_invitational", "選抜"))
MAIN_BATTER = ("contact", "power", "plate_discipline", "speed", "fielding", "arm_strength")
MAIN_PITCHER = ("control", "stamina", "stuff", "strikeout")
COACH_TENDENCIES = ("small_ball", "mobility", "substitutions", "pitching_change", "player_selection",
                    "lineup_style", "form_reliance", "pitcher_shuffle", "player_eye")
STRENGTH_FIELDS = ("overall", "batting", "pitching", "defense", "running")


# ---- 共通 ----


def write_csv(path: Path, columns, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=ENCODING, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def number(value):
    """表に出す数（整数はそのまま、小数は大きさに合わせて丸める）。"""
    if value is None or value == "":
        return ""
    if float(value).is_integer():
        return int(value)
    digits = 1 if abs(value) >= 100 else 3 if abs(value) >= 1 else 4
    return float(format(round(value, digits), ".10g"))


def flatten(node, path=()):
    """入れ子の結果から (鍵の並び, 数) を出す。並び（上位の選手など）と数でないものは出さない。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from flatten(value, (*path, str(key)))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield path, node


def category(path) -> str:
    for prefix, label in CATEGORIES:
        if tuple(path[:len(prefix)]) == prefix:
            return label
    return "その他"


def label(path) -> str:
    return "／".join(LABELS.get(part, part) for part in path)


def unit(path) -> str:
    leaf, parent = path[-1], path[0]
    if leaf == "change_z":
        return "z"
    if (any(word in leaf for word in ("share", "success", "average", "rate")) or leaf in ("on_base", "pitched", "started")
            or parent in ("starter_pitches",) and leaf not in ("starts", "mean", "max", "pitches")):
        return "割合"
    if leaf in ("pitches_mean", "mean_pitches", "per_plate_appearance", "per_team_game", "per_nine_innings"):
        return "球"
    if parent in ("per_game", "koshien_per_game") and leaf != "games":
        return "1試合あたり"
    if leaf in ("games", "starts", "team_games"):
        return "試合"
    if leaf in ("schools", "teams", "first_time", "repeat", "dominant_prefectures", "crowded_prefectures"):
        return "校" if leaf not in ("dominant_prefectures", "crowded_prefectures") else "県"
    if leaf in ("players", "third_year_pitchers"):
        return "人"
    return ""


def seed_values(report: dict) -> dict[tuple[str, str], float]:
    """1つの種の結果 → (年度, 指標) → 値。指標は鍵を . でつないだもの。"""
    out = {}
    for year, section in report.items():
        for path, value in flatten(section):
            out[(str(year), ".".join(path))] = value
    return out


def actual_values(actual: dict | None) -> dict[str, float]:
    return {".".join(path): value for path, value in flatten(actual or {})}


# ---- 指標の CSV ----


METRIC_COLUMNS = ("区分", "年度", "指標", "名前", "種", "値", "実際", "単位")


def metric_rows(reports: dict, actual: dict | None = None) -> list[dict]:
    """種ごとの値と、種の平均・最小・最大（全部の種にある指標だけ）。実際の値は年をまたぐ指標（通し）に付ける。"""
    per_seed = {str(seed): seed_values(report) for seed, report in reports.items()}
    real = actual_values(actual)
    keys = list(dict.fromkeys(key for values in per_seed.values() for key in values))
    rows = []
    for year, metric in keys:
        path = metric.split(".")
        base = {"区分": category(path), "年度": year, "指標": metric, "名前": label(path), "単位": unit(path),
                "実際": number(real.get(metric)) if year == POWER_KEY else ""}
        values = []
        for seed, seed_map in per_seed.items():
            if (year, metric) in seed_map:
                values.append(seed_map[(year, metric)])
                rows.append({**base, "種": seed, "値": number(seed_map[(year, metric)])})
        if len(per_seed) > 1 and len(values) == len(per_seed):
            for name, value in zip(AGGREGATES, (statistics.mean(values), min(values), max(values))):
                rows.append({**base, "種": name, "値": number(value)})
    return rows


def git_commit(root: Path = ROOT) -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    return f"{head}（コミットしていない変更あり）" if dirty else head


def config_revisions(root: Path = ROOT) -> dict[str, object]:
    out = {}
    for path in sorted((root / "config").rglob("*.json")):
        try:
            revision = json.loads(path.read_text(encoding="utf-8")).get("revision")
        except (OSError, ValueError, AttributeError):
            revision = None
        out[path.relative_to(root).as_posix()] = revision
    return out


def run_conditions(seeds, start: str, until: date | str, *, root: Path = ROOT, now: datetime | None = None) -> dict:
    return {
        "seeds": [int(s) for s in seeds],
        "start": start,
        "until": str(until),
        "commit": git_commit(root),
        "created_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "config_revisions": config_revisions(root),
    }


def condition_rows(conditions: dict) -> list[dict]:
    rows = [{"項目": "種", "値": ",".join(str(s) for s in conditions.get("seeds", ()))},
            {"項目": "開始", "値": conditions.get("start", "")},
            {"項目": "終わり（この日まで進めた）", "値": conditions.get("until", "")},
            {"項目": "コミット", "値": conditions.get("commit", "")},
            {"項目": "日時", "値": conditions.get("created_at", "")}]
    rows += [{"項目": f"revision {name}", "値": "" if value is None else value}
             for name, value in (conditions.get("config_revisions") or {}).items()]
    return rows


def write_metrics(directory: Path, reports: dict, actual: dict | None, conditions: dict) -> list[Path]:
    return [write_csv(directory / "metrics.csv", METRIC_COLUMNS, metric_rows(reports, actual)),
            write_csv(directory / "conditions.csv", ("項目", "値"), condition_rows(conditions))]


# ---- 前後の比較 ----


COMPARE_COLUMNS = ("区分", "年度", "指標", "名前", "前", "前の最小", "前の最大", "後", "後の最小", "後の最大",
                   "差", "実際", "単位")


def load_result(path: Path) -> tuple[dict, dict | None, dict]:
    """--json の結果 → (種 → 結果, 実際, 実行の条件)。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    reports = {key: value for key, value in data.items() if key not in ("actual", "conditions")}
    return reports, data.get("actual"), data.get("conditions") or {}


def summarize(reports: dict) -> dict[tuple[str, str], tuple[float, float, float]]:
    """(年度, 指標) → (種の平均, 最小, 最大)。年度ごとの指標は「全年度」（種ごとに年度を平均してから）も足す。"""
    per_seed = [seed_values(report) for report in reports.values()]
    for values in per_seed:
        by_metric = defaultdict(list)
        for (year, metric), value in values.items():
            if year != POWER_KEY:
                by_metric[metric].append(value)
        values.update({(ALL_YEARS, metric): statistics.mean(v) for metric, v in by_metric.items()})
    keys = list(dict.fromkeys(key for values in per_seed for key in values))
    out = {}
    for key in keys:
        values = [v[key] for v in per_seed if key in v]
        if len(values) == len(per_seed):
            out[key] = (statistics.mean(values), min(values), max(values))
    return out


def compare_rows(before: dict, after: dict, actual: dict | None = None) -> list[dict]:
    """``before``・``after`` は種 → 結果。指標ごとの前・後（種の平均と幅）・差（後 − 前）・実際。"""
    first, second = summarize(before), summarize(after)
    real = actual_values(actual)
    rows = []
    for year, metric in dict.fromkeys([*first, *second]):
        path = metric.split(".")
        a, b = first.get((year, metric)), second.get((year, metric))
        rows.append({
            "区分": category(path), "年度": year, "指標": metric, "名前": label(path), "単位": unit(path),
            "前": number(a[0]) if a else "", "前の最小": number(a[1]) if a else "", "前の最大": number(a[2]) if a else "",
            "後": number(b[0]) if b else "", "後の最小": number(b[1]) if b else "", "後の最大": number(b[2]) if b else "",
            "差": number(b[0] - a[0]) if a and b else "",
            "実際": number(real.get(metric)) if year == POWER_KEY and metric in real else "",
        })
    return rows


def _with_range(row: dict, side: str) -> str:
    value, low, high = row[side], row[f"{side}の最小"], row[f"{side}の最大"]
    if value == "":
        return "—"
    return f"{value}（{low}〜{high}）" if low != high else f"{value}"


def is_detail(metric: str) -> bool:
    """都道府県・地区ごとの内訳の指標か。"""
    return any(part in DETAIL_KEYS or PREFECTURE_CODE.fullmatch(part) for part in metric.split("."))


def compare_markdown(rows: list[dict], conditions: tuple[dict, dict] = ({}, {}), only=None,
                     years=(ALL_YEARS, POWER_KEY)) -> str:
    """PRの説明に貼る表。年度ごとの指標は「全年度」（年度の平均）、年をまたぐ指標は「通し」。
    都道府県・地区ごとの内訳は出さない（compare.csv にはある）。
    ``only`` は出す区分（なければ全部）。前・後は種の平均で、種が2つ以上なら（最小〜最大）を添える。"""
    lines = []
    for name, cond in zip(("前", "後"), conditions):
        if cond:
            lines.append(f"- {name}：種 {','.join(str(s) for s in cond.get('seeds', ()))}、"
                         f"{cond.get('start', '')}〜{cond.get('until', '')}、コミット {cond.get('commit', '')[:12]}")
    if lines:
        lines.append("")
    groups = defaultdict(list)
    for row in rows:
        if row["年度"] in years and (not only or row["区分"] in only) and not is_detail(row["指標"]):
            groups[row["区分"]].append(row)
    for group, items in sorted(groups.items(), key=lambda item: CATEGORY_ORDER.index(item[0])):
        lines += [f"### {group}", "", "| 指標 | 年度 | 前 | 後 | 差 | 実際 |", "|---|---|---|---|---|---|"]
        for row in items:
            unit_text = f"（{row['単位']}）" if row["単位"] else ""
            lines.append(f"| {row['名前']}{unit_text} | {row['年度']} | {_with_range(row, '前')} | "
                         f"{_with_range(row, '後')} | {row['差'] if row['差'] != '' else '—'} | {row['実際']} |")
        lines.append("")
    return "\n".join(lines)


def compare_files(before_path: Path, after_path: Path, *, csv_dir: Path | None = None, only=None) -> str:
    before, actual, first = load_result(before_path)
    after, actual_after, second = load_result(after_path)
    rows = compare_rows(before, after, actual_after or actual)
    if csv_dir is not None:
        write_csv(csv_dir / "compare.csv", COMPARE_COLUMNS, rows)
    return compare_markdown(rows, (first, second), only)


def competition_lookup(repo):
    """大会ID → competitions.csv の行（年度の付いたIDは元の大会）。"""
    cache = {}

    def competition_of(cid: str) -> dict:
        if cid not in cache:
            cache[cid] = repo.competitions.get(cid) or next(
                (row for key, row in repo.competitions.items() if cid.startswith(key)), {})
        return cache[cid]
    return competition_of


# ---- 試合ごとの一覧 ----


def match_columns() -> list[str]:
    columns = ["種", "年度", "日付", "大会ID", "大会", "大会の種類", "段階", "回戦", "試合ID", "先攻"]
    for side in ("1", "2"):
        columns += [f"学校{side}", f"学校{side}の評判ランク", f"学校{side}の連合", f"得点{side}"]
    columns += ["勝者", "終わった回", "コールド", "延長"]
    for side in ("1", "2"):
        columns += [f"学校{side}_{n}回" for n in range(1, 10)] + [f"学校{side}_延長"]
        columns += [f"安打{side}", f"失策{side}", f"先発{side}の球数", f"先発{side}の降板の回", f"投手の数{side}"]
    return columns


def called_label(detail: dict, thresholds) -> str:
    """コールドの種類（「5回10点」など）。9回より前に終わった試合だけ。"""
    last = int(detail["last_inning"])
    if last >= 9:
        return ""
    found = [(inning, margin) for inning, margin in thresholds if inning <= last]
    if not found:
        return "コールド"
    inning, margin = max(found)
    return f"{inning}回{margin}点"


def round_name(match_id: str, total_rounds: int | None) -> tuple[str, str]:
    """(段階, 回戦)。本大会は「決勝・準決勝・準々決勝・〇回戦」、本大会の前の段階は「予選」。"""
    from .screen.school_views import round_label
    from .tournament_runtime import THIRD_PLACE_SUFFIX

    if str(match_id).endswith(THIRD_PLACE_SUFFIX):
        return "本大会", "3位決定戦"
    found = ROUND_RE.search(str(match_id))
    if found is None:
        return "予選", ""
    round_no = int(found.group(1))
    return "本大会", round_label(round_no, total_rounds) if total_rounds else f"{round_no}回戦"


def _pitching(detail: dict, school_id: str) -> tuple:
    """(先発の球数, 先発の降板の回（完投なら空）, 使った投手の数)。"""
    pitchers = [p for p in detail.get("pitcher_stats") or () if p["school_id"] == school_id
                and (int(p.get("batters_faced", 0)) > 0 or int(p.get("pitches", 0)) > 0)]
    part = next((p for p in detail.get("team_participation") or () if p["school_id"] == school_id), {})
    starter = part.get("starting_pitcher_id")
    pitches = next((int(p.get("pitches", 0)) for p in pitchers if p["player_id"] == starter), "")
    exit_inning = ""
    for change in part.get("changes") or ():
        # 先発が初めて投手（守備位置 P）を外れた交代。DHありの継投は dh_transition に入る
        leaves = any(c.get("defensive_position") == "P" and c.get("before_player_id") == starter
                     for c in change.get("defensive_changes") or ())
        if leaves or (change.get("kind") == "pitcher_change" and not change.get("defensive_changes")):
            exit_inning = (change.get("moment") or {}).get("inning", "")
            break
    return pitches, exit_inning, len(pitchers)


def match_row(seed, detail: dict, *, year: int, played_on, competition_name: str, kind: str,
              total_rounds: int | None, ranks: dict, partners=lambda school_id: (), thresholds=()) -> dict:
    """1試合の行。``partners(学校ID)`` は連合の構成校（代表校のとき）。"""
    t1, t2 = detail["team1_school_id"], detail["team2_school_id"]
    stage, round_text = round_name(detail.get("match_id", ""), total_rounds)
    innings = detail.get("inning_scores") or ()
    first = next((i["batting_team_id"] for i in innings if int(i["inning"]) == 1 and i.get("half") == "top"), "")
    last = int(detail["last_inning"])
    row = {
        "種": seed, "年度": year, "日付": str(played_on), "大会ID": detail.get("competition_id", ""),
        "大会": competition_name, "大会の種類": kind, "段階": stage, "回戦": round_text,
        "試合ID": detail.get("match_id", ""), "先攻": "学校1" if first == t1 else "学校2" if first == t2 else "",
        "勝者": "学校1" if detail.get("winner_id") == t1 else "学校2" if detail.get("winner_id") == t2 else "",
        "終わった回": last, "コールド": called_label(detail, thresholds), "延長": int(last > 9),
    }
    team_stats = {t["school_id"]: t for t in detail.get("team_stats") or ()}
    for side, school in (("1", t1), ("2", t2)):
        union = tuple(partners(school))
        row.update({f"学校{side}": school, f"学校{side}の評判ランク": ranks.get(school, ""),
                    f"学校{side}の連合": "／".join(union) if union else "",
                    f"得点{side}": int(detail[f"team{side}_score"])})
        mine = [i for i in innings if i["batting_team_id"] == school]
        for n in range(1, 10):
            half = next((i for i in mine if int(i["inning"]) == n), None)
            row[f"学校{side}_{n}回"] = ("" if half is None else int(half["runs"]) if half.get("was_played", True)
                                       else "x")
        extra = [int(i["runs"]) for i in mine if int(i["inning"]) > 9 and i.get("was_played", True)]
        row[f"学校{side}_延長"] = sum(extra) if last > 9 else ""
        stats = team_stats.get(school, {})
        pitches, exit_inning, count = _pitching(detail, school)
        row.update({f"安打{side}": stats.get("hits", ""), f"失策{side}": stats.get("errors", ""),
                    f"先発{side}の球数": pitches, f"先発{side}の降板の回": exit_inning, f"投手の数{side}": count})
    return row


class MatchWriter:
    """試合ごとの一覧を1つの種の CSV に書いていく（全部を覚えておかない）。"""

    def __init__(self, path: Path, seed, *, kinds=None, years=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.seed = seed
        self.kinds = set(kinds) if kinds else None
        self.years = set(years) if years else None
        self.handle = path.open("w", encoding=ENCODING, newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=match_columns(), extrasaction="ignore")
        self.writer.writeheader()
        self.count = 0

    def wants(self, year: int, kind: str) -> bool:
        return (self.kinds is None or kind in self.kinds) and (self.years is None or year in self.years)

    def add(self, detail: dict, **kwargs) -> None:
        self.writer.writerow(match_row(self.seed, detail, **kwargs))
        self.count += 1

    def close(self) -> None:
        self.handle.close()


# ---- 学校×年度の一覧 ----


def school_columns() -> list[str]:
    columns = ["種", "年度", "時点", "学校ID", "学校", "都道府県コード", "都道府県", "夏の地方大会の区分",
               "設置者", "公立・私立", "評判z", "評判のランク"]
    columns += [f"強さ_{name}" for name in STRENGTH_FIELDS]
    columns += ["部員", "1年", "2年", "3年", "1年のA以上", "2年のA以上", "3年のA以上",
                "エースの学年", "エースの球速", *(f"エースの{name}" for name in MAIN_PITCHER),
                "監督ID", "監督の在任年数", "監督の年齢", "監督の評判", "監督の育成力",
                *(f"監督の{name}" for name in COACH_TENDENCIES), "前の監督", "今の監督の着任"]
    for _, name in COMPETITION_COLUMNS:
        columns.append(name)
    for _, name in KOSHIEN_COLUMNS:
        columns += [f"{name}の勝", f"{name}の負"]
    columns += ["夏の連合", "秋の連合"]
    return columns


class SchoolYearTable:
    """学校×年度の行。試合から大会の到達点を集め、7月1日の名簿・監督・評判と合わせる。"""

    def __init__(self, seed, competition_of):
        """``competition_of(大会ID)`` は大会の情報（competitions.csv の行。年度の付いたIDは元の大会）。"""
        self.seed = seed
        self.competition_of = competition_of
        self.matches = defaultdict(list)          # 年度 → 試合（画面の成績と同じ形）
        self.total_rounds = {}                    # 大会ID → 本大会の回戦の数
        self.unions = defaultdict(dict)           # (年度, 大会の種類) → 学校 → 連合の表示
        self.areas = defaultdict(dict)            # 年度 → 学校 → 夏の地方大会の区分
        self.attributes = {}                      # 年度 → 学校 → 7月1日の値

    def add_match(self, year: int, detail: dict, played_on, total_rounds: int | None,
                  partners=lambda school_id: ()) -> None:
        cid = detail["competition_id"]
        competition = self.competition_of(cid)
        kind = competition.get("competition_type", "")
        if total_rounds:
            self.total_rounds[cid] = total_rounds
        self.matches[year].append({
            "competition_id": cid, "match_id": detail["match_id"], "match_date": str(played_on),
            "team1_id": detail["team1_school_id"], "team2_id": detail["team2_school_id"],
            "team1_score": int(detail["team1_score"]), "team2_score": int(detail["team2_score"]),
            "winner_id": detail.get("winner_id"),
        })
        found = SUMMER_AREA_RE.search(competition.get("competition_name", ""))
        for school in (detail["team1_school_id"], detail["team2_school_id"]):
            union = tuple(partners(school))
            if kind == "summer_local_qualifier" and found:
                for member in (school, *union):
                    self.areas[year][member] = found.group(1)
            if union and kind in ("summer_local_qualifier", "autumn_prefectural"):
                self.unions[(year, kind)][school] = "代表"
                for member in union:
                    self.unions[(year, kind)][member] = f"構成（代表 {school}）"

    def set_attributes(self, year: int, attributes: dict[str, dict]) -> None:
        self.attributes[year] = attributes

    def results(self, year: int, unfinished=()) -> dict[str, dict[str, dict]]:
        """学校 → 大会の種類 → 画面の成績（到達・勝敗）。同じ種類が2つあれば到達の深い方。
        ``unfinished`` は終わっていない大会のID（勝ち残りの学校は画面と同じく「〇〇進出（勝ち残り）」）。"""
        from .screen.school_views import normalized_rows, year_results

        rows = normalized_rows(self.matches.get(year, []))
        competitions = {row["competition_id"]: self.competition_of(row["competition_id"]) for row in rows}
        by_school = year_results(rows, competitions, self.total_rounds, lambda cid, name: name,
                                 unfinished=set(unfinished))
        out = {}
        for school, results in by_school.items():
            best = {}
            for result in results:
                if result["type"] not in best or result["score"] > best[result["type"]]["score"]:
                    best[result["type"]] = result
            out[school] = best
        return out

    def rows(self, year: int, school_ids, unfinished=()) -> list[dict]:
        """その年度の学校ごとの行（``school_ids`` の学校を全部、この順に）。"""
        results = self.results(year, unfinished)
        attributes = self.attributes.get(year, {})
        rows = []
        for school in school_ids:
            row = {"種": self.seed, "年度": year, "学校ID": school, **attributes.get(school, {})}
            if not row.get("夏の地方大会の区分"):
                row["夏の地方大会の区分"] = self.areas[year].get(school) or row.get("都道府県", "")
            mine = results.get(school, {})
            for kind, name in COMPETITION_COLUMNS:
                row[name] = mine[kind]["finish"] if kind in mine else ""
            for kind, name in KOSHIEN_COLUMNS:
                row[f"{name}の勝"] = mine[kind]["wins"] if kind in mine else ""
                row[f"{name}の負"] = mine[kind]["losses"] if kind in mine else ""
            row["夏の連合"] = self.unions[(year, "summer_local_qualifier")].get(school, "")
            row["秋の連合"] = self.unions[(year, "autumn_prefectural")].get(school, "")
            rows.append(row)
        return rows

    def forget(self, year: int) -> None:
        self.matches.pop(year, None)
        self.attributes.pop(year, None)
        self.areas.pop(year, None)
        for key in [k for k in self.unions if k[0] == year]:
            del self.unions[key]


def prefecture_names(root: Path = ROOT) -> dict[str, str]:
    with (root / "data" / "master" / "prefectures.csv").open(encoding="utf-8-sig", newline="") as handle:
        return {row["prefecture_code"]: row["prefecture_name"] for row in csv.DictReader(handle)}


def school_attributes(state, repo, *, year: int, today: date, ranks: dict, abilities, seed: int,
                      public_types, prefectures: dict[str, str]) -> dict[str, dict]:
    """学校 → その日の名簿・能力・学校の強さ・監督・評判（学校×年度の一覧の列）。

    名簿は年度の全部員（夏の大会で引退した3年生も入れる）。学校の強さは画面と同じ計算（``SchoolAbilities``）。"""
    from game_core.roster_book import SCALARS

    book = state.rosters
    reputation = getattr(state, "reputation", None)
    coaches = getattr(state, "coaches", None)
    changes = defaultdict(dict)
    for event in getattr(coaches, "events", ()) if coaches is not None else ():
        if event.date == f"{year}-04-01":
            if event.kind in ("retirement", "transfer") and event.from_school_id:
                changes[event.from_school_id]["前の監督"] = "勇退" if event.kind == "retirement" else "異動"
            if event.kind in ("transfer", "appointment") and event.to_school_id:
                changes[event.to_school_id]["今の監督の着任"] = "異動" if event.kind == "transfer" else "新任"
    out = {}
    for school in book.school_ids:      # その年度の全校（名簿がまだなければここでつくる）
        team = repo.team(school)
        ownership = repo.ownership_type(school)
        players = book.roster(year, school).players
        row = {
            "時点": str(today), "学校": team.display_name, "都道府県コード": team.prefecture_code,
            "都道府県": prefectures.get(team.prefecture_code, ""), "設置者": ownership,
            "公立・私立": "公立" if ownership in public_types else "私立" if ownership == "private" else "",
            "評判z": round(reputation.values[school], 3) if reputation is not None and school in reputation.values else "",
            "評判のランク": ranks.get(school, ""),
            "部員": len(players),
        }
        for grade in (1, 2, 3):
            mine = [p for p in players if p.academic_year == grade]
            row[f"{grade}年"] = len(mine)
            high = 0
            for player in mine:
                values = book.state(player).values
                names = MAIN_PITCHER if player.primary_position == "P" else MAIN_BATTER
                high += any((values[SCALARS.index(name)] or 0) >= 80 for name in names)
            row[f"{grade}年のA以上"] = high
        made = abilities.team(players, year, seed) if abilities is not None else None
        if made is not None:
            strength, snapshots = made
            values = abilities.values(strength)
            row.update({f"強さ_{name}": values.get(name, "") for name in STRENGTH_FIELDS})
            ace = next((s for s in snapshots if s.player_id == strength.pitching_staff.ace_player_id), None)
            if ace is not None:
                row.update({"エースの学年": ace.academic_year, "エースの球速": ace.velocity_kmh or "",
                            **{f"エースの{name}": getattr(ace, name) or "" for name in MAIN_PITCHER}})
        coach = coaches.for_school(school, on=today) if coaches is not None else None
        if coach is not None:
            view = coach.view(today)
            row.update({"監督ID": coach.coach_id, "監督の在任年数": view["tenure_years"], "監督の年齢": view["age"],
                        "監督の評判": coach.reputation, "監督の育成力": coach.development,
                        **{f"監督の{name}": getattr(coach, name) for name in COACH_TENDENCIES}})
        row.update(changes.get(school, {}))
        out[school] = row
    return out


class SchoolYearWriter:
    """学校×年度の一覧を1つの種の CSV に書いていく（年度が終わるごとに書いて、その年度の集計を手放す）。"""

    def __init__(self, path: Path, seed, competition_of):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.table = SchoolYearTable(seed, competition_of)
        self.handle = path.open("w", encoding=ENCODING, newline="")
        self.writer = csv.DictWriter(self.handle, fieldnames=school_columns(), extrasaction="ignore")
        self.writer.writeheader()
        self.count = 0
        self.written = set()

    def write_year(self, year: int, school_ids, unfinished=()) -> None:
        if year in self.written:
            return
        rows = self.table.rows(year, school_ids, unfinished)
        self.writer.writerows(rows)
        self.count += len(rows)
        self.written.add(year)
        self.table.forget(year)

    def close(self) -> None:
        self.handle.close()
