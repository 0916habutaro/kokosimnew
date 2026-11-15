"""閉じた年度の連合チームの成績：年度の状態を戻さず、閉じたときに書いた連合の索引から引く。
架空の学校で確かめる。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from game_core.joint_teams import JointTeam, UnionPlan, season_unions
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.screen.data import GameScreenData

YEAR = 2031
NAMES = {"FAKE-A": "甲", "FAKE-B": "乙", "FAKE-C": "丙", "FAKE-D": "丁", "FAKE-E": "戊"}
COMPETITIONS = {
    "FAKE-PREF": {"competition_type": "autumn_prefectural", "competition_level": "prefectural"},
    "FAKE-REGION": {"competition_type": "autumn_regional", "competition_level": "regional"},
    "FAKE-SUMMER": {"competition_type": "summer_local_qualifier", "competition_level": "local"},
}


def _row(cid, match_id, round_no, date, team1, team2, winner):
    return {"competition_id": cid, "match_id": match_id, "round_no": round_no, "main": True,
            "match_date": date, "team1_id": team1, "team2_id": team2, "winner_id": winner}


ROWS = [
    _row("FAKE-SUMMER", "S1", 1, f"{YEAR}-07-10", "FAKE-C", "FAKE-D", "FAKE-C"),
    _row("FAKE-PREF", "P1", 1, f"{YEAR}-09-01", "FAKE-A", "FAKE-C", "FAKE-A"),
    _row("FAKE-PREF", "P2", 2, f"{YEAR}-09-08", "FAKE-A", "FAKE-D", "FAKE-A"),
    _row("FAKE-REGION", "R1", 1, f"{YEAR}-10-20", "FAKE-A", "FAKE-E", "FAKE-E"),
]


def _season():
    done = SimpleNamespace(is_complete=True)
    return SimpleNamespace(
        year=YEAR,
        repo=SimpleNamespace(competitions=COMPETITIONS),
        union_plans={"FAKE-PREF": UnionPlan((JointTeam("FAKE-A", ("FAKE-A", "FAKE-B")),), ())},
        competitions={cid: done for cid in COMPETITIONS},
    )


class _Service:
    def __init__(self, archive):
        self.archive = archive
        self.repo = SimpleNamespace(competitions=COMPETITIONS)

    def closed_unions(self, slot_id, year):
        return self.archive.closed_unions(year)

    def closed_season(self, *args):
        raise AssertionError("閉じた年度の状態を戻してはいけない")


def _screen(state, service):
    screen = SimpleNamespace(
        state=state, service=service, session=SimpleNamespace(slot_id="slot"),
        names=lambda sid, day="": NAMES.get(sid, sid),
        competition_names=lambda cid, name: name,
        _current_year=lambda: YEAR,
        _years=lambda: [YEAR],
        _year_rows=lambda year: (list(ROWS), {}),
        _season_of=lambda year: service.closed_season(),
        _closed_years={}, _closed_union_cache={},
    )
    for name in ("union", "_union_teams", "_closed_unions", "_add_union_results",
                 "_union_leads", "_results"):
        setattr(screen, name, getattr(GameScreenData, name).__get__(screen))
    return screen


class ClosedUnionResultsTests(unittest.TestCase):
    def test_results_after_closing_match_live_without_loading_the_season(self):
        with TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            service = _Service(archive)
            season = _season()
            live = _screen(season, service)
            before = live._results(YEAR)
            before_leads = live._union_leads("FAKE-B", YEAR)
            # 連合の構成校の行（地区大会へ進んだ連合も同じ）が閉じる前にある
            self.assertEqual(["FAKE-PREF", "FAKE-REGION"],
                             [r["competition_id"] for r in before["FAKE-B"]])
            self.assertEqual("FAKE-A", before["FAKE-B"][0]["union_lead"])

            archive.store_closed_season(YEAR, b"not a snapshot", {},
                                        union_records=season_unions(season))
            # 年度を閉じたあと（進行中の年度は次の年度だけ）
            closed = _screen(SimpleNamespace(year=YEAR + 1), service)
            self.assertEqual(before, closed._results(YEAR))
            self.assertEqual(before_leads, closed._union_leads("FAKE-B", YEAR))
            self.assertEqual(("FAKE-A", "FAKE-B"),
                             closed.union("FAKE-A", "FAKE-REGION", YEAR).schools)
            self.assertIsNone(closed.union("FAKE-C", "FAKE-PREF", YEAR))

    def test_union_index_is_replaced_when_the_year_is_sealed_again(self):
        with TemporaryDirectory() as tmp:
            archive = HistoricalMatchArchive(Path(tmp) / "history.sqlite3")
            archive.store_closed_season(YEAR, b"x", {}, union_records=[
                ("FAKE-PREF", ("FAKE-A", "FAKE-B")), ("FAKE-PREF", ("FAKE-A", "FAKE-C"))])
            self.assertEqual({"FAKE-PREF": [("FAKE-A", "FAKE-B")]}, archive.closed_unions(YEAR))
            archive.store_closed_season(YEAR, b"x", {}, union_records=[])
            self.assertEqual({}, archive.closed_unions(YEAR))
            self.assertEqual({}, archive.closed_unions(YEAR + 1))


if __name__ == "__main__":
    unittest.main()
