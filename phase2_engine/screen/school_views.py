"""学校の一覧と詳細に出す能力・成績をまとめる（game_definition.md §9）。

- 能力：今日の部員から学校の能力（打撃・投手・守備・走力）を出し、総合は
  ``config/screen/screen_v1.json`` の重みで合わせる。試合の処理とは別の
  計算部品を使い、部員が変わらない学校は計算し直さない
- 成績：大会ごとの勝敗と到達（優勝・準優勝・ベスト4…）。進行中の年度は
  大会の進行から、閉じた年度は試合の履歴から読む
"""
from __future__ import annotations

from pathlib import Path
import re
import threading


SUMMER_NATIONAL = "national_championship"
SPRING_NATIONAL = "national_invitational"
LEVEL_RANK = {"national": 3, "regional": 2}
ABILITY_FIELDS = (
    "batting_strength", "pitching_strength", "defense_strength",
    "running_strength", "contact_strength", "power_strength",
    "discipline_strength", "ace_strength", "pitching_depth_strength",
    "bullpen_strength",
)
_MAIN_ROUND = re.compile(r"-MAIN-R(\d+)-M\d+$")


# ---- 能力 ----


class SchoolAbilities:
    """学校ID → 能力。部員（選手IDの並び）が同じなら前の結果を使う。"""

    def __init__(self, config_root: str | Path, overall_weights: dict,
                 adjustments: dict | None = None, *, rosters=None):
        from game_core.school_intake import SchoolAwarePlayerAbilityGenerator
        from game_core.team_strength import TeamStrengthGenerator

        ability_dir = Path(config_root) / "abilities"
        self._abilities = SchoolAwarePlayerAbilityGenerator(ability_dir)
        # 学校の編集の補正（試合と同じ dict）。補正を変えたら作り直す
        if adjustments is not None:
            self._abilities.school_adjustments = adjustments
        # セーブに入った名簿（game_core/roster_book.py）。あれば能力をそこから読む
        self._abilities.source = rosters
        self._teams = TeamStrengthGenerator(ability_dir)
        self._weights = dict(overall_weights)
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple, dict]] = {}
        self._player_cache: dict[tuple, object] = {}

    def compute(self, members: dict, year: int, team_seed: int) -> None:
        """``members`` は学校ID → 部員（Player の並び）。"""
        for school_id, players in members.items():
            key = (year, tuple(player.player_id for player in players))
            with self._lock:
                cached = self._cache.get(school_id)
            if cached is not None and cached[0] == key:
                continue
            values = self._school(players, year, team_seed)
            with self._lock:
                self._cache[school_id] = (key, values)

    def _school(self, players, year: int, team_seed: int) -> dict | None:
        snapshots = []
        for player in players:
            pkey = (player.player_id, year)
            snapshot = self._player_cache.get(pkey)
            if snapshot is None:
                snapshot = self._abilities.generate(player, year, team_seed)
                self._player_cache[pkey] = snapshot
            snapshots.append(snapshot)
        if len(snapshots) < 9:
            return None
        team = self._teams.generate(snapshots)
        values = {
            name.replace("_strength", ""): round(getattr(team, name), 1)
            for name in ABILITY_FIELDS
        }
        values["overall"] = round(sum(
            getattr(team, name) * float(weight)
            for name, weight in self._weights.items()
        ), 1)
        return values

    def get(self, members: dict, year: int) -> tuple[dict, bool]:
        """(学校ID → 能力, 全校そろっているか)。部員が変わった学校は出さない。"""
        out = {}
        with self._lock:
            for school_id, players in members.items():
                cached = self._cache.get(school_id)
                key = (year, tuple(player.player_id for player in players))
                if cached is not None and cached[0] == key:
                    out[school_id] = cached[1]
        return out, len(out) == len(members)


# ---- 成績 ----


def normalized_rows(rows) -> list[dict]:
    """試合の要約をそろえる（大会の進行の試合・履歴の試合のどちらからでも）。"""
    out = []
    for row in rows:
        get = row.get if isinstance(row, dict) else (
            lambda key, default=None, _row=row: getattr(_row, key, default)
        )
        if get("status", "completed") != "completed":
            continue
        score1, score2 = get("team1_score"), get("team2_score")
        winner = get("winner_id") or (
            "" if score1 is None or score2 is None or score1 == score2
            else get("team1_id") if score1 > score2 else get("team2_id")
        )
        if not winner:
            continue
        match_id = get("match_id")
        stage = get("stage_code")
        round_no = get("round_no")
        if stage is None:
            found = _MAIN_ROUND.search(match_id)
            stage = "MAIN" if found else ""
            round_no = int(found.group(1)) if found else 0
        out.append({
            "competition_id": get("competition_id"),
            "match_id": match_id,
            "match_date": get("match_date"),
            "team1_id": get("team1_id"),
            "team2_id": get("team2_id"),
            "team1_score": score1,
            "team2_score": score2,
            "winner_id": winner,
            "main": stage == "MAIN",
            "round_no": int(round_no or 0),
        })
    return out


def finish_label(won_last: bool, last_round: int, total_rounds: int) -> tuple[str, int]:
    """MAIN での到達（表示, 並べ替えの深さ）。勝ち残っている学校は到達した回戦。"""
    if last_round >= total_rounds:
        return ("優勝", 100) if won_last else ("準優勝", 50)
    reached = last_round + 1 if won_last else last_round
    best = 2 ** (total_rounds - reached + 1)
    if best == 2:
        return "決勝進出", 40
    if best <= 16:
        return f"ベスト{best}", {4: 25, 8: 12, 16: 6}[best]
    if won_last:
        return f"{reached}回戦進出", 2
    return f"{last_round}回戦敗退", 1


def year_results(rows: list[dict], competitions: dict, total_rounds: dict,
                 short_name) -> dict[str, list[dict]]:
    """学校ID → その年度の大会ごとの成績。"""
    by_school: dict[str, dict[str, dict]] = {}
    max_round: dict[str, int] = {}
    for row in rows:
        if row["main"]:
            cid = row["competition_id"]
            max_round[cid] = max(max_round.get(cid, 0), row["round_no"])
    for row in rows:
        cid = row["competition_id"]
        for side in ("team1_id", "team2_id"):
            school = row[side]
            entry = by_school.setdefault(school, {}).setdefault(cid, {
                "competition_id": cid, "wins": 0, "losses": 0,
                "last_main_round": 0, "won_last_main": False,
                "first_date": row["match_date"],
            })
            won = row["winner_id"] == school
            entry["wins" if won else "losses"] += 1
            if row["main"] and row["round_no"] >= entry["last_main_round"]:
                entry["last_main_round"] = row["round_no"]
                entry["won_last_main"] = won
    out: dict[str, list[dict]] = {}
    for school, per_competition in by_school.items():
        results = []
        for cid, entry in per_competition.items():
            competition = competitions.get(cid, {})
            level = competition.get("competition_level", "")
            if entry["last_main_round"]:
                rounds = total_rounds.get(cid) or max_round.get(cid, 1)
                label, depth = finish_label(
                    entry["won_last_main"], entry["last_main_round"], rounds,
                )
            else:
                label, depth = "予選敗退", 0
            results.append({
                "competition_id": cid,
                "competition_name": short_name(
                    cid, competition.get("competition_name", cid)
                ),
                "type": competition.get("competition_type", ""),
                "segment": competition.get("season_segment", ""),
                "level": level,
                "wins": entry["wins"],
                "losses": entry["losses"],
                "finish": label,
                "score": LEVEL_RANK.get(level, 1) * 1000 + depth,
                "first_date": entry["first_date"],
            })
        out[school] = sorted(results, key=lambda r: r["first_date"])
    return out


def team_totals(school_id: str, details) -> dict:
    """試合の個人成績を足したチームの成績（チーム打率・本塁打・防御率）。

    ``details`` は試合ごとの個人成績（ない試合は None）。打数や投球回が
    なければその値は None。防御率は9回あたりの自責点。"""
    at_bats = hits = home_runs = outs = earned = games = 0
    for detail in details:
        if not detail:
            continue
        games += 1
        for stat in detail.get("batter_stats") or ():
            if stat.get("school_id") == school_id:
                at_bats += int(stat.get("at_bats") or 0)
                hits += int(stat.get("hits") or 0)
                home_runs += int(stat.get("home_runs") or 0)
        for stat in detail.get("pitcher_stats") or ():
            if stat.get("school_id") == school_id:
                outs += int(stat.get("outs_recorded") or 0)
                earned += int(stat.get("earned_runs") or 0)
    return {
        "games": games,
        "batting_average": round(hits / at_bats, 3) if at_bats else None,
        "home_runs": home_runs if games else None,
        "era": round(earned * 27 / outs, 2) if outs else None,
    }


def best_result(results: list[dict]) -> dict | None:
    if not results:
        return None
    best = max(results, key=lambda r: r["score"])
    return {
        "label": f"{best['competition_name']} {best['finish']}",
        "score": best["score"],
    }


def koshien_summary(results_by_year: dict[int, list[dict]]) -> dict:
    """ゲーム内の甲子園（夏・春）の出場回数・勝敗・最高成績・出場した年。"""
    out = {}
    for key, ctype in (("summer", SUMMER_NATIONAL), ("spring", SPRING_NATIONAL)):
        entries = [
            result
            for year, results in sorted(results_by_year.items())
            for result in results
            if result["type"] == ctype
        ]
        best = max(entries, key=lambda r: r["score"], default=None)
        out[key] = {
            "appearances": len(entries),
            "wins": sum(r["wins"] for r in entries),
            "losses": sum(r["losses"] for r in entries),
            "championships": sum(r["finish"] == "優勝" for r in entries),
            "best": best["finish"] if best else "",
            "years": [int(r["first_date"][:4]) for r in entries],
        }
    return out
