"""大差の試合：能力の差が極端な打席のアウトの割合、疲れの上限、勝っている側が手を緩める采配（架空の学校・選手）。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest

from game_core import fatigue
from game_core.coaches import CoachTactics
from game_core.match_config import validate_match_simulation_config
from game_core.match_contract import validate_match_simulation_result
from game_core.match_simulator import MatchSimulator, _OUT_EVENTS
from game_core.match_state import TeamMatchParticipation, replay_team_participation
from phase2_engine.balance_report import BalanceTally, SituationCounter, format_report
from test_stage13b3_team_strength import make_roster_abilities
import test_balance_report as report_fixture
import test_live_match_state as live


class _Tuned(MatchSimulator):
    """設定の一部を変えた試合計算。"""

    def __init__(self, **sections):
        super().__init__()
        self.params = deepcopy(self.params)
        for name, values in sections.items():
            target = self.params
            *path, last = name.split("__")
            for key in path:
                target = target[key]
            target[last] = values


def out_share(weights) -> float:
    return sum(weights[key] for key in _OUT_EVENTS) / sum(weights.values())


class ExtremeMismatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        abilities = make_roster_abilities(school_id="FAKE-BLOWOUT")
        batter = next(a for a in abilities if a.primary_position not in ("P", "C"))
        pitcher = next(a for a in abilities if a.primary_position == "P")
        cls.star = replace(batter, contact=92, power=92, plate_discipline=92, strikeout_resistance=92, speed=80)
        cls.even = replace(batter, contact=50, power=50, plate_discipline=50, strikeout_resistance=50, speed=50)
        cls.hopeless = replace(pitcher, velocity_kmh=105, stuff=5, control=5, strikeout=5, groundball=20,
                               pitch_repertoire=())
        cls.average = replace(pitcher, velocity_kmh=135, stuff=50, control=50, strikeout=50, groundball=50,
                              pitch_repertoire=())

    def test_out_share_is_pulled_back_toward_the_pivot_only_in_extreme_matchups(self):
        sim = MatchSimulator()
        rule = sim.params["plate_appearance_model"]["min_out_share"]
        free = _Tuned(plate_appearance_model__min_out_share={"pivot": rule["pivot"], "strength": 0.0})
        raw = out_share(free._event_weights(self.star, self.hopeless, 30.0))
        kept = out_share(sim._event_weights(self.star, self.hopeless, 30.0))
        self.assertLess(raw, rule["pivot"])
        self.assertAlmostEqual(raw + (rule["pivot"] - raw) * rule["strength"], kept)
        # アウト以外の結果どうしの比は変えない
        a, b = (s._event_weights(self.star, self.hopeless, 30.0) for s in (free, sim))
        self.assertAlmostEqual(a["single"] / a["walk"], b["single"] / b["walk"])
        # ふつうの対戦は変わらない
        self.assertEqual(free._event_weights(self.even, self.average, 50.0),
                         sim._event_weights(self.even, self.average, 50.0))

    def test_full_strength_is_a_hard_floor(self):
        hard = _Tuned(plate_appearance_model__min_out_share={"pivot": 0.45, "strength": 1.0})
        self.assertAlmostEqual(0.45, out_share(hard._event_weights(self.star, self.hopeless, 30.0)))

    def test_config_rejects_bad_values(self):
        document = MatchSimulator().config
        base = document.payload
        validate_match_simulation_config(document)
        for path, value in (
            (("plate_appearance_model", "min_out_share"), {"pivot": 0.9, "strength": 0.5}),
            (("plate_appearance_model", "min_out_share"), {"pivot": 0.4, "strength": 1.5}),
            (("blowout", "thresholds"), [[0, 10]]),
            (("blowout", "thresholds"), [[5]]),
            (("blowout", "per_half_inning"), -1),
            (("blowout", "pitcher_change_from_inning"), 0),
        ):
            with self.subTest(path=path, value=value):
                payload = deepcopy(base)
                payload[path[0]][path[1]] = value
                with self.assertRaises(ValueError):
                    validate_match_simulation_config(replace(document, payload=payload))


class FatigueCapTests(unittest.TestCase):
    def test_drop_stops_at_the_top_stage_however_many_pitches_are_thrown(self):
        rule = MatchSimulator().params["fatigue"]
        pitcher = next(a for a in make_roster_abilities(school_id="FAKE-TIRED") if a.primary_position == "P")
        pitcher = replace(pitcher, stuff=60, control=60)
        # 代える投手のいない学校：何球投げても段階は上限で止まる
        stages = [fatigue.stage_of(fatigue.in_game_fatigue(pitches, pitcher.stamina, rule), rule)
                  for pitches in (250, 400, 1000)]
        self.assertEqual([rule["max_stage"]] * 3, stages)
        worn = fatigue.tired(pitcher, stages[-1], rule)
        most = rule["max_stage"] * rule["stage_points"]
        self.assertEqual(60 - most * rule["drop"]["stuff"], worn.stuff)
        self.assertEqual(60 - most * rule["drop"]["control"], worn.control)
        # 上限まで疲れても、能力の半分以上は残る（下がり続けない）
        self.assertGreaterEqual(worn.stuff, 30)
        self.assertGreaterEqual(worn.control, 30)


def leads(result):
    """打席ごとの (イベント, 打席の前の攻める側のリード, 打席のあとのリード)。"""
    score = {result.team1_school_id: 0, result.team2_school_id: 0}
    for event in result.events:
        before = score[event.offense_school_id] - score[event.defense_school_id]
        score[event.offense_school_id] += event.runs_scored
        yield event, before, score[event.offense_school_id] - score[event.defense_school_id]


class EasingOffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        live.DHSimulationTests.setUpClass()
        cls.fixture = live.DHSimulationTests()

    def games(self, sim, mode="none", count=4):
        for number in range(count):
            inp = replace(self.fixture.match(mode), match_id=f"FAKE-EASE-{mode}-{number}",
                          generation_seed=20261600 + number)
            result = sim.simulate(inp)
            validate_match_simulation_result(result, inp)
            yield inp, result

    @staticmethod
    def busy(**blowout):
        """作戦と盗塁が多く、1点でもリードしたら大差とみなす試合計算（手を緩める作りを多くの場面で確かめる）。"""
        sim = _Tuned(blowout={"thresholds": [[1, 1]], "per_half_inning": 3,
                              "pitcher_change_from_inning": 1, **blowout})
        bunt = sim.params["strategy"]["sacrifice_bunt"]
        bunt.update(ahead_far_multiplier=1.0, close_margin=99)
        sim.params["stolen_bases"]["attempt"].update(second_base=0.4, blowout_multiplier=1.0)
        return sim

    def test_production_thresholds(self):
        sim = MatchSimulator()
        (inning, lead), = sim.params["blowout"]["thresholds"]
        self.assertTrue(sim._easing_off(inning, lead))
        self.assertTrue(sim._easing_off(inning + 2, lead + 5))
        self.assertFalse(sim._easing_off(inning - 1, lead))
        self.assertFalse(sim._easing_off(inning, lead - 1))
        self.assertFalse(sim._easing_off(inning, -lead))      # 負けている側は変えない

    def test_leading_side_stops_tactics_and_steals(self):
        counts = {}
        for name, thresholds in (("eased", [[1, 1]]), ("as_before", [])):
            tactics = steals = 0
            for _, result in self.games(self.busy(thresholds=thresholds)):
                for event, before, after in leads(result):
                    meta = dict(event.metadata)
                    tactics += before >= 1 and "tactic" in meta
                    steals += after >= 1 and "steal" in meta
            counts[name] = (tactics, steals)
        self.assertEqual((0, 0), counts["eased"])
        # 手を緩めない設定では同じ場面で作戦も盗塁もある（上の0が場面のなさのせいでないこと）
        self.assertGreater(counts["as_before"][0], 0)
        self.assertGreater(counts["as_before"][1], 0)

    def test_leading_side_rests_starters_and_changes_the_pitcher(self):
        rested = relieved = 0
        for mode in ("none", "normal", "pitcher"):
            for inp, result in self.games(self.busy(), mode=mode, count=3):
                first_lead = {}
                for event, before, _ in leads(result):
                    if before >= 1:
                        first_lead.setdefault(event.offense_school_id, event.plate_appearance_no)
                for raw in result.team_participation:
                    record = TeamMatchParticipation.from_dict(raw.to_dict())
                    self.assertEqual(raw, record)             # 交代の理由も保存・読込で残る
                    replay_team_participation(record, inp.reference_year)
                    starters = {e.player_id for e in raw.starting_lineup}
                    changes = [c for c in record.changes if c.reason == "blowout_rest"]
                    for change in changes:
                        # 休むのは先発、出るのは控え。リードする前には出さない
                        if change.dh_action is None:
                            self.assertIn(change.outgoing_player_id, starters)
                            entered = [change.incoming_player_id]
                        else:
                            # DHのある試合は打順の入れ替えとして記録される
                            entered = [slot.player_id for slot in change.dh_action.batting_changes]
                        self.assertTrue(entered)
                        self.assertFalse(set(entered) & starters)
                        self.assertIn(raw.school_id, first_lead)
                        self.assertGreaterEqual(change.moment.next_plate_appearance_no, first_lead[raw.school_id])
                    rested += len(changes)
                    # 勝っている側は先発投手を降ろし、投手陣の最後の投手を出す
                    if raw.school_id == result.winner_id and raw.school_id in first_lead:
                        team = inp.team1 if inp.team1.school_id == raw.school_id else inp.team2
                        last = max(team.team_strength.pitching_staff.entries, key=lambda e: e.order).player_id
                        pitched = {p.player_id for p in result.pitcher_stats
                                   if p.school_id == raw.school_id and p.batters_faced > 0}
                        relieved += last in pitched
        self.assertGreater(rested, 0)
        self.assertGreater(relieved, 0)

    def test_pitcher_change_while_easing_waits_for_the_configured_inning(self):
        """大差で手を緩めるときの投手の交代は pitcher_change_from_inning の回から
        （5回コールドの最後の回に先発を代えない）。ほかの理由の交代は止めて確かめる。"""
        def relief_innings(from_inning):
            sim = self.busy(pitcher_change_from_inning=from_inning)
            sim._should_change_pitcher = lambda **kwargs: False
            innings = []
            for _, result in self.games(sim, count=6):
                first = {}   # (守る学校, 投手) → 初めて投げた回。学校ごとの最初の投手が先発
                for event in result.events:
                    first.setdefault((event.defense_school_id, event.pitcher_id), event.inning)
                starters = {}
                for school_id, pitcher in first:
                    starters.setdefault(school_id, pitcher)
                innings += [inning for (school_id, pitcher), inning in first.items()
                            if pitcher != starters[school_id]]
            return innings

        early = relief_innings(1)
        self.assertTrue(any(inning < 7 for inning in early))   # 設定がなければ早い回にも代える
        self.assertTrue(all(inning >= 7 for inning in relief_innings(7)))
        self.assertEqual(7, MatchSimulator().params["blowout"]["pitcher_change_from_inning"])

    def test_coach_who_substitutes_often_rests_more_starters_per_half_inning(self):
        def most_in_a_half(substitutions):
            best = 0
            for inp, _ in self.games(MatchSimulator(), count=1):
                tactics = {sid: CoachTactics(substitutions=substitutions)
                           for sid in (inp.team1.school_id, inp.team2.school_id)}
                result = self.busy(per_half_inning=2).simulate(inp, tactics=tactics)
                for raw in result.team_participation:
                    halves = {}
                    for change in raw.changes:
                        if change.reason == "blowout_rest":
                            key = (change.moment.inning, change.moment.half)
                            halves[key] = halves.get(key, 0) + 1
                    best = max(best, *halves.values(), 0)
            return best

        self.assertLessEqual(most_in_a_half(0.5), 1)
        self.assertLessEqual(most_in_a_half(1.0), 2)
        self.assertGreater(most_in_a_half(2.0), 2)

    def test_empty_thresholds_change_nothing(self):
        plain = _Tuned(blowout={"thresholds": [], "per_half_inning": 3, "pitcher_change_from_inning": 7})
        for _, result in self.games(plain, count=2):
            self.assertFalse([c for raw in result.team_participation for c in raw.changes
                              if c.reason == "blowout_rest"])


class BalanceReportTests(unittest.TestCase):
    def test_rested_starters_are_counted_apart_from_tactical_substitutions(self):
        tally = BalanceTally(lambda cid: report_fixture.KINDS[cid[:3]], {}, report_fixture.RANKINGS)
        detail = report_fixture.match(2026, "LOC1", "FAKE-A", "FAKE-B", 12, 0, 5)
        a, b = detail["team_participation"]
        a["changes"] = [dict(reason="blowout_rest"), dict(reason="blowout_rest"), dict(reason="pinch_hitter")]
        b["changes"] = []
        coaches = {"FAKE-A": SimpleNamespace(pitcher_shuffle=50, substitutions=50),
                   "FAKE-B": SimpleNamespace(pitcher_shuffle=50, substitutions=50)}
        tally.add_match("LOC1", detail, coaches.get)
        row = tally.summary()[2026]["substitutions"]
        self.assertEqual((2.0, 1, 1.0), (row["blowout_rest"], row["blowout_rest_team_games"], row["pinch_hitters"]))
        self.assertEqual(0.5, row["by_tendency"]["中"]["substitutions"])
        report = tally.summary()
        report[2026]["blowout"] = {"plate_appearances": 30, "tactics": 0, "steal_attempts": 0}
        self.assertIn("大差の場面（勝っている側）: 打席 30 / 作戦 0 / 盗塁の試み 0 / 出た控え 1試合あたり 2.0",
                      format_report("x", report))

    def test_situation_counter_counts_plate_appearances_tactics_and_steals_while_easing(self):
        live.DHSimulationTests.setUpClass()
        inp = replace(live.DHSimulationTests().match("none"), match_id="FAKE-EASE-COUNT")
        counter = SituationCounter(lambda cid: "summer_local_qualifier")
        with counter.watching():
            EasingOffTests.busy().simulate(inp)
        row = counter.play_summary()[inp.reference_year]["blowout"]
        self.assertGreater(row["plate_appearances"], 0)
        self.assertEqual((0, 0), (row["tactics"], row["steal_attempts"]))


if __name__ == "__main__":
    unittest.main()
