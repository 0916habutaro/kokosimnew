"""部員：入学・引退・卒業と、大会ごとの出場メンバー（game_definition.md §8）。"""
from __future__ import annotations

from datetime import date
import unittest
import unittest.mock

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
    prefecture_code="13",
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
        roster = self.book.roster(2026, "SCH-TEST").players
        before = self.members.members_on("SCH-TEST", date(2026, 7, 20))
        self.assertEqual(len(roster), len(before))
        self.summer_end[(2026, "SCH-TEST")] = date(2026, 7, 20)
        # 負けた日まではまだ部員
        self.assertEqual(
            len(roster), len(self.members.members_on("SCH-TEST", date(2026, 7, 20)))
        )
        after = self.members.members_on("SCH-TEST", date(2026, 7, 21))
        self.assertNotIn(3, self.grades(after))
        self.assertEqual(sum(p.academic_year < 3 for p in roster), len(after))

    def test_graduation_march_31_and_entrance_april_1(self):
        self.summer_end[(2026, "SCH-TEST")] = date(2026, 7, 20)
        march = self.members.members_on("SCH-TEST", date(2027, 3, 31))
        april = self.members.members_on("SCH-TEST", date(2027, 4, 1))
        self.assertEqual(
            {p.player_id for p in march},
            {p.player_id for p in april if p.academic_year >= 2},
        )
        newcomers = [p for p in april if p.academic_year == 1]
        self.assertGreaterEqual(len(newcomers), 1)
        self.assertTrue(all(p.entry_year == 2027 for p in newcomers))
        self.assertEqual(len(self.book.roster(2027, "SCH-TEST").players), len(april))

    def test_competition_members_are_fixed_at_start(self):
        self.summer_end[(2026, "SCH-TEST")] = date(2026, 7, 20)
        # 3月に始まり4月まで続く春の大会：新入生は入らない
        spring = self.members.competition_members(
            "CMP-TEST", "SCH-TEST",
            start_date=date(2027, 3, 25), season_segment="spring",
        )
        self.assertEqual(2026, spring.roster_year)
        first = self.book.roster(2026, "SCH-TEST").players
        self.assertEqual(sorted(p.academic_year for p in first if p.academic_year < 3),
                         self.grades(spring.players))

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
        self.assertEqual(len(self.book.roster(2026, "SCH-TEST").players), len(summer.players))

    def test_march_before_the_first_year_uses_returning_players(self):
        march = self.members.members_on("SCH-TEST", date(2026, 3, 20))
        first = self.book.roster(2026, "SCH-TEST")
        self.assertEqual(
            {p.player_id for p in first.players if p.academic_year >= 2},
            {p.player_id for p in march},
        )
        self.assertEqual(sorted(p.academic_year - 1 for p in first.players if p.academic_year >= 2),
                         self.grades(march))


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
            lambda school_id: Team("SCH-OTHER", "PRG-OTHER", "架空第二高校", "13"),
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


class _Match:
    status = "completed"

    def __init__(self, match_date, team1_id, team2_id, loser_id):
        self.match_date = match_date
        self.team1_id = team1_id
        self.team2_id = team2_id
        self.loser_id = loser_id


class _Competition:
    def __init__(self, matches=(), is_complete=True):
        self.matches = dict(enumerate(matches))
        self.is_complete = is_complete


class _State:
    def __init__(self, competitions):
        self.current_date = date(2026, 9, 1)
        self.history = []
        self.competitions = competitions
        self.bench_members = {}


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

        book = _book()
        roster = book.roster(2026, "SCH-TEST").players
        live = LiveSeasonMembers(Plan(), book)
        self.assertEqual(date(2026, 8, 10), live.starts["AUTUMN"])
        state = _State({
            "LOCAL": _Competition([
                _Match("2026-07-10", "SCH-TEST", "SCH-X", "SCH-TEST"),
            ]),
            "NATIONAL": _Competition(),
        })
        live.attach(state)
        new_team = sum(p.academic_year < 3 for p in roster)
        self.assertEqual(
            len(roster), len(live.members_on("SCH-TEST", date(2026, 7, 10)))
        )
        self.assertEqual(
            new_team, len(live.members_on("SCH-TEST", date(2026, 7, 11)))
        )
        # 部員が多いときは大会ごとにベンチ入りの20人
        spring = live("SPRING", "SCH-TEST")
        self.assertEqual(min(20, len(roster)), len(spring.players))
        autumn = live("AUTUMN", "SCH-TEST")
        self.assertEqual(min(20, new_team), len(autumn.players))
        self.assertNotIn(3, self.grades_of(autumn.players))
        # 全員が入る大会も大会ごとに記録する（画面が前の大会のベンチ入りを出さない）
        for cid, players in (("SPRING", spring.players), ("AUTUMN", autumn.players)):
            saved = state.bench_members[f"{cid}:SCH-TEST"]
            if len(players) < 20 or saved == ():
                self.assertEqual((), saved)
            else:
                self.assertEqual(tuple(p.player_id for p in players), saved)
        # 一度決めたメンバーは固定。状態に入るので読み込み直しても同じ
        self.assertIs(autumn, live("AUTUMN", "SCH-TEST"))
        again = LiveSeasonMembers(Plan(), book)
        again.attach(state)
        if len(roster) > 20:
            self.assertIn("SPRING:SCH-TEST", state.bench_members)
            with unittest.mock.patch.object(book, "ability", side_effect=AssertionError):
                self.assertEqual(spring.players, again("SPRING", "SCH-TEST").players)

    def test_small_team_records_that_everyone_is_on_the_bench(self):
        from types import SimpleNamespace

        from game_core.live_members import ALL_MEMBERS, LiveSeasonMembers
        from game_core.membership import CompetitionMembers

        book = _book()
        plan = SimpleNamespace(year=2026, calendar_rows=[], stage_calendar_rows=[], entries={})
        live = LiveSeasonMembers(plan, book)
        state = _State({})
        live.attach(state)
        players = tuple(book.roster(2026, "SCH-TEST").players)
        small = CompetitionMembers("AUTUMN", "SCH-TEST", date(2026, 9, 20), 2026, players[:15])
        self.assertEqual(small, live._bench(small))
        # 夏の大会で20人を選んでいても、秋の大会は「全員」として記録する
        self.assertEqual(ALL_MEMBERS, state.bench_members["AUTUMN:SCH-TEST"])
        big = CompetitionMembers("SUMMER", "SCH-TEST", date(2026, 7, 1), 2026, players[:30])
        self.assertEqual(20, len(live._bench(big).players))
        self.assertEqual(20, len(state.bench_members["SUMMER:SCH-TEST"]))

    @staticmethod
    def grades_of(players):
        return sorted(p.academic_year for p in players)


if __name__ == "__main__":
    unittest.main()


class ScreenBenchMarkTests(unittest.TestCase):
    """学校の詳細の部員の◎：大会開始日の出場メンバーから付ける（今日の部員ではない）。"""

    def setUp(self):
        from types import SimpleNamespace

        from game_core.live_members import LiveSeasonMembers
        from game_core.roster_size import roster_size_model

        # 部員が全員ベンチ入りする（記録が「全員」になる）ように、ベンチの人数を大きくする
        bench = roster_size_model().config["bench"]
        patcher = unittest.mock.patch.dict(bench, {"size": 500})
        patcher.start()
        self.addCleanup(patcher.stop)

        class Plan:
            year = 2026
            calendar_rows = [
                {"competition_id": "SUMMER", "start_date": "2026-07-01",
                 "game_date_list": "2026-07-01"},
                # 3月に始まり4月まで続く春の大会（翌年度の大会だが、2026年度の名簿の部員）
                {"competition_id": "SPRING", "start_date": "2027-03-25",
                 "game_date_list": "2027-03-25"},
            ]
            stage_calendar_rows = []
            entries = {"SUMMER": _Entry("summer"), "SPRING": _Entry("spring")}

        self.Plan = Plan
        self.book = _book()
        self.state = _State({
            "SUMMER": _Competition([_Match("2026-07-10", "SCH-TEST", "SCH-X", "SCH-TEST")]),
        })
        self.live = LiveSeasonMembers(Plan(), self.book)
        self.live.attach(self.state)
        self.state.engine = SimpleNamespace(
            main_match_resolver=SimpleNamespace(member_provider=self.live))

    def info(self, rows, today, state=None):
        from types import SimpleNamespace

        from phase2_engine.screen.data import GameScreenData

        state = state or self.state
        state.current_date = today
        screen = SimpleNamespace(state=state, _competition_name=lambda season, cid, fallback: cid)
        rows = [{"player_id": p.player_id} for p in rows]
        return GameScreenData._bench_info(screen, "SCH-TEST", rows), rows

    def test_freshmen_after_a_march_competition_are_not_marked(self):
        from game_core.live_members import ALL_MEMBERS

        spring = self.live("SPRING", "SCH-TEST")
        self.assertEqual(ALL_MEMBERS, self.state.bench_members["SPRING:SCH-TEST"])
        april = self.book.roster(2027, "SCH-TEST").players
        info, rows = self.info(april, date(2027, 4, 2))
        registered = {p.player_id for p in spring.players}
        self.assertEqual("SPRING", info["competition"])
        self.assertFalse(info["all"])
        for player, row in zip(april, rows):
            # 4月1日の新入生は出場資格がない（◎なし）。進級した部員は◎
            self.assertEqual(player.player_id in registered, row["bench"])
            if player.academic_year == 1:
                self.assertFalse(row["bench"])
        self.assertEqual(sum(row["bench"] for row in rows), info["count"])

    def test_summer_marks_before_and_after_retirement(self):
        summer = self.live("SUMMER", "SCH-TEST")
        roster = self.book.roster(2026, "SCH-TEST").players
        self.assertEqual(len(roster), len(summer.players))
        before = self.live.members_on("SCH-TEST", date(2026, 7, 10))
        info, rows = self.info(before, date(2026, 7, 10))
        self.assertTrue(info["all"])
        self.assertEqual(len(roster), info["count"])
        # 負けた次の日に3年生が引退。残った部員は夏の出場メンバーなので全員◎
        after = self.live.members_on("SCH-TEST", date(2026, 7, 11))
        self.assertNotIn(3, {p.academic_year for p in after})
        info, rows = self.info(after, date(2026, 7, 11))
        self.assertTrue(all(row["bench"] for row in rows))
        self.assertEqual(len(after), info["count"])

    def test_marks_are_the_same_after_save_and_load(self):
        import pickle

        from game_core.live_members import LiveSeasonMembers

        self.live("SPRING", "SCH-TEST")
        april = self.book.roster(2027, "SCH-TEST").players
        expected, expected_rows = self.info(april, date(2027, 4, 2))
        from types import SimpleNamespace

        # 名簿は保存して読み込み直す。進行中の状態は保存されるベンチ入りの記録だけを引き継ぐ
        book = pickle.loads(pickle.dumps(self.book))
        book.bind(lambda school_id: TEAM)
        state = _State(self.state.competitions)
        state.bench_members = pickle.loads(pickle.dumps(self.state.bench_members))
        live = LiveSeasonMembers(self.Plan(), book)
        live.attach(state)
        state.engine = SimpleNamespace(main_match_resolver=SimpleNamespace(member_provider=live))
        with unittest.mock.patch.object(book, "ability", side_effect=AssertionError):
            info, rows = self.info(book.roster(2027, "SCH-TEST").players, date(2027, 4, 2), state)
        self.assertEqual(expected, info)
        self.assertEqual(expected_rows, rows)
