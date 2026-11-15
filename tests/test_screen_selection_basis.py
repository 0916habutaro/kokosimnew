"""選抜の21世紀枠・神宮枠の札（記録の画面）。架空の学校で確かめる。"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

import test_screen_best8 as fixtures
from test_competition_records import tournament

SENBATSU = 'CMP000001'  # 選抜（national_invitational）


class SelectionBasisRecordTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Best8ScreenTests.setUpClass.__func__)
    setUp = fixtures.Best8ScreenTests.setUp

    def use_season(self, history):
        # 架空の32校。1回戦から上側が勝つので、優勝は A、準々決勝敗退に FAKE-04
        main, scheduled, calendar = tournament()
        season = SimpleNamespace(
            year=2026, competitions={SENBATSU: scheduled}, calendar_rows={SENBATSU: calendar},
            annual_templates={SENBATSU: None}, current_date=date(2027, 4, 5), history=history)
        self.data.state.seasons = {2026: season}
        self.data.state.current_date = date(2027, 4, 5)
        self.data._plans = lambda: {}
        return main

    def selection(self, basis):
        return [{'action': 'select_invitational', 'competition_id': SENBATSU,
                 'selection_basis': basis}]

    def test_century_and_jingu_schools_have_labels(self):
        self.use_season(self.selection({'A': 'century', 'FAKE-04': 'jingu', 'FAKE-08': 'general'}))
        filters = {'competition_id': SENBATSU, 'start': 2026, 'end': 2026}

        entrants = self.data.records_entrants(filters)['rows'][0]['entrants']
        labels = {e['school_id']: e['basis_label'] for e in entrants}
        self.assertEqual('21世紀枠', labels['A'])
        self.assertEqual('神宮枠', labels['FAKE-04'])
        # 一般の選考と、選考の記録にない学校は札なし
        self.assertEqual('', labels['FAKE-08'])
        self.assertEqual('', labels['FAKE-01'])

        groups = self.data.records_best8(filters)['rows'][0]['groups']
        best8 = {s['school_id']: s['basis_label'] for rows in groups.values() for s in rows}
        self.assertEqual('21世紀枠', best8['A'])
        self.assertEqual('神宮枠', best8['FAKE-04'])
        self.assertEqual('', best8['FAKE-08'])

    def test_no_labels_without_selection_record(self):
        self.use_season([])
        filters = {'competition_id': SENBATSU, 'start': 2026, 'end': 2026}
        entrants = self.data.records_entrants(filters)['rows'][0]['entrants']
        self.assertTrue(entrants)
        self.assertTrue(all(e['basis_label'] == '' for e in entrants))


if __name__ == '__main__':
    unittest.main()
