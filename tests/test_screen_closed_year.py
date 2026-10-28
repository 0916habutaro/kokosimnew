"""閉じた年度（前の年度）の大会・試合を見る（game_definition.md §9）。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.screen.data import GameScreenData


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


class ClosedYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        repo = DataRepository(DATA_ROOT)
        cls.service = LiveGameService(
            repo, DATA_ROOT, save_root=cls.tmp.name, autosave_after_action=False,
        )
        cls.session = cls.service.new_game("closed", rng_seed=20261026, save_initial=False)
        cls.service.advance_through(cls.session, "2026-08-31")
        cls.live_summer = GameScreenData(cls.service, cls.session).records_best8(
            {'competition_id': 'CMP000002', 'start': 2026, 'end': 2026})['rows'][0]
        cls.service.advance_through(cls.session, "2027-04-05")
        cls.data = GameScreenData(cls.service, cls.session)
        cls.koshien = next(
            cid for cid, row in repo.competitions.items()
            if row.get("competition_type") == "national_championship"
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_best8_seal_readonly_and_save_load(self):
        from phase2_engine.runtime_snapshot import dump_runtime_state
        from phase2_engine.competition_history import FINISHES
        filters = {'competition_id': self.koshien, 'start': 2026, 'end': 2026}
        archive = self.service._history_archive(self.session.slot_id)
        runtime_before = dump_runtime_state(self.session.state)
        db_before = archive.db_path.read_bytes()
        self.assertEqual(self.live_summer, self.data.records_best8(filters)['rows'][0])
        # 162大会の封印がそろい、予選だけの学校を順位へ混ぜない。
        for cid in self.service.repo.competitions:
            rows = self.data.records_best8({**filters, 'competition_id': cid})['rows']
            self.assertEqual('完了', rows[0]['status'], cid)
            groups = rows[0]['groups']
            ids = [s['school_id'] for f in FINISHES for s in groups[f]]
            self.assertEqual(len(ids), len(set(ids)), cid)
            self.assertLessEqual(len(ids), 8, cid)
            self.assertEqual(1, len(groups['優勝']), cid)
        self.assertEqual(db_before, archive.db_path.read_bytes())
        self.assertEqual(runtime_before, dump_runtime_state(self.session.state))
        # 開催年度を維持する（選抜の3月、年度をまたぐ春季も同じ索引）。
        self.service.save_game(self.session)
        reopened = self.service.load_game(self.session.slot_id)
        loaded = GameScreenData(self.service, reopened)
        self.assertEqual(self.data.records_best8(filters), loaded.records_best8(filters))

    def test_multi_year_entrants_match_official_registration(self):
        from phase2_engine.competition_history import result_main
        archive = self.service._history_archive(self.session.slot_id)
        before = archive.db_path.read_bytes()
        for year in (2026, 2027):
            season = self.data._season_of(year)
            for cid in self.service.repo.competitions:
                data = self.data.records_entrants({'competition_id': cid, 'start': year, 'end': year})
                row = data['rows'][0]
                scheduled = season.competitions.get(cid)
                main = result_main(scheduled) if scheduled else None
                self.assertEqual(set(main.entrant_school_ids) if main else set(),
                                 {e['school_id'] for e in row.get('entrants', [])}, (year, cid))
        summer = self.data.records_entrants({'competition_id': self.koshien, 'start':2026, 'end':2026})
        entries = summer['rows'][0]['entrants']
        self.assertEqual(49, len(entries))
        self.assertEqual(49, len({e['routes'][0]['competition_id'] for e in entries}))
        self.assertEqual({e['school_id'] for e in entries},
                         {e['school_id'] for e in self.data.bracket(2026, self.koshien)['entrants']})
        senbatsu = self.data.records_entrants({'competition_id':'CMP000001', 'start':2026, 'end':2026})['rows'][0]
        self.assertTrue(senbatsu['start_date'].startswith('2027-'))
        prefs = [e['prefecture_code'] for e in senbatsu['entrants']]
        self.assertLess(len(set(prefs)), len(prefs))
        self.assertEqual(before, archive.db_path.read_bytes())
        self.service.save_game(self.session)
        loaded = GameScreenData(self.service, self.service.load_game(self.session.slot_id))
        self.assertEqual(summer, loaded.records_entrants(summer['filters']))

    def test_closed_year_can_be_chosen(self):
        self.assertNotIn(2026, self.session.state.seasons)
        current = self.data.competitions()
        self.assertEqual(2027, current["school_year"])
        self.assertIn(2026, current["school_years"])
        closed = self.data.competitions(2026)
        rows = closed["competitions"]
        self.assertEqual(162, len(rows))
        self.assertTrue(all(row["status"] == "completed" for row in rows))
        # 大会の表示名（第108回…）も残る
        koshien = next(row for row in rows if row["competition_id"] == self.koshien)
        self.assertIn("108", koshien["name"])

    def test_closed_bracket_entrants_and_matches(self):
        bracket = self.data.bracket(2026, self.koshien)
        self.assertTrue(bracket["main"]["champion_id"] or bracket["main"].get("champion_after_draw"))
        self.assertEqual(49, len(bracket["entrants"]))
        # 夏の代表の地区名（東東京など）も閉じた年度で出る
        self.assertEqual(4, len({
            row["area"] for row in bracket["entrants"] if row["prefecture_code"] in ("01", "13")
        }))
        entrant = self.data.entrant(2026, self.koshien, bracket["entrants"][0]["school_id"])
        self.assertIn("results", entrant)
        # 前の年度の試合（試合の履歴から）
        row = next(
            r for r in self.service.historical_match_index(self.session.slot_id, 2026)
            if r["competition_id"] == self.koshien
        )
        match = self.data.match(2026, self.koshien, row["match_id"])
        self.assertEqual(2026, match["school_year"])
        self.assertEqual((row["team1_id"], row["team2_id"]), (match["team1_id"], match["team2_id"]))
        # 校名の札（夏の代表の地区名）も閉じた年度で出る
        tags = self.data.entry_tags(self.koshien, 2026)
        self.assertEqual(49, len(tags))

if __name__ == "__main__":
    unittest.main()
