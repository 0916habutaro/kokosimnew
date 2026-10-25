"""大会の日程の割り当てと、全国大会の組み合わせの形。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import tempfile
import unittest

from phase2_engine import DataRepository, LiveGameService
from phase2_engine.main_tournament import BYE_LAYOUT_PAIRED, generate_main_slots
from phase2_engine.national_day_plan import draw_separation, load_plans, match_dates, round_number
from phase2_engine.tournament_runtime import MainTournamentRuntimeState


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"


def r2_blocks(slots: list[str]) -> list[str]:
    """2回戦の組（4枠）ごとの形を上から。B＝不戦勝の枠を含む1回戦、T＝1回戦の試合。"""
    pairs = ["T" if slots[i] and slots[i + 1] else "B" for i in range(0, len(slots), 2)]
    return [pairs[i] + pairs[i + 1] for i in range(0, len(pairs), 2)]


def play_all(runtime) -> None:
    while not runtime.is_complete:
        for row in runtime.ready_matches():
            runtime.resolve_match(row["match_id"])


class PairedByeLayoutTests(unittest.TestCase):
    def test_49_teams_meet_like_the_summer_koshien(self):
        teams = [f"SCHX{i:02d}" for i in range(49)]
        slots, seeds = generate_main_slots(
            teams, seed_ids=[], base_seed=7, namespace="x",
            bye_layout=BYE_LAYOUT_PAIRED,
        )
        self.assertEqual({}, seeds)
        self.assertEqual(sorted(teams), sorted(x for x in slots if x))
        # 組み合わせ表の上に2回戦から始まる学校どうし7組、次に49校目と1回戦、
        # その下に1回戦16試合
        self.assertEqual(["BB"] * 7 + ["BT"] + ["TT"] * 8, r2_blocks(slots))
        other, _ = generate_main_slots(
            teams, seed_ids=[], base_seed=8, namespace="x",
            bye_layout=BYE_LAYOUT_PAIRED,
        )
        self.assertNotEqual(slots, other)  # 学校の位置は抽選


class RedrawTests(unittest.TestCase):
    def test_quarterfinal_and_semifinal_are_drawn_after_the_previous_round(self):
        teams = [f"SCHX{i:02d}" for i in range(49)]
        runtime = MainTournamentRuntimeState.create(
            competition_id="CMPX", reference_year=2026, generation_seed=3,
            stage_id="STGX", entrants=teams, bye_layout=BYE_LAYOUT_PAIRED,
            redraw_rounds={4: 2, 5: 1},
        )
        quarter = runtime.match_ids_by_round[4]
        while not all(
            runtime.matches[m].status == "completed"
            for m in runtime.match_ids_by_round[3]
        ):
            # 3回戦が全部終わるまで準々決勝は決まらない
            self.assertFalse(runtime.is_drawn(4))
            row = next(r for r in runtime.ready_matches() if r["round_no"] <= 3)
            runtime.resolve_match(row["match_id"])
        self.assertTrue(runtime.is_drawn(4))
        third = [runtime.matches[m].winner for m in runtime.match_ids_by_round[3]]
        # 上の4試合の勝者どうし・下の4試合の勝者どうしで対戦
        top = {runtime.matches[m].team1 for m in quarter[:2]} | {
            runtime.matches[m].team2 for m in quarter[:2]
        }
        self.assertEqual(set(third[:4]), top)
        self.assertFalse(runtime.is_drawn(5))
        play_all(runtime)
        self.assertTrue(runtime.champion_school_id)


class DayPlanTests(unittest.TestCase):
    def test_invitational_plan_fits_32_teams(self):
        plan = load_plans(DATA_ROOT)["national_invitational"]
        teams = [f"SCHX{i:02d}" for i in range(32)]
        runtime = MainTournamentRuntimeState.create(
            competition_id="CMPX", reference_year=2027, generation_seed=3,
            stage_id="STGX", entrants=teams,
        )
        dates = [f"2027-03-{day:02d}" for day in range(19, 30)]
        planned = match_dates(plan, runtime, dates)
        self.assertEqual(31, len(planned))
        per_day = Counter(planned.values())
        self.assertEqual([3, 3, 3, 3, 3, 3, 3, 3, 4, 2, 1], [per_day[d] for d in dates])
        # 1回戦は組み合わせ表の上から順
        first = [m for m in runtime.match_ids_by_round[1]]
        self.assertEqual(sorted(first[:3]), sorted(m for m, d in planned.items() if d == dates[0]))
        # 計画の日が足りない年は使わない
        self.assertEqual({}, match_dates(plan, runtime, dates[:5]))


class SeparationTests(unittest.TestCase):
    """選抜の抽選：同じ都道府県は決勝まで、同じ地区は準々決勝まで当たらない。"""

    def _keys(self):
        # 地区ごとの校数（実際の選抜に近い形）。同じ地区の中に同じ都道府県の2校を含める
        sizes = {"RA": 7, "RB": 6, "RC": 5, "RD": 4, "RE": 3, "RF": 3, "RG": 2, "RH": 1, "RI": 1}
        keys = {}
        for region, count in sizes.items():
            for i in range(count):
                keys[f"SCHX{region}{i}"] = (f"{region}-P{0 if i < 2 else i}", region)
        return keys

    def test_same_region_and_prefecture_are_kept_apart(self):
        keys = self._keys()
        self.assertEqual(32, len(keys))
        for seed in range(30):
            slots, _ = generate_main_slots(
                list(keys), seed_ids=[], base_seed=seed, namespace="x",
                separation={"keys": keys, "prefecture_block": 16, "region_block": 4},
            )
            self.assertEqual(sorted(keys), sorted(slots))
            where = {sid: index for index, sid in enumerate(slots)}
            for a in keys:
                for b in keys:
                    if a >= b:
                        continue
                    if keys[a][0] == keys[b][0]:
                        self.assertNotEqual(where[a] // 16, where[b] // 16, (seed, a, b))
                    if keys[a][1] == keys[b][1]:
                        self.assertNotEqual(where[a] // 4, where[b] // 4, (seed, a, b))
            # 2校・4校の地区は上下・4分の1に分かれる
            for region, block in (("RG", 16), ("RD", 8)):
                blocks = [where[sid] // block for sid in keys if keys[sid][1] == region]
                self.assertEqual(len(blocks), len(set(blocks)), (seed, region))

    def test_separation_uses_autumn_regions(self):
        repo = DataRepository(DATA_ROOT)
        by_pref = {}
        for sid, row in repo.schools.items():
            by_pref.setdefault(row["prefecture_code"], sid)
        codes = ["13", "14", "27"] + [c for c in sorted(by_pref) if c not in ("13", "14", "27")]
        entrants = [by_pref[code] for code in codes[:32]]
        separation = draw_separation(repo, "national_invitational", entrants)
        self.assertEqual((16, 4), (separation["prefecture_block"], separation["region_block"]))
        keys = separation["keys"]
        # 抽選では関東と東京を一つの地区として扱う
        self.assertEqual(keys[by_pref["13"]][1], keys[by_pref["14"]][1])
        self.assertNotEqual(keys[by_pref["13"]][1], keys[by_pref["27"]][1])
        self.assertIsNone(draw_separation(repo, "national_championship", entrants))


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

    def _koshien(self):
        return next(
            scheduled for cid, scheduled in self.season.competitions.items()
            if self.repo.competition(cid).get("competition_type") == "national_championship"
        )

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

    def test_koshien_teams_play_autumn_games_after_elimination(self):
        koshien = self._koshien()
        last_day = max(m.match_date for m in koshien.matches.values())
        out_on = {
            m.loser_id: m.completed_on
            for m in koshien.matches.values() if m.status == "completed"
        }
        teams = set(koshien.runtime.entrant_school_ids)
        exempt_seen = 0
        for cid, scheduled in self.season.competitions.items():
            if self.repo.competition(cid).get("season_segment") != "autumn":
                continue
            annual = getattr(scheduled.runtime, "annual", None)
            exempt = set(getattr(annual, "koshien_exempt_school_ids", []))
            codes = set(getattr(annual, "koshien_exempt_stage_codes", []))
            exempt_seen += bool(exempt)
            for match in scheduled.matches.values():
                for team in {match.team1_id, match.team2_id} & teams:
                    # 敗退した日の翌日より後（優勝・準優勝は決勝の翌日より後）
                    self.assertGreater(match.match_date, out_on.get(team, last_day), cid)
                    # 甲子園の間に始まる予選・シード決めには出ない
                    if team in exempt:
                        self.assertNotIn(match.stage_code, codes, cid)
        self.assertGreater(exempt_seen, 0)
        # 甲子園の日程は動かさない
        self.assertEqual(koshien.calendar_dates[-1], last_day)

    def test_summer_koshien_bracket_and_day_plan(self):
        from phase2_engine.screen.competition_views import main_runtime

        koshien = self._koshien()
        main = main_runtime(koshien)
        self.assertEqual(["BB"] * 7 + ["BT"] + ["TT"] * 8, r2_blocks(main.initial_slots))
        # 日ごとの試合数は計画どおり（第N日＝N番目の試合日）
        plan = load_plans(DATA_ROOT)["national_championship"]
        per_day = Counter(m.match_date for m in koshien.matches.values())
        self.assertEqual(
            [sum(count for _, count in day) for day in plan["days"]],
            [per_day[day] for day in koshien.calendar_dates],
        )
        # 第1日は49校目と当たる1回戦。2回戦は上（2回戦から始まる学校どうし）から
        first_day = [m for m in koshien.matches.values() if m.match_date == koshien.calendar_dates[0]]
        bt_round1 = main.match_ids_by_round[1][15]
        self.assertEqual([bt_round1], [m.match_id for m in first_day])
        day6 = sorted(
            (m for m in koshien.matches.values() if m.match_date == koshien.calendar_dates[5]),
            key=lambda m: (m.round_no, m.match_id),
        )
        self.assertEqual([1, 1, 2, 2], [m.round_no for m in day6])
        self.assertEqual(main.match_ids_by_round[2][:2], [m.match_id for m in day6[2:]])
        # 準々決勝は3回戦の上4試合の勝者どうし・下4試合の勝者どうし
        third = [main.matches[m].winner for m in main.match_ids_by_round[3]]
        quarter = [main.matches[m] for m in main.match_ids_by_round[4]]
        self.assertEqual(set(third[:4]), {t for m in quarter[:2] for t in (m.team1, m.team2)})
        self.assertEqual(round_number("QF", main.total_rounds), 4)


if __name__ == "__main__":
    unittest.main()
