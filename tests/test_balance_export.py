"""balance_report の CSV と前後の比較（phase2_engine/balance_export.py）。架空の小さな結果で確かめる。"""
from __future__ import annotations

import csv
from datetime import date
import tempfile
import unittest
from pathlib import Path

from phase2_engine import balance_export as export

ROOT = Path(__file__).resolve().parents[1]


def report(runs: float, called: float, streak: int) -> dict:
    return {
        "2026": {"local": {"games": 10, "runs_per_team": runs, "called_share": called},
                 "koshien_leaders": {"home_runs": [3, 2]}},          # 並びは指標にしない
        "2027": {"local": {"games": 12, "runs_per_team": runs + 1, "called_share": called}},
        "通し": {"dynasty": {"longest_streak": streak}},
    }


ACTUAL = {"dynasty": {"longest_streak": 6}}


def read(path: Path) -> list[dict]:
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Excel で開けるよう BOM 付き"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class MetricsCsvTests(unittest.TestCase):
    def test_one_row_per_metric_and_seed_with_mean_min_max(self):
        reports = {11: report(4.0, 0.3, 5), 12: report(5.0, 0.4, 7)}
        with tempfile.TemporaryDirectory() as tmp:
            conditions = export.run_conditions([11, 12], "2026-04-01", "2028-04-02", root=ROOT)
            metrics, cond = export.write_metrics(Path(tmp), reports, ACTUAL, conditions)
            rows = read(metrics)
            self.assertEqual(list(export.METRIC_COLUMNS), list(rows[0]))
            # 指標は 2026・2027 の3つずつと通しの1つ。種2つ＋平均・最小・最大
            self.assertEqual(7 * 5, len(rows))
            runs = {r["種"]: r for r in rows if r["年度"] == "2027" and r["指標"] == "local.runs_per_team"}
            self.assertEqual(("5", "6", "5.5", "5", "6"),
                             tuple(runs[k]["値"] for k in ("11", "12", "平均", "最小", "最大")))
            self.assertEqual("§11", runs["11"]["区分"])
            streak = [r for r in rows if r["指標"] == "dynasty.longest_streak"]
            self.assertEqual({"6"}, {r["実際"] for r in streak})
            self.assertEqual({"強豪の続き方"}, {r["区分"] for r in streak})
            items = {r["項目"]: r["値"] for r in read(cond)}
            self.assertEqual("11,12", items["種"])
            self.assertEqual("2028-04-02", items["終わり（この日まで進めた）"])
            self.assertIn("revision config/coaches/coach_personnel_v1.json", items)


class CompareTests(unittest.TestCase):
    def test_difference_is_after_minus_before_with_all_years_and_actual(self):
        before = {11: report(4.0, 0.3, 5), 12: report(5.0, 0.4, 7)}
        after = {11: report(4.5, 0.3, 8)}
        rows = {(r["年度"], r["指標"]): r for r in export.compare_rows(before, after, ACTUAL)}
        row = rows[("2026", "local.runs_per_team")]
        self.assertEqual((4.5, 4, 5, 4.5, 0), (row["前"], row["前の最小"], row["前の最大"], row["後"], row["差"]))
        # 全年度：種ごとに年度を平均してから種の平均（前 (4.5+5.5)/2=5、後 5）
        self.assertEqual((5, 5, 0), tuple(rows[(export.ALL_YEARS, "local.runs_per_team")][k]
                                          for k in ("前", "後", "差")))
        streak = rows[("通し", "dynasty.longest_streak")]
        self.assertEqual((6, 8, 2, 6), (streak["前"], streak["後"], streak["差"], streak["実際"]))
        markdown = export.compare_markdown(list(rows.values()), only={"強豪の続き方"})
        self.assertIn("| 夏の甲子園の続き方／最長の連続出場 | 通し | 6（5〜7） | 8 | 2 | 6 |", markdown)
        self.assertNotIn("§11", markdown)


def inning(team: str, n: int, half: str, runs: int, played: bool = True) -> dict:
    return {"inning": n, "half": half, "batting_team_id": team, "was_played": played, "runs": runs}


def fictional_match(innings_a, innings_b, *, match_id="STG9-MAIN-R1-M1", competition_id="CMP-X"):
    """架空校 A（先攻）と B の試合。``innings_*`` は回ごとの点（None はその裏をしていない）。"""
    scores = []
    for n in range(max(len(innings_a), len(innings_b))):
        if n < len(innings_a):
            scores.append(inning("SCH-TA", n + 1, "top", innings_a[n]))
        if n < len(innings_b):
            runs = innings_b[n]
            scores.append(inning("SCH-TB", n + 1, "bottom", runs or 0, runs is not None))
    a, b = sum(innings_a), sum(r or 0 for r in innings_b)
    return {
        "match_id": match_id, "competition_id": competition_id,
        "team1_school_id": "SCH-TA", "team2_school_id": "SCH-TB", "team1_score": a, "team2_score": b,
        "winner_id": "SCH-TA" if a > b else "SCH-TB", "last_inning": max(len(innings_a), len(innings_b)),
        "inning_scores": scores,
        "team_stats": [{"school_id": "SCH-TA", "hits": 9, "errors": 1}, {"school_id": "SCH-TB", "hits": 4, "errors": 2}],
        "pitcher_stats": [{"school_id": "SCH-TA", "player_id": "PA1", "pitches": 120, "batters_faced": 30},
                          {"school_id": "SCH-TB", "player_id": "PB1", "pitches": 80, "batters_faced": 20},
                          {"school_id": "SCH-TB", "player_id": "PB2", "pitches": 30, "batters_faced": 9}],
        "team_participation": [
            {"school_id": "SCH-TA", "starting_pitcher_id": "PA1", "changes": []},
            {"school_id": "SCH-TB", "starting_pitcher_id": "PB1",
             "changes": [{"kind": "substitution", "moment": {"inning": 3}},
                         {"kind": "pitcher_change", "moment": {"inning": 5}}]}],
    }


class MatchCsvTests(unittest.TestCase):
    def row(self, detail, **kwargs):
        return export.match_row(7, detail, year=2026, played_on=date(2026, 7, 10), competition_name="架空大会",
                                kind="summer_local_qualifier", total_rounds=kwargs.get("total_rounds", 3),
                                ranks={"SCH-TA": "B", "SCH-TB": "D"}, thresholds=((5, 10), (7, 7)))

    def test_inning_runs_add_up_to_the_score(self):
        cases = (
            fictional_match([1, 0, 2, 0, 0, 3, 0, 0, 1], [0, 0, 0, 1, 0, 0, 2, 0, None]),     # 9回裏なし
            fictional_match([2, 0, 5, 0, 4, 0, 0], [0, 0, 0, 0, 0, 0, 0]),                    # 7回コールド
            fictional_match([0] * 8 + [1, 0, 2], [0] * 8 + [1, 0, 1]),                        # 延長11回
        )
        for detail in cases:
            row = self.row(detail)
            for side in ("1", "2"):
                runs = [row[f"学校{side}_{n}回"] for n in range(1, 10)] + [row[f"学校{side}_延長"]]
                self.assertEqual(row[f"得点{side}"], sum(r for r in runs if isinstance(r, int)), (side, runs))
        self.assertEqual("x", self.row(cases[0])["学校2_9回"])
        self.assertEqual(("7回7点", 0, ""), tuple(self.row(cases[1])[k] for k in ("コールド", "延長", "学校1_8回")))
        self.assertEqual((11, 1, 2), tuple(self.row(cases[2])[k] for k in ("終わった回", "延長", "学校1_延長")))

    def test_columns_round_and_pitching(self):
        row = self.row(fictional_match([1] * 9, [0] * 8 + [None], match_id="STG9-MAIN-R3-M1"))
        self.assertEqual(set(export.match_columns()), set(row))
        self.assertEqual(("本大会", "決勝", "学校1", "学校1"), (row["段階"], row["回戦"], row["先攻"], row["勝者"]))
        self.assertEqual((120, "", 1), (row["先発1の球数"], row["先発1の降板の回"], row["投手の数1"]))
        self.assertEqual((80, 5, 2), (row["先発2の球数"], row["先発2の降板の回"], row["投手の数2"]))
        self.assertEqual(("B", "D", 9, 2), (row["学校1の評判ランク"], row["学校2の評判ランク"], row["安打1"], row["失策2"]))
        self.assertEqual(("予選", ""), export.round_name("STG1-SGR2-B01-BLOCK_KO-001", None))


COMPETITIONS = {
    "CMP-LOC": {"competition_type": "summer_local_qualifier", "competition_level": "prefectural",
                "competition_name": "第1回全国高等学校野球選手権架空大会"},
    "CMP-KOS": {"competition_type": "national_championship", "competition_level": "national",
                "competition_name": "架空甲子園"},
}


def game(cid, match_id, team1, team2, winner) -> dict:
    return {"competition_id": cid, "match_id": match_id, "team1_school_id": team1, "team2_school_id": team2,
            "team1_score": 3 if winner == team1 else 1, "team2_score": 3 if winner == team2 else 1,
            "winner_id": winner}


class SchoolYearTests(unittest.TestCase):
    def test_one_row_per_school_and_finish_matches_the_results(self):
        table = export.SchoolYearTable(7, COMPETITIONS.__getitem__)
        schools = ["SCH-T1", "SCH-T2", "SCH-T3", "SCH-T4", "SCH-T5"]      # T5 は出ていない
        day = date(2026, 7, 20)
        local = (game("CMP-LOC", "S-MAIN-R1-M1", "SCH-T1", "SCH-T2", "SCH-T1"),
                 game("CMP-LOC", "S-MAIN-R1-M2", "SCH-T3", "SCH-T4", "SCH-T4"),
                 game("CMP-LOC", "S-MAIN-R2-M1", "SCH-T1", "SCH-T4", "SCH-T1"))
        for detail in local:
            table.add_match(2026, detail, day, 2, lambda school: ("SCH-T5",) if school == "SCH-T3" else ())
        koshien = game("CMP-KOS", "K-MAIN-R1-M1", "SCH-T1", "SCH-X9", "SCH-X9")
        table.add_match(2026, koshien, date(2026, 8, 8), 6)
        table.set_attributes(2026, {s: {"学校": f"架空{s}"} for s in schools})
        rows = {row["学校ID"]: row for row in table.rows(2026, schools)}
        self.assertEqual(len(schools), len(rows))
        self.assertTrue(set(rows["SCH-T1"]) <= set(export.school_columns()))
        finishes = {s: rows[s]["夏の地方大会"] for s in schools}
        self.assertEqual({"SCH-T1": "優勝", "SCH-T2": "ベスト4", "SCH-T3": "ベスト4", "SCH-T4": "準優勝",
                          "SCH-T5": ""}, finishes)
        # 優勝は決勝の勝者、準優勝は決勝の敗者
        self.assertEqual(local[-1]["winner_id"], next(s for s, f in finishes.items() if f == "優勝"))
        self.assertEqual(("1回戦敗退", 0, 1), (rows["SCH-T1"]["夏の甲子園"], rows["SCH-T1"]["夏の甲子園の勝"],
                                            rows["SCH-T1"]["夏の甲子園の負"]))
        self.assertEqual(("代表", "構成（代表 SCH-T3）"), (rows["SCH-T3"]["夏の連合"], rows["SCH-T5"]["夏の連合"]))
        self.assertEqual("架空", rows["SCH-T5"]["夏の地方大会の区分"])


if __name__ == "__main__":
    unittest.main()
