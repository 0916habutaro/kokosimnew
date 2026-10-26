"""夏の地方大会（全国高校野球選手権の49大会）のゲーム開始前の実際の試合（2021〜2025年）。

- ``historical_data/summer_local_games.csv``：1行＝1試合（先攻・後攻の校名と学校ID、得点、回戦、出典）。
  学校IDは都道府県と校名で学校マスターに照合し、連合チームと照合できない校名は空欄
- ``historical_data/summer_local_team_aliases.csv``：校名の表記（略称・改称前の校名など）→ 今の学校。
  学校の短い表示名・正式名と同じ表記のものは載せない
- ``historical_data/summer_local_union_members.csv``：連合チーム（校名を「・」でつないだもの）の構成校。
  構成校ごとに照合し、照合できない校名は学校IDが空欄。「〇〇連合」のように分けられない名前は載せない

初期の勢力図（学校の評判、``game_core/school_reputation.py``）が、県の中の強さと毎年の勝ち上がりを
数えるのに使う。ゲームの記録とは混ぜない。検証：``python -m historical_results.summer_local``
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .koshien import DATA_DIR, ROOT, Issue, read_rows

GAMES_FILE = "summer_local_games.csv"
ALIASES_FILE = "summer_local_team_aliases.csv"
GAME_COLUMNS = (
    "year", "prefecture_code", "tournament", "round_label", "game_date",
    "top_team", "top_school_id", "bottom_team", "bottom_school_id",
    "top_score", "bottom_score", "winner", "result_type", "innings",
    "called", "tiebreak", "source_id", "source_url",
)
ALIAS_COLUMNS = ("prefecture_code", "team_name", "school_id", "notes")
UNION_FILE = "summer_local_union_members.csv"
UNION_COLUMNS = ("prefecture_code", "team_name", "member_name", "school_id")
# decided 勝敗決定、walkover 不戦勝、forfeit 没収試合、draw 引き分け（再試合は別の行）
RESULT_TYPES = frozenset({"decided", "walkover", "forfeit", "draw"})
YES_NO = frozenset({"yes", "no", ""})
FIRST_YEAR, LAST_YEAR = 2021, 2025
# 日本高野連が公表した参加チーム数（抽選時。https://www.jhbf.or.jp/topics/detail/593）。
# 勝敗の決まった試合（引き分けを除く）は、参加チーム数から49代表を引いた数になる
PARTICIPANTS = {2021: 3603, 2022: 3547, 2023: 3486, 2024: 3441, 2025: 3396}
REPRESENTATIVES = 49


def read_games(data_dir: Path = DATA_DIR) -> list[dict[str, str]]:
    path = data_dir / GAMES_FILE
    if not path.is_file():
        return []
    return read_rows(path)[1]


def read_union_members(data_dir: Path = DATA_DIR) -> list[dict[str, str]]:
    path = data_dir / UNION_FILE
    if not path.is_file():
        return []
    return read_rows(path)[1]


def winner_loser(game: dict[str, str]) -> tuple[str, str] | None:
    """勝った校名と負けた校名。引き分けは None。"""
    if game["result_type"] == "draw":
        return None
    if game["winner"] == "top":
        return game["top_team"], game["bottom_team"]
    return game["bottom_team"], game["top_team"]


def finishes(games: list[dict[str, str]]) -> dict[tuple[str, str], int]:
    """（大会, 校名）→ 勝ち上がり（1＝優勝、2＝準優勝、4＝ベスト4、8＝ベスト8 …）。

    大会の規模や回戦の呼び方によらず、決勝から数えて何試合前に負けたかで決める。
    決勝を0とし、ある試合に出た2校それぞれの1つ前の試合（勝った試合）を1つ深くする。
    k の試合で負けた学校は ``2 ** (k + 1)``。"""
    by_tournament: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for order, game in enumerate(games):
        if game["result_type"] != "draw":
            by_tournament[game["tournament"]].append((order, game))
    out: dict[tuple[str, str], int] = {}
    for tournament, rows in by_tournament.items():
        rows.sort(key=lambda item: (item[1]["game_date"], item[0]))
        played: dict[str, list[int]] = defaultdict(list)
        losers: set[str] = set()
        for index, (_, game) in enumerate(rows):
            winner, loser = winner_loser(game)
            played[winner].append(index)
            played[loser].append(index)
            losers.add(loser)
        unbeaten = [team for team in played if team not in losers]
        if len(unbeaten) != 1:
            continue
        champion = unbeaten[0]
        final = played[champion][-1]
        depth = {final: 0}
        stack = [final]
        while stack:
            index = stack.pop()
            for team in winner_loser(rows[index][1]):
                earlier = [i for i in played[team] if i < index]
                if earlier and earlier[-1] not in depth:
                    depth[earlier[-1]] = depth[index] + 1
                    stack.append(earlier[-1])
        out[(tournament, champion)] = 1
        for index, (_, game) in enumerate(rows):
            if index in depth:
                out[(tournament, winner_loser(game)[1])] = 2 ** (depth[index] + 1)
    return out


def validate(
    data_dir: Path = DATA_DIR,
    school_master: Path = ROOT / "data/master/schools.csv",
) -> list[Issue]:
    issues: list[Issue] = []
    if not (data_dir / GAMES_FILE).is_file():
        return issues

    def error(table: str, line: int, code: str, detail: str) -> None:
        issues.append(Issue(table, line, code, detail))

    _, schools = read_rows(school_master)
    prefecture = {row["school_id"]: row["prefecture_code"] for row in schools}
    _, sources = read_rows(data_dir / "sources.csv")
    source_ids = {row["source_id"] for row in sources}
    columns, games = read_rows(data_dir / GAMES_FILE)
    if tuple(columns) != GAME_COLUMNS:
        return [Issue("summer_local", 1, "SCHEMA", repr(columns))]
    named: dict[tuple[str, str], set[str]] = defaultdict(set)
    decided: dict[int, int] = defaultdict(int)
    for line, game in enumerate(games, 2):
        year = int(game["year"]) if game["year"].isdigit() else 0
        if not FIRST_YEAR <= year <= LAST_YEAR:
            # ゲーム開始（2026年4月）より後の大会は入れない
            error("summer_local", line, "YEAR", game["year"])
        if not game["tournament"].startswith(f"{year}年") or game["game_date"][:4] != str(year):
            error("summer_local", line, "TOURNAMENT_YEAR", game["tournament"])
        if game["source_id"] not in source_ids:
            error("summer_local", line, "UNKNOWN_SOURCE", game["source_id"])
        kind = game["result_type"]
        if kind not in RESULT_TYPES or game["called"] not in YES_NO or game["tiebreak"] not in YES_NO:
            error("summer_local", line, "VALUE", f"{kind}/{game['called']}/{game['tiebreak']}")
            continue
        if (kind == "draw") != (game["winner"] == "") or game["winner"] not in ("top", "bottom", ""):
            error("summer_local", line, "WINNER", game["winner"])
            continue
        if kind != "draw":
            decided[year] += 1
        if kind in ("decided", "draw"):
            try:
                top, bottom = int(game["top_score"]), int(game["bottom_score"])
            except ValueError:
                error("summer_local", line, "SCORE", f"{game['top_score']}-{game['bottom_score']}")
                continue
            if (kind == "draw" and top != bottom) or (
                kind == "decided" and (top > bottom) != (game["winner"] == "top")
            ) or (kind == "decided" and top == bottom):
                error("summer_local", line, "SCORE", f"{top}-{bottom} {game['winner']}")
        for side in ("top", "bottom"):
            school_id = game[f"{side}_school_id"]
            if not school_id:
                continue
            if prefecture.get(school_id) != game["prefecture_code"]:
                error("summer_local", line, "PREFECTURE", school_id)
            named[(game["prefecture_code"], game[f"{side}_team"])].add(school_id)
    for (code, team), ids in sorted(named.items()):
        if len(ids) > 1:
            error("summer_local", 0, "AMBIGUOUS_NAME", f"{code}/{team} {sorted(ids)}")
    for year, count in sorted(PARTICIPANTS.items()):
        if decided.get(year, 0) != count - REPRESENTATIVES:
            error("summer_local", 0, "GAME_COUNT", f"{year}: {decided.get(year, 0)} != {count - REPRESENTATIVES}")
    issues.extend(_validate_brackets(games))
    union_teams = {
        (game["prefecture_code"], game[f"{side}_team"])
        for game in games for side in ("top", "bottom") if not game[f"{side}_school_id"]
    }
    if (data_dir / UNION_FILE).is_file():
        columns, members = read_rows(data_dir / UNION_FILE)
        if tuple(columns) != UNION_COLUMNS:
            error("summer_local_unions", 1, "SCHEMA", repr(columns))
            members = []
        for line, row in enumerate(members, 2):
            if (row["prefecture_code"], row["team_name"]) not in union_teams:
                error("summer_local_unions", line, "UNKNOWN_TEAM", row["team_name"])
            if row["member_name"] not in row["team_name"].split("・"):
                error("summer_local_unions", line, "MEMBER", row["member_name"])
            if row["school_id"]:
                if prefecture.get(row["school_id"]) != row["prefecture_code"]:
                    error("summer_local_unions", line, "PREFECTURE", row["school_id"])
                key = (row["prefecture_code"], row["member_name"])
                if named.get(key, {row["school_id"]}) != {row["school_id"]}:
                    error("summer_local_unions", line, "AMBIGUOUS_NAME", row["member_name"])
                named[key].add(row["school_id"])
    columns, aliases = read_rows(data_dir / ALIASES_FILE)
    if tuple(columns) != ALIAS_COLUMNS:
        error("summer_local_aliases", 1, "SCHEMA", repr(columns))
        return issues
    for line, row in enumerate(aliases, 2):
        if prefecture.get(row["school_id"]) != row["prefecture_code"]:
            error("summer_local_aliases", line, "PREFECTURE", row["school_id"])
        if named.get((row["prefecture_code"], row["team_name"])) != {row["school_id"]}:
            # 対応表の行は、試合の行の照合と同じでなければならない
            error("summer_local_aliases", line, "NOT_USED", f"{row['team_name']}/{row['school_id']}")
    return issues


def _validate_brackets(games: list[dict[str, str]]) -> list[Issue]:
    """大会ごとに、負けは1校1回まで、負けなかった学校は1校、全試合の勝ち上がりが決まる。"""
    issues: list[Issue] = []
    losses: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    teams: dict[str, set[str]] = defaultdict(set)
    for game in games:
        result = winner_loser(game)
        if result is None:
            continue
        losses[game["tournament"]][result[1]] += 1
        teams[game["tournament"]].update(result)
    reached = finishes(games)
    for tournament in sorted(teams):
        twice = sorted(team for team, n in losses[tournament].items() if n > 1)
        if twice:
            issues.append(Issue("summer_local", 0, "LOST_TWICE", f"{tournament} {twice}"))
        unbeaten = teams[tournament] - set(losses[tournament])
        if len(unbeaten) != 1:
            issues.append(Issue("summer_local", 0, "CHAMPION", f"{tournament} {sorted(unbeaten)}"))
            continue
        missing = sorted(team for team in teams[tournament] if (tournament, team) not in reached)
        if missing:
            issues.append(Issue("summer_local", 0, "BRACKET", f"{tournament} {missing[:5]}"))
    return issues


def main() -> int:
    issues = validate()
    for issue in issues:
        print(issue)
    print("OK" if not issues else f"INVALID: {len(issues)} issue(s)")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
