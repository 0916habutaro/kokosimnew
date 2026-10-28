"""選手で試合をするゲームの年度の切り替え：名簿はセーブに入り、閉じた年度の名簿は
履歴に書き出して手放す（game_core/roster_book.py）。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import shutil
import pickle
import tempfile
import unittest
from unittest.mock import patch

from phase2_engine import (
    PLAYER_RESOLVER_CONTRACT,
    DataRepository,
    LiveGameService,
)
from phase2_engine.screen.data import GameScreenData
from game_core.live_members import competition_start_dates


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class PlayerCareerYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.service = LiveGameService(
            DataRepository(DATA_ROOT), DATA_ROOT, save_root=cls.tmp.name,
            resolver_contract=PLAYER_RESOLVER_CONTRACT,
            autosave_after_action=False,
        )
        session = cls.service.new_game("year", rng_seed=20261021, save_initial=False)
        cls.initial_coaches = dict(session.state.coaches.coaches)
        # 3月：選抜（2026年度）と春季県大会（2027年度、2026年度の名簿の部員）が重なる
        cls.service.advance_through(session, "2027-03-25")
        cls.service.save_game(session)
        cls.march = cls.service.load_game("year")
        cls.march_rosters = cls.march.state.rosters.years()
        # 補正の有無で4月開始の大会は結果が変わり得るため、履歴DBも別にする。
        control_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(control_tmp.cleanup)
        shutil.copytree(Path(cls.tmp.name) / "year", Path(control_tmp.name) / "year")
        control_service = LiveGameService(
            DataRepository(DATA_ROOT), DATA_ROOT, save_root=control_tmp.name,
            resolver_contract=PLAYER_RESOLVER_CONTRACT, autosave_after_action=False,
        )
        control = control_service.load_game("year")
        control.state.coaches.intake_config['max_abs_z'] = 0.0
        # 4月：春季県大会は3月の部員のまま続く。前の年度の名簿は大会が終わるまで残す
        cls.service.advance_through(cls.march, "2027-04-05")
        control_service.advance_through(control, "2027-04-05")
        old_cups = {cid for cid, day in competition_start_dates(cls.march.state.plans[2027]).items()
                    if day < date(2027, 4, 1)}
        def old_results(rows):
            return {key: value for key, value in rows.items() if key.split(':', 1)[0] in old_cups}
        cls.personnel_results_equal = old_results(cls.march.state.completed_results()) == old_results(control.state.completed_results())
        cls.personnel_details_equal = old_results(cls.march.state.pending_match_details) == old_results(control.state.pending_match_details)
        left, right = cls.march.state.rosters, control.state.rosters
        cls.personnel_reputation_equal = (left.reputation.values == right.reputation.values
                                         and left.reputation.intake_by_year == right.reputation.intake_by_year)
        cls.returning_values_equal = all(bytes(state.values) == bytes(right._states[sid][key].values)
            for sid, states in left._states.items() for key, state in states.items() if key[0] <= 2026)
        cls.new_intake_changed = any(bytes(state.values) != bytes(right._states[sid][key].values)
            for sid, states in left._states.items() for key, state in states.items() if key[0] == 2027)
        cls.growth_potential_equal = all((state.growth_type, state.potential) ==
            (right._states[sid][key].growth_type, right._states[sid][key].potential)
            for sid, states in left._states.items() for key, state in states.items())
        del control, control_service, left, right
        control_tmp.cleanup()
        cls.april_rosters = cls.march.state.rosters.years()
        cls.service.save_game(cls.march)
        cls.session = cls.service.load_game("year")
        # 入部品質は両側で有効のまま、5月1日から計算する育成力だけを比較。
        growth_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(growth_tmp.cleanup)
        shutil.copytree(Path(cls.tmp.name) / "year", Path(growth_tmp.name) / "year")
        growth_service = LiveGameService(
            DataRepository(DATA_ROOT), DATA_ROOT, save_root=growth_tmp.name,
            resolver_contract=PLAYER_RESOLVER_CONTRACT, autosave_after_action=False,
        )
        growth_control = growth_service.load_game("year")
        growth_control.state.coaches.growth_config['max_abs_delta'] = 0.0
        cls.service.advance_through(cls.session, "2027-06-10")
        growth_service.advance_through(growth_control, "2027-06-10")
        left, right = cls.session.state.rosters, growth_control.state.rosters
        cls.practice_growth_changed = any(bytes(s.values) != bytes(right._states[sid][key].values)
            for sid, rows in left._states.items() for key, s in rows.items())
        cls.practice_traits_unchanged = all((s.growth_type, s.potential) ==
            (right._states[sid][key].growth_type, right._states[sid][key].potential)
            for sid, rows in left._states.items() for key, s in rows.items())
        cls.practice_intake_unchanged = left.coaches.intake_ratings == right.coaches.intake_ratings
        cls.service.save_game(cls.session)
        cls.session = cls.service.load_game("year")
        del growth_control, growth_service, left, right
        growth_tmp.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_saved_reputation_is_shared_with_intake_after_load(self):
        rep = self.session.state.reputation
        book = self.session.state.rosters
        self.assertIs(rep, book.reputation)
        self.assertIs(book.coaches, self.session.state.coaches)
        self.assertEqual(2027, rep.updated_year)
        sid = book.schools(2027)[0]
        profile = book.ability_generator.intake_model.profile(
            school_id=sid, entry_year=2027, base_seed=book.career_seed,
        )
        self.assertAlmostEqual(rep.program_z(sid, 2027), profile.program_quality_z, places=5)
        screen = GameScreenData(self.service, self.session)
        self.assertEqual(rep.rank(sid), screen.school(sid)["reputation_rank"])
        # 保存された最新値を変えれば表示も変わる。初期評判の再計算では通らない。
        with patch.dict(rep.values, {sid: max(rep.values.values()) + 1}):
            self.assertEqual("S", screen.school(sid)["reputation_rank"])

    def test_coaches_survive_year_boundary_and_reload(self):
        self.assertLessEqual(set(self.initial_coaches), set(self.session.state.coaches.coaches))
        self.assertEqual(2027, self.session.state.coaches.updated_year)
        for cid, coach in self.initial_coaches.items():
            new = self.session.state.coaches.coaches[cid]
            for field in ("display_name", "birth_year", "reputation", "development", "pitching_change", "player_selection"):
                self.assertEqual(getattr(coach, field), getattr(new, field))
        sid = next(iter(self.initial_coaches.values())).school_id
        coach = self.session.state.coaches.for_school(sid)
        shown = GameScreenData(self.service, self.session).school(sid)["coach"]
        self.assertEqual(coach.coach_id, shown["coach_id"])
        self.assertEqual(2027 - coach.birth_year, shown["age"])
        self.assertEqual(2027 - coach.appointment_year + 1, shown["tenure_years"])

    def test_coach_intake_changes_freshmen_only_and_preserves_old_cups_and_potential(self):
        self.assertTrue(self.personnel_results_equal)
        self.assertTrue(self.personnel_details_equal)
        self.assertTrue(self.personnel_reputation_equal)
        self.assertTrue(self.returning_values_equal)
        self.assertTrue(self.new_intake_changed)
        self.assertTrue(self.growth_potential_equal)

    def test_practice_growth_starts_after_april_and_is_saved_with_intake_unchanged(self):
        self.assertEqual(date(2027, 3, 1), self.march.state.rosters.grown_through)
        self.assertTrue(self.practice_growth_changed)
        self.assertTrue(self.practice_traits_unchanged)
        self.assertTrue(self.practice_intake_unchanged)
        self.assertEqual(date(2027, 5, 1), self.session.state.rosters.grown_through)
        self.assertEqual(.10, self.session.state.coaches.growth_config['max_abs_delta'])
        self.assertIs(self.session.state.rosters.coaches, self.session.state.coaches)

    def test_coach_screen_reads_live_saved_and_transferred_people_without_mutation(self):
        state=self.session.state
        before=pickle.dumps((state.coaches.__getstate__(),state.rosters.__getstate__()))
        screen=GameScreenData(self.service,self.session)
        coach=next(iter(self.initial_coaches.values()))
        d=screen.coach(coach.coach_id)
        rows=screen.school_coaches(coach.school_id)
        self.assertEqual(coach.display_name,d['name'])
        self.assertEqual(coach.coach_id,rows['coaches'][0]['coach_id'])
        self.assertEqual(before,pickle.dumps((state.coaches.__getstate__(),state.rosters.__getstate__())))

    def test_previous_roster_is_kept_until_its_competitions_end(self):
        self.assertEqual([2026], self.march_rosters)
        self.assertIn(2026, self.april_rosters)
        rosters = self.session.state.rosters
        self.assertEqual([2027], rosters.years())
        self.assertEqual(2026, rosters.closed_through)

    def test_closed_year_names_come_from_the_history(self):
        archived = self.service.closed_roster("year", 2026, "SCH000001")
        self.assertEqual(20, len(archived))
        # 年度末の能力と成長の型も残る
        self.assertTrue(all(row["abilities"] and row["growth_type"] for row in archived))
        # 終わった大会の試合の記録はまとめて圧縮してある
        self.assertTrue(self.service._history_archive("year").packed_competitions(2026))
        screen = GameScreenData(self.service, self.session)
        matches = self.service._history_archive("year").match_index(2026)
        row = next(
            m for m in matches
            if "SCH000001" in (m["team1_id"], m["team2_id"]) and m["team1_score"] is not None
        )
        detail = screen.match(2026, row["competition_id"], row["match_id"])
        names = [b["name"] for rows in detail["batting"].values() for b in rows]
        self.assertTrue(names)
        self.assertTrue(all(" " in name for name in names))

    def test_returning_players_keep_their_name_and_hometown(self):
        archived = {
            row["player_id"]: row
            for row in self.service.closed_roster("year", 2026, "SCH000001")
        }
        now = self.session.state.rosters.roster(2027, "SCH000001").players
        returning = [p for p in now if p.player_id in archived]
        self.assertEqual(12, len(returning))
        for player in returning:
            self.assertEqual(archived[player.player_id]["display_name"], player.display_name)
            self.assertEqual(
                archived[player.player_id]["hometown_prefecture_code"],
                player.hometown_prefecture_code,
            )

    def test_player_screen_shows_growth_trend_and_seasons(self):
        screen = GameScreenData(self.service, self.session)
        archived = self.service.closed_roster("year", 2026, "SCH000001")
        returning = next(row for row in archived if row["academic_year"] == 2)
        player = screen.player("SCH000001", returning["player_id"])
        self.assertEqual(returning["display_name"], player["name"])
        self.assertEqual(3, player["grade"])
        self.assertEqual("在学", player["status"])
        self.assertIn(player["growth_type"], ("早熟", "普通", "晩成"))
        self.assertTrue(player["hometown"])
        self.assertTrue(player["abilities"])
        # 2026年度末（2年）と今（3年）の能力
        self.assertEqual(
            [(2026, 2, "年度末"), (2027, 3, "今")],
            [(t["school_year"], t["grade"], t["label"]) for t in player["trend"]],
        )
        # 開始前の年度（2026年3月の大会）から
        self.assertEqual([2025, 2026, 2027], [s["school_year"] for s in player["seasons"]])
        self.assertTrue(any(s["batting"] or s["pitching"] for s in player["seasons"]))
        graduate = next(row for row in archived if row["academic_year"] == 3)
        old = screen.player("SCH000001", graduate["player_id"])
        self.assertEqual("卒業", old["status"])
        self.assertEqual([], old["abilities"])
        # 卒業した選手は今の怪我はなく、履歴は名簿の記録から出す
        self.assertIsNone(old["injury"])
        self.assertIsInstance(old["injuries"], list)
        self.assertEqual([2026], [t["school_year"] for t in old["trend"]])


if __name__ == "__main__":
    unittest.main()
