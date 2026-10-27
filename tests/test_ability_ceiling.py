"""入部品質の上の方の頭打ち（school_intake_v1 の upper_soft_cap）。"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from game_core.school_intake import SchoolAwarePlayerAbilityGenerator, soft_cap


ROOT = Path(__file__).resolve().parents[1]


class SoftCapTests(unittest.TestCase):
    def test_soft_cap_keeps_order_and_approaches_the_cap(self):
        self.assertEqual(70.0, soft_cap(70.0, 80, 100))
        values = [soft_cap(v, 80, 100) for v in range(60, 200, 5)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(v < 100 for v in values))
        self.assertGreater(soft_cap(1000, 80, 100), 99.9)
        # 傾き rate が小さいほど knee の上を強く縮める
        self.assertLess(soft_cap(130, 122, 170, 0.5), soft_cap(130, 122, 170, 1.0))

    def test_config_caps_velocity_and_scalars(self):
        caps = json.loads(
            (ROOT / "config" / "abilities" / "school_intake_v1.json").read_text(encoding="utf-8")
        )["upper_soft_cap"]
        generator = SchoolAwarePlayerAbilityGenerator(ROOT / "config" / "abilities")
        # 強い学校の入部品質（z=3.5）を足しても上限に届かない
        self.assertLess(round(generator._soft_cap(55 + 13.5 * 3.5, "scalar")), 100)
        self.assertLess(
            round(generator._soft_cap(138 + 6 * 3.5 + 16, "velocity_kmh")),
            float(caps["velocity_kmh"]["cap"]),
        )
        self.assertEqual(60.0, generator._soft_cap(60.0, "scalar"))


if __name__ == "__main__":
    unittest.main()
