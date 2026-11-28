"""全国大会の出場校一覧の並び（夏は区分の順、選抜は地区大会の順位の順）。学校はすべて架空。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from phase2_engine.screen.data import GameScreenData, load_screen_config

ROOT = Path(__file__).resolve().parents[1]


def screen(competitions=None, locals_=None, finishes=None, regions=None, season=None):
    data = GameScreenData.__new__(GameScreenData)
    data.config = load_screen_config(ROOT / "config")
    data.service = SimpleNamespace(repo=SimpleNamespace(competitions=competitions or {}, data_dir=ROOT / "data"))
    data._summer_area_competitions = lambda year: dict(locals_ or {})
    if finishes is not None:
        data._autumn_regional_finishes = lambda year: dict(finishes)
    data._regions = dict(regions or {})
    data._season_of = lambda year: season
    return data


def ordered(data, kind, schools, basis=None):
    key = data._entrant_order(2028, kind, basis or {})
    return [sid for sid, _ in sorted(schools.items(), key=lambda item: (*key(*item), item[0]))]


class SummerOrderTests(unittest.TestCase):
    def test_north_and_east_come_first(self):
        # 北海道・東京は夏の代表区分（地域のデータの area_id）、記念大会は区分の名前（北大阪→南大阪）
        competitions = {
            "L_HS": {"qualifying_area_id": "AREA000011", "prefecture_code": "01"},  # 南北海道
            "L_HN": {"qualifying_area_id": "AREA000012", "prefecture_code": "01"},  # 北北海道
            "L_TE": {"qualifying_area_id": "AREA000013", "prefecture_code": "13"},  # 東東京
            "L_TW": {"qualifying_area_id": "AREA000014", "prefecture_code": "13"},  # 西東京
            "L_OS": {"prefecture_code": "27", "commemorative_district": "南大阪"},
            "L_ON": {"prefecture_code": "27", "commemorative_district": "北大阪"},
        }
        locals_ = {"a_south": "L_HS", "z_north": "L_HN", "a_west": "L_TW", "z_east": "L_TE",
                   "a_osaka_s": "L_OS", "z_osaka_n": "L_ON"}
        schools = {"a_south": "01", "z_north": "01", "a_west": "13", "z_east": "13",
                   "a_osaka_s": "27", "z_osaka_n": "27", "aomori": "02"}
        self.assertEqual(["z_north", "a_south", "aomori", "z_east", "a_west", "z_osaka_n", "a_osaka_s"],
                         ordered(screen(competitions, locals_), "summer", schools))


class InvitationalOrderTests(unittest.TestCase):
    def test_regions_then_finish_with_century_last(self):
        # 地区の到達点（1=優勝, 2=準優勝, 4=ベスト4…）。関東(REG03)→東京(REG04)、東海(REG06)→北信越(REG05)
        finishes = {
            "kanto_best4": ("REG03", 4), "kanto_champ": ("REG03", 1), "tokyo_champ": ("REG04", 1),
            "hokushinetsu_champ": ("REG05", 1), "tokai_runner": ("REG06", 2),
            "kyushu_jingu": ("REG10", 2), "hokkaido_champ": ("REG01", 1),
        }
        schools = {"kanto_best4": "08", "kanto_champ": "12", "tokyo_champ": "13",
                   "hokushinetsu_champ": "15", "tokai_runner": "22", "kyushu_jingu": "40",
                   "hokkaido_champ": "01", "century_b": "36", "century_a": "05"}
        basis = {"kyushu_jingu": "jingu", "century_a": "century", "century_b": "century"}
        self.assertEqual(
            ["hokkaido_champ", "kanto_champ", "kanto_best4", "tokyo_champ", "tokai_runner",
             "hokushinetsu_champ", "kyushu_jingu", "century_a", "century_b"],
            ordered(screen(finishes=finishes), "spring", schools, basis))

    def test_without_regional_results_regions_then_prefecture(self):
        # 地区大会の結果がない年（ゲーム開始より前など）：地区 → 都道府県コード
        data = screen(regions={"01": "REG01", "13": "REG04", "14": "REG03", "11": "REG03"}, season=None)
        self.assertEqual({}, data._autumn_regional_finishes(2025))
        schools = {"tokyo": "13", "kanagawa": "14", "saitama": "11", "hokkaido": "01"}
        self.assertEqual(["hokkaido", "saitama", "kanagawa", "tokyo"], ordered(data, "spring", schools))

    def test_other_nationals_are_by_prefecture(self):
        self.assertEqual(["b", "a"], ordered(screen(), None, {"a": "40", "b": "01"}))


if __name__ == "__main__":
    unittest.main()
