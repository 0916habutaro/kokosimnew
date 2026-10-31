"""今日の画面のデータ（注目の試合・前の試合日の結果・直近の大きな結果）。

大会の進行は小さな作り物で置き換え、データの層の選び方だけを確かめる。
校名・大会は架空。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

from phase2_engine.screen.data import GameScreenData, load_screen_config


ROOT = Path(__file__).resolve().parents[1]

TYPES = {
    "NAT": "national_championship",
    "REG": "spring_regional",
    "PRE": "spring_prefectural",
    "PRE2": "autumn_prefectural",
    "LOC1": "summer_local_qualifier",
    "LOC2": "summer_local_qualifier",
}


def match(cid, mid, day, round_name="1回戦", stage="MAIN", status="completed", round_no=1):
    row = {
        "competition_id": cid, "competition_name": cid, "match_id": mid,
        "match_date": day, "stage_code": stage, "round_no": round_no,
        "round_name": round_name, "group_name": "",
        "team1_id": f"{mid}-a", "team2_id": f"{mid}-b",
        "team1_score": 3, "team2_score": 1, "winner_id": f"{mid}-a",
        "status": status,
    }
    return SimpleNamespace(**row, public_dict=lambda row=row: dict(row))


class FakeData(GameScreenData):
    def __init__(self, today, competitions, complete=()):
        self.config = load_screen_config(ROOT / "config")
        self.abilities = None
        self.service = SimpleNamespace(repo=SimpleNamespace(competitions={
            cid: {"competition_type": ctype} for cid, ctype in TYPES.items()
        }))
        self._state = SimpleNamespace(
            year=2026, current_date=today,
            competitions={
                cid: SimpleNamespace(
                    is_complete=cid in complete,
                    matches={m.match_id: m for m in rows},
                )
                for cid, rows in competitions.items()
            },
        )
        self._state.today_matches = lambda: [
            m.public_dict()
            for scheduled in self._state.competitions.values()
            for m in scheduled.matches.values()
            if m.match_date == today.isoformat()
        ]

    @property
    def state(self):
        return self._state

    def _match_summary(self, row):
        return {"competition_id": row["competition_id"], "match_id": row["match_id"],
                "match_date": row["match_date"]}


def ids(rows):
    return [row["match_id"] for row in rows]


class PreviousDayTests(unittest.TestCase):
    def test_whole_national_and_regional_main_others_limited(self):
        day = "2026-05-02"
        data = FakeData(date(2026, 5, 4), {
            "NAT": [match("NAT", f"n{i}", day) for i in range(3)],
            "REG": [match("REG", f"r{i}", day) for i in range(5)]
            + [match("REG", "rq", day, stage="QUAL")],
            "PRE": [match("PRE", f"p{i}", day) for i in range(10)]
            + [match("PRE", "old", "2026-05-01")],
            "PRE2": [match("PRE2", f"q{i}", day) for i in range(10)]
            + [match("PRE2", "later", "2026-05-04", status="pending")],
            "LOC1": [match("LOC1", f"l{i}", day) for i in range(10)],
        })
        out = data.previous_day_results()
        self.assertEqual(day, out["date"])
        self.assertEqual("2026年5月2日（土）", out["date_label"])
        got = ids(out["matches"])
        # 全国大会が先、地区大会の本大会は全試合
        self.assertEqual(["n0", "n1", "n2", "r0", "r1", "r2", "r3", "r4"], got[:8])
        rule = data.config["previous_day_results"]
        rest = out["matches"][8:]
        self.assertEqual(rule["other_count"], len(rest))
        limit = data.config["featured_match"]["max_per_competition"]
        cids = [row["competition_id"] for row in rest]
        self.assertTrue(all(cids.count(cid) <= limit for cid in cids))
        self.assertNotIn("old", got)

    def test_no_previous_match_day(self):
        data = FakeData(date(2026, 4, 1), {"PRE": [match("PRE", "p", "2026-04-01", status="pending")]})
        self.assertEqual([], data.previous_day_results()["matches"])


class RecentResultsTests(unittest.TestCase):
    def competitions(self):
        return {
            "NAT": [match("NAT", "n-qf", "2026-08-18", "準々決勝"),
                    match("NAT", "n-r2", "2026-08-14", "2回戦")],
            "LOC1": [match("LOC1", "l1-f", "2026-07-20", "決勝"),
                     match("LOC1", "l1-sf", "2026-07-19", "準決勝")],
            "LOC2": [match("LOC2", "l2-f", "2026-07-28", "決勝")],
            "PRE": [match("PRE", "p-f", "2026-05-01", "決勝")],
        }

    def test_qualifier_finals_and_national_rounds_until_national_ends(self):
        data = FakeData(date(2026, 8, 19), self.competitions())
        got = ids(data.recent_results())
        # 全国大会が先、残りは新しい順。7日以内でなくても代表決定は出る
        self.assertEqual(["n-qf", "l2-f", "l1-f"], got)

    def test_after_national_ends_only_recent_finals(self):
        data = FakeData(date(2026, 8, 19), self.competitions(), complete={"NAT"})
        self.assertEqual([], data.recent_results())


class FeaturedTests(unittest.TestCase):
    def test_national_matches_first_without_limit(self):
        day = "2026-08-10"
        data = FakeData(date(2026, 8, 10), {
            "NAT": [match("NAT", f"n{i}", day, status="pending") for i in range(4)],
            "PRE": [match("PRE", f"p{i}", day, status="pending") for i in range(5)],
            "PRE2": [match("PRE2", f"q{i}", day, status="pending") for i in range(5)],
        })
        rule = data.config["featured_match"]
        got = data.featured_matches()
        self.assertEqual({"n0", "n1", "n2", "n3"}, set(ids(got[:4])))
        self.assertEqual(rule["count"], len(got))
        cids = [row["competition_id"] for row in got[4:]]
        self.assertTrue(all(cids.count(cid) <= rule["max_per_competition"] for cid in cids))


if __name__ == "__main__":
    unittest.main()
