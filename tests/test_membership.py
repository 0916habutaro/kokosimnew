"""部員：入学・引退・卒業と、大会ごとの出場メンバー（game_definition.md §8）。"""
from __future__ import annotations

from datetime import date
import unittest

from game_core.abilities import PlayerAbilityGenerator
from game_core.membership import (
    RosterBook,
    SchoolMembers,
    summer_end_dates,
)
from game_core.team_strength import TeamStrengthGenerator
from phase2_engine.models import Team
from phase2_engine.school_year import school_year_of


TEAM = Team(
    school_id="SCH-TEST",
    program_id="PRG-TEST",
    display_name="架空高校",
    prefecture_code="99",
)


def _book():
    return RosterBook(lambda school_id: TEAM, first_year=2026, career_seed=7)


class SchoolYearOfTests(unittest.TestCase):
    def test_april_starts_a_new_school_year(self):
        self.assertEqual(2025, school_year_of(date(2026, 3, 31)))
        self.assertEqual(2026, school_year_of(date(2026, 4, 1)))


class MembersByDateTests(unittest.TestCase):
    def setUp(self):
        self.book = _book()
        self.summer_end = {}
        self.members = SchoolMembers(
            self.book,
            lambda year, school: self.summer_end.get((year, school)),
        )

    def grades(self, players):
        return sorted(p.academic_year for p in players)

    def test_third_years_retire_after_their_summer(self):
        before = self.members.members_on("SCH-TEST", date(2026, 7, 20))
        self.assertEqual(20, len(before))
        self.summer_end[(2026, "SCH-TEST")] = date(2026, 7, 20)
        # 負けた日まではまだ部員
        self.assertEqual(
            20, len(self.members.members_on("SCH-TEST", date(2026, 7, 20)))
        )
        after = self.members.members_on("SCH-TEST", date(2026, 7, 21))
        self.assertNotIn(3, self.grades(after))
        self.assertEqual(12, len(after))

    def test_graduation_march_31_and_entrance_april_1(self):
        self.summer_end[(2026, "SCH-TEST")] = date(2026, 7, 20)
        march = self.members.members_on("SCH-TEST", date(2027, 3, 31))
        april = self.members.members_on("SCH-TEST", date(2027, 4, 1))
        self.assertEqual(
            {p.player_id for p in march},
            {p.player_id for p in april if p.academic_year >= 2},
        )
        newcomers = [p for p in april if p.academic_year == 1]
        self.assertEqual(8, len(newcomers))
        self.assertTrue(all(p.entry_year == 2027 for p in newcomers))
        self.assertEqual(20, len(april))

    def test_competition_members_are_fixed_at_start(self):
        self.summer_end[(2026, "SCH-TEST")] = date(2026, 7, 20)
        # 3月に始まり4月まで続く春の大会：新入生は入らない
        spring = self.members.competition_members(
            "CMP-TEST", "SCH-TEST",
            start_date=date(2027, 3, 25), season_segment="spring",
        )
        self.assertEqual(2026, spring.roster_year)
        self.assertEqual([1] * 5 + [2] * 7, self.grades(spring.players))

    def test_autumn_is_played_by_the_new_team(self):
        # 甲子園の途中で秋の県大会が始まっても3年生は出ない
        autumn = self.members.competition_members(
            "CMP-TEST", "SCH-TEST",
            start_date=date(2026, 8, 15), season_segment="autumn",
        )
        self.assertNotIn(3, self.grades(autumn.players))
        summer = self.members.competition_members(
            "CMP-TEST", "SCH-TEST",
            start_date=date(2026, 8, 6), season_segment="summer",
        )
        self.assertEqual(20, len(summer.players))

    def test_march_before_the_first_year_uses_returning_players(self):
        march = self.members.members_on("SCH-TEST", date(2026, 3, 20))
        first = self.book.roster(2026, "SCH-TEST")
        self.assertEqual(
            {p.player_id for p in first.players if p.academic_year >= 2},
            {p.player_id for p in march},
        )
        self.assertEqual([1] * 7 + [2] * 8, self.grades(march))


class SummerEndTests(unittest.TestCase):
    def test_loser_ends_on_loss_and_champion_when_final_completes(self):
        results = {
            "a": {"competition_id": "LOCAL", "match_date": "2026-07-10",
                  "team1_id": "A", "team2_id": "B",
                  "winner_id": "A", "loser_id": "B"},
            "b": {"competition_id": "NATIONAL", "match_date": "2026-08-20",
                  "team1_id": "A", "team2_id": "C",
                  "winner_id": "A", "loser_id": "C"},
            "c": {"competition_id": "SPRING", "match_date": "2026-05-01",
                  "team1_id": "D", "team2_id": "A",
                  "winner_id": "D", "loser_id": "A"},
        }
        ends = summer_end_dates(results, {"LOCAL", "NATIONAL"})
        self.assertEqual(date(2026, 7, 10), ends["B"])
        self.assertEqual(date(2026, 8, 20), ends["C"])
        self.assertNotIn("A", ends)
        ends = summer_end_dates(
            results, {"LOCAL", "NATIONAL"}, {"NATIONAL"}
        )
        self.assertEqual(date(2026, 8, 20), ends["A"])
        self.assertNotIn("D", ends)


class SmallRosterLineupTests(unittest.TestCase):
    """引退後など部員が少なくても先発と投手陣を組める。"""

    @classmethod
    def setUpClass(cls):
        cls.abilities = PlayerAbilityGenerator()
        cls.teams = TeamStrengthGenerator()
        cls.roster = _book().roster(2026, "SCH-TEST")

    def snapshots(self, players):
        return [self.abilities.generate(p, 2026, 7) for p in players]

    def test_new_team_after_retirement(self):
        players = [p for p in self.roster.players if p.academic_year != 3]
        team = self.teams.generate(self.snapshots(players))
        self.assertEqual(9, len(team.starting_lineup.entries))
        self.assertEqual(len(players), team.roster_size)

    def test_missing_positions_and_no_pitcher(self):
        nonpitchers = [
            p for p in self.roster.players if p.primary_position != "P"
        ]
        # 一塁手も捕手もいない9人
        players = [
            p for p in nonpitchers if p.primary_position not in ("1B", "C")
        ][:9]
        team = self.teams.generate(self.snapshots(players))
        positions = {
            e.defensive_position for e in team.starting_lineup.entries
        }
        self.assertEqual(9, len(positions))
        self.assertEqual(1, len(team.pitching_staff.entries))
        self.assertEqual(
            team.starting_lineup.player_for_position("P"),
            team.pitching_staff.entries[0].player_id,
        )


    def test_team_without_pitchers_can_play_a_game(self):
        from game_core.match_contract import (
            MatchSimulationInput,
            TeamMatchInput,
        )
        from game_core.match_simulator import MatchSimulator

        def team(players):
            snapshots = tuple(self.snapshots(players))
            return TeamMatchInput(
                school_id="SCH-TEST",
                team_strength=self.teams.generate(snapshots),
                player_abilities=snapshots,
            )

        short = [
            p for p in self.roster.players if p.primary_position != "P"
        ][:10]
        other = RosterBook(
            lambda school_id: Team("SCH-OTHER", "PRG-OTHER", "架空第二高校", "99"),
            first_year=2026, career_seed=7,
        ).roster(2026, "SCH-OTHER")
        other_team = TeamMatchInput(
            school_id="SCH-OTHER",
            team_strength=self.teams.generate(self.snapshots(other.players)),
            player_abilities=tuple(self.snapshots(other.players)),
        )
        result = MatchSimulator().simulate(MatchSimulationInput(
            match_id="M1", competition_id="CMP-TEST", reference_year=2026,
            generation_seed=7, team1=team(short), team2=other_team,
            team_generation_seed=7,
        ))
        self.assertIn(result.winner_id, {"SCH-TEST", "SCH-OTHER"})


class _Entry:
    def __init__(self, segment, ctype="x"):
        self.season_segment = segment
        self.competition_type = ctype


class _Done:
    is_complete = True


class _State:
    def __init__(self, results):
        self.current_date = date(2026, 9, 1)
        self.history = []
        self.competitions = {"NATIONAL": _Done()}
        self._results = results

    def completed_results(self):
        return self._results


class LiveSeasonMembersTests(unittest.TestCase):
    def test_start_dates_and_summer_retirement_from_results(self):
        from game_core.live_members import LiveSeasonMembers

        class Plan:
            year = 2026
            calendar_rows = [
                {"competition_id": "LOCAL", "start_date": "2026-07-01",
                 "game_date_list": "2026-07-01;2026-07-10"},
                {"competition_id": "NATIONAL", "start_date": "2026-08-05",
                 "game_date_list": "2026-08-05"},
                {"competition_id": "AUTUMN", "start_date": "2026-09-20",
                 "game_date_list": "2026-09-20"},
                {"competition_id": "SPRING", "start_date": "2026-04-20",
                 "game_date_list": "2026-04-20"},
            ]
            # 予選の日程が本大会より前にある
            stage_calendar_rows = [
                {"competition_id": "AUTUMN", "date_list": "2026-08-10"},
            ]
            entries = {
                "LOCAL": _Entry("summer"),
                "NATIONAL": _Entry("summer", "national_championship"),
                "AUTUMN": _Entry("autumn"),
                "SPRING": _Entry("spring"),
            }

        live = LiveSeasonMembers(Plan(), _book())
        self.assertEqual(date(2026, 8, 10), live.starts["AUTUMN"])
        live.attach(_State({
            "m": {"competition_id": "LOCAL", "match_date": "2026-07-10",
                  "team1_id": "SCH-TEST", "team2_id": "SCH-X",
                  "winner_id": "SCH-X", "loser_id": "SCH-TEST"},
        }))
        self.assertEqual(
            20, len(live.members_on("SCH-TEST", date(2026, 7, 10)))
        )
        self.assertEqual(
            12, len(live.members_on("SCH-TEST", date(2026, 7, 11)))
        )
        spring = live("SPRING", "SCH-TEST")
        self.assertEqual(20, len(spring.players))
        autumn = live("AUTUMN", "SCH-TEST")
        self.assertEqual(12, len(autumn.players))
        # 一度決めたメンバーは固定
        self.assertIs(autumn, live("AUTUMN", "SCH-TEST"))


if __name__ == "__main__":
    unittest.main()
