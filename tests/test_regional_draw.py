"""地区大会の開催県・出場枠・組み合わせの決まり。

架空の地区・都道府県（90〜99）・学校（SCHX…）で確かめる。data/ の中身は固定しない。
"""
from __future__ import annotations

from collections import Counter
import unittest

from phase2_engine.regional_draw import (
    DrawRule, apply_host_quotas, draw_report, draw_slots, entrant_classes,
    first_game_pairs, host_of, meet_round, next_host_of,
)

HOST_ROW = {"host_2026": "91", "rotation": "91;92;93", "host_bonus": "1",
            "next_host_bonus": "1", "next_host_2026": "93"}


def feeder(pref, quota, mode="direct"):
    return {"source_type": "prefectural_result", "source_prefecture_code": pref,
            "rank_from": "1", "rank_to": str(quota), "quota": str(quota),
            "qualification_mode": mode}


def region(per_prefecture, prefectures=("91", "92", "93", "94", "95", "96")):
    """都道府県ごとに per_prefecture 校（県大会の順位の順）。"""
    rankings, prefecture_of = {}, {}
    for pref in prefectures:
        ids = [f"SCHX{pref}{i}" for i in range(per_prefecture)]
        rankings[pref] = ids + [f"SCHX{pref}9{i}" for i in range(3)]  # 出ない学校も順位にいる
        prefecture_of.update({s: pref for s in rankings[pref]})
    entrants = [s for pref in prefectures for s in rankings[pref][:per_prefecture]]
    return entrants, rankings, prefecture_of


class HostTests(unittest.TestCase):
    def test_rotation_moves_one_step_each_year_and_wraps(self):
        self.assertEqual(["91", "92", "93", "91"], [host_of(HOST_ROW, y) for y in range(2026, 2030)])
        # 2026年の次の開催県は実際の値、それ以降は順番の次
        self.assertEqual("93", next_host_of(HOST_ROW, 2026))
        self.assertEqual("93", next_host_of(HOST_ROW, 2027))
        self.assertEqual("91", next_host_of(HOST_ROW, 2028))

    def test_host_and_next_host_get_the_bonus(self):
        rules = [feeder("91", 2), feeder("92", 2), feeder("93", 2), feeder("93", 1, "playoff_candidate")]
        q2026 = [int(r["quota"]) for r in apply_host_quotas(rules, HOST_ROW, 2026)]
        self.assertEqual([3, 2, 3, 1], q2026)   # 開催91＋次の開催93。出場決定戦の候補はそのまま
        q2027 = apply_host_quotas(rules, HOST_ROW, 2027)
        self.assertEqual([2, 3, 3, 1], [int(r["quota"]) for r in q2027])
        self.assertEqual("3", q2027[1]["rank_to"])
        self.assertEqual("2", rules[1]["quota"])  # 元の行は変えない


class ClassTests(unittest.TestCase):
    def test_rank_host_and_invited(self):
        entrants, rankings, pref = region(2, ("91", "92"))
        invited = "SCHX929"
        pref[invited] = "92"
        rankings["92"] = [invited] + rankings["92"]
        classes = entrant_classes(entrants + [invited], pref, rankings, host="91", invited=[invited])
        self.assertEqual({"rank1", "host", "host_rank1"}, classes["SCHX910"])
        self.assertEqual({"rank1", "nonhost"}, classes["SCHX920"])  # 推薦校は数えない
        self.assertEqual({"invited", "nonhost"}, classes[invited])


class BracketTests(unittest.TestCase):
    def draw(self, entrants, rankings, pref, rule, host="", seed=1):
        classes = entrant_classes(entrants, pref, rankings, host=host)
        slots, relaxed = draw_slots(entrants, classes, pref, rule, base_seed=seed, namespace="REGX")
        self.assertEqual(sorted(entrants), sorted(s for s in slots if s))
        return slots, classes, relaxed

    def test_rank1_and_2_get_byes_and_rank1_never_meet_first(self):
        # 6県×3校＝18校（秋季東北の形）
        entrants, rankings, pref = region(3)
        rule = DrawRule(bye_order=("rank1", "rank2"), same_prefecture_round="QF",
                        first_game_forbid=(("rank1", "rank1"),))
        for seed in range(5):
            slots, classes, relaxed = self.draw(entrants, rankings, pref, rule, seed=seed)
            self.assertEqual(0, relaxed)
            report = draw_report(slots, classes, pref)
            self.assertEqual(14, report["byes"])
            self.assertEqual(0, report["same_prefecture_first_games"])
            self.assertEqual(0, report["rank1_first_games"])
            first_round = [s for i in range(0, 32, 2) if slots[i] and slots[i + 1]
                           for s in slots[i:i + 2]]
            self.assertTrue(all("rank3" in classes[s] for s in first_round))

    def test_same_prefecture_apart_until_the_round(self):
        entrants, rankings, pref = region(2, ("91", "92", "93", "94", "95", "96", "97", "98"))
        rule = DrawRule(same_prefecture_round="F", opening_pairs=(("rank1", "rank2"),))
        slots, classes, relaxed = self.draw(entrants, rankings, pref, rule)
        self.assertEqual(0, relaxed)
        for a, b in first_game_pairs(slots):
            self.assertEqual({"rank1", "rank2"}, {c for c in classes[a] | classes[b] if c.startswith("rank")})
        where = {s: i for i, s in enumerate(slots) if s}
        for p in set(pref[s] for s in entrants):
            a, b = [s for s in entrants if pref[s] == p]
            self.assertEqual(4, meet_round(where[a], where[b]))  # 決勝まで当たらない

    def test_host_rank1_bye_and_host_vs_champions(self):
        # 開催県1位だけ1回戦免除（15校）
        entrants, rankings, pref = region(2, ("91", "92", "93", "94", "95", "96", "97"))
        entrants.append(rankings["91"][2])
        slots, classes, _ = self.draw(entrants, rankings, pref,
                                      DrawRule(bye_order=("host_rank1",), same_prefecture_round="SF"),
                                      host="91")
        bye = [slots[i] or slots[i + 1] for i in range(0, 16, 2) if not (slots[i] and slots[i + 1])]
        self.assertEqual(["SCHX910"], bye)
        # 開催県4校対ほかの県の優勝校（8校、1回戦4試合）
        host4 = rankings["91"][:4]
        others = [rankings[p][0] for p in ("92", "93", "94", "95")]
        rule = DrawRule(same_prefecture_round="QF", opening_pairs=(("host", "rank1"),))
        slots, classes, relaxed = self.draw(host4 + others, rankings, pref, rule, host="91")
        self.assertEqual(0, relaxed)
        for a, b in first_game_pairs(slots):
            self.assertEqual(1, sum(s in host4 for s in (a, b)))

    def test_impossible_rules_are_relaxed_not_failed(self):
        entrants, rankings, pref = region(4, ("91", "92"))
        rule = DrawRule(same_prefecture_round="F")  # 2県×4校では無理
        slots, _, relaxed = self.draw(entrants, rankings, pref, rule)
        self.assertGreater(relaxed, 0)

    def test_same_input_same_draw(self):
        entrants, rankings, pref = region(3)
        rule = DrawRule(bye_order=("rank1", "rank2"), same_prefecture_round="QF")
        a = self.draw(entrants, rankings, pref, rule, seed=7)[0]
        b = self.draw(entrants, rankings, pref, rule, seed=7)[0]
        c = self.draw(entrants, rankings, pref, rule, seed=8)[0]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(Counter(), Counter(s for s in a if s) - Counter(entrants))


if __name__ == "__main__":
    unittest.main()
