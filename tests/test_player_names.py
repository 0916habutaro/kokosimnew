"""選手名と出身（game_core/player_names.py）。架空の小さなデータで確かめる。"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from game_core.player_names import PlayerNameGenerator
from phase2_engine.models import Team
from phase2_engine.randomness import rng_for


CONFIG = {
    "config_id": "player_names_v1",
    "revision": 1,
    "given_names": {"popular_count": 1, "popular_weight": 50.0, "other_weight": 1.0},
    "out_of_prefecture_rate": {
        "private": {"S": 1.0, "A": 0.5, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0},
        "public": 0.0,
    },
    "display_separator": " ",
    "max_name_attempts": 50,
}
SURNAMES = """prefecture_code,surname,count
01,北山,90
01,北川,10
02,南野,60
02,南田,40
03,西原,1
"""
SCHOOLS = """school_id,prefecture_code,ownership_type
SCH-PUB,01,prefectural
SCH-PRI,01,private
"""
PUBLIC = Team("SCH-PUB", "PRG-PUB", "架空公立高校", "01")
PRIVATE = Team("SCH-PRI", "PRG-PRI", "架空私立高校", "01")


def _root(directory: Path, *, given=("一郎", "二郎", "三郎", "四郎"), config=None) -> Path:
    (directory / "config" / "players").mkdir(parents=True)
    (directory / "config" / "players" / "player_names_v1.json").write_text(
        json.dumps(config or CONFIG, ensure_ascii=False), encoding="utf-8",
    )
    names = directory / "data" / "generation" / "player_names"
    names.mkdir(parents=True)
    (names / "surnames.csv").write_text(SURNAMES, encoding="utf-8")
    (names / "given_names.json").write_text(
        json.dumps(list(given), ensure_ascii=False), encoding="utf-8",
    )
    (directory / "data" / "master").mkdir(parents=True)
    (directory / "data" / "master" / "schools.csv").write_text(SCHOOLS, encoding="utf-8")
    return directory


class PlayerNameGeneratorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _root(Path(self._tmp.name))
        self.rank = "S"
        self.names = PlayerNameGenerator(self.root, rank_of=lambda school_id, seed: self.rank)

    def tearDown(self):
        self._tmp.cleanup()

    def _draw(self, team, count=400, seed=7):
        return [
            self.names(team, seed, rng_for(seed, f"test:{index}"), ())
            for index in range(count)
        ]

    def test_public_school_players_come_from_its_prefecture(self):
        drawn = self._draw(PUBLIC)
        self.assertEqual({"01"}, {p.hometown_prefecture_code for p in drawn})
        surnames = Counter(p.display_name.split(" ")[0] for p in drawn)
        self.assertEqual({"北山", "北川"}, set(surnames))
        # 件数の重み（90:10）
        self.assertGreater(surnames["北山"], surnames["北川"] * 4)
        self.assertTrue(all(p.name_source == "player_names_v1" for p in drawn))

    def test_private_out_of_prefecture_rate_follows_reputation_rank(self):
        drawn = self._draw(PRIVATE)
        self.assertNotIn("01", {p.hometown_prefecture_code for p in drawn})
        # 県外の出身地は苗字の件数の合計で重み付け（02 が 100、03 が 1）
        towns = Counter(p.hometown_prefecture_code for p in drawn)
        self.assertGreater(towns["02"], towns["03"] * 10)
        for p in drawn:
            expected = {"02": ("南野", "南田"), "03": ("西原",)}[p.hometown_prefecture_code]
            self.assertIn(p.display_name.split(" ")[0], expected)
        self.rank = "B"
        self.assertEqual({"01"}, {p.hometown_prefecture_code for p in self._draw(PRIVATE, 50)})
        self.rank = "A"
        away = sum(p.hometown_prefecture_code != "01" for p in self._draw(PRIVATE))
        self.assertTrue(140 < away < 260, away)

    def test_popular_given_names_are_drawn_more_often(self):
        given = Counter(p.display_name.split(" ")[1] for p in self._draw(PUBLIC))
        self.assertEqual("一郎", given.most_common(1)[0][0])
        self.assertGreater(given["一郎"], 300)
        self.assertGreater(given["二郎"] + given["三郎"] + given["四郎"], 0)

    def test_taken_names_are_avoided_and_exhaustion_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {**CONFIG, "given_names": {**CONFIG["given_names"], "popular_count": 0}}
            narrow = PlayerNameGenerator(
                _root(Path(tmp), given=("一郎", "二郎"), config=config),
                rank_of=lambda school_id, seed: "E",
            )
            taken = {"北山 一郎", "北川 一郎", "北川 二郎"}
            drawn = narrow(PUBLIC, 7, rng_for(7, "taken"), taken)
            self.assertEqual("北山 二郎", drawn.display_name)
            with self.assertRaisesRegex(ValueError, "unique"):
                narrow(PUBLIC, 7, rng_for(7, "full"), taken | {"北山 二郎"})

    def test_same_seed_gives_same_names(self):
        self.assertEqual(self._draw(PRIVATE, 30), self._draw(PRIVATE, 30))
        self.assertNotEqual(self._draw(PRIVATE, 30), self._draw(PRIVATE, 30, seed=8))


if __name__ == "__main__":
    unittest.main()
