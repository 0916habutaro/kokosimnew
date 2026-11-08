"""連合チーム（game_core/joint_teams.py）：組める条件・相手の選び方・不参加・代表校・
大会の入力からの除外・勝ち進んだ大会での扱い・成績（評判）の付け方。架空の学校で確かめる。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

from game_core.annual_reputation import AnnualReputation
from game_core.joint_teams import (
    JointTeam, UnionPlan, apply_to_annual, form_unions, joint_team_config, team_name,
)
from phase2_engine.models import AnnualCompetitionInput

ROOT = Path(__file__).resolve().parents[1]


def plan(entrants, players, **kwargs):
    return form_unions("CUP", entrants, players, seed=7, **kwargs)


class FormUnionsTests(unittest.TestCase):
    def test_only_schools_with_eight_or_fewer_join(self):
        rule = joint_team_config()
        self.assertEqual(8, rule["eligible_max_players"])
        self.assertEqual(9, rule["team_min_players"])
        result = plan(["A", "B", "C"], {"A": 4, "B": 6, "C": 9})
        self.assertEqual((JointTeam("B", ("B", "A")),), result.teams)
        # 9人いる学校は単独で出る
        self.assertNotIn("C", {s for team in result.teams for s in team.schools})
        self.assertEqual((), result.absent)

    def test_near_schools_are_chosen_first(self):
        branch = {"A": "north", "B": "south", "C": "north", "D": "south"}.get
        town = {"A": "town1", "B": "town1", "C": "town2", "D": "town2"}.get
        players = {"A": 4, "B": 5, "C": 5, "D": 5}
        result = plan(["A", "B", "C", "D"], players, branch_of=branch, municipality_of=town)
        first = next(team for team in result.teams if "A" in team.schools)
        # 同じ支部・地区（C）を、同じ市町村（B）より先に選ぶ
        self.assertIn("C", first.schools)
        result = plan(["A", "B", "C", "D"], players, municipality_of=town)
        first = next(team for team in result.teams if "A" in team.schools)
        self.assertIn("B", first.schools)

    def test_schools_that_cannot_reach_nine_do_not_play(self):
        result = plan(["A", "B", "C"], {"A": 3, "B": 4, "C": 0})
        self.assertEqual((), result.teams)
        self.assertEqual(("A", "B", "C"), result.absent)
        # 4校まで集めても届かなければ出ない
        many = {f"S{n}": 1 for n in range(6)}
        self.assertEqual((), plan(list(many), many).teams)

    def test_leftover_school_joins_a_union_with_room(self):
        result = plan(["A", "B", "C", "D"], {"A": 3, "B": 5, "C": 6, "D": 8})
        self.assertEqual(1, len(result.teams))
        self.assertEqual({"A", "B", "C", "D"}, set(result.teams[0].schools))
        self.assertEqual((), result.absent)

    def test_lead_is_the_seeded_school_or_the_largest(self):
        players = {"A": 4, "B": 7}
        self.assertEqual("B", plan(["A", "B"], players).teams[0].lead)
        self.assertEqual("A", plan(["A", "B"], players, preferred={"A"}).teams[0].lead)
        team = plan(["A", "B"], players).teams[0]
        self.assertEqual("乙・甲", team_name(team, {"A": "甲", "B": "乙"}.get))

    def test_same_input_gives_the_same_unions(self):
        players = {f"S{n}": 2 + n % 6 for n in range(20)}
        first = form_unions("CUP", list(players), players, seed=3)
        self.assertEqual(first, form_unions("CUP", list(players), players, seed=3))


class ApplyToAnnualTests(unittest.TestCase):
    def test_partners_and_absent_schools_leave_every_list(self):
        annual = AnnualCompetitionInput(
            competition_id="CUP", year=2027, entrant_school_ids=["A", "B", "C", "D"],
            rng_seed=1, direct_main_entry_school_ids=["A"],
            group_entrant_school_ids={"G1": ["A", "B"], "G2": ["C", "D"]},
            group_pool_assignments={"G2": [["C", "D"]]},
            main_bracket_slots=["A", "B", "C", "D"],
        )
        result = apply_to_annual(annual, UnionPlan((JointTeam("A", ("A", "B")),), ("D",)))
        self.assertEqual(["A", "C"], result.entrant_school_ids)
        self.assertEqual(["A"], result.direct_main_entry_school_ids)
        self.assertEqual({"G1": ["A"], "G2": ["C"]}, result.group_entrant_school_ids)
        self.assertEqual({"G2": [["C"]]}, result.group_pool_assignments)
        self.assertEqual(["A", "", "C", ""], result.main_bracket_slots)
        # 元の入力は変えない（4月1日に組み直すときに使う）
        self.assertEqual(["A", "B", "C", "D"], annual.entrant_school_ids)
        self.assertIs(annual, apply_to_annual(annual, UnionPlan()))


class _Entry:
    def __init__(self, segment, ctype):
        self.season_segment = segment
        self.competition_type = ctype


class AdvanceAndMembersTests(unittest.TestCase):
    """連合で勝ち進んだ大会（地区大会など）も同じ連合の部員で出る。"""

    def setUp(self):
        from game_core.live_members import LiveSeasonMembers
        from game_core.roster_book import RosterBook
        from phase2_engine.models import Team

        teams = {sid: Team(sid, "P-" + sid, "架空高校" + sid[-1], "13") for sid in ("SCH-A", "SCH-B")}
        self.book = RosterBook(teams.__getitem__, first_year=2026, career_seed=7)

        class Plan:
            year = 2026
            rng_seed = 7
            calendar_rows = [
                {"competition_id": "PREF", "start_date": "2026-09-01", "game_date_list": "2026-09-01"},
                {"competition_id": "REGION", "start_date": "2026-10-20", "game_date_list": "2026-10-20"},
                {"competition_id": "SUMMER", "start_date": "2026-07-01", "game_date_list": "2026-07-01"},
            ]
            stage_calendar_rows = []
            entries = {
                "PREF": _Entry("autumn", "autumn_prefectural"),
                "REGION": _Entry("autumn", "autumn_regional"),
                "SUMMER": _Entry("summer", "summer_local_qualifier"),
            }

        self.live = LiveSeasonMembers(Plan(), self.book)
        self.state = SimpleNamespace(
            current_date=date(2026, 10, 20), history=[], competitions={}, bench_members={},
            union_plans={"PREF": UnionPlan((JointTeam("SCH-A", ("SCH-A", "SCH-B")),))},
        )
        self.live.attach(self.state)

    def test_union_continues_into_the_regional_competition(self):
        self.assertEqual(("SCH-A", "SCH-B"), self.live.union_for("REGION", "SCH-A").schools)
        self.assertIsNone(self.live.union_for("REGION", "SCH-B"))
        # 夏は別のつながり（秋の連合は使わない）
        self.assertIsNone(self.live.union_for("SUMMER", "SCH-A"))
        members = self.live("REGION", "SCH-A").players
        schools = {p.school_id for p in members}
        self.assertEqual({"SCH-A", "SCH-B"}, schools)
        own = [p for p in self.book.roster(2026, "SCH-B").players if p.academic_year < 3]
        self.assertTrue({p.player_id for p in own} & {p.player_id for p in members}
                        or len(members) == 20)

    def test_union_is_not_formed_before_the_roster_exists(self):
        self.book.set_today(date(2026, 11, 1))
        self.assertTrue(self.book.can_build(2026))
        self.assertFalse(self.book.can_build(2027))


class UnionReputationTests(unittest.TestCase):
    def test_union_result_counts_for_every_member_school(self):
        book = AnnualReputation(ROOT, 7)
        book.values = {"SCH-A": 0.0, "SCH-B": 0.0, "SCH-C": 0.0}
        book.intake_by_year = {2026: dict(book.values)}
        outcome = SimpleNamespace(
            champion_school_id="SCH-A", runner_up_school_id="SCH-C",
            semifinalist_school_ids=[], quarterfinalist_school_ids=[],
        )
        run = SimpleNamespace(entrant_school_ids=["SCH-A", "SCH-C"], outcome=outcome)
        cup = SimpleNamespace(is_complete=True, to_competition_run=lambda: run,
                              matches={"final": SimpleNamespace(completed_on="2026-07-20")})
        season = SimpleNamespace(
            competitions={"CUP": cup},
            repo=SimpleNamespace(competitions={"CUP": {"competition_type": "summer_local_qualifier"}}),
            union_plans={"CUP": UnionPlan((JointTeam("SCH-A", ("SCH-A", "SCH-B")),))},
        )
        book.collect({2026: season})
        points = book.pending[(2026, "CUP")][1]
        self.assertEqual(points["SCH-A"], points["SCH-B"])
        self.assertGreater(points["SCH-B"], points["SCH-C"])


if __name__ == "__main__":
    unittest.main()


class UnionMatchTests(unittest.TestCase):
    """連合チームの試合：構成校の選手をまとめて代表校のチームとして出る。成績・経験は選手の学校に付く。"""

    def test_union_team_plays_and_players_keep_their_school(self):
        from types import SimpleNamespace as NS

        from test_fielding_experience import make_bridge, short_game
        from test_roster_book import TEAMS

        book, bridge = make_bridge()
        a, b = TEAMS
        own = book.roster(2026, a).players[:5]
        other = book.roster(2026, b).players[:6]
        solo = book.roster(2026, b).players[6:20]
        bridge.member_provider = lambda cid, sid: NS(players=tuple(own + other) if sid == a else tuple(solo))
        team = bridge.team_input(school_id=a, reference_year=2026, generation_seed=7,
                                 competition_id="FAKE-EXPERIENCE-2026")
        self.assertEqual({a}, {s.school_id for s in team.player_abilities})
        self.assertEqual({p.player_id for p in own + other}, {s.player_id for s in team.player_abilities})
        result = short_game(bridge)
        bridge._record_games(result.competition_id, result)
        played = {s.player_id for s in result.batter_stats if s.plate_appearances} | {
            pid for t in result.team_participation if t.school_id == a for pid in t.fielding_player_ids}
        partner = [p for p in other if p.player_id in played]
        self.assertTrue(partner)
        for player in partner:
            # 名簿上は構成校の選手のまま、試合の経験が付く
            self.assertEqual(b, player.school_id)
            self.assertEqual(1, book.state(player).games)
