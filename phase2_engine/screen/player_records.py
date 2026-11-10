"""記録の画面の「個人の記録」：部門ごとの上位と達成の記録（game_definition.md §9）。

どれも保存済みの試合の記録（``batter_stats``・``pitcher_stats``・``team_stats``・
``highlights``）から求める。保存形式は変えない。

試合の記録を1つずつ ``PlayerTally`` に足し、年度（大会の年度。記録の画面のほかのタブと
同じ）・大会・学校・選手ごとの合計を持つ。閉じた年度の集計は年度を閉じるときに一度だけ作って
試合の履歴に残し（``to_blob``）、画面はそれを読む。進行中の年度は、まだ足していない
試合だけを足していく。

- 勝利は ``match_summary.pitchers_of_record``（公認野球規則 9.17 の考え方）。決められない
  試合は勝利を付けない（``undecided`` に数える）
- ノーヒットノーラン：1人で投げ切り（そのチームの投手が1人）、被安打0・失点0
- 完全試合：ノーヒットノーランのうえ、四球・死球・味方の失策がなく、
  対戦した打者の数とアウトの数が同じ（走者を1人も出していない）
- サイクル安打：1試合で単打・二塁打・三塁打・本塁打をそれぞれ1本以上
- 1試合の最多奪三振：年度・大会ごとに、1人の投手が1試合で奪った三振のいちばん多い記録
- 1大会の最多本塁打：年度・大会ごとに、1人の打者がその大会で打った本塁打のいちばん多い記録

継投でのノーヒットノーランは、投手ごとの記録では「1人の投手の記録」にならないので出さない。
"""
from __future__ import annotations

from datetime import date
import heapq
import json
import zlib

from .match_summary import pitchers_of_record

TALLY_VERSION = 1
# 合計する打撃・投手の項目（並びは保存する集計の列の順）
BATTING = ("games", "plate_appearances", "at_bats", "hits", "home_runs", "rbi", "stolen_bases")
PITCHING = ("games", "outs_recorded", "earned_runs", "strikeouts", "wins")

NO_HITTER = "no_hitter"
PERFECT = "perfect"
CYCLE = "cycle"
FEAT_LABELS = {NO_HITTER: "ノーヒットノーラン", PERFECT: "完全試合", CYCLE: "サイクル安打"}

# 部門：(キー, 名前, 打撃か投手か, 規定が要るか, 小さいほど上か)
CATEGORIES = (
    ("average", "打率", "batting", True, False),
    ("home_runs", "本塁打", "batting", False, False),
    ("rbi", "打点", "batting", False, False),
    ("hits", "安打", "batting", False, False),
    ("stolen_bases", "盗塁", "batting", False, False),
    ("era", "防御率", "pitching", True, True),
    ("strikeouts", "奪三振", "pitching", False, False),
    ("wins", "勝利", "pitching", False, False),
)


def _school_year(day: str) -> int:
    d = date.fromisoformat(day)
    return d.year if d.month >= 4 else d.year - 1


def _teams(detail: dict) -> tuple[str, str]:
    return (
        detail.get("team1_school_id") or detail.get("team1_id"),
        detail.get("team2_school_id") or detail.get("team2_id"),
    )


def _key(*parts) -> str:
    return "|".join(str(p) for p in parts)


class PlayerTally:
    """年度・大会・学校・選手ごとの合計と、達成の記録。JSON にできる形で持つ。"""

    def __init__(self, data: dict | None = None, *, year: int = 0):
        data = data or {}
        # 試合の履歴の年度（大会の年度。試合の画面を開くのに使う）
        self.year: int = data.get("year", year)
        # "年度|大会|学校|選手" → BATTING / PITCHING の並び
        self.batters: dict[str, list[int]] = data.get("batters", {})
        self.pitchers: dict[str, list[int]] = data.get("pitchers", {})
        # "年度|大会|学校" → チームの試合数（規定の基準）
        self.teams: dict[str, int] = data.get("teams", {})
        # 達成の記録（ノーヒットノーラン・完全試合・サイクル安打）
        self.feats: list[dict] = data.get("feats", [])
        # "年度|大会" → [奪三振, [{school_id, player_id, ...}, ...]]（1試合の最多奪三振）
        self.top_strikeouts: dict[str, list] = data.get("top_strikeouts", {})
        # "年度|選手" → 学年（その年度の名簿から。分からなければ入れない）
        self.grades: dict[str, int] = data.get("grades", {})
        # 勝利投手・敗戦投手を決められなかった試合の数
        self.undecided: int = data.get("undecided", 0)
        # 足した試合（"大会|試合"）。進行中の年度で、まだ足していない試合だけを足すため
        self.seen: set[str] = set(data.get("seen", ()))
        self._parsed = None

    def parsed(self) -> dict:
        """キーを分けた行（絞り込みのたびに分けないよう、足すまでとっておく）。"""
        if self._parsed is None:
            def split(source):
                return [(*_parse(key), values) for key, values in source.items()]

            self._parsed = {
                "batters": split(self.batters), "pitchers": split(self.pitchers),
                "teams": [(int(y), c, sc, games) for (y, c, sc), games in
                          ((key.split("|"), games) for key, games in self.teams.items())],
            }
        return self._parsed

    def to_dict(self) -> dict:
        return {
            "version": TALLY_VERSION, "year": self.year, "grades": self.grades, "batters": self.batters, "pitchers": self.pitchers,
            "teams": self.teams, "feats": self.feats, "top_strikeouts": self.top_strikeouts,
            "undecided": self.undecided, "seen": sorted(self.seen),
        }

    def to_blob(self) -> bytes:
        data = self.to_dict()
        data.pop("seen")  # 閉じた年度は足し直さない
        return zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)

    @classmethod
    def from_blob(cls, blob: bytes) -> "PlayerTally":
        data = json.loads(zlib.decompress(blob))
        if data.get("version") != TALLY_VERSION:
            raise ValueError("個人の記録の集計の形が違います")
        return cls(data)

    def add(self, competition_id: str, match_id: str, detail: dict, member_of=None) -> bool:
        """試合の記録を1つ足す。足したら True（同じ試合は2回足さない）。

        ``member_of(名簿の年度, 記録の学校ID, 選手ID, 大会ID)`` は（選手の学校ID, 学年）か None。
        連合チームの試合の記録は代表校のIDで残るので、構成校の選手は自分の学校に数え直す。"""
        seen = _key(competition_id, match_id)
        if seen in self.seen or not detail or not detail.get("match_date"):
            return False
        self.seen.add(seen)
        self._parsed = None
        day = detail["match_date"]
        # 年度は大会の年度（記録の画面のほかのタブと同じ。翌年3月の選抜はその年度、
        # 3月に始まる春季大会は次の年度）
        year = self.year
        roster_year = _school_year(day)
        base = _key(year, competition_id)
        batters = detail.get("batter_stats") or ()
        pitchers = detail.get("pitcher_stats") or ()
        team1, team2 = _teams(detail)
        own: dict[tuple, str] = {}

        def school_of(row) -> str:
            """選手の学校（記録の学校＝試合に出たチームの学校とは、連合のとき違う）。"""
            ident = (row["school_id"], row["player_id"])
            if ident not in own:
                found = member_of(roster_year, *ident, competition_id) if member_of is not None else None
                own[ident] = found[0] if found else row["school_id"]
                key = _key(year, row["player_id"])
                if found and found[1] and key not in self.grades:
                    # 3月の試合はその前の年度の名簿なので、4月からの学年にそろえる
                    self.grades[key] = found[1] + (year - roster_year)
            return own[ident]

        # チームの試合数（規定の基準）：選手が出た学校ごとに1試合
        for school in {school_of(r) for r in (*batters, *pitchers)}:
            key = _key(base, school)
            self.teams[key] = self.teams.get(key, 0) + 1
        for row in batters:
            key = _key(base, school_of(row), row["player_id"])
            values = self.batters.setdefault(key, [0] * len(BATTING))
            values[0] += 1
            for i, name in enumerate(BATTING[1:], start=1):
                values[i] += int(row.get(name) or 0)
            singles = (int(row.get("hits") or 0) - int(row.get("doubles") or 0)
                       - int(row.get("triples") or 0) - int(row.get("home_runs") or 0))
            if singles > 0 and all(int(row.get(k) or 0) > 0 for k in ("doubles", "triples", "home_runs")):
                self.feats.append(self._feat(CYCLE, competition_id, match_id, day, row, school_of(row),
                                             team1, team2, int(row.get("hits") or 0)))
        decision = pitchers_of_record(detail)
        if decision is None and detail.get("winner_id"):
            self.undecided += 1
        win = decision["win"] if decision else None
        by_team: dict[str, list[dict]] = {}
        for row in pitchers:
            if int(row.get("batters_faced") or 0) > 0 or int(row.get("outs_recorded") or 0) > 0:
                by_team.setdefault(row["school_id"], []).append(row)
            key = _key(base, school_of(row), row["player_id"])
            values = self.pitchers.setdefault(key, [0] * len(PITCHING))
            values[0] += 1
            values[1] += int(row.get("outs_recorded") or 0)
            values[2] += int(row.get("earned_runs") or 0)
            values[3] += int(row.get("strikeouts") or 0)
            if win == (row["school_id"], row["player_id"]):
                values[4] += 1
            strikeouts = int(row.get("strikeouts") or 0)
            if strikeouts:
                best = self.top_strikeouts.setdefault(base, [0, []])
                holder = {**self._holder(row, school_of(row), match_id, day, team1, team2),
                          "season_year": self.year}
                if strikeouts > best[0]:
                    self.top_strikeouts[base] = [strikeouts, [holder]]
                elif strikeouts == best[0]:
                    best[1].append(holder)
        errors = {t.get("school_id"): int(t.get("errors") or 0) for t in detail.get("team_stats") or ()}
        for team, rows in by_team.items():
            if len(rows) != 1 or not detail.get("winner_id"):
                continue
            row = rows[0]
            if int(row.get("hits_allowed") or 0) or int(row.get("runs_allowed") or 0):
                continue
            # 味方の失策（チームの記録がなければ、そのチームの選手の失策の合計）
            mistakes = errors[team] if team in errors else sum(
                int(r.get("errors") or 0) for r in (*batters, *pitchers) if r.get("school_id") == team)
            perfect = (
                not int(row.get("walks") or 0) and not int(row.get("hit_batters") or 0) and not mistakes
                and int(row.get("batters_faced") or 0) == int(row.get("outs_recorded") or 0)
            )
            self.feats.append(self._feat(PERFECT if perfect else NO_HITTER, competition_id,
                                         match_id, day, row, school_of(row), team1, team2,
                                         int(row.get("strikeouts") or 0),
                                         outs=int(row.get("outs_recorded") or 0)))
        return True

    @staticmethod
    def _holder(row, school, match_id, day, team1, team2) -> dict:
        team = row["school_id"]
        return {"school_id": school, "player_id": row["player_id"], "match_id": match_id,
                "match_date": day, "opponent_id": team2 if team == team1 else team1}

    def _feat(self, kind, competition_id, match_id, day, row, school, team1, team2, value, outs=None):
        feat = {"kind": kind, "season_year": self.year, "school_year": self.year,
                "competition_id": competition_id,
                **self._holder(row, school, match_id, day, team1, team2), "value": value}
        if outs is not None:
            feat["outs"] = outs
        return feat


# ---- 絞り込みと並べ方（画面に出す前の計算。学校・選手の名前は付けない） ----


def _parse(key: str) -> tuple[int, str, str, str]:
    year, cid, school, player = key.split("|")
    return int(year), cid, school, player


def merge(tallies, *, years=None, competition_id: str = "", school_ok=None, grade=None) -> dict:
    """集計を絞り込んで選手ごとに足す。

    ``years`` は入れる年度の集まり（None ならすべて＝通算）、``competition_id`` が空なら
    すべての公式戦、``school_ok(学校ID)`` が偽の学校は入れない。``grade`` があれば、その学年の
    年度の記録だけを足す（通算なら「3年生のときの記録」の合計）。

    戻り値：``batters``・``pitchers`` は（学校ID, 選手ID）→ 項目 → 合計（``team_games`` は
    その選手の学校の、同じ絞り込みでの試合数。学年で絞ったときは、その選手がその学年だった
    年度のチームの試合数）。``years_of`` は（学校ID, 選手ID）→ 記録のある年度の集まり。"""
    def wanted(year, cid, school):
        return ((years is None or year in years) and (not competition_id or cid == competition_id)
                and (school_ok is None or school_ok(school)))

    teams: dict[tuple, int] = {}  # (学校, 年度) → 試合数
    batters: dict[tuple, dict] = {}
    pitchers: dict[tuple, dict] = {}
    years_of: dict[tuple, set] = {}
    for tally in tallies:
        parsed = tally.parsed()
        for year, cid, school, games in parsed["teams"]:
            if wanted(year, cid, school):
                teams[(school, year)] = teams.get((school, year), 0) + games
        for kind, out in (("batters", batters), ("pitchers", pitchers)):
            for year, cid, school, player, values in parsed[kind]:
                if not wanted(year, cid, school):
                    continue
                if grade is not None and tally.grades.get(_key(year, player)) != grade:
                    continue
                ident = (school, player)
                total = out.get(ident)
                if total is None:
                    out[ident] = list(values)
                else:
                    for i, value in enumerate(values):
                        total[i] += value
                years_of.setdefault(ident, set()).add(year)
    named = {}
    for kind, out, names in (("batters", batters, BATTING), ("pitchers", pitchers, PITCHING)):
        named[kind] = {
            ident: {**dict(zip(names, values)),
                    "team_games": sum(teams.get((ident[0], year), 0) for year in years_of[ident])}
            for ident, values in out.items()
        }
    return {**named, "years_of": years_of}


def qualifies(total: dict, kind: str, rule: dict) -> bool:
    """規定：打率は打席がチームの試合数×係数以上、防御率は投球回がチームの試合数×係数以上。"""
    if kind == "batting":
        need = total["team_games"] * float(rule["plate_appearances_per_team_game"])
        return total["plate_appearances"] > 0 and total["plate_appearances"] >= need
    need = total["team_games"] * float(rule["innings_per_team_game"]) * 3
    return total["outs_recorded"] > 0 and total["outs_recorded"] >= need


def category_value(key: str, total: dict):
    """部門の値。値がなければ None。

    打率・防御率は小数で比べる。打数・アウトの数は数千までなので、違う値が同じ小数になる
    ことはなく（差は 1/(分母×分母) 以上）、同じ値は同じ小数になる（同率の判定が正しい）。"""
    if key == "average":
        return total["hits"] / total["at_bats"] if total["at_bats"] else None
    if key == "era":
        return total["earned_runs"] * 27 / total["outs_recorded"] if total["outs_recorded"] else None
    value = total.get(key, 0)
    return value if value > 0 else None


def leaders(rows: dict, key: str, *, lower_first: bool, limit: int, eligible=None) -> list[dict]:
    """部門の上位。同じ値は同じ順位（1 + 自分より上の人数）で、順位が ``limit`` 以内の人を出す。

    同じ順位の人が多くて ``limit`` 人を超えるときは ``limit`` 人で切り、``rest`` に残りの人数を返す
    （最後の行に付ける）。同じ値の中は、打率は打数の多い順、防御率は投球回の多い順、そのほかは
    学校ID・選手IDの順（毎回同じ並び）。``eligible(学校ID, 選手ID, 合計)`` が偽の人は入れない。"""
    items = []
    for ident, total in rows.items():
        if eligible is not None and not eligible(ident, total):
            continue
        value = category_value(key, total)
        if value is None:
            continue
        weight = total["at_bats"] if key == "average" else total.get("outs_recorded", 0) if key == "era" else 0
        items.append(((value if lower_first else -value), -weight, ident, value, total))
    # 全員を並べず、上から limit 人だけを取り出す
    top = heapq.nsmallest(limit, items, key=lambda item: item[:3])
    out = []
    better = 0
    previous = None
    for index, (_, _, ident, value, total) in enumerate(top):
        if value != previous:
            better = index
            previous = value
        out.append({"rank": better + 1, "school_id": ident[0], "player_id": ident[1], "value": value, "total": total})
    if out and len(out) == limit:
        # 最後の順位と同じ値で limit 人を超えた分は数だけ
        last = out[-1]["value"]
        rest = sum(1 for item in items if item[3] == last) - sum(1 for row in out if row["value"] == last)
        if rest:
            out[-1]["rest"] = rest
    return out


def most_home_runs(tallies, *, years=None, competition_id: str = "", school_ok=None) -> list[dict]:
    """年度・大会ごとの「1大会の最多本塁打」（いちばん多く打った打者。同じ数なら全員）。"""
    best: dict[tuple, list] = {}
    for tally in tallies:
        for year, cid, school, player, values in tally.parsed()["batters"]:
            if ((years is not None and year not in years) or (competition_id and cid != competition_id)
                    or (school_ok is not None and not school_ok(school))):
                continue
            home_runs = values[BATTING.index("home_runs")]
            if not home_runs:
                continue
            cell = best.setdefault((year, cid), [0, [], tally.year])
            if home_runs > cell[0]:
                best[(year, cid)] = [home_runs, [(school, player)], tally.year]
            elif home_runs == cell[0]:
                cell[1].append((school, player))
    return [
        {"season_year": season, "school_year": year, "competition_id": cid, "value": value,
         "holders": [{"school_id": s, "player_id": p} for s, p in sorted(holders)]}
        for (year, cid), (value, holders, season) in best.items()
    ]


def most_strikeouts(tallies, *, years=None, competition_id: str = "", school_ok=None) -> list[dict]:
    """年度・大会ごとの「1試合の最多奪三振」。"""
    out = []
    for tally in tallies:
        for key, (value, holders) in tally.top_strikeouts.items():
            year, cid = key.split("|")
            year = int(year)
            if (years is not None and year not in years) or (competition_id and cid != competition_id):
                continue
            kept = [h for h in holders if school_ok is None or school_ok(h["school_id"])]
            if kept:
                out.append({"season_year": tally.year, "school_year": year, "competition_id": cid,
                            "value": value, "holders": kept})
    return out


def feats(tallies, *, years=None, competition_id: str = "", school_ok=None) -> list[dict]:
    """ノーヒットノーラン・完全試合・サイクル安打（日付の新しい順）。"""
    out = [
        feat for tally in tallies for feat in tally.feats
        if (years is None or feat["school_year"] in years)
        and (not competition_id or feat["competition_id"] == competition_id)
        and (school_ok is None or school_ok(feat["school_id"]))
    ]
    out.sort(key=lambda f: (f["match_date"], f["competition_id"], f["match_id"]), reverse=True)
    return out


def feat_detail(feat: dict) -> str:
    """達成の記録の内容（「4安打」「12奪三振」「8奪三振・5回コールド」「延長10回」）。"""
    if feat["kind"] == CYCLE:
        return f"{feat['value']}安打"
    text = f"{feat['value']}奪三振"
    outs = feat.get("outs", 27)
    if outs < 27:
        # 投げ切って27アウトに届かないのはコールド（後攻の勝ちで9回裏がない試合も、守る側は27アウト）
        text += f"・{innings_label(outs)}回コールド"
    elif outs > 27:
        text += f"・延長{-(-outs // 3)}回"
    return text


def average_label(value: float) -> str:
    return f"{value:.3f}".lstrip("0") if value < 1 else f"{value:.3f}"


def era_label(value: float) -> str:
    return f"{value:.2f}"


def innings_label(outs: int) -> str:
    whole, part = divmod(outs, 3)
    return f"{whole}" + (f" {part}/3" if part else "")


class RosterLookup:
    """年度・学校の名簿から選手の名前と学年を引く（学校ごとに1回だけ読む）。

    今の名簿（``RosterBook``）にあればそこから、閉じた年度は ``closed_roster(年度, 学校ID)``
    （試合の履歴の名簿。``Player.to_dict()`` の並び）から。``partners(大会ID, 学校ID)`` は、
    その学校が代表の連合チームの構成校（連合でなければ空）。"""

    def __init__(self, rosters=None, closed_roster=None, partners=None):
        self.rosters = rosters
        self.closed_roster = closed_roster
        self.partners = partners
        self._cache: dict[tuple, dict] = {}
        self._kept: dict[int, set] = {}

    def _in_book(self, year: int, school_id: str) -> bool:
        """今の名簿にあるか（ない年度の名簿を新しくつくらないように確かめる）。"""
        book = self.rosters
        if book is None or year <= book.closed_through:
            return False
        if year == book.first_year - 1:
            return True
        if year not in self._kept:
            self._kept[year] = set(book.schools(year))
        return school_id in self._kept[year]

    def players(self, year: int, school_id: str) -> dict[str, tuple[str, int]]:
        key = (year, school_id)
        if key not in self._cache:
            found = {}
            if self._in_book(year, school_id):
                try:
                    roster = self.rosters.roster(year, school_id)
                except (ValueError, KeyError):
                    roster = None
                if roster is not None:
                    found = {p.player_id: (p.display_name, p.academic_year) for p in roster.players}
            if not found and self.closed_roster is not None:
                found = {
                    row["player_id"]: (row["display_name"], row["academic_year"])
                    for row in self.closed_roster(year, school_id) or ()
                }
            self._cache[key] = found
        return self._cache[key]

    def member(self, year: int, school_id: str, player_id: str, competition_id: str = ""):
        """（選手の学校ID, 学年）。記録の学校の名簿になければ、連合の構成校の名簿から。"""
        found = self.players(year, school_id).get(player_id)
        if found:
            return school_id, found[1]
        for partner in (self.partners(competition_id, school_id) if self.partners else ()):
            found = self.players(year, partner).get(player_id)
            if found:
                return partner, found[1]
        return None

    def name(self, year: int, school_id: str, player_id: str) -> str:
        found = self.players(year, school_id).get(player_id)
        return found[0] if found else ""


def build_tally(year: int, matches, member_of=None) -> PlayerTally:
    """試合の記録の並び（(大会ID, 試合ID, 記録)）から、その年度の集計をつくる。"""
    tally = PlayerTally(year=year)
    for competition_id, match_id, detail in matches:
        tally.add(competition_id, match_id, detail, member_of)
    return tally


def union_partners(season):
    """``RosterLookup`` の ``partners``：その年度の連合チーム（代表校 → 構成校）。"""
    from game_core.joint_teams import union_teams

    cache: dict[str, dict] = {}

    def partners(competition_id: str, school_id: str):
        if season is None or not getattr(season, "union_plans", None):
            return ()
        if competition_id not in cache:
            cache[competition_id] = {team.lead: [s for s in team.schools if s != team.lead]
                                     for team in union_teams(season, competition_id)}
        return cache[competition_id].get(school_id, ())

    return partners
