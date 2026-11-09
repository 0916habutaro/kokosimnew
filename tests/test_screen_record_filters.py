"""記録の画面：都道府県の並び順、絞り込みの連動、複数年度の出場校の行。"""
from pathlib import Path
import unittest

from phase2_engine import DataRepository
from phase2_engine.screen import record_filters as rf
from phase2_engine.screen.competition_views import _level

ROOT = Path(__file__).resolve().parents[1]
# 架空の都道府県名（コードだけ本物の並びにする）
PREFS = {f"{n:02d}": f"架空県{n:02d}" for n in range(1, 48)}
REGIONS = {"R1": "架空地区1", "R2": "架空地区2"}


def fake_catalog():
    def comp(cid, segment, level, regions=(), prefectures=(), pref=""):
        return {"competition_id": cid, "name": f"架空大会{cid}", "segment": segment, "level": level,
                "prefecture": pref, "regions": list(regions), "prefectures": list(prefectures)}
    return [
        comp("N-SPRING", "spring", "national"),
        comp("N-SUMMER", "summer", "national"),
        comp("R1-AUTUMN", "autumn", "regional", ["R1"], ["01", "02"]),
        comp("R2-AUTUMN", "autumn", "regional", ["R2"], ["12", "13"]),
        comp("P01-AUTUMN", "autumn", "local", ["R1"], ["01"], "01"),
        comp("P12-AUTUMN", "autumn", "local", ["R2"], ["12"], "12"),
        comp("P12-SUMMER", "summer", "local", ["R2"], ["12"], "12"),
    ]


class CascadeTests(unittest.TestCase):
    def cascade(self, **filters):
        return rf.cascade_filters(fake_catalog(), filters, REGIONS, PREFS)

    def test_region_limits_prefectures_and_drops_mismatch(self):
        f, options, pool = self.cascade(region="R1", prefecture="12")
        self.assertEqual("", f["prefecture"])  # 地域にない都道府県は外す
        self.assertEqual(["01", "02"], [p for p, _ in options["prefecture"]])
        self.assertEqual({"R1-AUTUMN", "P01-AUTUMN"}, {c["competition_id"] for c in pool})
        # 地図では地域の外の都道府県も押せる（押すと地域を外す）
        self.assertEqual(["01", "02", "12", "13"], options["map_prefecture"])

    def test_national_disables_region_and_prefecture(self):
        f, options, pool = self.cascade(level="national", region="R1", prefecture="01")
        self.assertEqual(("", ""), (f["region"], f["prefecture"]))
        self.assertEqual({"region": True, "prefecture": True}, options["disabled"])
        self.assertEqual({"N-SPRING", "N-SUMMER"}, {c["competition_id"] for c in pool})

    def test_level_options_follow_segment_and_competition_never_empty(self):
        f, options, pool = self.cascade(segment="spring", level="regional", competition_id="P12-SUMMER")
        self.assertEqual([["national", "全国"]], options["level"])
        self.assertEqual("", f["level"])
        self.assertEqual("N-SPRING", f["competition_id"])
        for filters in ({"segment": "summer", "prefecture": "01"}, {"region": "R9"},
                        {"segment": "autumn", "level": "local", "region": "R2", "prefecture": "12"}):
            f, _, pool = self.cascade(**filters)
            self.assertTrue(pool)
            self.assertIn(f["competition_id"], {c["competition_id"] for c in pool})

    def test_prefecture_also_finds_its_regional_competition(self):
        f, _, pool = self.cascade(segment="autumn", prefecture="13")
        self.assertEqual(["R2-AUTUMN"], [c["competition_id"] for c in pool])

    def test_prefecture_options_are_in_code_order(self):
        _, options, _ = self.cascade()
        codes = [p for p, _ in options["prefecture"]]
        self.assertEqual(sorted(codes), codes)
        self.assertEqual(["01", "02", "12", "13"], codes)


class AxisTests(unittest.TestCase):
    def test_national_axes_are_all_prefectures_in_code_order(self):
        axes = rf.entrant_axes(None, "national", False, [], PREFS)
        self.assertEqual(47, len(axes))
        self.assertEqual(["01", "02", "03"], [a[0] for a in axes[:3]])
        self.assertEqual("47", axes[-1][0])

    def test_regional_axes_only_member_prefectures_and_outsider_is_unknown(self):
        entry = fake_catalog()[2]
        axes = rf.entrant_axes(entry, "regional", False, [], PREFS)
        self.assertEqual([["01", "架空県01"], ["02", "架空県02"]], axes)
        rows = [{"entrants": [
            {"school_id": "FAKE-A", "prefecture_code": "02", "routes": []},
            {"school_id": "FAKE-B", "prefecture_code": "05",
             "routes": [{"competition_id": "X", "prefecture_code": "01"}]},
            {"school_id": "FAKE-C", "prefecture_code": "30", "routes": []}]}]
        shown = rf.place_entrants(rows, axes, False, only_entered=False)
        self.assertEqual(["01", "02", "unknown"], [a[0] for a in shown])
        self.assertEqual(["02", "01", "unknown"], [e["axis"] for e in rows[0]["entrants"]])

    def test_only_entered_keeps_rows_with_entrants(self):
        rows = [{"entrants": [{"school_id": "FAKE-A", "prefecture_code": "13", "routes": []}]},
                {"entrants": []}]
        axes = rf.entrant_axes(None, "national", False, [], PREFS)
        self.assertEqual([["13", "架空県13"]], rf.place_entrants(rows, axes, False, only_entered=True))
        self.assertEqual(47, len(rf.place_entrants(rows, axes, False, only_entered=False)))

    def test_summer_axes_use_qualifier_route(self):
        areas = [["Q1", "架空北"], ["Q2", "架空南"]]
        rows = [{"entrants": [{"school_id": "FAKE-A", "prefecture_code": "01",
                               "routes": [{"competition_id": "Q2", "prefecture_code": ""}]}]}]
        self.assertEqual(areas, rf.place_entrants(rows, rf.entrant_axes(None, "national", True, areas, PREFS),
                                                  True, only_entered=False))
        self.assertEqual("Q2", rows[0]["entrants"][0]["axis"])


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo = DataRepository(ROOT / "data")
        import csv
        with (ROOT / "data/competitions/prefecture_region_memberships.csv").open(encoding="utf-8-sig") as h:
            cls.memberships = list(csv.DictReader(h))
        cls.catalog = rf.build_catalog(repo.competitions, cls.memberships, _level, lambda cid, name: name)

    def test_regional_competitions_list_their_member_prefectures(self):
        for c in self.catalog:
            if c["level"] != "regional":
                continue
            expected = sorted({r["prefecture_code"] for r in self.memberships
                               if r["region_id"] == c["regions"][0] and r["season_segment"] == c["segment"]})
            self.assertEqual(expected, c["prefectures"])
            self.assertTrue(0 < len(c["prefectures"]) < 47)

    def test_every_region_and_prefecture_choice_leaves_a_competition(self):
        for segment in ("", *rf.SEGMENTS):
            f, options, _ = rf.cascade_filters(self.catalog, {"segment": segment}, {}, PREFS)
            for level, _ in options["level"]:
                _, by_level, _ = rf.cascade_filters(self.catalog, {"segment": segment, "level": level}, {}, PREFS)
                for region, _ in by_level["region"]:
                    _, by_region, pool = rf.cascade_filters(
                        self.catalog, {"segment": segment, "level": level, "region": region}, {}, PREFS)
                    self.assertTrue(pool)
                    for pref, _ in by_region["prefecture"]:
                        f, _, pool = rf.cascade_filters(self.catalog, {
                            "segment": segment, "level": level, "region": region, "prefecture": pref}, {}, PREFS)
                        self.assertEqual((region, pref), (f["region"], f["prefecture"]))
                        self.assertTrue(pool)


class TileMapTests(unittest.TestCase):
    def test_layout_covers_47_prefectures_without_overlap(self):
        import json
        config = json.loads((ROOT / "config/screen/tile_map_v1.json").read_text(encoding="utf-8"))
        tiles = config["tiles"]
        self.assertEqual(sorted(PREFS), sorted(tiles))
        self.assertEqual(47, len({tuple(pos) for pos in tiles.values()}))
        # 北海道は右上、沖縄は左下
        cols = [c for c, _ in tiles.values()]
        rows = [r for _, r in tiles.values()]
        self.assertEqual((max(cols), min(rows)), tuple(tiles["01"]))
        self.assertEqual((min(cols), max(rows)), tuple(tiles["47"]))
        # 地図の左上（地域の名前を置く場所）にはマスがない
        self.assertFalse([code for code, (c, r) in tiles.items() if c < 9 and r < 4])

    def test_regions_follow_autumn_memberships_and_names_are_short(self):
        import csv
        from phase2_engine.screen.data import GameScreenData
        from phase2_engine import LiveGameService
        repo = DataRepository(ROOT / "data")
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = LiveGameService(repo, ROOT / "data", save_root=tmp.name)
        shell = GameScreenData(service, None).shell()
        self.assertIsNone(shell["header"])  # セーブを選ぶ前でも地図は出せる
        tiles = {t["code"]: t for t in shell["tile_map"]["tiles"]}
        with (ROOT / "data/competitions/prefecture_region_memberships.csv").open(encoding="utf-8-sig") as h:
            autumn = {r["prefecture_code"]: r["region_id"] for r in csv.DictReader(h) if r["season_segment"] == "autumn"}
        self.assertEqual(autumn, {code: t["region_id"] for code, t in tiles.items()})
        self.assertEqual(sorted(set(autumn.values())), [r["region_id"] for r in shell["tile_map"]["regions"]])
        self.assertEqual(sorted(tiles), list(tiles))  # コード順（北海道〜沖縄）
        # 県名は「都・府・県」を除いた短い名前（京都府 → 京都、北海道はそのまま）
        self.assertEqual(("北海道", "東京", "京都", "大阪", "香川"),
                         tuple(tiles[c]["name"] for c in ("01", "13", "26", "27", "37")))
        for t in tiles.values():
            self.assertEqual(t["full_name"][:len(t["name"])], t["name"])
            self.assertLessEqual(len(t["name"]), 3)


class TextTests(unittest.TestCase):
    def test_edition_and_empty_hint(self):
        self.assertEqual("第109回", rf.edition("第109回架空大会"))
        self.assertEqual("", rf.edition("架空地区大会"))
        self.assertIn("未開催の年度も出す", rf.empty_hint(rows=0, hidden_upcoming=2, before_start=None, earliest=2026))
        self.assertIn("2026年度以降", rf.empty_hint(rows=0, hidden_upcoming=0,
                                                 before_start={"start": 2020, "end": 2022}, earliest=2026))
        self.assertIn("出場のあった都道府県だけ", rf.empty_hint(rows=1, hidden_upcoming=0, before_start=None,
                                                         earliest=2026, axes=0, only_entered=True))
        self.assertEqual("", rf.empty_hint(rows=1, hidden_upcoming=0, before_start=None, earliest=2026))


if __name__ == "__main__":
    unittest.main()
