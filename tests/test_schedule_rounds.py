"""大会の日程の割り当てと、全国大会の組み合わせの形。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.main_tournament import BYE_LAYOUT_PAIRED, generate_main_slots


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


def r2_blocks(slots: list[str]) -> Counter:
    """2回戦の組（4枠）ごとの形。B＝不戦勝の枠を含む1回戦、T＝1回戦の試合。"""
    pairs = ["T" if slots[i] and slots[i + 1] else "B" for i in range(0, len(slots), 2)]
    return Counter("".join(sorted(pairs[i:i + 2])) for i in range(0, len(pairs), 2))


class PairedByeLayoutTests(unittest.TestCase):
    def test_49_teams_meet_like_the_summer_koshien(self):
        teams = [f"SCHX{i:02d}" for i in range(49)]
        slots, seeds = generate_main_slots(
            teams, seed_ids=[], base_seed=7, namespace="x",
            bye_layout=BYE_LAYOUT_PAIRED,
        )
        self.assertEqual({}, seeds)
        self.assertEqual(sorted(teams), sorted(x for x in slots if x))
        # 1回戦17試合、2回戦は不戦勝どうし7・不戦勝と1回戦の勝者1・1回戦の勝者どうし8
        self.assertEqual({"BB": 7, "BT": 1, "TT": 8}, dict(r2_blocks(slots)))
        other, _ = generate_main_slots(
            teams, seed_ids=[], base_seed=8, namespace="x",
            bye_layout=BYE_LAYOUT_PAIRED,
        )
        self.assertNotEqual(slots, other)  # 位置は抽選


class RoundDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = DataRepository(DATA_ROOT)
        service = LiveGameService(
            cls.repo, DATA_ROOT, save_root=cls.tmp.name, autosave_after_action=False,
        )
        cls.session = service.new_game("rounds", rng_seed=11, save_initial=False)
        service.advance_through(cls.session, "2026-08-31")
        cls.season = cls.session.state.seasons[2026]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_summer_local_tournaments_use_the_whole_schedule(self):
        checked = 0
        for cid, scheduled in self.season.competitions.items():
            competition = self.repo.competition(cid)
            if competition.get("competition_type") != "summer_local_qualifier":
                continue
            rounds: dict[int, list[str]] = {}
            for match in scheduled.matches.values():
                rounds.setdefault(match.round_no, []).append(match.match_date)
            last = max(rounds)
            # 決勝は最後の試合日、準決勝はその前の試合日
            self.assertEqual([scheduled.calendar_dates[-1]], sorted(set(rounds[last])), cid)
            self.assertEqual([scheduled.calendar_dates[-2]], sorted(set(rounds[last - 1])), cid)
            # 回戦の日は重ならず、早い回戦ほど前
            for round_no in range(min(rounds), last):
                self.assertLess(max(rounds[round_no]), min(rounds[round_no + 1]), cid)
            checked += 1
        self.assertEqual(49, checked)

    def test_summer_koshien_bracket_shape(self):
        from phase2_engine.screen.competition_views import main_runtime

        koshien = next(
            scheduled for cid, scheduled in self.season.competitions.items()
            if self.repo.competition(cid).get("competition_type") == "national_championship"
        )
        main = main_runtime(koshien)
        self.assertEqual({"BB": 7, "BT": 1, "TT": 8}, dict(r2_blocks(main.initial_slots)))


if __name__ == "__main__":
    unittest.main()
