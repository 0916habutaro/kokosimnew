"""試合の結果の要約：コールド、勝利投手・敗戦投手、本塁打（game_definition.md §9）。

どれも保存済みの試合の記録（``inning_scores``・``highlights``・``pitcher_stats``）から
求める。保存形式は変えない。

勝利投手・敗戦投手は公認野球規則 9.17 の考え方で決める。

- 勝ったチームが最後にリードを奪った得点（決勝点）の時点で、そのチームの責任投手
  （いちばん最後に投げていた投手）を勝利投手とする
- ただし先発投手は、守備の回が6回以上の試合なら5回（15アウト）、5回以下なら4回
  （12アウト）を投げていなければ勝利投手にしない。そのときは救援投手のうち、
  いちばん多くアウトを取った投手（同じなら失点の少ない投手、次に先に投げた投手）
- 決勝点の責任を負う投手を敗戦投手とする

打席ごとの記録は残していないので、走者の責任は次のように数え直す。投手が回の途中で
降りたあと、その回に入った得点は、降りた投手の失点（``runs_allowed``）が残っている間は
降りた投手（先に降りた順）の責任、残っていなければ投げている投手の責任とする（残した
走者は前を走るので先にかえる）。数え直した失点が保存済みの投手ごとの失点と合わないとき
は決められないので、勝利投手・敗戦投手は出さない（None）。

記録員の判断に任される規則（救援投手が短くて効果がなかったときに次の救援投手に勝ちを
付ける 9.17(c) など）は扱わない。
"""
from __future__ import annotations

REGULATION_INNINGS = 9
_HALF_BATTING = {"t": 1, "b": 2}


def _teams(detail: dict) -> tuple:
    """先攻・後攻の学校ID（試合の直後の記録と、履歴に書き出した記録で名前が違う）。"""
    return (
        detail.get("team1_school_id") or detail.get("team1_id"),
        detail.get("team2_school_id") or detail.get("team2_id"),
    )


def last_inning(detail: dict) -> int | None:
    """試合が終わった回（記録した半イニングのいちばん後の回）。"""
    innings = [int(row["inning"]) for row in detail.get("inning_scores") or ()]
    if innings:
        return max(innings)
    last = detail.get("last_inning")
    return last if isinstance(last, int) else None


def called_inning(detail: dict | None, thresholds, regulation: int = REGULATION_INNINGS) -> int | None:
    """コールドで終わった試合なら終わった回。そうでなければ None。

    試合が規定の回より前に終わり、終わった時点の点差がコールドの規則
    （``thresholds`` は [回, 点差] の並び）に当たるときにコールドとする。"""
    if not detail:
        return None
    last = last_inning(detail)
    score1, score2 = detail.get("team1_score"), detail.get("team2_score")
    if last is None or last >= regulation or score1 is None or score2 is None:
        return None
    margin = abs(int(score1) - int(score2))
    if any(last >= int(inning) and margin >= int(points) for inning, points in thresholds):
        return last
    return None


def called_label(detail: dict | None, thresholds) -> str:
    inning = called_inning(detail, thresholds)
    return f"{inning}回コールド" if inning else ""


def home_runs(detail: dict | None) -> list[dict]:
    """本塁打（打った順）：学校ID・選手ID・回。"""
    if not detail:
        return []
    team1, team2 = _teams(detail)
    teams = {"t": team1, "b": team2}
    return [
        {"school_id": teams[item[2]], "player_id": item[3], "inning": item[1]}
        for item in detail.get("highlights") or ()
        if item[0] == "S" and item[4] == "home_run"
    ]


def pitchers_of_record(detail: dict | None) -> dict | None:
    """勝利投手・敗戦投手 {"win": (学校ID, 選手ID), "loss": (学校ID, 選手ID)}。

    決められないとき（引き分け・記録が足りない・失点の数え直しが合わない）は None。"""
    if not detail:
        return None
    team1, team2 = _teams(detail)
    winner = detail.get("winner_id")
    stats = detail.get("pitcher_stats") or ()
    highlights = detail.get("highlights")
    if winner not in (team1, team2) or not stats or highlights is None:
        return None
    loser = team2 if winner == team1 else team1
    allowed: dict[tuple, int] = {}
    outs: dict[tuple, int] = {}
    order: dict[str, list[str]] = {team1: [], team2: []}
    for row in stats:
        key = (row.get("school_id"), row.get("player_id"))
        if key[0] not in order:
            return None
        allowed[key] = int(row.get("runs_allowed") or 0)
        outs[key] = int(row.get("outs_recorded") or 0)
        order[key[0]].append(key[1])
    if not order[team1] or not order[team2]:
        return None
    starter = {team: order[team][0] for team in order}
    current = dict(starter)
    assigned = {key: 0 for key in allowed}
    departed: dict[str, list[str]] = {team1: [], team2: []}
    half_of: dict[str, tuple] = {}
    score = {team1: 0, team2: 0}
    runs = []  # (得点したチーム, 得点後の点, 責任投手のキー, 勝ったチームの責任投手)

    for item in highlights:
        kind, inning, half = item[0], item[1], item[2]
        if kind == "P":
            team, pitcher = item[3], item[4]
            if team not in current:
                return None
            # 回が変わったら、前の回に降りた投手の走者はもういない
            if half_of.get(team) != (inning, half):
                departed[team] = []
                half_of[team] = (inning, half)
            old = (team, current[team])
            if allowed.get(old, 0) - assigned.get(old, 0) > 0:
                departed[team].append(current[team])
            current[team] = pitcher
            if (team, pitcher) not in allowed:
                return None
            continue
        offense = team1 if _HALF_BATTING[half] == 1 else team2
        defense = team2 if offense == team1 else team1
        if half_of.get(defense) != (inning, half):
            departed[defense] = []
            half_of[defense] = (inning, half)
        for _ in range(int(item[5])):
            charged = None
            for pitcher in departed[defense]:
                key = (defense, pitcher)
                if allowed[key] - assigned[key] > 0:
                    charged = key
                    break
            if charged is None:
                charged = (defense, current[defense])
            assigned[charged] = assigned.get(charged, 0) + 1
            score[offense] += 1
            runs.append((offense, dict(score), charged, current[winner]))

    if assigned != allowed:
        return None
    if (score[team1], score[team2]) != (detail.get("team1_score"), detail.get("team2_score")):
        return None

    # 決勝点：勝ったチームが同点からリードを奪った、いちばん最後の得点
    go_ahead = None
    for offense, after, charged, winner_pitcher in runs:
        if offense == winner and after[winner] == after[loser] + 1:
            go_ahead = (charged, winner_pitcher)
    if go_ahead is None:
        return None
    charged, win_pitcher = go_ahead
    if win_pitcher == starter[winner]:
        defense_halves = sum(
            1 for row in detail.get("inning_scores") or ()
            if row.get("batting_team_id") == loser and row.get("was_played", True)
        )
        needed = 15 if defense_halves >= 6 else 12
        relievers = order[winner][1:]
        if outs[(winner, win_pitcher)] < needed and relievers:
            win_pitcher = min(
                relievers,
                key=lambda pid: (-outs[(winner, pid)], allowed[(winner, pid)],
                                 relievers.index(pid)),
            )
    return {"win": (winner, win_pitcher), "loss": charged}
