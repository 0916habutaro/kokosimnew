from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from phase2_engine.randomness import rng_for

from .abilities import PlayerAbilitySnapshot
from .coaches import CoachTactics
from .match_config import load_and_validate_match_configs
from .match_contract import (
    BatterGameStats,
    InningScore,
    MatchEvent,
    MatchSimulationInput,
    MatchSimulationResult,
    PitcherGameStats,
    TeamGameStats,
    TeamMatchInput,
    match_contract_provenance,
    validate_match_simulation_input,
    validate_match_simulation_result,
    _history_after_validation,
)
from . import fatigue as fatigue_model
from .match_state import ChangeMoment, CompletedPlateAppearanceMoment, TeamMatchState
from .team_strength import TeamStrengthGenerator


@dataclass(frozen=True)
class GameRules:
    """試合の規定（config/match/game_rules_v1.json）。

    ``tiebreak_start_inning``：この回から無死一・二塁で始める（None なら使わない）。
    ``mercy``：（回, 点差）。その回が終わった時点で点差がこれ以上なら試合終了。"""

    tiebreak_start_inning: int | None = None
    mercy: tuple[tuple[int, int], ...] = ()


# 左右別の成績の欄（段階F2）
_SPLIT_KEYS = ("at_bats", "hits", "home_runs", "walks", "strikeouts")
BATTER_SPLIT_FIELDS = tuple(f"vs_{hand}_{key}" for hand in ("rhp", "lhp") for key in _SPLIT_KEYS)
PITCHER_SPLIT_FIELDS = tuple(f"vs_{hand}_{key}" for hand in ("rhb", "lhb") for key in _SPLIT_KEYS)


@dataclass(frozen=True)
class LineupAdjustment:
    """直接試合計算での明示的な交代指示。AIや全国自動進行からは生成しない。"""
    next_plate_appearance_no: int
    school_id: str
    batting_changes: tuple[tuple[int, str], ...] = ()
    defensive_changes: tuple[tuple[str, str], ...] = ()
    medical_exception: str | None = None
    umpire_approved: bool = False

    def __post_init__(self):
        for name in ('batting_changes', 'defensive_changes'):
            pairs = tuple(tuple(pair) for pair in getattr(self, name))
            if any(len(pair) != 2 for pair in pairs) or len({p[0] for p in pairs}) != len(pairs):
                raise ValueError('duplicate or invalid adjustment entries')
            object.__setattr__(self, name, pairs)
        if type(self.next_plate_appearance_no) is not int or self.next_plate_appearance_no < 1:
            raise ValueError('adjustment requires a positive next plate appearance')


@dataclass(frozen=True)
class _RunnerResponsibility:
    """Responsibility and unearned lineage, including replacements under 9.16(g)."""

    player_id: str
    responsible_pitcher_id: str
    reached_on_error: bool = False
    tiebreak_placed: bool = False
    plate_appearance_no: int | None = None


class _DeferredEventRandom:
    """独立した進塁用乱数を、実際に使う打席だけ初期化する。"""

    __slots__ = ('_seed', '_namespace', '_rng')

    def __init__(self, seed, namespace):
        self._seed, self._namespace, self._rng = seed, namespace, None

    def __getattr__(self, name):
        if self._rng is None:
            self._rng = rng_for(self._seed, self._namespace)
        return getattr(self._rng, name)


class _RunnerResponsibilityTracker:
    """Inning-local responsibility, separate from the existing base/outcome model.

    This tracker neither consumes randomness nor mutates the simulator's bases.
    """

    def __init__(self) -> None:
        self._active: dict[str, _RunnerResponsibility] = {}
        self._pitcher_order: dict[str, int] = {}

    def substitute_runner(self, outgoing: str, incoming: str) -> None:
        if outgoing not in self._active or incoming in self._active:
            raise ValueError('invalid runner substitution')
        origin = self._active.pop(outgoing)
        self._active[incoming] = replace(origin, player_id=incoming)

    def retire_runner(self, player_id: str) -> None:
        """盗塁死・牽制死：走者は責任を残さずに塁からいなくなる。"""
        if player_id not in self._active:
            raise ValueError('retired runner is not on base')
        del self._active[player_id]

    def seed_tiebreak(
        self, bases: list[str | None], pitcher_id: str,
    ) -> None:
        """Assign placed runners to the pitcher who actually starts this half-inning."""
        if self._active:
            raise ValueError("tiebreak runner responsibility already initialized")
        runners = [player_id for player_id in bases if player_id is not None]
        if len(runners) != len(set(runners)):
            raise ValueError("duplicate tiebreak runner")
        self._active = {
            player_id: _RunnerResponsibility(
                player_id=player_id,
                responsible_pitcher_id=pitcher_id,
                tiebreak_placed=True,
            )
            for player_id in runners
        }
        self._pitcher_order.setdefault(pitcher_id, len(self._pitcher_order))

    def record_play(
        self,
        *,
        bases_before: list[str | None],
        bases_after: list[str | None],
        scored_runner_ids: list[str],
        batter_id: str,
        pitcher_id: str,
        event_type: str,
        plate_appearance_no: int,
    ) -> tuple[_RunnerResponsibility, ...]:
        """Return the origins of scoring runners in scoring order.

        A fielder's choice preserves the retired runner's responsibility slot.
        If a later runner scores first, earlier pitchers' outstanding slots take
        precedence (9.16(g)); simultaneous scorers retain their slots if possible.
        """
        before = [pid for pid in bases_before if pid is not None]
        after = [pid for pid in bases_after if pid is not None]
        if len(before) != len(set(before)) or set(before) != set(self._active):
            raise ValueError("runner responsibility differs from occupied bases")
        if len(after) != len(set(after)):
            raise ValueError("duplicate runner after play")
        if len(scored_runner_ids) != len(set(scored_runner_ids)):
            raise ValueError("duplicate scoring runner")

        newcomer = _RunnerResponsibility(
            player_id=batter_id,
            responsible_pitcher_id=pitcher_id,
            reached_on_error=event_type == "reached_on_error",
            plate_appearance_no=plate_appearance_no,
        )
        self._pitcher_order.setdefault(pitcher_id, len(self._pitcher_order))
        if event_type == "fielder_choice":
            removed = set(before) - set(after) - set(scored_runner_ids)
            if len(removed) == 1 and batter_id in after:
                newcomer = replace(
                    self._active[removed.pop()], player_id=batter_id,
                    plate_appearance_no=plate_appearance_no,
                )

        def origin(player_id: str) -> _RunnerResponsibility:
            prior = self._active.get(player_id)
            if prior is not None:
                return prior
            if player_id == batter_id:
                return newcomer
            raise ValueError("unknown runner after play")

        if set(scored_runner_ids) & set(after):
            raise ValueError("scoring runner remains on base")
        origins = {pid: origin(pid) for pid in [*scored_runner_ids, *after]}
        if not scored_runner_ids:
            self._active = origins
            return ()
        scoring = set(scored_runner_ids)
        ordered = sorted(origins, key=lambda pid: (
            self._pitcher_order[origins[pid].responsible_pitcher_id],
            pid not in scoring, pid,
        ))
        selected = set(ordered[:len(scored_runner_ids)])
        assignments = {pid: pid for pid in scored_runner_ids if pid in selected}
        unused = [pid for pid in ordered if pid in selected and pid not in assignments]
        for pid in scored_runner_ids:
            if pid not in assignments:
                assignments[pid] = unused.pop(0)
        available = [pid for pid in origins if pid not in assignments.values()]
        for pid in after:
            if pid in available:
                assignments[pid] = pid
                available.remove(pid)
        for pid in after:
            if pid not in assignments:
                assignments[pid] = available.pop(0)
        credited = {
            pid: replace(origins[source], player_id=pid,
                         plate_appearance_no=origins[pid].plate_appearance_no)
            for pid, source in assignments.items()
        }
        self._active = {pid: credited[pid] for pid in after}
        return tuple(credited[pid] for pid in scored_runner_ids)


# Appearance keys distinguish two trips around the order by the same player.
_RunnerKey = tuple[int, str]


class _ErrorFreeInning:
    """Scoring-only reconstruction; never draws randomness or changes actual play.

    ROE is a missed batter out in the current event model. On clean hits, use an
    observed advance only from the same base; otherwise credit the minimum bases
    guaranteed by that hit (doubt benefits the pitcher, 9.16(d/f)).
    """

    def __init__(self, outs: int, bases: list[_RunnerKey | None]):
        self.outs = outs
        self.bases = list(bases)
        self.scored: set[_RunnerKey] = set()

    def record_play(self, event: str, batter: _RunnerKey,
                    before: list[_RunnerKey | None], after: list[_RunnerKey | None],
                    scored: set[_RunnerKey], outs_on_play: int) -> None:
        if self.outs >= 3:
            return
        if event == "reached_on_error":
            self.outs += 1
            return
        self.outs += outs_on_play
        if self.outs >= 3:
            return
        if event in {"walk", "hit_by_pitch"}:
            carry = batter
            for index in range(3):
                carry, self.bases[index] = self.bases[index], carry
                if carry is None:
                    break
            else:
                self.scored.add(carry)
        elif event == "home_run":
            self.scored.update(key for key in self.bases if key is not None)
            self.scored.add(batter)
            self.bases = [None] * 3
        elif event in {"single", "double", "triple"}:
            distance = {"single": 1, "double": 2, "triple": 3}[event]
            advanced: list[_RunnerKey | None] = [None] * 3
            for index in (2, 1, 0):
                key = self.bases[index]
                if key is None:
                    continue
                target = index + distance
                if before[index] == key:
                    if key in scored:
                        target = 3
                    elif key in after:
                        target = max(target, after.index(key))
                if target >= 3:
                    self.scored.add(key)
                else:
                    while advanced[target] is not None:
                        target -= 1
                    advanced[target] = key
            advanced[distance - 1] = batter
            self.bases = advanced
        elif event == "fielder_choice":
            removed = {key for key in before if key is not None} - set(after) - scored
            # An already eliminated error runner cannot be retired again in the
            # reconstructed bases. Treat that play as a batter out instead.
            victim = next((key for key in removed if key in self.bases), None)
            if victim is not None:
                self.bases[self.bases.index(victim)] = None
                for index in (2, 1, 0):
                    key = self.bases[index]
                    if key is not None and before[index] == key and key in after:
                        target = after.index(key)
                        if target > index and self.bases[target] is None:
                            self.bases[target], self.bases[index] = key, None
                if self.bases[0] is None:
                    self.bases[0] = batter
        elif event == "passed_ball":
            # 捕逸は捕手の失策と同じく、失策のない再構成では走者を進めない
            return
        elif event in {"sacrifice_fly", "fly_out", "ground_out", "double_play", "sacrifice_bunt",
                       "bunt_pop_out", "bunt_double_play", "line_drive_double_play",
                       "wild_pitch", "stolen_base"}:
            # 凡退・犠打（スクイズを含む）・暴投・本盗の間の進塁・得点は、同じ塁にいる同じ走者の実際の動きだけを写す。
            # 実際にアウトになった走者は再構成の塁からも除く（いなければ打者のアウト
            # だけになる。疑わしいときは投手の有利に、9.16(d/f)）。
            if event == "sacrifice_fly" and self.bases[2] is not None:
                # 犠飛は再構成の三塁走者を生還させる（従来どおり）
                self.scored.add(self.bases[2])
                self.bases[2] = None
            removed = {key for key in before if key is not None} - set(after) - scored
            for victim in removed:
                if victim in self.bases:
                    self.bases[self.bases.index(victim)] = None
            for index in (2, 1, 0):
                key = self.bases[index]
                if key is None or before[index] != key:
                    continue
                if key in scored:
                    self.scored.add(key)
                    self.bases[index] = None
                elif key in after:
                    target = after.index(key)
                    if target > index and self.bases[target] is None:
                        self.bases[target], self.bases[index] = key, None
        elif event not in {"strikeout", "field_out"}:
            raise ValueError(f"unsupported earned-run event: {event}")

    def baserunning(self, key: _RunnerKey, from_index: int, to_index: int | None) -> None:
        """打席の間の走塁。盗塁は失策のない進塁として写し、盗塁死・牽制死はアウト。"""
        if self.outs >= 3:
            return
        if to_index is None:
            self.outs += 1
            if key in self.bases:
                self.bases[self.bases.index(key)] = None
            return
        if self.bases[from_index] == key and self.bases[to_index] is None:
            self.bases[to_index], self.bases[from_index] = key, None


class _EarnedRunTracker:
    """One team reconstruction plus a separate entry state per pitcher (9.16(i)).

    Retired pitchers' views continue through later relief and errors. An actual
    run can become earned on a subsequent clean advance, so settle at half end.
    Team ER is deliberately not equated to the sum of individual pitcher ER.
    """

    def __init__(self) -> None:
        self._active: dict[str, _RunnerKey] = {}
        self._views: dict[str, _ErrorFreeInning] = {}
        self._team: _ErrorFreeInning | None = None
        self._runs: list[tuple[_RunnerKey, _RunnerResponsibility]] = []
        self._unearned: set[_RunnerKey] = set()

    def substitute_runner(self, outgoing: str, incoming: str) -> None:
        if outgoing not in self._active or incoming in self._active:
            raise ValueError('invalid earned-run runner substitution')
        # 仮想イニングは元の出塁キーを使い続け、実走者IDへの対応だけを変える。
        self._active[incoming] = self._active.pop(outgoing)

    def record_play(self, *, bases_before, bases_after, scored_runners,
                    batter_id, pitcher_id, event_type, plate_appearance_no,
                    outs_before, outs_on_play) -> None:
        if self._team is None:
            # Only tiebreak runners can be on base before the first actual PA.
            self._active = {pid: (-1, pid) for pid in bases_before if pid is not None}
            self._unearned.update(self._active.values())
        before = [self._active.get(pid) for pid in bases_before]
        batter = (plate_appearance_no, batter_id)
        keys = {**self._active, batter_id: batter}
        after = [keys.get(pid) for pid in bases_after]
        scored = {keys[runner.player_id] for runner in scored_runners}
        if self._team is None:
            self._team = _ErrorFreeInning(0, before)
        if pitcher_id not in self._views:
            self._views[pitcher_id] = _ErrorFreeInning(outs_before, before)
        if event_type == "reached_on_error":
            self._unearned.add(batter)
        for view in (self._team, *self._views.values()):
            view.record_play(event_type, batter, before, after, scored, outs_on_play)
        self._runs.extend((keys[runner.player_id], runner) for runner in scored_runners)
        self._active = {pid: keys[pid] for pid in bases_after if pid is not None}

    def record_baserunning(self, runner_id: str, from_index: int, to_index: int | None) -> None:
        key = self._active[runner_id]
        for view in (self._team, *self._views.values()):
            view.baserunning(key, from_index, to_index)
        if to_index is None:
            del self._active[runner_id]

    def earned_runs(self) -> Counter[str]:
        return Counter(
            runner.responsible_pitcher_id for key, runner in self._runs
            if key not in self._unearned
            and not (runner.reached_on_error or runner.tiebreak_placed)
            and key in self._views[runner.responsible_pitcher_id].scored
        )

    @property
    def team_earned_runs(self) -> int:
        return sum(
            key not in self._unearned
            and not (runner.reached_on_error or runner.tiebreak_placed)
            and key in self._team.scored
            for key, runner in self._runs
        )


# 打球を処理する守備位置（H2）。左打者は左右を入れ替える
_MIRROR_POSITION = {"3B": "1B", "1B": "3B", "SS": "2B", "2B": "SS", "LF": "RF", "RF": "LF"}
_OUTFIELD = frozenset(("LF", "CF", "RF"))
# 守った選手で結果が変わりうる打球（本塁打・三振・四死球・バントは対象外）
_FIELDED_EVENTS = frozenset(("single", "double", "triple", "field_out", "reached_on_error"))


@dataclass(frozen=True)
class _Fielded:
    """打球を処理した選手。skill_gap・arm_gap はチームの基準（守っている9人の平均）との差。"""

    position: str
    player_id: str
    ball_type: str
    skill: float
    aptitude: int
    skill_gap: float
    arm_gap: float


@dataclass(frozen=True)
class _FieldingProfile:
    """守っている並びごとの、守備位置 → (選手, 守備の値, 肩の値, 適性) とチームの基準。"""

    players: Mapping[str, tuple[str, float, float, int]]
    skill_reference: float
    arm_reference: float


class MatchSimulator:
    def __init__(
        self,
        config_dir: str | Path = "config/match",
        *,
        team_generator: TeamStrengthGenerator | None = None,
    ):
        self.config_dir = Path(config_dir)
        self._team_generator = team_generator
        self.configs = load_and_validate_match_configs(self.config_dir)
        self.config = self.configs["match_simulation_v1"]
        self.params = self.config.payload
        self.event_catalog = {
            str(item["event_type"]): item
            for item in self.configs["event_catalog_v1"].payload[
                "event_types"
            ]
        }

    @staticmethod
    def _players(team: TeamMatchInput) -> dict[str, PlayerAbilitySnapshot]:
        return {
            player.player_id: player
            for player in team.player_abilities
        }

    @staticmethod
    def _pitcher_order(team: TeamMatchInput) -> tuple[str, ...]:
        entries = sorted(
            team.team_strength.pitching_staff.entries,
            key=lambda entry: entry.order,
        )
        order = tuple(entry.player_id for entry in entries)
        lineup = team.team_strength.starting_lineup
        if lineup.designated_hitter_id is not None:
            planned = lineup.player_for_position('P')
            return (planned, *(pid for pid in order if pid != planned))
        return order

    @staticmethod
    def _quality_order(team: TeamMatchInput) -> tuple[str, ...]:
        """投手陣の能力の順（エースが先頭）。DHの予定の先発で並べ替えない。"""
        return tuple(entry.player_id for entry in sorted(
            team.team_strength.pitching_staff.entries, key=lambda entry: entry.order))

    def rested_ace(self, team: TeamMatchInput, carry: Mapping[str, float] | None) -> str | None:
        """疲れで先発を外すエース。DHで予定の先発が変わっていても、能力の順の先頭で決める。"""
        return self._rested_ace(self._quality_order(team), carry)

    def carry_fatigue(
        self, team: TeamMatchInput, history: Mapping[str, Mapping[int, int]] | None,
    ) -> dict[str, float]:
        """試合の始まりの疲れ（連投）：選手 → 疲れの点。``history`` は選手 → (何日前 → 球数)。"""
        if not history:
            return {}
        rule = self.params["fatigue"]
        return {
            player.player_id: fatigue_model.carry_fatigue(history[player.player_id], player.stamina, rule)
            for player in team.player_abilities
            if history.get(player.player_id)
        }

    def _game_staff(
        self,
        team: TeamMatchInput,
        allowances: Mapping[str, int] | None,
        carry: Mapping[str, float] | None = None,
    ) -> tuple[tuple[str, ...], int]:
        """この試合で投げる順と、そのうち投手陣の人数。球数制限（``allowances``：
        あと何球投げられるか）があれば、残りの少ない投手は先発にせず、投げられない
        投手は外す。後ろに野手を並べ、球数制限で投手がいなくなったときだけ使う。"""
        staff = self._pitcher_order(team)
        ace = self.rested_ace(team, carry) if carry else None
        if ace is not None:
            if staff[0] == ace:
                staff = self._rest_tired_starter(staff, carry)
            else:
                # DHで予定の先発（二番手など）が先頭のときも、エースは救援の順番の最後
                staff = (*[pid for pid in staff if pid != ace], ace)
        if allowances is None:
            return staff, len(staff)
        usage = self.params["pitching_usage"]
        left = lambda player_id: allowances.get(player_id, math.inf)  # noqa: E731
        able = [
            player_id for player_id in staff
            if left(player_id) >= int(usage["reliever_minimum_pitches"])
        ]
        starter = next(
            (
                player_id for player_id in able
                if left(player_id) >= int(usage["starter_minimum_pitches"])
            ),
            able[0] if able else None,
        )
        order = [starter] if starter else []
        order += [player_id for player_id in able if player_id != starter]
        fielders = sorted(
            (
                player for player in team.player_abilities
                if player.player_id not in staff and left(player.player_id) > 0
            ),
            key=lambda player: (-player.arm_strength, player.player_id),
        )
        return tuple(order) + tuple(player.player_id for player in fielders), len(order)

    def fatigue_pitch_budget(
        self, pitcher: PlayerAbilitySnapshot, carry_points: float, *, starter: bool,
        tactics: CoachTactics = CoachTactics(),
    ) -> float:
        """疲れで代わるまでの球数の目安（始まりの疲れと、試合の中の疲れの増え方から）。"""
        rule = self.params["fatigue"]
        game = rule["in_game"]
        limit = float(rule["change"]["starter_points" if starter else "reliever_points"]) * tactics.bf_multiplier
        per_pitch = float(game["per_pitch"])
        if carry_points >= limit:
            # 登板の始めから交代の基準以上：最低の対戦打者数だけ投げて代わる
            return 0.0
        if per_pitch <= 0:
            return math.inf
        threshold = float(game["base_pitches"]) + (float(pitcher.stamina or 50) - 50.0) * float(game["per_stamina"])
        return max(0.0, threshold + max(0.0, limit - carry_points) / per_pitch)

    def _rested_ace(self, staff: tuple[str, ...], carry: Mapping[str, float] | None) -> str | None:
        """始まりの疲れが大きく、もっと疲れの少ない投手がいるので先発を外すエース（なければ None）。"""
        if not carry or not staff:
            return None
        rest = float(self.params["fatigue"]["rest_starter_points"])
        if carry.get(staff[0], 0.0) < rest:
            return None
        if not any(carry.get(pid, 0.0) < rest for pid in staff[1:]):
            return None
        return staff[0]

    def _rest_tired_starter(self, staff: tuple[str, ...], carry: Mapping[str, float]) -> tuple[str, ...]:
        """疲れたエースは先発を外し、救援の順番の最後に回す（基本は休養。球数制限とは別）。"""
        ace = self._rested_ace(staff, carry)
        if ace is None:
            return staff
        rest = float(self.params["fatigue"]["rest_starter_points"])
        fresher = next(pid for pid in staff[1:] if carry.get(pid, 0.0) < rest)
        return (fresher, *[pid for pid in staff if pid not in (fresher, ace)], ace)

    def _call_rested_ace(
        self, *, ace: PlayerAbilitySnapshot, ace_carry: float, candidate: PlayerAbilitySnapshot | None,
        candidate_stage: int, ace_stage: int, inning: int, lead: int,
        tactics: CoachTactics, rng,
    ) -> bool:
        """休ませているエースを、この交代で救援に出すか（終盤・接戦・エースが明らかに良いとき）。"""
        rule = self.params["fatigue"]["rested_ace_relief"]
        if inning < int(rule["late_inning_from"]) or abs(lead) > int(rule["close_margin"]):
            return False
        if ace_carry >= float(rule["max_carry_points"]):
            return False
        fatigue_rule = self.params["fatigue"]

        def quality(pitcher, stage):
            worn = fatigue_model.tired(pitcher, stage, fatigue_rule)
            return (float(worn.stuff or 50) + float(worn.control or 50) + float(worn.strikeout or 50)) / 3.0

        if candidate is not None and (
                quality(ace, ace_stage) - quality(candidate, candidate_stage)
                < float(rule["quality_gap_points"])):
            return False
        probability = min(float(rule["max_probability"]),
                          float(rule["base_probability"]) / max(0.1, tactics.bf_multiplier))
        return rng.random() < probability

    def _strength_generator(self) -> TeamStrengthGenerator:
        if self._team_generator is None:
            self._team_generator = TeamStrengthGenerator()
        return self._team_generator

    def _initial_state(self, team: TeamMatchInput, actual_pitcher_id: str, *,
                       opponent_pitcher: PlayerAbilitySnapshot | None = None,
                       staff: tuple[str, ...] = (),
                       tactics: CoachTactics = CoachTactics()) -> TeamMatchState:
        """開始前にP配置を確定する。外れた先発予定選手は未出場の控えに戻す。

        ``opponent_pitcher`` を渡すと、相手の先発投手の腕を見て先発メンバーを少し変える（段階F2）。"""
        lineup = team.team_strength.starting_lineup
        planned_pitcher = lineup.player_for_position("P")
        if actual_pitcher_id != planned_pitcher and lineup.designated_hitter_id is not None:
            lineup = self._strength_generator().select_starting_lineup(
                team.lineup_abilities, starting_pitcher_id=actual_pitcher_id,
                dh_mode='pitcher' if lineup.designated_hitter_id == planned_pitcher else 'normal',
                order_style=tactics.batting_order, form_bonus=dict(tactics.form_bonus))
        elif actual_pitcher_id != planned_pitcher:
            position = next((entry.defensive_position for entry in lineup.entries
                             if entry.player_id == actual_pitcher_id), None)
            if position is None:
                player = {p.player_id: p for p in team.lineup_abilities}[actual_pitcher_id]
                score = round(self._strength_generator()._selection_score(player, "P"), 4)
                entries = tuple(
                    replace(entry, player_id=actual_pitcher_id, selection_score=score)
                    if entry.defensive_position == "P" else entry
                    for entry in lineup.entries
                )
            else:
                entries = tuple(
                    replace(entry, defensive_position=position)
                    if entry.player_id == planned_pitcher else
                    replace(entry, defensive_position="P")
                    if entry.player_id == actual_pitcher_id else entry
                    for entry in lineup.entries
                )
            lineup = replace(lineup, entries=entries)
        lineup = self._platoon_lineup(lineup, team, opponent_pitcher, staff, tactics)
        available = frozenset(p.player_id for p in team.player_abilities)
        return TeamMatchState(
            lineup, team.registered_player_ids if team.registered_player_ids is not None else available,
            available_player_ids=available, actual_pitcher_id=actual_pitcher_id,
        )

    def _current_defense(self, state: TeamMatchState,
                         players: Mapping[str, PlayerAbilitySnapshot]) -> float:
        return self._strength_generator().defense_for_alignment(
            players, ((a.defensive_position, a.player_id) for a in state.defensive_alignment),
        )

    def _as_pitcher(
        self,
        player: PlayerAbilitySnapshot,
    ) -> PlayerAbilitySnapshot:
        """投手の能力のない野手が投げるときの能力（``emergency_pitcher_ability``）。"""
        if player.stuff is not None:
            return player
        value = int(self.params["pitching_usage"]["emergency_pitcher_ability"])
        return replace(
            player,
            control=value, stamina=value, stuff=value,
            strikeout=value, groundball=value, composure=value, quick=value,
        )

    def _pitches(self, event_type: str, rng, pitcher: PlayerAbilitySnapshot | None = None,
                 batter: PlayerAbilitySnapshot | None = None) -> int:
        """1打席の球数。結果ごとの範囲に、投手の奪三振・制球と打者の選球で決まる球を足す（H1）。"""
        rule = self.params["pitch_count"]
        minimum, extra = rule["by_event"][event_type]
        count = int(minimum) + rng.randint(0, int(extra))
        if pitcher is not None:
            t = rule["tendency"]
            chance = self._clamp_probability(
                float(t["base"])
                + (float(pitcher.strikeout or 50) - 50.0) * float(t["per_strikeout_point"])
                + (50.0 - self._effective_control(pitcher)) * float(t["per_control_point"])
                + ((float(batter.plate_discipline) - 50.0) * float(t["per_discipline_point"])
                   if batter is not None else 0.0),
                0.0, float(t["max_probability"]))
            count += sum(rng.random() < chance for _ in range(int(t["max_extra"])))
        return count

    # ---- 度胸（G） ----
    def _under_pressure(self, bases: list[str | None], inning: int, margin: int) -> bool:
        """ピンチ（二塁か三塁に走者）か、終盤の接戦。"""
        rule = self.params["pressure"]
        return (bases[1] is not None or bases[2] is not None
                or (inning >= int(rule["late_inning_from"]) and abs(margin) <= int(rule["close_margin"])))

    def _pressure_points(self, pitcher: PlayerAbilitySnapshot) -> float:
        rule = self.params["pressure"]
        composure = float(pitcher.composure if pitcher.composure is not None else 50)
        return min(float(rule["max_points"]), max(0.0, float(rule["pivot"]) - composure))

    def _pressured(self, pitcher: PlayerAbilitySnapshot) -> PlayerAbilitySnapshot:
        """度胸が低い投手がピンチ・終盤の接戦で投げるときの能力（制球・球威・変化球の質が少し落ちる）。"""
        rule = self.params["pressure"]
        points = self._pressure_points(pitcher)
        if points <= 0:
            return pitcher
        control = points * float(rule["control_per_point"])
        stuff = points * float(rule["stuff_per_point"])

        def lower(value, amount):
            return None if value is None else max(1.0, float(value) - amount)

        return replace(
            pitcher, control=lower(pitcher.control, control), stuff=lower(pitcher.stuff, stuff),
            pitch_repertoire=tuple(replace(p, quality=lower(p.quality, stuff), command=lower(p.command, control))
                                   for p in pitcher.pitch_repertoire),
        )

    # ---- 暴投・捕逸（H1） ----
    def _wild_pitch_probabilities(
        self, pitcher: PlayerAbilitySnapshot, catcher: PlayerAbilitySnapshot,
    ) -> tuple[float, float]:
        """走者がいる打席のあとの (暴投の確率, 捕逸の確率)。"""
        rule = self.params["wild_pitches"]
        breaking = sum(p.usage for p in pitcher.pitch_repertoire if p.pitch_type != "four_seam") / 100.0
        wp_rule, pb_rule = rule["wild_pitch"], rule["passed_ball"]
        wild = min(float(wp_rule["max"]), float(wp_rule["base"]) * math.exp(
            (50.0 - self._effective_control(pitcher)) * float(wp_rule["per_control_point"])
            + (breaking - 0.4) * float(wp_rule["per_breaking_usage"])))
        catching = catcher.catching if catcher.catching is not None else int(rule["catcher_catching_default"])
        passed = min(float(pb_rule["max"]), float(pb_rule["base"]) * math.exp(
            (50.0 - float(catching)) * float(pb_rule["per_catching_point"])))
        return wild, passed

    def _wild_pitch_or_passed_ball(
        self, *, bases: list[str | None], pitcher: PlayerAbilitySnapshot,
        catcher: PlayerAbilitySnapshot, rng,
    ) -> str | None:
        """走者がいるときの暴投（wp）・捕逸（pb）か None。"""
        if not any(bases):
            return None
        wild, passed = self._wild_pitch_probabilities(pitcher, catcher)
        roll = rng.random()
        if roll < wild:
            return "wp"
        if roll < wild + passed:
            return "pb"
        return None

    @staticmethod
    def _clamp_probability(
        value: float,
        minimum: float,
        maximum: float,
    ) -> float:
        return min(maximum, max(minimum, value))

    @staticmethod
    def _multiplier(exponent: float) -> float:
        return math.exp(min(2.0, max(-2.0, exponent)))

    @staticmethod
    def _pitch_quality(pitcher: PlayerAbilitySnapshot) -> float:
        if not pitcher.pitch_repertoire:
            return float(pitcher.stuff or 50)
        return sum(
            float(pitch.quality) * float(pitch.usage) / 100.0
            for pitch in pitcher.pitch_repertoire
        )

    def _effective_control(self, pitcher: PlayerAbilitySnapshot) -> float:
        """制球に変化球の制球を、変化球を使う割合の重みで混ぜたもの。"""
        control = float(pitcher.control or 50)
        breaking = [p for p in pitcher.pitch_repertoire if p.pitch_type != "four_seam"]
        share = sum(p.usage for p in breaking) / 100.0
        if not breaking or share <= 0:
            return control
        command = sum(p.command * p.usage for p in breaking) / sum(p.usage for p in breaking)
        weight = float(self.params["pitcher_effects"]["command_weight"]) * share
        return control * (1.0 - weight) + float(command) * weight

    def _pitcher_indexes(self, pitcher: PlayerAbilitySnapshot) -> dict[str, float]:
        """結果ごとの投手の指数（50が基準。大きいほど投手に有利）。"""
        rule = self.params["pitcher_effects"]
        velocity = pitcher.velocity_kmh
        components = {
            "velocity": (0.0 if velocity is None else
                         (float(velocity) - float(rule["velocity_center"])) * float(rule["points_per_kmh"])),
            "stuff": float(pitcher.stuff or 50) - 50.0,
            "pitch_quality": self._pitch_quality(pitcher) - 50.0,
            "groundball": float(pitcher.groundball or 50) - 50.0,
            "control_low": min(0.0, self._effective_control(pitcher) - float(rule["control_pivot"])),
        }
        return {
            outcome: 50.0 + sum(float(w) * components[key] for key, w in weights.items())
            for outcome, weights in rule["weights"].items()
        }

    @staticmethod
    def batting_side(batter: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot) -> str:
        """打者の立つ打席。両打ちはいつも投手と逆の側（有利な側）。"""
        if batter.bats == "S":
            return "L" if pitcher.throws == "R" else "R"
        return batter.bats

    def _platoon_points(self, batter: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot) -> float:
        """打者の打撃の能力に足す左右の差（＋は打者に有利）。"""
        rule = self.params["platoon"]
        side = self.batting_side(batter, pitcher)
        points = (-float(rule["same_side_points"][side]) if side == pitcher.throws
                  else float(rule["opposite_side_points"]))
        trait = float(rule["trait_points"])
        # 野手の特性は対左投手、投手の特性は対左打者
        if batter.primary_position != "P" and pitcher.throws == "L" and batter.platoon_trait:
            points += trait if batter.platoon_trait == "vs_left_good" else -trait
        if pitcher.primary_position == "P" and side == "L" and pitcher.platoon_trait:
            points += -trait if pitcher.platoon_trait == "vs_left_good" else trait
        return points

    def _platoon_batter(
        self, batter: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot,
    ) -> PlayerAbilitySnapshot:
        points = self._platoon_points(batter, pitcher)
        if not points:
            return batter
        weights = self.params["platoon"]["ability_weights"]
        return replace(batter, **{
            # 打席の結果の計算だけに使う写し（端数を丸めない）
            key: min(100.0, max(1.0, getattr(batter, key) + points * float(weight)))
            for key, weight in weights.items()
        })

    def _event_weights(
        self,
        batter: PlayerAbilitySnapshot,
        pitcher: PlayerAbilitySnapshot,
        defense_strength: float,
    ) -> dict[str, float]:
        batter = self._platoon_batter(batter, pitcher)
        model = self.params["plate_appearance_model"]
        base = model["base_probabilities"]
        scale = model["ability_effect_scale"]
        floor = float(model["probability_floor"])
        defense_center = float(model["defense_center"])

        index = self._pitcher_indexes(pitcher)
        p_control = self._effective_control(pitcher)
        p_strikeout = float(pitcher.strikeout or 50)

        so_exp = (
            (p_strikeout - float(batter.strikeout_resistance))
            * float(scale["strikeout"])
            + (index["whiff"] - float(batter.contact))
            * float(scale["strikeout"])
            * 0.45
        )
        walk_exp = (
            float(batter.plate_discipline) - p_control
        ) * float(scale["walk"])
        single_exp = (
            float(batter.contact) - index["single"]
        ) * float(scale["single"]) + (
            defense_center - defense_strength
        ) * float(scale["single"]) * 0.45

        extra_batter = (
            float(batter.contact) * 0.45
            + float(batter.power) * 0.55
        )
        xbh_exp = (
            extra_batter - index["extra_base_hit"]
        ) * float(scale["extra_base_hit"])
        hr_exp = (
            float(batter.power) - index["home_run"]
        ) * float(scale["home_run"])
        error_exp = (
            50.0 - defense_strength
        ) * float(scale["error"]) + (
            float(batter.speed) - 50.0
        ) * float(scale["error"]) * 0.25
        out_exp = (
            (index["field_out"] - 50.0)
            + (defense_strength - 50.0) * 0.30
            - (float(batter.contact) - 50.0)
        ) * float(scale["field_out"])

        weights = {
            "strikeout": float(base["strikeout"])
            * self._multiplier(so_exp),
            "walk": float(base["walk"])
            * self._multiplier(walk_exp),
            "hit_by_pitch": float(base["hit_by_pitch"])
            * self._multiplier((50.0 - p_control) * 0.004),
            "single": float(base["single"])
            * self._multiplier(single_exp),
            "double": float(base["double"])
            * self._multiplier(xbh_exp),
            "triple": float(base["triple"])
            * self._multiplier(
                xbh_exp * 0.50
                + (float(batter.speed) - 50.0) * 0.006
            ),
            "home_run": float(base["home_run"])
            * self._multiplier(hr_exp),
            "reached_on_error": float(base["reached_on_error"])
            * self._multiplier(error_exp),
            "fielder_choice": float(base["fielder_choice"]),
            "field_out": float(base["field_out"])
            * self._multiplier(out_exp),
        }
        return {
            key: max(floor, value)
            for key, value in weights.items()
        }

    @staticmethod
    def _weighted_choice(rng, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        roll = rng.random() * total
        cumulative = 0.0
        for event_type, weight in weights.items():
            cumulative += weight
            if roll <= cumulative:
                return event_type
        return next(reversed(weights))

    # ---- 作戦（段階F1。値は match_simulation_v1.json の strategy） ----
    def _strategy(self) -> dict:
        return self.params["strategy"]

    @staticmethod
    def _hitting(batter: PlayerAbilitySnapshot) -> float:
        """打者の打撃（ミートと長打の平均）。高いほどバント・スクイズをさせない。"""
        return (float(batter.contact) + float(batter.power)) / 2.0

    @staticmethod
    def _runner_shape(bases: list[str | None]) -> str | None:
        if bases[0] is not None and bases[1] is not None:
            return "first_second"
        if bases[0] is not None:
            return "first"
        if bases[1] is not None:
            return "second"
        return None

    def _bunt_attempt_probability(
        self, batter: PlayerAbilitySnapshot, bases: list[str | None], outs: int,
        margin: int, inning: int, small_ball: float = 1.0,
    ) -> float:
        """送りバントを試みる確率（三塁が空き・一塁か二塁に走者・0〜1死）。"""
        rule = self._strategy()["sacrifice_bunt"]
        shape = self._runner_shape(bases)
        if outs > 1 or bases[2] is not None or shape is None:
            return 0.0
        value = float(rule["base"][str(outs)][shape])
        if abs(margin) <= int(rule["close_margin"]):
            if inning >= int(rule["late_inning_from"]):
                value *= float(rule["late_close_multiplier"])
        else:
            value *= float(rule["ahead_far_multiplier" if margin > 0 else "behind_far_multiplier"])
        value *= math.exp(
            -(self._hitting(batter) - 50.0) * float(rule["batter_hitting_log_per_point"])
            + (float(batter.bunt) - 50.0) * float(rule["bunt_log_per_point"])
        )
        return min(float(rule["max_probability"]), value * small_ball)

    def _squeeze_attempt_probability(
        self, batter: PlayerAbilitySnapshot, bases: list[str | None], outs: int,
        margin: int, inning: int, small_ball: float = 1.0,
    ) -> float:
        """スクイズを試みる確率（三塁に走者・0〜1死・点差が max_margin 以内）。"""
        rule = self._strategy()["squeeze"]
        if outs > 1 or bases[2] is None or abs(margin) > int(rule["max_margin"]):
            return 0.0
        value = float(rule["base"][outs])
        if abs(margin) <= int(rule["close_margin"]) and inning >= int(rule["late_inning_from"]):
            value *= float(rule["late_close_multiplier"])
        value *= math.exp(-(self._hitting(batter) - 50.0) * float(rule["batter_hitting_log_per_point"]))
        return min(float(rule["max_probability"]), value * small_ball)

    def _hit_and_run_probability(
        self, batter: PlayerAbilitySnapshot, runner: PlayerAbilitySnapshot | None,
        bases: list[str | None], outs: int, margin: int, mobility: float = 1.0,
    ) -> float:
        """エンドランを試みる確率（一塁に走者・満塁でない・max_outs まで）。

        一・二塁では両方の走者が走る。空振り三振なら重盗として盗塁・盗塁死を走者ごとに記録する。"""
        rule = self._strategy()["hit_and_run"]
        if (runner is None or bases[0] is None or (bases[1] is not None and bases[2] is not None)
                or outs > int(rule["max_outs"])):
            return 0.0
        value = float(rule["base"]) * math.exp(
            (float(batter.contact) - 50.0) * float(rule["contact_log_per_point"])
            + (float(batter.strikeout_resistance) - 50.0) * float(rule["strikeout_resistance_log_per_point"])
            + (float(runner.speed) - 50.0) * float(rule["runner_speed_log_per_point"])
        )
        if abs(margin) > int(rule["max_margin"]):
            value *= float(rule["far_margin_multiplier"])
        return min(float(rule["max_probability"]), value * mobility)

    def _choose_tactic(
        self, *, batter: PlayerAbilitySnapshot, bases: list[str | None], outs: int, margin: int,
        inning: int, offense_players: Mapping[str, PlayerAbilitySnapshot],
        tactics: CoachTactics, rng,
    ) -> str | None:
        """打席の前の作戦：スクイズ → 送りバント → エンドランの順に1つだけ（なければ None）。

        どの場面でも3回引くので、乱数の使い方は場面によらない。"""
        squeeze = self._squeeze_attempt_probability(batter, bases, outs, margin, inning, tactics.small_ball)
        bunt = self._bunt_attempt_probability(batter, bases, outs, margin, inning, tactics.small_ball)
        runner = offense_players.get(bases[0]) if bases[0] is not None else None
        hit_and_run = self._hit_and_run_probability(batter, runner, bases, outs, margin, tactics.mobility)
        draws = (rng.random(), rng.random(), rng.random())
        if draws[0] < squeeze:
            return "squeeze"
        if draws[1] < bunt:
            return "bunt"
        if draws[2] < hit_and_run:
            return "hit_and_run"
        return None

    def _bunt_outcome(
        self, tactic: str, *, batter: PlayerAbilitySnapshot, bases: list[str | None],
        offense_players: Mapping[str, PlayerAbilitySnapshot], defense_strength: float, rng,
    ) -> str:
        """バント・スクイズの成否：``ok``（成功）か失敗の種類 ``foul``・``pop``・``fc``・``dp``。

        成功の確率はバントの能力（スクイズは三塁走者の走力、送りバントは打者の走力と守備力も）。"""
        rule = self._strategy()["squeeze" if tactic == "squeeze" else "sacrifice_bunt"]
        success = rule["success"]
        value = float(success["base"]) + (float(batter.bunt) - 50.0) * float(success["per_bunt_point"])
        if tactic == "squeeze":
            value += (float(offense_players[bases[2]].speed) - 50.0) * float(success["per_runner_speed_point"])
        else:
            value += ((float(batter.speed) - 50.0) * float(success["per_speed_point"])
                      - (defense_strength - 50.0) * float(success["per_defense_point"]))
        if rng.random() < self._clamp_probability(value, float(success["min"]), float(success["max"])):
            return "ok"
        weights = {key: float(value) for key, value in rule["failure_weights"].items()}
        if tactic == "bunt" and bases[0] is None:
            # 一塁に走者がいなければ併殺にならない（先の走者のアウトだけ）
            weights["fc"] += weights.pop("dp")
        return self._weighted_choice(rng, weights)

    @staticmethod
    def _apply_bunt(
        tactic: str, outcome: str, batter_id: str, bases: list[str | None],
    ) -> tuple[str, list[str], int, int]:
        """バント・スクイズ（ファウルで追い込まれた場合を除く）を塁に写す。

        返り値は (イベントの種類, 生還した走者, この打席のアウトの数, 打点)。"""
        first, second, third = bases
        if tactic == "squeeze":
            if outcome == "ok":
                # 三塁走者が生還し、打者はアウト。ほかの走者は1つ進む（犠打・打点1）
                bases[:] = [None, first, second]
                return "sacrifice_bunt", [third], 1, 1
            if outcome == "fc":
                # 三塁走者が本塁でアウト。打者は一塁へ、ほかの走者は1つ進む
                bases[:] = [batter_id, first, second]
                return "fielder_choice", [], 1, 0
            if outcome == "pop":
                return "bunt_pop_out", [], 1, 0
            # 小フライで三塁走者も戻れず併殺
            bases[2] = None
            return "bunt_double_play", [], 2, 0
        if outcome == "ok":
            bases[:] = [None, first, second]
            return "sacrifice_bunt", [], 1, 0
        if outcome == "pop":
            return "bunt_pop_out", [], 1, 0
        # 先の走者（二塁の走者がいれば三塁で、いなければ二塁で）がアウト
        trailing = first if second is not None else None
        if outcome == "fc":
            bases[:] = [batter_id, trailing, None]
            return "fielder_choice", [], 1, 0
        if first is None:
            raise ValueError("bunt double play requires a runner on first")
        bases[:] = [None, trailing, None]
        return "bunt_double_play", [], 2, 0

    def _tactic_weights(self, weights: dict[str, float], mode: str) -> dict[str, float]:
        """作戦の打席の重み：追い込まれた打席（two_strike）かエンドラン（hit_and_run）。"""
        rule = self._strategy()[mode]
        out = dict(weights)
        out["strikeout"] = out.get("strikeout", 0.0) * float(rule["strikeout_multiplier"])
        out["walk"] = out.get("walk", 0.0) * float(rule["walk_multiplier"])
        return out

    # ---- 選手の交代（段階F2。値は match_simulation_v1.json の substitutions） ----
    def _substitutions(self) -> dict:
        return self.params["substitutions"]

    def _hitting_value(self, batter: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot) -> float:
        """この投手に対する打撃の値（左右の差を入れた打撃の総合）。1試合の中では覚えておく。"""
        cache = self.__dict__.setdefault("_value_cache", {})
        key = ("hit", id(batter), id(pitcher))
        hit = cache.get(key)
        # 写しも一緒に持つので、試合の途中で捨てられた写しの番号が別の選手に使われても取り違えない
        if hit is None or hit[0] is not batter or hit[1] is not pitcher:
            hit = (batter, pitcher,
                   self._strength_generator()._batting_composite(self._platoon_batter(batter, pitcher)))
            cache[key] = hit
        return hit[2]

    def _defense_value(self, player: PlayerAbilitySnapshot, position: str) -> float:
        cache = self.__dict__.setdefault("_value_cache", {})
        key = ("def", id(player), position)
        held = cache.get(key)
        if held is None or held[0] is not player:
            held = (player, self._strength_generator()._defense_composite(player, position))
            cache[key] = held
        return held[1]

    @staticmethod
    def _bench(state: TeamMatchState, players: Mapping[str, PlayerAbilitySnapshot],
               staff: tuple[str, ...]) -> list[PlayerAbilitySnapshot]:
        """代打・代走・守備固めに使える控え（投手陣を除く。退いた選手は入らない）。"""
        keep = set(staff)
        return [players[pid] for pid in sorted(state.bench_player_ids) if pid in players and pid not in keep]

    def _choose_pinch_hitter(
        self, *, batter: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot,
        bench: list[PlayerAbilitySnapshot], inning: int, margin: int, pitcher_slot: bool,
        tactics: CoachTactics,
    ) -> str | None:
        """代打に出す控え（なければ None）。終盤の接戦・負けている場面で、明らかに打てる控えがいるとき。"""
        rule = self._substitutions()["pinch_hitter"]
        if (inning < int(self._substitutions()["late_inning_from"]) or not bench
                or not -int(rule["max_deficit"]) <= margin <= int(rule["max_lead"])):
            return None
        need = float(rule["pitcher_slot_min_gain" if pitcher_slot else "min_gain"]) / tactics.substitutions
        best = max(bench, key=lambda p: (self._hitting_value(p, pitcher), p.player_id))
        if self._hitting_value(best, pitcher) - self._hitting_value(batter, pitcher) >= need:
            return best.player_id
        return None

    def _choose_pinch_runner(
        self, *, bases: list[str | None], players: Mapping[str, PlayerAbilitySnapshot],
        bench: list[PlayerAbilitySnapshot], inning: int, margin: int, protected: set[str],
        tactics: CoachTactics,
    ) -> tuple[str, str] | None:
        """代走：(退く走者, 入る控え) かNone。終盤の接戦で、足の遅い走者（先の塁から）に足の速い控え。"""
        rule = self._substitutions()["pinch_runner"]
        if (inning < int(rule["inning_from"]) or not bench
                or not -int(rule["max_deficit"]) <= margin <= int(rule["max_lead"])):
            return None
        fastest = max(bench, key=lambda p: (p.speed, p.player_id))
        need = float(rule["min_speed_gain"]) / tactics.substitutions
        for runner_id in (bases[2], bases[1], bases[0]):
            if runner_id is None or runner_id in protected:
                continue
            runner = players[runner_id]
            if runner.speed <= int(rule["max_runner_speed"]) and fastest.speed - runner.speed >= need:
                return runner_id, fastest.player_id
        return None

    def _choose_defensive_replacements(
        self, *, state: TeamMatchState, players: Mapping[str, PlayerAbilitySnapshot],
        bench: list[PlayerAbilitySnapshot], inning: int, lead: int, entered: set[str],
        tactics: CoachTactics,
    ) -> list[tuple[str, str]]:
        """守りの初めの守備固め：(退く野手, 入る控え) の並び。代打・代走で入った野手はリードに関係なく見る。"""
        rule = self._substitutions()["defensive_replacement"]
        late = inning >= int(self._substitutions()["late_inning_from"])
        leading = late and int(rule["min_lead"]) <= lead <= int(rule["max_lead"])
        out, used = [], set()
        candidates = []
        for assignment in state.defensive_alignment:
            if assignment.defensive_position == "P":
                continue
            pid = assignment.player_id
            if not (leading or (late and pid in entered)):
                continue
            need = float(rule["entered_min_gain" if pid in entered else "min_gain"]) / tactics.substitutions
            current = self._defense_value(players[pid], assignment.defensive_position)
            options = [p for p in bench if p.player_id not in used]
            if not options:
                break
            best = max(options, key=lambda p: (self._defense_value(p, assignment.defensive_position), p.player_id))
            gain = self._defense_value(best, assignment.defensive_position) - current
            if gain >= need:
                candidates.append((gain, pid, best.player_id))
                used.add(best.player_id)
        for _, outgoing, incoming in sorted(candidates, reverse=True)[:int(rule["max_per_half"])]:
            out.append((outgoing, incoming))
        return out

    def _platoon_lineup(self, lineup, team: TeamMatchInput, opponent: PlayerAbilitySnapshot | None,
                        staff: tuple[str, ...], tactics: CoachTactics):
        """相手の先発投手の腕を見て、先発メンバーを少しだけ変える（1人まで入れ替え、隣どうしの打順の入れ替え）。"""
        if opponent is None:
            return lineup
        rule = self._substitutions()["platoon_lineup"]
        # 先発選びなので、調子を入れない能力に、監督が見た調子の加点（段階F4）を足して比べる
        # （先発・打順を選んだときと同じ物差し。試合の中身の能力ではない）
        players = {p.player_id: p for p in team.lineup_abilities}
        bonus = dict(tactics.form_bonus)

        def hitting(player):
            return self._hitting_value(player, opponent) + bonus.get(player.player_id, 0.0)

        starters = {entry.player_id for entry in lineup.entries} | {a.player_id for a in lineup.defense}
        bench = [p for p in team.lineup_abilities if p.player_id not in starters and p.player_id not in set(staff)]
        entries = list(lineup.entries)
        defense = list(lineup.defense)
        swaps = 0
        need = float(rule["selection_min_gain"]) / tactics.substitutions
        while swaps < int(rule["max_selection_swaps"]) and bench:
            best = None
            for index, entry in enumerate(entries):
                if entry.defensive_position in ("P", "C", "DH"):
                    continue
                starter = players[entry.player_id]
                base_hit = hitting(starter)
                base_def = self._defense_value(starter, entry.defensive_position)
                for candidate in bench:
                    gain = hitting(candidate) - base_hit
                    loss = base_def - self._defense_value(candidate, entry.defensive_position)
                    if gain >= need and loss <= float(rule["max_defense_loss"]):
                        key = (gain, candidate.player_id)
                        if best is None or key > best[0]:
                            best = (key, index, candidate)
            if best is None:
                break
            _, index, candidate = best
            outgoing = entries[index]
            score = round(self._strength_generator()._selection_score(candidate, outgoing.defensive_position), 4)
            entries[index] = replace(outgoing, player_id=candidate.player_id, selection_score=score)
            defense = [replace(a, player_id=candidate.player_id) if a.player_id == outgoing.player_id else a
                       for a in defense]
            bench = [p for p in bench if p.player_id != candidate.player_id]
            swaps += 1
        order = sorted(entries, key=lambda e: e.batting_order)
        swaps = 0
        index = 0
        composite = self._strength_generator()._batting_composite
        while index < len(order) - 1 and swaps < int(rule["max_order_swaps"]):
            here, after = order[index], order[index + 1]
            a, b = players[after.player_id], players[here.player_id]
            gain = hitting(a) - hitting(b)
            # 左右の差だけでも基準に届くときに限る（役割で組んだ打順を、打撃の差や調子の加点だけで
            # 崩さない）。打てる順の打順では後ろの打者の総合はほぼ前以下なので、今までとほぼ同じ判定になる
            platoon = gain - (composite(a) + bonus.get(a.player_id, 0.0)
                              - composite(b) - bonus.get(b.player_id, 0.0))
            if min(gain, platoon) >= float(rule["order_min_gain"]):
                order[index] = replace(after, batting_order=here.batting_order)
                order[index + 1] = replace(here, batting_order=after.batting_order)
                swaps += 1
                index += 2
            else:
                index += 1
        changed = replace(lineup, entries=tuple(order), defense=tuple(defense))
        return lineup if changed == lineup else changed

    def _platoon_reliever(
        self, *, candidates: list[str], players: Mapping[str, PlayerAbilitySnapshot],
        upcoming: list[PlayerAbilitySnapshot], inning: int, margin: int, tactics: CoachTactics,
    ) -> str | None:
        """終盤の接戦で次の打者が同じ側に続くなら、その側に強い腕の救援（候補の中で能力の差が小さいもの）。"""
        rule = self._substitutions()["platoon_relief"]
        if inning < int(rule["inning_from"]) or abs(margin) > int(rule["close_margin"]) or not candidates:
            return None
        sides = [b.bats for b in upcoming[:int(rule["lookahead"])] if b.bats in ("L", "R")]
        side = next((s for s in ("L", "R") if sides.count(s) >= int(rule["min_same_side"])), None)
        if side is None:
            return None
        quality = self._strength_generator()._pitcher_quality
        first = quality(players[candidates[0]])
        gap = float(rule["max_quality_gap"]) / tactics.substitutions
        return next((pid for pid in candidates
                     if players[pid].throws == side and first - quality(players[pid]) <= gap), None)

    def _outs_in_play(self) -> dict:
        return self.params["outs_in_play"]

    def _ground_share(self, batter: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot) -> float:
        """凡退のうちゴロの割合（打者のミート・長打と投手のゴロで決まる）。"""
        rule = self._outs_in_play()["ground_share"]
        value = (
            float(rule["base"])
            + (float(pitcher.groundball or 50) - 50.0) * float(rule["per_groundball_point"])
            + (float(batter.power) - 50.0) * float(rule["per_power_point"])
            + (float(batter.contact) - 50.0) * float(rule["per_contact_point"])
        )
        return self._clamp_probability(value, float(rule["min"]), float(rule["max"]))

    def _double_play_probability(self, runner_speed: float, defense_strength: float) -> float:
        """一塁に走者・2死未満のゴロが併殺になる確率（打者の走力・守備力）。"""
        rule = self._outs_in_play()["double_play"]
        value = (
            float(rule["base"])
            - (runner_speed - 50.0) * float(rule["speed_effect_per_point"])
            + (defense_strength - 50.0) * float(rule["defense_effect_per_point"])
        )
        return self._clamp_probability(value, float(rule["min"]), float(rule["max"]))

    # ---- 打球の方向ごとの守備（H2） ----
    def _fielding_value(self, player: PlayerAbilitySnapshot, position: str, weights: Mapping) -> float:
        untrained = float(self.params["fielding"]["untrained_ability_value"])
        total = 0.0
        for key, weight in weights.items():
            if key == "position_aptitude":
                value = float(player.aptitude(position))
            else:
                raw = getattr(player, key)
                value = untrained if raw is None else float(raw)
            total += value * float(weight)
        return total / sum(float(w) for w in weights.values())

    def _fielding_profile(self, alignment, players: Mapping[str, PlayerAbilitySnapshot]) -> _FieldingProfile:
        """守っている並び（守備位置, 選手）から、打球を処理する8つの位置の値とチームの基準。"""
        rule = self.params["fielding"]
        shares = rule["reference_share"]
        out: dict[str, tuple[str, float, float, int]] = {}
        for position, player_id in alignment:
            if position not in shares:
                continue
            player = players[player_id]
            group = "outfield" if position in _OUTFIELD else "infield"
            out[position] = (
                player_id,
                self._fielding_value(player, position, rule["skill_weights"][group]),
                self._fielding_value(player, position, rule["arm_weights"]),
                int(player.aptitude(position)),
            )
        total = sum(float(shares[p]) for p in out)
        return _FieldingProfile(
            players=out,
            skill_reference=sum(out[p][1] * float(shares[p]) for p in out) / total,
            arm_reference=sum(out[p][2] * float(shares[p]) for p in out) / total,
        )

    @staticmethod
    def _draw_share(shares: Mapping[str, float], rng) -> str:
        roll = rng.random()
        last = None
        for key, share in shares.items():
            last = key
            roll -= float(share)
            if roll < 0:
                return key
        return last

    def _ball_type(self, event_type: str, batter: PlayerAbilitySnapshot,
                   pitcher: PlayerAbilitySnapshot, rng) -> str:
        rule = self.params["fielding"]
        if event_type == "field_out":
            if rng.random() < self._ground_share(batter, pitcher):
                return "ground"
            return "line" if rng.random() < float(rule["air_line_share"]) else "fly"
        key = "extra_base" if event_type in ("double", "triple") else event_type
        return self._draw_share(rule["ball_types"][key], rng)

    def _fielding_position(self, event_type: str, ball_type: str, side: str, rng) -> str:
        """打球の種類と方向から処理する守備位置（右打者の引っ張りは左方向）。"""
        rule = self.params["fielding"]
        direction = self._draw_share(rule["direction"][ball_type], rng)
        table = rule["positions"]["outfield" if event_type in ("double", "triple") else ball_type]
        position = self._draw_share(table[direction], rng)
        return _MIRROR_POSITION.get(position, position) if side == "L" else position

    def _fielding_multiplier(self, gap: float, per_point: float) -> float:
        rule = self.params["fielding"]
        return min(float(rule["max_multiplier"]), max(float(rule["min_multiplier"]),
                                                       math.exp(max(-20.0, min(20.0, -gap * per_point)))))

    def _fielded_event(self, event_type: str, weights: Mapping[str, float], skill_gap: float, rng) -> str:
        """処理した選手の守備の値とチームの基準の差で、単打⇔凡退、失策⇔凡退を少し動かす。

        単打（失策）の確率をその打球だけ倍率 m 倍にする：m < 1 なら単打（失策）を m の割合だけ残し、
        m > 1 なら凡退を (m − 1) × 単打（失策）の重み ÷ 凡退の重み の割合で単打（失策）にする。
        基準との差の平均は0なので、チーム全体の単打・失策の割合はほとんど変わらない。重みに
        単打・凡退・失策がない（試験用の打席列）ときは変えない。"""
        rule = self.params["fielding"]
        out_weight = float(weights.get("field_out", 0.0))
        for target, per_point in (("single", rule["hit_log_per_point"]),
                                  ("reached_on_error", rule["error_log_per_point"])):
            weight = float(weights.get(target, 0.0))
            if out_weight <= 0 or weight <= 0:
                continue
            m = self._fielding_multiplier(skill_gap, float(per_point))
            roll = rng.random()
            if event_type == target and m < 1 and roll >= m:
                event_type = "field_out"
            elif event_type == "field_out" and m > 1 and roll < min(1.0, (m - 1) * weight / out_weight):
                event_type = target
        return event_type

    def _field_ball(self, event_type: str, *, weights: Mapping[str, float], batter: PlayerAbilitySnapshot,
                    pitcher: PlayerAbilitySnapshot, profile: _FieldingProfile, rng):
        """インプレーの打球の行き先を決め、守った選手で結果を動かす。(結果, _Fielded か None)。"""
        if event_type not in _FIELDED_EVENTS:
            return event_type, None
        ball_type = self._ball_type(event_type, batter, pitcher, rng)
        position = self._fielding_position(event_type, ball_type, self.batting_side(batter, pitcher), rng)
        player_id, skill, arm, aptitude = profile.players[position]
        gap = skill - profile.skill_reference
        if event_type in ("single", "field_out", "reached_on_error"):
            event_type = self._fielded_event(event_type, weights, gap, rng)
        return event_type, _Fielded(position, player_id, ball_type, skill, aptitude, gap,
                                    arm - profile.arm_reference)

    def _classify_out(
        self,
        event_type: str,
        bases: list[str | None],
        outs: int,
        batter: PlayerAbilitySnapshot,
        rng,
        pitcher: PlayerAbilitySnapshot | None = None,
        defense_strength: float = 50.0,
        ball_type: str | None = None,
        double_play_bonus: float = 0.0,
    ) -> str:
        """凡退（field_out）をゴロ・併殺打・フライ・犠飛に分ける。

        ``ball_type`` は打球の行き先を決めたときの打球の種類（ゴロ・ライナー・フライ。ライナーは犠飛に
        しない）、``double_play_bonus`` は処理した内野手の肩・送球による併殺の確率の増減（H2）。

        ゴロ／フライの割合は打者と投手の能力、併殺は一塁に走者・2死未満のゴロで打者の
        走力と守備力、犠飛は三塁に走者・2死未満のフライで打者のミート・長打で決める。"""
        if event_type != "field_out":
            return event_type
        pitcher = pitcher or batter
        ground = (rng.random() < self._ground_share(batter, pitcher)) if ball_type is None else ball_type == "ground"
        if ground:
            rule = self._outs_in_play()["double_play"]
            if (bases[0] is not None and outs < 2
                    and rng.random() < self._clamp_probability(
                        self._double_play_probability(float(batter.speed), defense_strength) + double_play_bonus,
                        float(rule["min"]), float(rule["max"]))):
                return "double_play"
            return "ground_out"
        settings = self.params["situational_events"]["sacrifice_fly"]
        if (settings["enabled"] and outs <= int(settings["max_outs"]) and bases[2] is not None
                and ball_type != "line"):
            contact_factor = 0.75 + float(batter.contact) / 200.0
            power_factor = 0.85 + float(batter.power) / 300.0
            probability = min(
                0.95, float(settings["base_probability"]) * contact_factor * power_factor,
            )
            if rng.random() < probability:
                return "sacrifice_fly"
        return "fly_out"

    @staticmethod
    def _record_baserunning_play(event_type, before, after, scored, responsibility, earned, pitcher_id,
                                 plate_appearance_no, outs):
        """打席のあとの走塁（暴投・捕逸・本盗）で走者が進む・生還するのを責任と自責点の記録に写す。

        打者はいない（batter_id は空）。生還した走者の責任（責任投手）を返す。"""
        runners = responsibility.record_play(
            bases_before=before, bases_after=after, scored_runner_ids=scored, batter_id="",
            pitcher_id=pitcher_id, event_type=event_type, plate_appearance_no=plate_appearance_no)
        earned.record_play(
            bases_before=before, bases_after=after, scored_runners=runners, batter_id="",
            pitcher_id=pitcher_id, event_type=event_type, plate_appearance_no=plate_appearance_no,
            outs_before=outs, outs_on_play=0)
        return runners

    def _advance_out(self, key: str, runner: PlayerAbilitySnapshot, defense_strength: float, rng) -> bool:
        """凡退の間に走者が次の塁へ進むか（進塁打・タッチアップ）。"""
        return rng.random() < self._advance_probability(
            base_probability=float(self._outs_in_play()["advance"][key]),
            runner=runner,
            defense_strength=defense_strength,
        )

    @staticmethod
    def _steal_base(bases: list[str | None]) -> int | None:
        """盗塁を試みうる走者の塁（0：一塁から二盗、1：二塁から三盗）。本盗はしない。"""
        if bases[0] is not None and bases[1] is None:
            return 0
        if bases[1] is not None and bases[2] is None:
            return 1
        return None

    def _steal_attempt_probability(
        self, runner: PlayerAbilitySnapshot, from_index: int, *, outs: int, margin: int, inning: int,
        mobility: float = 1.0,
    ) -> float:
        rule = self.params["stolen_bases"]["attempt"]
        base = float(rule["second_base" if from_index == 0 else "third_base"])
        value = base * math.exp(
            (float(runner.stealing) - 50.0) * float(rule["per_stealing_point"])
            + (float(runner.speed) - 50.0) * float(rule["per_speed_point"])
        )
        value *= float(rule["outs_multiplier"][outs])
        if abs(margin) >= int(rule["blowout_margin"]):
            value *= float(rule["blowout_multiplier"])
        elif inning >= int(rule["late_inning_from"]) and abs(margin) <= int(rule["close_margin"]):
            value *= float(rule["late_close_multiplier"])
        # 監督の機動力の倍率（coach_tactics_v1 の strategy）
        value *= mobility
        return min(float(rule["max_probability"]), value)

    def _steal_success_probability(
        self, runner: PlayerAbilitySnapshot, catcher: PlayerAbilitySnapshot,
        pitcher: PlayerAbilitySnapshot, from_index: int,
    ) -> float:
        rule = self.params["stolen_bases"]["success"]
        catching = catcher.catching
        if catching is None:
            catching = int(self.params["stolen_bases"]["catcher_catching_default"])
        value = (
            float(rule["second_base" if from_index == 0 else "third_base"])
            + (float(runner.stealing) - 50.0) * float(rule["per_stealing_point"])
            + (float(runner.speed) - 50.0) * float(rule["per_speed_point"])
            - (float(catcher.arm_strength) - 50.0) * float(rule["per_catcher_arm_point"])
            - (float(catcher.throwing) - 50.0) * float(rule["per_catcher_throwing_point"])
            - (float(catching) - 50.0) * float(rule["per_catcher_catching_point"])
            - (float(pitcher.quick or 50) - 50.0) * float(rule["per_pitcher_quick_point"])
        )
        return self._clamp_probability(value, float(rule["min"]), float(rule["max"]))

    def _pickoff_probability(self, runner: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot) -> float:
        rule = self.params["stolen_bases"]["pickoff"]
        value = float(rule["base"]) * math.exp(
            (float(pitcher.quick or 50) - 50.0) * float(rule["per_quick_point"])
            - (float(runner.baserunning) - 50.0) * float(rule["per_baserunning_point"])
        )
        return self._clamp_probability(value, float(rule["min"]), float(rule["max"]))

    def _home_steal_probabilities(
        self, runner: PlayerAbilitySnapshot, catcher: PlayerAbilitySnapshot,
        pitcher: PlayerAbilitySnapshot, mobility: float = 1.0,
    ) -> tuple[float, float]:
        """本盗の (試みる確率, 成功の確率)。"""
        rule = self.params["stolen_bases"]["home_steal"]
        attempt = min(float(rule["max_probability"]), float(rule["base"]) * math.exp(
            (float(runner.stealing) - 50.0) * float(rule["per_stealing_point"])
            + (float(runner.speed) - 50.0) * float(rule["per_speed_point"])) * mobility)
        s = rule["success"]
        catching = catcher.catching
        if catching is None:
            catching = int(self.params["stolen_bases"]["catcher_catching_default"])
        success = self._clamp_probability(
            float(s["base"])
            + (float(runner.stealing) - 50.0) * float(s["per_stealing_point"])
            + (float(runner.speed) - 50.0) * float(s["per_speed_point"])
            - (float(catcher.arm_strength) - 50.0) * float(s["per_catcher_arm_point"])
            - (float(catching) - 50.0) * float(s["per_catcher_catching_point"])
            - (float(pitcher.quick or 50) - 50.0) * float(s["per_pitcher_quick_point"]),
            float(s["min"]), float(s["max"]))
        return attempt, success

    def _attempt_steal(
        self, *, bases: list[str | None], outs: int, margin: int, inning: int,
        offense_players: Mapping[str, PlayerAbilitySnapshot],
        catcher: PlayerAbilitySnapshot, pitcher: PlayerAbilitySnapshot, rng,
        mobility: float = 1.0, forced: bool = False,
    ) -> list[tuple[str, int, str]] | None:
        """打席のあとの盗塁：走者ごとの (走者, 元の塁, 結果) の並び（先の走者から）か None。

        結果は sb（盗塁）・cs（盗塁死）・po（牽制死）・adv（重盗で二塁走者が刺される間に一塁走者が
        進む。盗塁は付かない）。元の塁は 0〜2（2 は本盗）。``forced`` はエンドランの空振り
        （走者はもう走っているので必ず試み、牽制はない）。"""
        if outs >= 3:
            return None
        rule = self.params["stolen_bases"]
        bonus = float(rule["hit_and_run_strikeout_success_bonus"]) if forced else 0.0
        if bases[0] is not None and bases[1] is not None and bases[2] is None:
            # 一・二塁の重盗（二塁走者の三盗の成否で決まる）
            lead, trail = bases[1], bases[0]
            runner = offense_players[lead]
            double = rule["double_steal"]
            if not forced and rng.random() >= float(double["attempt_multiplier"]) * self._steal_attempt_probability(
                    runner, 1, outs=outs, margin=margin, inning=inning, mobility=mobility):
                return None
            success = self._clamp_probability(
                self._steal_success_probability(runner, catcher, pitcher, 1)
                + float(double["success_bonus"]) + bonus,
                float(rule["success"]["min"]), float(rule["success"]["max"]))
            if rng.random() < success:
                return [(lead, 1, "sb"), (trail, 0, "sb")]
            # 3アウト目なら一塁走者は進まない
            return [(lead, 1, "cs")] + ([(trail, 0, "adv")] if outs < 2 else [])
        if bases[2] is not None and outs < 2 and not forced:
            # 本盗（まれ）
            runner = offense_players[bases[2]]
            attempt, success = self._home_steal_probabilities(runner, catcher, pitcher, mobility)
            if rng.random() < attempt:
                return [(bases[2], 2, "sb" if rng.random() < success else "cs")]
        from_index = self._steal_base(bases)
        if from_index is None:
            return None
        runner_id = bases[from_index]
        runner = offense_players[runner_id]
        if forced:
            probability = self._clamp_probability(
                self._steal_success_probability(runner, catcher, pitcher, from_index) + bonus,
                float(rule["success"]["min"]), float(rule["success"]["max"]))
            return [(runner_id, from_index, "sb" if rng.random() < probability else "cs")]
        if rng.random() >= self._steal_attempt_probability(
                runner, from_index, outs=outs, margin=margin, inning=inning, mobility=mobility):
            return None
        if rng.random() < self._pickoff_probability(runner, pitcher):
            return [(runner_id, from_index, "po")]
        success = rng.random() < self._steal_success_probability(runner, catcher, pitcher, from_index)
        return [(runner_id, from_index, "sb" if success else "cs")]

    def _advance_probability(
        self,
        *,
        base_probability: float,
        runner: PlayerAbilitySnapshot,
        defense_strength: float,
    ) -> float:
        params = self.params["baserunning"]
        value = (
            base_probability
            + (float(runner.baserunning) - 50.0)
            * float(params["speed_effect_per_point"])
            + (float(runner.speed) - 50.0)
            * float(params["speed_effect_per_point"])
            * 0.50
            - (defense_strength - 50.0)
            * float(params["defense_effect_per_point"])
        )
        return self._clamp_probability(
            value,
            float(params["min_probability"]),
            float(params["max_probability"]),
        )

    @staticmethod
    def _force_walk(
        bases: list[str | None],
        batter_id: str,
    ) -> list[str]:
        scored: list[str] = []
        first, second, third = bases
        if first is not None:
            if second is not None:
                if third is not None:
                    scored.append(third)
                bases[2] = second
            bases[1] = first
        bases[0] = batter_id
        return scored

    def _apply_event(
        self,
        *,
        event_type: str,
        batter_id: str,
        bases: list[str | None],
        offense_players: dict[str, PlayerAbilitySnapshot],
        defense_strength: float,
        rng,
        outs: int = 0,
        running_start: bool = False,
    ) -> tuple[list[str], int, int]:
        """``outs`` は打席の前のアウトの数（凡退の間の進塁・得点は3アウト目では起きない）。
        ``running_start`` はエンドラン（一塁走者が先にスタートしている）。"""
        hit_and_run = self._strategy()["hit_and_run"] if running_start else None
        outs_before = outs
        scored: list[str] = []
        outs = 0
        rbi = 0
        first, second, third = bases

        if event_type in {"walk", "hit_by_pitch"}:
            scored = self._force_walk(bases, batter_id)
            rbi = len(scored)
            return scored, outs, rbi

        if event_type == "single":
            if third is not None:
                scored.append(third)
            new_third: str | None = None
            if second is not None:
                runner = offense_players[second]
                probability = self._advance_probability(
                    base_probability=float(
                        self.params["baserunning"][
                            "single_runner_from_second_score_base"
                        ]
                    ),
                    runner=runner,
                    defense_strength=defense_strength,
                )
                if rng.random() < probability:
                    scored.append(second)
                else:
                    new_third = second
            new_second: str | None = None
            if first is not None:
                runner = offense_players[first]
                probability = self._advance_probability(
                    base_probability=float(
                        self.params["baserunning"][
                            "single_runner_from_first_to_third_base"
                        ]
                    ) + (float(hit_and_run["single_first_to_third_bonus"]) if hit_and_run else 0.0),
                    runner=runner,
                    defense_strength=defense_strength,
                )
                if new_third is None and rng.random() < probability:
                    new_third = first
                else:
                    new_second = first
            bases[:] = [batter_id, new_second, new_third]
            rbi = len(scored)
            return scored, outs, rbi

        if event_type == "double":
            if third is not None:
                scored.append(third)
            if second is not None:
                scored.append(second)
            new_third = None
            if first is not None:
                runner = offense_players[first]
                probability = self._advance_probability(
                    base_probability=float(
                        self.params["baserunning"][
                            "double_runner_from_first_score_base"
                        ]
                    ) + (float(hit_and_run["double_first_scores_bonus"]) if hit_and_run else 0.0),
                    runner=runner,
                    defense_strength=defense_strength,
                )
                if rng.random() < probability:
                    scored.append(first)
                else:
                    new_third = first
            bases[:] = [None, batter_id, new_third]
            rbi = len(scored)
            return scored, outs, rbi

        if event_type == "triple":
            scored.extend(
                runner_id
                for runner_id in (first, second, third)
                if runner_id is not None
            )
            bases[:] = [None, None, batter_id]
            rbi = len(scored)
            return scored, outs, rbi

        if event_type == "home_run":
            scored.extend(
                runner_id
                for runner_id in (first, second, third)
                if runner_id is not None
            )
            scored.append(batter_id)
            bases[:] = [None, None, None]
            rbi = len(scored)
            return scored, outs, rbi

        if event_type == "reached_on_error":
            if third is not None:
                scored.append(third)
            new_third = None
            if second is not None:
                runner = offense_players[second]
                probability = self._advance_probability(
                    base_probability=float(
                        self.params["baserunning"][
                            "error_runner_from_second_score_base"
                        ]
                    ),
                    runner=runner,
                    defense_strength=defense_strength,
                )
                if rng.random() < probability:
                    scored.append(second)
                else:
                    new_third = second
            new_second = first
            bases[:] = [batter_id, new_second, new_third]
            return scored, outs, 0

        if event_type == "fielder_choice":
            outs = 1
            if first is not None:
                bases[:] = [batter_id, second, third]
            elif second is not None:
                bases[:] = [batter_id, None, third]
            elif third is not None:
                bases[:] = [batter_id, second, None]
            else:
                bases[:] = [None, None, None]
            return scored, outs, 0

        if event_type == "sacrifice_bunt":
            # 打者はアウトで走者は1つずつ進む（スクイズは _apply_bunt）
            if third is not None:
                raise ValueError("sacrifice bunt with a runner on third is a squeeze")
            bases[:] = [None, first, second]
            return scored, 1, 0

        if event_type == "bunt_pop_out":
            return scored, 1, 0

        if event_type == "line_drive_double_play":
            # エンドランのライナー・フライ：一塁走者も戻れずアウト。ほかの走者は戻る
            if first is None:
                raise ValueError("line drive double play requires a runner on first")
            bases[0] = None
            return scored, 2, 0

        if event_type == "sacrifice_fly":
            outs = 1
            if third is not None:
                scored.append(third)
                bases[2] = None
                rbi = 1
            if (second is not None and outs_before + outs < 3
                    and self._advance_out("fly_second_to_third", offense_players[second],
                                          defense_strength, rng)):
                bases[1], bases[2] = None, second
            return scored, outs, rbi

        if event_type == "fly_out":
            # 二塁走者のタッチアップ（三塁の走者の生還は犠飛）
            if (outs_before + 1 < 3 and second is not None and third is None
                    and self._advance_out("fly_second_to_third", offense_players[second],
                                          defense_strength, rng)):
                bases[1], bases[2] = None, second
            return scored, 1, 0

        if event_type == "ground_out":
            # 打者はアウト。押し出される走者は進み、三塁・二塁の走者は進塁打で進む
            if outs_before + 1 >= 3:
                return scored, 1, 0
            new = [None, None, None]
            if third is not None:
                if (first is not None and second is not None) or self._advance_out(
                        "ground_third_scores", offense_players[third], defense_strength, rng):
                    scored.append(third)
                else:
                    new[2] = third
            if second is not None:
                if first is not None or (new[2] is None and self._advance_out(
                        "ground_second_to_third", offense_players[second], defense_strength, rng)):
                    new[2] = second
                else:
                    new[1] = second
            if first is not None:
                new[1] = first
            bases[:] = new
            # 内野ゴロの間の得点は打点
            return scored, 1, len(scored)

        if event_type == "double_play":
            # 一塁の走者と打者がアウト。0死からなら他の走者は進み、三塁の走者は生還（打点なし）
            if first is None:
                raise ValueError("double play requires a runner on first")
            if outs_before + 2 >= 3:
                bases[:] = [None, second, third]
                return scored, 2, 0
            new = [None, None, None]
            if third is not None:
                scored.append(third)
            if second is not None:
                new[2] = second
            bases[:] = new
            return scored, 2, 0

        if event_type in {"strikeout", "field_out"}:
            return scored, 1, 0

        raise ValueError(f"unsupported event_type: {event_type}")

    @staticmethod
    def _finish_walkoff(event_type, batter_id, bases_before, bases, scored, rbi, runs_needed):
        """本塁打以外は勝ち越し点で終了。安打の塁打は規則9.06(f)で確定する。"""
        if event_type not in ('single', 'double', 'triple', 'reached_on_error'):
            return event_type, scored, rbi
        # 三塁側からホームへ着く順で勝ち越し走者を決める。
        counted = [pid for pid in reversed(bases_before) if pid in scored][:runs_needed]
        credited = 1
        if event_type != 'reached_on_error':
            hit_bases = ('single', 'double', 'triple').index(event_type) + 1
            winning_runner = counted[-1]
            advanced = 3 - bases_before.index(winning_runner)
            credited = min(hit_bases, advanced)
            recorded_type = ('single', 'double', 'triple')[credited-1]
        else:
            recorded_type = event_type
        if recorded_type == event_type and len(counted) == len(scored):
            return event_type, scored, rbi
        # 勝ち越し後の走者を得点させず、前後の走者順と占有塁を維持する。
        destinations = {pid: index+1 for index, pid in enumerate(bases) if pid}
        terminal = [None, None, None]
        highest = 3
        for runner in reversed(bases_before):
            if runner is not None and runner not in counted:
                target = min(highest, destinations.get(runner, 3))
                terminal[target-1] = runner
                highest = target-1
        terminal[credited-1] = batter_id
        bases[:] = terminal
        return recorded_type, counted, min(rbi, len(counted))

    def _pitcher_limit(
        self,
        pitcher: PlayerAbilitySnapshot,
        *,
        starter: bool,
    ) -> float:
        usage = self.params["pitching_usage"]
        stamina = float(pitcher.stamina or 50)
        if starter:
            return (
                float(usage["starter_bf_base"])
                + (stamina - 50.0)
                * float(usage["starter_stamina_effect"])
            )
        return (
            float(usage["reliever_bf_base"])
            + (stamina - 50.0)
            * float(usage["reliever_stamina_effect"])
        )

    def _should_change_pitcher(
        self,
        *,
        pitcher: PlayerAbilitySnapshot,
        stats: dict[str, int],
        starter: bool,
        has_next: bool,
        tactics: CoachTactics = CoachTactics(),
        fatigue: float = 0.0,
    ) -> bool:
        if not has_next:
            return False
        usage = self.params["pitching_usage"]
        minimum = int(usage["minimum_bf_before_change"])
        if stats["batters_faced"] < minimum:
            return False
        quick_hook = int(usage["runs_allowed_quick_hook"])
        # 0は従来どおり無失点でも交代する設定。中立時にも1へ切り上げない。
        if quick_hook:
            quick_hook = max(1, quick_hook - tactics.quick_hook_reduction)
        if stats["runs_allowed"] >= quick_hook:
            return True
        # 疲れ（球数・連投）が大きければ代える。監督の継投傾向の倍率を同じく掛ける
        change = self.params["fatigue"]["change"]
        if fatigue >= float(change["starter_points" if starter else "reliever_points"]) * tactics.bf_multiplier:
            return True
        return stats["batters_faced"] >= self._pitcher_limit(
            pitcher,
            starter=starter,
        ) * tactics.bf_multiplier

    @staticmethod
    def _empty_batter_stats(
        player_id: str,
        school_id: str,
    ) -> dict[str, int | str]:
        return {
            "player_id": player_id,
            "school_id": school_id,
            "plate_appearances": 0,
            "at_bats": 0,
            "runs": 0,
            "hits": 0,
            "doubles": 0,
            "triples": 0,
            "home_runs": 0,
            "rbi": 0,
            "walks": 0,
            "strikeouts": 0,
            "hit_by_pitch": 0,
            "sacrifice_flies": 0,
            "sacrifice_bunts": 0,
            "stolen_bases": 0,
            "caught_stealing": 0,
            "grounded_into_double_plays": 0,
            "picked_off": 0,
            "catcher_steal_attempts": 0,
            "catcher_caught_stealing": 0,
            "passed_balls": 0,
            "errors": 0,
            **{key: 0 for key in BATTER_SPLIT_FIELDS},
            "pinch_hit_at_bats": 0,
            "pinch_hit_hits": 0,
        }

    @staticmethod
    def _empty_pitcher_stats(
        player_id: str,
        school_id: str,
    ) -> dict[str, int | str]:
        return {
            "player_id": player_id,
            "school_id": school_id,
            "outs_recorded": 0,
            "batters_faced": 0,
            "runs_allowed": 0,
            "earned_runs": 0,
            "hits_allowed": 0,
            "home_runs_allowed": 0,
            "walks": 0,
            "strikeouts": 0,
            "hit_batters": 0,
            "pitches": 0,
            "exit_fatigue": 0,
            "wild_pitches": 0,
            "errors": 0,
            **{key: 0 for key in PITCHER_SPLIT_FIELDS},
        }

    def _record_batter_event(
        self,
        row: dict[str, int | str],
        event_type: str,
        rbi: int,
    ) -> None:
        rule = self.event_catalog[event_type]
        row["plate_appearances"] = int(row["plate_appearances"]) + 1
        if bool(rule["counts_as_at_bat"]):
            row["at_bats"] = int(row["at_bats"]) + 1
        if event_type in {"single", "double", "triple", "home_run"}:
            row["hits"] = int(row["hits"]) + 1
        if event_type == "double":
            row["doubles"] = int(row["doubles"]) + 1
        elif event_type == "triple":
            row["triples"] = int(row["triples"]) + 1
        elif event_type == "home_run":
            row["home_runs"] = int(row["home_runs"]) + 1
        elif event_type == "walk":
            row["walks"] = int(row["walks"]) + 1
        elif event_type == "strikeout":
            row["strikeouts"] = int(row["strikeouts"]) + 1
        elif event_type == "hit_by_pitch":
            row["hit_by_pitch"] = int(row["hit_by_pitch"]) + 1
        elif event_type == "sacrifice_fly":
            row["sacrifice_flies"] = int(row["sacrifice_flies"]) + 1
        elif event_type == "sacrifice_bunt":
            row["sacrifice_bunts"] = int(row["sacrifice_bunts"]) + 1
        elif event_type == "double_play":
            row["grounded_into_double_plays"] = int(row["grounded_into_double_plays"]) + 1
        row["rbi"] = int(row["rbi"]) + rbi

    def _record_split(self, batter_row, pitcher_row, event_type: str, throws: str | None,
                      side: str) -> None:
        """左右別の数（打者は相手投手の腕、投手は打者の打席の側ごと）。"""
        batter_prefix = "vs_lhp_" if throws == "L" else "vs_rhp_"
        pitcher_prefix = "vs_lhb_" if side == "L" else "vs_rhb_"
        keys = []
        if bool(self.event_catalog[event_type]["counts_as_at_bat"]):
            keys.append("at_bats")
        if event_type in {"single", "double", "triple", "home_run"}:
            keys.append("hits")
        if event_type == "home_run":
            keys.append("home_runs")
        if event_type in {"walk", "hit_by_pitch"}:
            keys.append("walks")
        if event_type == "strikeout":
            keys.append("strikeouts")
        for key in keys:
            batter_row[batter_prefix + key] = int(batter_row[batter_prefix + key]) + 1
            pitcher_row[pitcher_prefix + key] = int(pitcher_row[pitcher_prefix + key]) + 1

    @staticmethod
    def _bases_text(bases: list[str | None]) -> str:
        return "|".join(value or "" for value in bases)

    def simulate(
        self,
        match_input: MatchSimulationInput,
        *,
        regulation_innings: int | None = None,
        rules: GameRules | None = None,
        pitch_allowances: Mapping[str, int] | None = None,
        tactics: Mapping[str, CoachTactics] | None = None,
        state_sink: dict[str, TeamMatchState] | None = None,
        validated_history_sink: dict | None = None,
        lineup_changes: tuple[LineupAdjustment, ...] = (),
        pitch_history: Mapping[str, Mapping[int, int]] | None = None,
    ) -> MatchSimulationResult:
        """``pitch_allowances``：選手 → この試合であと何球投げられるか（球数制限）。
        届いたら次の打者から投げない。None なら制限なし。
        state_sink指定時は、成功した試合の開始配置・最終状態・交代履歴を返す。
        lineup_changesは直接計算の明示交代。全国進行からは渡さない。
        validated_history_sinkは厳密検証した入力・結果そのものとA詳細を一時的に返す。
        この計算経路から永続保存は行わない。"""
        validate_match_simulation_input(match_input)
        # 交代の判断に使う能力の値は1試合の中だけ覚えておく（選手の写しのidで引くので試合ごとに捨てる）
        self._value_cache = {}
        rules = rules or GameRules()
        regulation = (
            int(regulation_innings)
            if regulation_innings is not None
            else int(self.params["innings"]["default_regulation_innings"])
        )
        if regulation < 1:
            raise ValueError("regulation_innings must be >= 1")
        hard_max = int(self.params["innings"]["hard_max_innings"])
        if hard_max < regulation:
            raise ValueError(
                "hard_max_innings must be >= regulation_innings"
            )

        teams = {
            match_input.team1.school_id: match_input.team1,
            match_input.team2.school_id: match_input.team2,
        }
        # 同じ試合の同じ投打能力・守備値なら重みは変わらない。試合をまたがず、
        # 独自の確率/抽選実装では再利用しない（試験用の打席列も従来どおり）。
        weight_model = self._event_weights
        reuse_weights = (type(self) is MatchSimulator
                         and getattr(weight_model, '__func__', None) is _EVENT_WEIGHT_MODEL
                         and self._weighted_choice is _WEIGHTED_CHOICE_MODEL)
        weight_cache = {}
        # 守っている並びごとの守備の値（H2）。打席の結果の重みはチーム全体の守備力だけで決まり、
        # 選手ごとの守備は打球の行き先を決めてから効くので、交代で並びが変わってもそのまま正しい
        fielding_profiles: dict[tuple, _FieldingProfile] = {}
        defer_event_random = (type(self) is MatchSimulator and rng_for is _RNG_FACTORY
            and getattr(self._apply_event, '__func__', None) is _APPLY_EVENT_MODEL)
        policies = {sid: (tactics or {}).get(sid, CoachTactics()) for sid in teams}
        team1_id = match_input.team1.school_id
        team2_id = match_input.team2.school_id
        player_maps = {
            school_id: self._players(team)
            for school_id, team in teams.items()
        }
        carry = {
            school_id: self.carry_fatigue(team, pitch_history)
            for school_id, team in teams.items()
        }
        fatigue_rule = self.params["fatigue"]
        tired_cache: dict[tuple[str, int, bool], PlayerAbilitySnapshot] = {}

        # 守備に回した投手が守っている間に戻した疲れ（球数に直した分。段階F5）
        rest_credit: dict[str, dict[str, int]] = {sid: {} for sid in teams}

        def fatigue_points(school_id: str, pitcher_id: str, pitches: int) -> float:
            stamina = player_maps[school_id][pitcher_id].stamina
            pitches = max(0, pitches - rest_credit[school_id].get(pitcher_id, 0))
            return carry[school_id].get(pitcher_id, 0.0) + fatigue_model.in_game_fatigue(
                pitches, stamina, fatigue_rule)

        game_staffs = {
            school_id: self._game_staff(team, pitch_allowances, carry[school_id])
            for school_id, team in teams.items()
        }
        # 疲れで先発を外したエース（救援の順番の最後。終盤・接戦では救援に出すことがある）
        rested_aces = {
            school_id: self.rested_ace(team, carry[school_id])
            for school_id, team in teams.items()
        }
        pitcher_orders = {
            school_id: order for school_id, (order, _) in game_staffs.items()
        }
        staff_sizes = {
            school_id: size for school_id, (_, size) in game_staffs.items()
        }
        for school_id, order in pitcher_orders.items():
            if not order:
                raise ValueError(f"{school_id}: no available pitcher within pitch limits")
        opponents = {team1_id: team2_id, team2_id: team1_id}
        states = {
            school_id: self._initial_state(
                team, pitcher_orders[school_id][0],
                # 相手の先発投手の腕を見て先発メンバーを少し変える（段階F2）
                opponent_pitcher=player_maps[opponents[school_id]][pitcher_orders[opponents[school_id]][0]],
                staff=pitcher_orders[school_id][:staff_sizes[school_id]], tactics=policies[school_id])
            for school_id, team in teams.items()
        }
        defense_values = {
            school_id: (team.team_strength.defense_strength
                        if states[school_id].initial_lineup == team.team_strength.starting_lineup
                        else self._current_defense(states[school_id], player_maps[school_id]))
            for school_id, team in teams.items()
        }
        lineup_index = {team1_id: 0, team2_id: 0}
        pitcher_index = {team1_id: 0, team2_id: 0}

        batter_rows = {
            school_id: {
                player_id: self._empty_batter_stats(
                    player_id,
                    school_id,
                )
                for player_id in (slot.player_id for slot in states[school_id].batting_order)
            }
            for school_id in (team1_id, team2_id)
        }
        pitcher_rows: dict[str, dict[str, dict[str, int | str]]] = {
            team1_id: {},
            team2_id: {},
        }
        for school_id in (team1_id, team2_id):
            first_pitcher = states[school_id].current_pitcher_id
            pitcher_rows[school_id][first_pitcher] = (
                self._empty_pitcher_stats(first_pitcher, school_id)
            )

        team_runs = {team1_id: 0, team2_id: 0}
        team_hits = {team1_id: 0, team2_id: 0}
        team_errors = {team1_id: 0, team2_id: 0}
        # Preserve the existing quick-hook decisions: runs scored during an
        # outing are a usage signal, distinct from official pitcher liability.
        outing_runs: Counter[str] = Counter()

        events: list[MatchEvent] = []
        inning_scores: list[InningScore] = []
        # 代打で入り、まだ打席に立っていない選手（段階F2）
        pinch_hitters = {team1_id: set(), team2_id: set()}
        # 代打・代走で入った選手（守りでは守備固め・投手の交代の対象）と、交代の数
        entered_off_bench = {team1_id: set(), team2_id: set()}
        substitution_counts = {team1_id: Counter(), team2_id: Counter()}
        defense_checked: set[tuple[int, str]] = set()
        pa_no = 0
        event_no = 0
        last_inning = 1
        ending_half = "bottom"
        game_over = False
        dh_game = any(s.designated_hitter_id is not None for s in states.values())
        adjustments = {}
        for adjustment in lineup_changes:
            if not isinstance(adjustment, LineupAdjustment) or adjustment.school_id not in states:
                raise ValueError('invalid lineup adjustment team or request')
            adjustments.setdefault(adjustment.next_plate_appearance_no, []).append(adjustment)
        boundary_order = 0

        def before_moment():
            nonlocal boundary_order
            if dh_game:
                boundary_order += 1
            return ChangeMoment(inning, half, pa_no+1, boundary_order)

        # 守備から投手に戻った回数（(学校, 選手, 回) → 回数。公認野球規則：同じイニングに1度まで）
        pitcher_returns: Counter[tuple[str, str, int]] = Counter()

        def check_new_pitcher(school_id, incoming):
            """登板できるか。一度投げた投手は、守備に残っていて（退いていない）、その回にまだ投手に
            戻っていなければ戻れる。戻るときはその回の回数を数える。"""
            if incoming in pitcher_rows[school_id] and int(pitcher_rows[school_id][incoming]['batters_faced']) > 0:
                state = states[school_id]
                fielding = {a.player_id for a in state.defensive_alignment if a.defensive_position != 'P'}
                if incoming in state.exited_player_ids or incoming not in fielding:
                    raise ValueError(f'{school_id}: a pitcher who left the game cannot pitch again: {incoming}')
                if pitcher_returns[(school_id, incoming, inning)] >= 1:
                    raise ValueError(f'{school_id}: a pitcher may return to the mound once per inning: {incoming}')
                pitcher_returns[(school_id, incoming, inning)] += 1
            if pitch_allowances is not None and pitch_allowances.get(incoming, math.inf) <= 0:
                raise ValueError(f'{school_id}: incoming pitcher has no pitch allowance')

        def refresh_after_change(school_id, old_pitcher, *, defense_changed=True):
            state = states[school_id]
            pitcher_id = state.current_pitcher_id
            for slot in state.batting_order:
                if slot.player_id not in batter_rows[school_id]:
                    batter_rows[school_id][slot.player_id] = self._empty_batter_stats(slot.player_id, school_id)
            if defense_changed:
                defense_values[school_id] = self._current_defense(state, player_maps[school_id])
            if pitcher_id != old_pitcher:
                order = pitcher_orders[school_id]
                pitcher_index[school_id] = order.index(pitcher_id) if pitcher_id in order else len(order)
                pitcher_rows[school_id].setdefault(pitcher_id, self._empty_pitcher_stats(pitcher_id, school_id))
                opponent_id = team2_id if school_id == team1_id else team1_id
                if (old_pitcher == state.initial_lineup.player_for_position('P')
                        and states[opponent_id].dh_batting_required):
                    states[opponent_id].record_opposing_starter_replaced(moment=before_moment())

        def available_relievers(school_id):
            """まだ投げていない、交代で出せる投手（投手陣の順。疲れで休ませるエースは除く）。"""
            state = states[school_id]
            out = []
            for pid in pitcher_orders[school_id][:staff_sizes[school_id]]:
                if (pid == state.current_pitcher_id or pid in state.exited_player_ids
                        or pid == rested_aces[school_id]
                        or (pid in pitcher_rows[school_id]
                            and int(pitcher_rows[school_id][pid]['batters_faced']) > 0)
                        or (pid == state.initial_lineup.designated_hitter_id
                            and 'pitcher' in state.retired_two_way_roles)
                        or (pitch_allowances is not None and pitch_allowances.get(pid, math.inf) <= 0)):
                    continue
                out.append(pid)
            return out

        shuffle_rule = self.params["pitcher_shuffle"]
        shuffle_namespace = self.params["rng_namespace_policy"]["pitcher_shuffle"]
        in_field: dict[str, str | None] = {sid: None for sid in teams}  # 守備に残した投手
        field_since: dict[str, int] = {}       # 守備に残した投手 → そのときのチームの守備のアウト数
        shuffle_counts: Counter[str] = Counter()
        return_start: dict[tuple[str, str], int] = {}  # 投手に戻った投手 → 戻ったときの対戦打者数

        def defense_outs(school_id):
            return sum(int(row["outs_recorded"]) for row in pitcher_rows[school_id].values())

        def pitches_left(pitcher_id, pitches):
            return math.inf if pitch_allowances is None else pitch_allowances.get(pitcher_id, math.inf) - pitches

        def shuffle_fielder(school_id, outgoing, incoming, margin):
            """降りる投手を守備に残すなら、代わりに退く野手（残さないなら None）。段階F5。"""
            state = states[school_id]
            rate = policies[school_id].shuffle_rate
            stat = pitcher_rows[school_id].get(outgoing)
            if (rate <= 0 or stat is None
                    # 投げながらDHも兼ねる投手（投・DH）は守備に残さない
                    or outgoing == state.designated_hitter_id
                    or outgoing == state.initial_lineup.designated_hitter_id
                    or shuffle_counts[school_id] >= int(shuffle_rule["max_per_game"])
                    or inning > int(shuffle_rule["latest_inning"])
                    or abs(margin) > int(shuffle_rule["max_margin"])
                    or incoming in state.active_player_ids
                    or outgoing not in self._quality_order(teams[school_id])[:int(shuffle_rule["candidate_quality_ranks"])]
                    or pitches_left(outgoing, int(stat["pitches"])) < int(shuffle_rule["min_remaining_pitches"])
                    or fatigue_model.stage_of(fatigue_points(school_id, outgoing, int(stat["pitches"])), fatigue_rule)
                    > int(shuffle_rule["max_exit_fatigue_stage"])):
                return None
            pitcher = player_maps[school_id][outgoing]
            options = [a for a in state.defensive_alignment
                       if a.defensive_position in shuffle_rule["positions"]
                       and self._defense_value(pitcher, a.defensive_position)
                       >= float(shuffle_rule["min_defense_value"])]
            if not options:
                return None
            rng = rng_for(match_input.generation_seed, shuffle_namespace.format(
                match_id=match_input.match_id, plate_appearance_no=pa_no + 1))
            if rng.random() >= rate:
                return None
            # 一塁・外野のうち、その投手が最も守れる位置に入る（そこを守っていた野手が退く）
            return max(options, key=lambda a: (self._defense_value(pitcher, a.defensive_position),
                                               a.defensive_position)).player_id

        def try_return(school_id, offense_id, bases):
            """守備に残した投手を、投手に戻すか（戻したら True）。段階F5。"""
            nonlocal fielding_pending
            pid = in_field[school_id]
            if pid is None:
                return False
            state = states[school_id]
            fielding = {a.player_id: a.defensive_position for a in state.defensive_alignment
                        if a.defensive_position != 'P'}
            if pid not in fielding:
                in_field[school_id] = None
                return False
            back = shuffle_rule["return"]
            stat = pitcher_rows[school_id][pid]
            rest = (defense_outs(school_id) - field_since[pid]) * float(shuffle_rule["rest_pitches_per_out"])
            rest_credit[school_id][pid] = min(int(shuffle_rule["max_rest_pitches"]), int(rest))
            if (pitcher_returns[(school_id, pid, inning)] >= 1
                    or pitches_left(pid, int(stat["pitches"])) < int(back["min_remaining_pitches"])
                    or fatigue_model.stage_of(fatigue_points(school_id, pid, int(stat["pitches"])), fatigue_rule)
                    > int(back["max_fatigue_stage"])):
                return False
            margin = team_runs[school_id] - team_runs[offense_id]
            points = ((inning >= int(back["late_inning_from"])) + (abs(margin) <= int(back["close_margin"]))
                      + (bases[1] is not None or bases[2] is not None)
                      + (lineup_index[offense_id] % 9 + 1 in back["cleanup_slots"]))
            misread = policies[school_id].return_misread
            if misread:
                roll = rng_for(match_input.generation_seed, shuffle_namespace.format(
                    match_id=match_input.match_id, plate_appearance_no=pa_no + 1) + ":return").random()
                points += -1 if roll < misread / 2 else 1 if roll < misread else 0
            if points < int(back["min_points"]):
                return False
            check_new_pitcher(school_id, pid)
            old_pitcher = state.current_pitcher_id
            position = fielding[pid]
            state.change_pitcher(pid, moment=before_moment())
            state.label_last_change("pitcher_return")
            in_field[school_id] = None
            return_start[(school_id, pid)] = int(stat["batters_faced"])
            outing_runs[pid] = 0
            refresh_after_change(school_id, old_pitcher)
            # 投げていた投手がその位置を守れなければ、控えの野手と交代する（打順はそのまま）
            mover = player_maps[school_id][old_pitcher]
            if self._defense_value(mover, position) < float(shuffle_rule["min_defense_value"]):
                bench = [p for p in self._bench(state, player_maps[school_id],
                                                pitcher_orders[school_id][:staff_sizes[school_id]])
                         if p.primary_position != "P"]
                if bench:
                    best = max(bench, key=lambda p: (self._defense_value(p, position), p.player_id))
                    bench_substitute(school_id, old_pitcher, best.player_id, "defensive_replacement")
            fielding_pending = True
            return True

        def bench_substitute(school_id, outgoing, incoming, reason):
            """采配の交代（代打・代走・守備固め）。規則に合わなければ何もしない（False）。"""
            state = states[school_id]
            try:
                state.substitute(outgoing, incoming, moment=before_moment())
            except ValueError:
                return False
            state.label_last_change(reason)
            # 代打・代走で投手の位置に入っても、その守りの初めに投手を代える（投手の成績は作らない）
            refresh_after_change(school_id, state.current_pitcher_id)
            substitution_counts[school_id][reason] += 1
            entered_off_bench[school_id].discard(outgoing)
            if reason != "defensive_replacement":
                entered_off_bench[school_id].add(incoming)
            return True

        def upcoming_batters(school_id, count):
            state = states[school_id]
            return [player_maps[school_id][state.player_at_order((lineup_index[school_id] + k) % 9 + 1)]
                    for k in range(count)]

        for inning in range(1, hard_max + 1):
            last_inning = inning
            for half in ("top", "bottom"):
                offense_id = team1_id if half == "top" else team2_id
                defense_id = team2_id if half == "top" else team1_id

                if (
                    half == "bottom"
                    and inning >= regulation
                    and team_runs[team2_id] > team_runs[team1_id]
                ):
                    inning_scores.append(InningScore(
                        inning=inning, half=half,
                        batting_team_id=offense_id,
                        was_played=False, runs=None,
                    ))
                    ending_half = "top"
                    game_over = True
                    break

                runs_before_half = team_runs[offense_id]
                pa_before_half = pa_no
                outs = 0
                fielding_pending = True
                bases: list[str | None] = [None, None, None]
                runner_responsibility = _RunnerResponsibilityTracker()
                earned_run_tracker = _EarnedRunTracker()
                tiebreak_pending = False
                # タイブレーク：打順は続け、先頭打者の1人前が一塁、2人前が二塁。
                # 置いた走者の得点は自責点にしない
                if (
                    rules.tiebreak_start_inning is not None
                    and inning >= rules.tiebreak_start_inning
                ):
                    tiebreak_pending = True

                while outs < 3:
                    boundary_order = 0
                    for adjustment in adjustments.pop(pa_no+1, ()):
                        changed_state = states[adjustment.school_id]
                        old_pitcher = changed_state.current_pitcher_id
                        runner_changes = [(changed_state.player_at_order(slot), incoming)
                                          for slot, incoming in adjustment.batting_changes
                                          if adjustment.school_id == offense_id
                                          and changed_state.player_at_order(slot) in bases]
                        incoming = dict(adjustment.defensive_changes).get('P', old_pitcher)
                        if incoming != old_pitcher:
                            check_new_pitcher(adjustment.school_id, incoming)
                        applied = changed_state.transition(
                            batting_changes=dict(adjustment.batting_changes),
                            defensive_changes=dict(adjustment.defensive_changes),
                            medical_exception=adjustment.medical_exception,
                            umpire_approved=adjustment.umpire_approved,
                            moment=before_moment())
                        if applied is None:
                            raise ValueError('lineup adjustment must change the state')
                        refresh_after_change(adjustment.school_id, old_pitcher,
                                             defense_changed=bool(applied.defensive_changes))
                        for outgoing, incoming in runner_changes:
                            runner_responsibility.substitute_runner(outgoing, incoming)
                            earned_run_tracker.substitute_runner(outgoing, incoming)
                            bases[bases.index(outgoing)] = incoming
                        if adjustment.school_id == defense_id:
                            fielding_pending = True
                    staff = pitcher_orders[defense_id]
                    if (inning, half) not in defense_checked:
                        # 守りの初めの守備固め（段階F2）
                        defense_checked.add((inning, half))
                        for outgoing, incoming in self._choose_defensive_replacements(
                                state=states[defense_id], players=player_maps[defense_id],
                                bench=self._bench(states[defense_id], player_maps[defense_id],
                                                  staff[:staff_sizes[defense_id]]),
                                inning=inning, lead=team_runs[defense_id] - team_runs[offense_id],
                                entered=entered_off_bench[defense_id], tactics=policies[defense_id]):
                            if bench_substitute(defense_id, outgoing, incoming, "defensive_replacement"):
                                fielding_pending = True
                    # 守備に残した投手を戻す（段階F5）
                    try_return(defense_id, offense_id, bases)
                    current_index = pitcher_index[defense_id]
                    state = states[defense_id]
                    pitcher_id = state.current_pitcher_id
                    # 代打・代走で投手の位置に入った選手は投げない（救援がいれば必ず代える）
                    bench_pitcher = (pitcher_id in entered_off_bench[defense_id]
                                     and bool(available_relievers(defense_id)))
                    if pitcher_id not in pitcher_rows[defense_id] and not bench_pitcher:
                        pitcher_rows[defense_id][pitcher_id] = (
                            self._empty_pitcher_stats(
                                pitcher_id,
                                defense_id,
                            )
                        )
                    pitcher = self._as_pitcher(player_maps[defense_id][pitcher_id])
                    pitcher_stat = (pitcher_rows[defense_id][pitcher_id] if not bench_pitcher
                                    else self._empty_pitcher_stats(pitcher_id, defense_id))

                    limit_reached = (
                        pitch_allowances is not None
                        and int(pitcher_stat["pitches"])
                        >= pitch_allowances.get(pitcher_id, math.inf)
                    )
                    # 明示交代で投手陣の途中を選んでも、未登板の候補を失わない。
                    next_index = 0
                    while next_index < len(staff) and (
                            staff[next_index] == pitcher_id
                            or staff[next_index] in state.exited_player_ids
                            or (staff[next_index] in pitcher_rows[defense_id]
                                and int(pitcher_rows[defense_id][staff[next_index]]['batters_faced']) > 0)
                            or (staff[next_index] == state.initial_lineup.designated_hitter_id
                                and 'pitcher' in state.retired_two_way_roles)):
                        next_index += 1
                    if limit_reached and next_index >= len(staff):
                        raise ValueError(f"{defense_id}: no available relief pitcher within pitch limits")
                    # 継投の左右（段階F2）：次の打者が同じ側に続くなら、その側に強い腕の救援
                    platoon_rule = self._substitutions()["platoon_relief"]
                    platoon_pick = None
                    if next_index < staff_sizes[defense_id]:
                        platoon_pick = self._platoon_reliever(
                            candidates=available_relievers(defense_id)[:3], players=player_maps[defense_id],
                            upcoming=upcoming_batters(offense_id, int(platoon_rule["lookahead"])),
                            inning=inning, margin=team_runs[defense_id] - team_runs[offense_id],
                            tactics=policies[defense_id])
                    platoon_trigger = (
                        platoon_pick is not None and not bench_pitcher
                        and player_maps[defense_id][platoon_pick].throws != pitcher.throws
                        and int(pitcher_stat["batters_faced"]) >= int(platoon_rule["min_batters_faced"]))
                    if bench_pitcher or platoon_trigger or limit_reached or self._should_change_pitcher(
                        pitcher=pitcher,
                        stats={**pitcher_stat, "runs_allowed": outing_runs[pitcher_id],
                               # 守備から戻った投手は、戻ってからの対戦打者数で見る（段階F5）
                               "batters_faced": int(pitcher_stat["batters_faced"])
                               - return_start.get((defense_id, pitcher_id), 0)},
                        starter=(pitcher_id == state.initial_lineup.player_for_position('P')
                                 and (defense_id, pitcher_id) not in return_start),
                        has_next=next_index < staff_sizes[defense_id],
                        tactics=policies[defense_id],
                        fatigue=fatigue_points(defense_id, pitcher_id, int(pitcher_stat["pitches"])),
                    ):
                        ace = rested_aces[defense_id]
                        if (ace is not None and ace != pitcher_id and ace in staff
                                and staff.index(ace) > next_index
                                and staff.index(ace) < staff_sizes[defense_id]
                                and ace not in state.exited_player_ids
                                and not (ace in pitcher_rows[defense_id]
                                         and int(pitcher_rows[defense_id][ace]["batters_faced"]) > 0)
                                and (pitch_allowances is None or pitch_allowances.get(ace, math.inf)
                                     >= int(self.params["pitching_usage"]["reliever_minimum_pitches"]))):
                            candidate_id = staff[next_index] if next_index < staff_sizes[defense_id] else None
                            if self._call_rested_ace(
                                ace=player_maps[defense_id][ace],
                                ace_carry=carry[defense_id].get(ace, 0.0),
                                candidate=(player_maps[defense_id][candidate_id]
                                           if candidate_id is not None else None),
                                candidate_stage=fatigue_model.stage_of(
                                    carry[defense_id].get(candidate_id, 0.0), fatigue_rule),
                                ace_stage=fatigue_model.stage_of(
                                    carry[defense_id].get(ace, 0.0), fatigue_rule),
                                inning=inning,
                                lead=team_runs[defense_id] - team_runs[offense_id],
                                tactics=policies[defense_id],
                                rng=rng_for(
                                    match_input.generation_seed,
                                    self.params["rng_namespace_policy"]["relief"].format(
                                        match_id=match_input.match_id, plate_appearance_no=pa_no + 1,
                                    ),
                                ),
                            ):
                                next_index = staff.index(ace)
                                platoon_pick = None
                        if platoon_pick is not None:
                            next_index = staff.index(platoon_pick)
                        current_index = next_index
                        pitcher_index[defense_id] = current_index
                        incoming = staff[current_index]
                        check_new_pitcher(defense_id, incoming)
                        old_pitcher = state.current_pitcher_id
                        # 降りる投手を守備に残すか（段階F5。球数の上限・代打で入った投手の交代では残さない）
                        fielder = None if (limit_reached or bench_pitcher) else shuffle_fielder(
                            defense_id, old_pitcher, incoming, team_runs[defense_id] - team_runs[offense_id])
                        state.relieve_pitcher(incoming, keep_in_field=fielder, moment=before_moment())
                        if fielder is not None:
                            state.label_last_change("pitcher_to_field")
                            in_field[defense_id] = old_pitcher
                            field_since[old_pitcher] = defense_outs(defense_id)
                            shuffle_counts[defense_id] += 1
                        refresh_after_change(defense_id, old_pitcher)
                        fielding_pending = True
                        state.validate(actual_pitcher_id=incoming)
                        pitcher_id = state.current_pitcher_id
                        if pitcher_id not in pitcher_rows[defense_id]:
                            pitcher_rows[defense_id][pitcher_id] = (
                                self._empty_pitcher_stats(
                                    pitcher_id,
                                    defense_id,
                                )
                            )
                        pitcher = self._as_pitcher(
                            player_maps[defense_id][pitcher_id]
                        )
                        pitcher_stat = pitcher_rows[defense_id][pitcher_id]

                    if fielding_pending:
                        state.record_fielding_appearance()
                        fielding_pending = False
                    # 攻める側の代走・代打（段階F2）
                    offense_state = states[offense_id]
                    # 投手陣（並びの後ろの、投手がいなくなったときに投げる野手は含めない）
                    offense_staff = pitcher_orders[offense_id][:staff_sizes[offense_id]]
                    margin_now = team_runs[offense_id] - team_runs[defense_id]
                    rule_pr = self._substitutions()["pinch_runner"]
                    if (not tiebreak_pending and any(bases)
                            and substitution_counts[offense_id]["pinch_runner"] < int(rule_pr["max_per_game"])):
                        runner_change = self._choose_pinch_runner(
                            bases=bases, players=player_maps[offense_id],
                            bench=self._bench(offense_state, player_maps[offense_id], offense_staff),
                            inning=inning, margin=margin_now,
                            protected={offense_state.current_pitcher_id, *offense_staff},
                            tactics=policies[offense_id])
                        if runner_change is not None:
                            outgoing, incoming = runner_change
                            if bench_substitute(offense_id, outgoing, incoming, "pinch_runner"):
                                runner_responsibility.substitute_runner(outgoing, incoming)
                                earned_run_tracker.substitute_runner(outgoing, incoming)
                                bases[bases.index(outgoing)] = incoming
                    rule_ph = self._substitutions()["pinch_hitter"]
                    if substitution_counts[offense_id]["pinch_hitter"] < int(rule_ph["max_per_game"]):
                        scheduled = offense_state.player_at_order(lineup_index[offense_id] % 9 + 1)
                        pitcher_slot = (offense_state.designated_hitter_id is None
                                        and scheduled == offense_state.current_pitcher_id)
                        if (scheduled not in bases
                                and (not pitcher_slot or available_relievers(offense_id))):
                            hitter = self._choose_pinch_hitter(
                                batter=player_maps[offense_id][scheduled], pitcher=pitcher,
                                bench=self._bench(offense_state, player_maps[offense_id], offense_staff),
                                inning=inning, margin=margin_now, pitcher_slot=pitcher_slot,
                                tactics=policies[offense_id])
                            if hitter is not None and bench_substitute(offense_id, scheduled, hitter, "pinch_hitter"):
                                pinch_hitters[offense_id].add(hitter)
                    if tiebreak_pending:
                        # 打席前の明示交代も反映した打順から配置する。
                        lead = lineup_index[offense_id]
                        bases[0] = states[offense_id].player_at_order((lead - 1) % 9 + 1)
                        bases[1] = states[offense_id].player_at_order((lead - 2) % 9 + 1)
                    batter_id = states[offense_id].player_at_order(lineup_index[offense_id] % 9 + 1)
                    lineup_index[offense_id] += 1
                    batter = player_maps[offense_id][batter_id]
                    if tiebreak_pending:
                        # Wait until pitch limits/substitutions select the actual pitcher.
                        runner_responsibility.seed_tiebreak(bases, pitcher_id)
                        tiebreak_pending = False

                    pa_no += 1
                    event_no += 1
                    namespace = self.params["rng_namespace_policy"][
                        "plate_appearance"
                    ].format(
                        match_id=match_input.match_id,
                        plate_appearance_no=pa_no,
                    )
                    pa_rng = rng_for(
                        match_input.generation_seed,
                        namespace,
                    )
                    event_namespace = self.params["rng_namespace_policy"][
                        "event"
                    ].format(
                        match_id=match_input.match_id,
                        event_no=event_no,
                    )
                    event_rng = (_DeferredEventRandom if defer_event_random else rng_for)(
                        match_input.generation_seed,
                        event_namespace,
                    )

                    bases_before = list(bases)
                    score_margin = (
                        team_runs[offense_id] - team_runs[defense_id]
                    )
                    # 作戦（段階F1）：攻める側の監督がスクイズ・送りバント・エンドランを決める
                    tactic_rng = rng_for(
                        match_input.generation_seed,
                        self.params["rng_namespace_policy"]["tactic"].format(
                            match_id=match_input.match_id, plate_appearance_no=pa_no,
                        ),
                    )
                    tactic = self._choose_tactic(
                        batter=batter, bases=bases, outs=outs, margin=score_margin,
                        inning=inning, offense_players=player_maps[offense_id],
                        tactics=policies[offense_id], rng=tactic_rng,
                    )
                    tactic_outcome = None
                    weight_mode = "hit_and_run" if tactic == "hit_and_run" else None
                    if tactic in ("squeeze", "bunt"):
                        tactic_outcome = self._bunt_outcome(
                            tactic, batter=batter, bases=bases,
                            offense_players=player_maps[offense_id],
                            defense_strength=defense_values[defense_id], rng=tactic_rng,
                        )
                        if tactic_outcome == "foul":
                            # ファウルで追い込まれ、打席が続く（打って出る）
                            weight_mode = "two_strike"
                    bunt_play = tactic_outcome not in (None, "foul")
                    fielded = None
                    # 疲れの段階と度胸（ピンチ・終盤の接戦で能力が落ちるか）ごとに能力が決まるので、
                    # どちらも使い回しのキーに入れる
                    stage = fatigue_model.stage_of(
                        fatigue_points(defense_id, pitcher_id, int(pitcher_stat["pitches"])),
                        fatigue_rule)
                    pressed = (self._under_pressure(bases, inning, score_margin)
                               and self._pressure_points(pitcher) > 0)
                    tired_pitcher = tired_cache.get((pitcher_id, stage, pressed))
                    if tired_pitcher is None:
                        tired_pitcher = fatigue_model.tired(pitcher, stage, fatigue_rule)
                        if pressed:
                            tired_pitcher = self._pressured(tired_pitcher)
                        tired_cache[(pitcher_id, stage, pressed)] = tired_pitcher
                    if bunt_play:
                        event_type = "bunt"
                    else:
                        weight_key = (batter_id, pitcher_id, defense_values[defense_id], stage, pressed)
                        weights = weight_cache.get(weight_key) if reuse_weights else None
                        if weights is None:
                            weights = weight_model(batter, tired_pitcher, defense_values[defense_id])
                            if reuse_weights:
                                weight_cache[weight_key] = weights
                        if weight_mode is not None:
                            # 作戦の打席の重みも、元の重みと作戦の種類ごとに使い回す
                            mode_key = (weight_key, weight_mode)
                            moded = weight_cache.get(mode_key) if reuse_weights else None
                            if moded is None:
                                moded = self._tactic_weights(weights, weight_mode)
                                if reuse_weights:
                                    weight_cache[mode_key] = moded
                            weights = moded
                        event_type = self._weighted_choice(pa_rng, weights)
                        # 打球の行き先と守った選手（H2）。守っている並びが変われば値も変わる
                        alignment = tuple((a.defensive_position, a.player_id)
                                          for a in states[defense_id].defensive_alignment)
                        profile = fielding_profiles.get(alignment)
                        if profile is None:
                            profile = self._fielding_profile(alignment, player_maps[defense_id])
                            fielding_profiles[alignment] = profile
                        event_type, fielded = self._field_ball(
                            event_type, weights=weights, batter=batter, pitcher=pitcher, profile=profile,
                            rng=rng_for(
                                match_input.generation_seed,
                                self.params["rng_namespace_policy"]["fielding"].format(
                                    match_id=match_input.match_id, plate_appearance_no=pa_no,
                                ),
                            ),
                        )
                        event_type = self._classify_out(
                            event_type,
                            bases,
                            outs,
                            batter,
                            pa_rng,
                            pitcher,
                            defense_values[defense_id],
                            None if fielded is None else fielded.ball_type,
                            0.0 if fielded is None else (
                                fielded.arm_gap * float(self.params["fielding"]["double_play_per_arm_point"])),
                        )
                        if tactic == "hit_and_run":
                            rule = self._strategy()["hit_and_run"]
                            # 走者が先に走るので、ゴロの併殺は減り、フライ・ライナーでは戻れない
                            if (event_type == "double_play"
                                    and tactic_rng.random() >= float(rule["double_play_multiplier"])):
                                event_type = "ground_out"
                            elif (event_type == "fly_out" and bases[0] is not None
                                    and tactic_rng.random() < float(rule["fly_runner_doubled_off"])):
                                event_type = "line_drive_double_play"

                    if bunt_play:
                        event_type, scored, outs_on_play, rbi = self._apply_bunt(
                            tactic, tactic_outcome, batter_id, bases)
                    else:
                        scored, outs_on_play, rbi = self._apply_event(
                            event_type=event_type,
                            batter_id=batter_id,
                            bases=bases,
                            offense_players=player_maps[offense_id],
                            # 走者の進塁は、処理した選手の肩・送球（チームの基準との差）でも変わる
                            defense_strength=defense_values[defense_id] + (0.0 if fielded is None else (
                                fielded.arm_gap * float(self.params["fielding"]["advance_points_per_arm_point"]))),
                            rng=event_rng,
                            outs=outs,
                            **({"running_start": True} if tactic == "hit_and_run" else {}),
                        )
                    if tactic == "hit_and_run":
                        tactic_outcome = event_type
                    # 球数は抽選した打球結果のまま。サヨナラの記録確定で乱数を引き直さない。
                    pitch_event_type = event_type
                    if (half == 'bottom' and inning >= regulation
                            and team_runs[team2_id] + len(scored) > team_runs[team1_id]):
                        event_type, scored, rbi = self._finish_walkoff(
                            event_type, batter_id, bases_before, bases, scored, rbi,
                            team_runs[team1_id]-team_runs[team2_id]+1)
                    scored_runners = runner_responsibility.record_play(
                        bases_before=bases_before,
                        bases_after=bases,
                        scored_runner_ids=scored,
                        batter_id=batter_id,
                        pitcher_id=pitcher_id,
                        event_type=event_type,
                        plate_appearance_no=pa_no,
                    )
                    earned_run_tracker.record_play(
                        bases_before=bases_before, bases_after=bases,
                        scored_runners=scored_runners, batter_id=batter_id,
                        pitcher_id=pitcher_id, event_type=pitch_event_type,
                        plate_appearance_no=pa_no, outs_before=outs,
                        outs_on_play=outs_on_play,
                    )
                    outs += outs_on_play

                    batter_row = batter_rows[offense_id][batter_id]
                    self._record_batter_event(
                        batter_row,
                        event_type,
                        rbi,
                    )
                    # 左右別の成績と、代打で入った打席の成績（段階F2）
                    self._record_split(batter_row, pitcher_stat, event_type,
                                       pitcher.throws, self.batting_side(batter, pitcher))
                    if batter_id in pinch_hitters[offense_id]:
                        pinch_hitters[offense_id].discard(batter_id)
                        if bool(self.event_catalog[event_type]["counts_as_at_bat"]):
                            batter_row["pinch_hit_at_bats"] = int(batter_row["pinch_hit_at_bats"]) + 1
                        if event_type in {"single", "double", "triple", "home_run"}:
                            batter_row["pinch_hit_hits"] = int(batter_row["pinch_hit_hits"]) + 1
                    for runner_id in scored:
                        runner_row = batter_rows[offense_id].get(runner_id)
                        if runner_row is None:
                            raise ValueError(
                                f"scoring runner {runner_id} not in batting lineup"
                            )
                        runner_row["runs"] = int(runner_row["runs"]) + 1

                    hit = event_type in {
                        "single",
                        "double",
                        "triple",
                        "home_run",
                    }
                    team_runs[offense_id] += len(scored)
                    if hit:
                        team_hits[offense_id] += 1
                    if event_type == "reached_on_error":
                        team_errors[defense_id] += 1
                        # 失策は処理した選手に付ける（投手は投手の成績に）
                        if fielded is not None:
                            if fielded.position == "P":
                                pitcher_stat["errors"] = int(pitcher_stat["errors"]) + 1
                            else:
                                fielder_row = batter_rows[defense_id].get(fielded.player_id)
                                if fielder_row is None:
                                    raise ValueError(f"fielder {fielded.player_id} not in batting lineup")
                                fielder_row["errors"] = int(fielder_row["errors"]) + 1

                    pitcher_stat["batters_faced"] = (
                        int(pitcher_stat["batters_faced"]) + 1
                    )
                    pitches_on_play = self._pitches(
                        pitch_event_type,
                        rng_for(
                            match_input.generation_seed,
                            self.params["rng_namespace_policy"]["pitches"].format(
                                match_id=match_input.match_id,
                                plate_appearance_no=pa_no,
                            ),
                        ),
                        None if bunt_play else tired_pitcher, batter,
                    )
                    if tactic_outcome == "foul":
                        pitches_on_play += int(self._strategy()["two_strike"]["extra_pitches"])
                    pitcher_stat['pitches'] = int(pitcher_stat['pitches']) + pitches_on_play
                    # 降板時（またはこの試合の最後）の疲れの段階
                    pitcher_stat['exit_fatigue'] = fatigue_model.stage_of(
                        fatigue_points(defense_id, pitcher_id, int(pitcher_stat['pitches'])), fatigue_rule)
                    pitcher_stat["outs_recorded"] = (
                        int(pitcher_stat["outs_recorded"])
                        + outs_on_play
                    )
                    outing_runs[pitcher_id] += len(scored)
                    for runner in scored_runners:
                        responsible = pitcher_rows[defense_id][runner.responsible_pitcher_id]
                        responsible["runs_allowed"] = int(responsible["runs_allowed"]) + 1
                    if hit:
                        pitcher_stat["hits_allowed"] = (
                            int(pitcher_stat["hits_allowed"]) + 1
                        )
                    if event_type == "home_run":
                        pitcher_stat["home_runs_allowed"] = (
                            int(pitcher_stat["home_runs_allowed"]) + 1
                        )
                    elif event_type == "walk":
                        pitcher_stat["walks"] = (
                            int(pitcher_stat["walks"]) + 1
                        )
                    elif event_type == "strikeout":
                        pitcher_stat["strikeouts"] = (
                            int(pitcher_stat["strikeouts"]) + 1
                        )
                    elif event_type == "hit_by_pitch":
                        pitcher_stat["hit_batters"] = (
                            int(pitcher_stat["hit_batters"]) + 1
                        )

                    # 打席のあとの暴投・捕逸と盗塁（サヨナラ・3アウトのあとはない）
                    bases_after_play = list(bases)
                    steal = advance = None
                    if outs < 3 and not (half == "bottom" and inning >= regulation
                                         and team_runs[team2_id] > team_runs[team1_id]):
                        catcher_id = states[defense_id].player_for_position("C")
                        catcher = player_maps[defense_id][catcher_id]
                        # エンドランの空振り三振：走者はもう走っている
                        forced = tactic == "hit_and_run" and event_type == "strikeout"
                        if not forced:
                            advance = self._wild_pitch_or_passed_ball(
                                bases=bases, pitcher=tired_pitcher, catcher=catcher,
                                rng=rng_for(
                                    match_input.generation_seed,
                                    self.params["rng_namespace_policy"]["wild_pitch"].format(
                                        match_id=match_input.match_id, plate_appearance_no=pa_no,
                                    ),
                                ),
                            )
                        if advance is None:
                            steal = self._attempt_steal(
                                bases=bases, outs=outs,
                                margin=team_runs[offense_id] - team_runs[defense_id], inning=inning,
                                offense_players=player_maps[offense_id],
                                catcher=catcher, pitcher=pitcher,
                                mobility=policies[offense_id].mobility, forced=forced,
                                rng=rng_for(
                                    match_input.generation_seed,
                                    self.params["rng_namespace_policy"]["steal"].format(
                                        match_id=match_input.match_id, plate_appearance_no=pa_no,
                                    ),
                                ),
                            )
                    baserunning_scored: list[str] = []
                    baserunning_runners: list[_RunnerResponsibility] = []
                    if advance is not None:
                        # 走者が全員1つ進み、三塁走者は生還する
                        if bases[2] is not None:
                            baserunning_scored.append(bases[2])
                        bases[:] = [None, bases[0], bases[1]]
                        if advance == "wp":
                            pitcher_stat["wild_pitches"] = int(pitcher_stat["wild_pitches"]) + 1
                        else:
                            catcher_row = batter_rows[defense_id].get(catcher_id)
                            if catcher_row is not None:
                                catcher_row["passed_balls"] = int(catcher_row["passed_balls"]) + 1
                        baserunning_runners.extend(self._record_baserunning_play(
                            "wild_pitch" if advance == "wp" else "passed_ball",
                            bases_after_play, bases, baserunning_scored,
                            runner_responsibility, earned_run_tracker, pitcher_id, pa_no, outs))
                    for runner_id, from_index, steal_result in steal or ():
                        runner_row = batter_rows[offense_id][runner_id]
                        catcher_row = batter_rows[defense_id].get(catcher_id)
                        if steal_result in ("sb", "adv") and from_index == 2:
                            # 本盗の成功：得点
                            before_home = list(bases)
                            bases[2] = None
                            baserunning_scored.append(runner_id)
                            baserunning_runners.extend(self._record_baserunning_play(
                                "stolen_base", before_home, bases, [runner_id],
                                runner_responsibility, earned_run_tracker, pitcher_id, pa_no, outs))
                        elif steal_result in ("sb", "adv"):
                            bases[from_index] = None
                            bases[from_index + 1] = runner_id
                            earned_run_tracker.record_baserunning(runner_id, from_index, from_index + 1)
                        else:
                            bases[from_index] = None
                            outs += 1
                            outs_on_play += 1
                            pitcher_stat["outs_recorded"] = int(pitcher_stat["outs_recorded"]) + 1
                            runner_responsibility.retire_runner(runner_id)
                            earned_run_tracker.record_baserunning(runner_id, from_index, None)
                        if steal_result == "sb":
                            runner_row["stolen_bases"] = int(runner_row["stolen_bases"]) + 1
                        elif steal_result in ("cs", "po"):
                            key = "caught_stealing" if steal_result == "cs" else "picked_off"
                            runner_row[key] = int(runner_row[key]) + 1
                        if steal_result in ("sb", "cs") and catcher_row is not None:
                            catcher_row["catcher_steal_attempts"] = int(catcher_row["catcher_steal_attempts"]) + 1
                            if steal_result == "cs":
                                catcher_row["catcher_caught_stealing"] = int(catcher_row["catcher_caught_stealing"]) + 1
                    if baserunning_scored:
                        scored = [*scored, *baserunning_scored]
                        for runner_id in baserunning_scored:
                            runner_row = batter_rows[offense_id][runner_id]
                            runner_row["runs"] = int(runner_row["runs"]) + 1
                        team_runs[offense_id] += len(baserunning_scored)
                        outing_runs[pitcher_id] += len(baserunning_scored)
                        for runner in baserunning_runners:
                            responsible = pitcher_rows[defense_id][runner.responsible_pitcher_id]
                            responsible["runs_allowed"] = int(responsible["runs_allowed"]) + 1

                    events.append(
                        MatchEvent(
                            event_no=event_no,
                            plate_appearance_no=pa_no,
                            inning=inning,
                            half=half,
                            offense_school_id=offense_id,
                            defense_school_id=defense_id,
                            batter_id=batter_id,
                            pitcher_id=pitcher_id,
                            event_type=event_type,
                            runs_scored=len(scored),
                            outs_on_play=outs_on_play,
                            rbi=rbi,
                            metadata=(
                                (
                                    "bases_before",
                                    self._bases_text(bases_before),
                                ),
                                (
                                    "bases_after",
                                    self._bases_text(bases),
                                ),
                                ("outs_after", str(outs)),
                                (
                                    "pitcher_staff_order",
                                    str(current_index + 1),
                                ),
                                *((('pitches', str(pitches_on_play)),) if dh_game else ()),
                                *((('scored_runners', '|'.join(scored)),) if dh_game else ()),
                                *((('walkoff_hit', pitch_event_type),) if event_type != pitch_event_type else ()),
                                *((('tactic', f"{tactic}:{tactic_outcome}"),) if tactic else ()),
                                *((('fielder', f"{fielded.position}|{fielded.player_id}"),)
                                  if fielded is not None and event_type == "reached_on_error" else ()),
                                *((('bases_after_play', self._bases_text(bases_after_play)),)
                                  if steal or advance else ()),
                                *((('steal', ';'.join(f"{r}|{f + 1}|{x}|{catcher_id}" for r, f, x in steal)),)
                                  if steal else ()),
                                *((('advance', f"{advance}|{pitcher_id if advance == 'wp' else catcher_id}"),)
                                  if advance else ()),
                            ),
                        )
                    )

                    if (states[offense_id].dh_batting_required
                            and states[offense_id].designated_hitter_id == batter_id):
                        states[offense_id].record_completed_plate_appearance(
                            batter_id, moment=CompletedPlateAppearanceMoment(inning, half, pa_no))

                    if (
                        half == "bottom"
                        and inning >= regulation
                        and team_runs[team2_id] > team_runs[team1_id]
                    ):
                        ending_half = "bottom"
                        game_over = True
                        break

                for responsible_id, earned in earned_run_tracker.earned_runs().items():
                    row = pitcher_rows[defense_id][responsible_id]
                    row["earned_runs"] = int(row["earned_runs"]) + earned
                inning_scores.append(InningScore(
                    inning=inning, half=half,
                    batting_team_id=offense_id,
                    was_played=True,
                    runs=team_runs[offense_id] - runs_before_half,
                    plate_appearances=pa_no - pa_before_half,
                ))
                if game_over:
                    break

                ending_half = half
                # 得点差コールド：その回が終わった時点（後攻が勝っていれば表が
                # 終わった時点）で点差が決まった数以上
                margin = team_runs[team2_id] - team_runs[team1_id]
                called = any(
                    inning >= mercy_inning
                    and (abs(margin) if half == "bottom" else margin) >= mercy_margin
                    for mercy_inning, mercy_margin in rules.mercy
                )
                if called and half == "bottom":
                    game_over = True
                    break
                if (
                    half == "top"
                    and (inning >= regulation or called)
                    and team_runs[team2_id] > team_runs[team1_id]
                ):
                    # Home team is already ahead: final bottom was never played.
                    inning_scores.append(InningScore(
                        inning=inning, half="bottom",
                        batting_team_id=team2_id,
                        was_played=False, runs=None,
                    ))
                    game_over = True
                    break
                if (
                    half == "bottom"
                    and inning >= regulation
                    and team_runs[team1_id] != team_runs[team2_id]
                ):
                    game_over = True
                    break

            if game_over:
                break

        if not game_over:
            raise RuntimeError(
                f"{match_input.match_id}: game tied after hard_max_innings={hard_max}"
            )
        if adjustments:
            raise ValueError('lineup adjustment refers to an unplayed plate appearance')

        if team_runs[team1_id] > team_runs[team2_id]:
            winner_id, loser_id = team1_id, team2_id
        else:
            winner_id, loser_id = team2_id, team1_id

        provenance = match_contract_provenance(self.config_dir)
        result = MatchSimulationResult(
            match_id=match_input.match_id,
            competition_id=match_input.competition_id,
            reference_year=match_input.reference_year,
            generation_seed=match_input.generation_seed,
            team1_school_id=team1_id,
            team2_school_id=team2_id,
            team1_score=team_runs[team1_id],
            team2_score=team_runs[team2_id],
            winner_id=winner_id,
            loser_id=loser_id,
            last_inning=last_inning,
            ending_half=ending_half,
            score_source=provenance.score_source,
            match_config_id=provenance.match_config_id,
            match_config_revision=provenance.match_config_revision,
            match_config_sha256=provenance.match_config_sha256,
            event_catalog_id=provenance.event_catalog_id,
            event_catalog_revision=provenance.event_catalog_revision,
            event_catalog_sha256=provenance.event_catalog_sha256,
            stats_config_id=provenance.stats_config_id,
            stats_config_revision=provenance.stats_config_revision,
            stats_config_sha256=provenance.stats_config_sha256,
            team_stats=(
                TeamGameStats(
                    school_id=team1_id,
                    runs=team_runs[team1_id],
                    hits=team_hits[team1_id],
                    errors=team_errors[team1_id],
                ),
                TeamGameStats(
                    school_id=team2_id,
                    runs=team_runs[team2_id],
                    hits=team_hits[team2_id],
                    errors=team_errors[team2_id],
                ),
            ),
            events=tuple(events),
            team_participation=tuple(states[sid].participation() for sid in (team1_id, team2_id)),
            inning_scores=tuple(inning_scores),
            batter_stats=tuple(
                BatterGameStats(**row)
                for school_id in (team1_id, team2_id)
                for row in batter_rows[school_id].values()
            ),
            pitcher_stats=tuple(
                PitcherGameStats(**row)
                for school_id in (team1_id, team2_id)
                for row in pitcher_rows[school_id].values()
            ),
        )
        validate_match_simulation_result(
            result,
            match_input,
            config_dir=self.config_dir,
            final_states=states,
        )
        if validated_history_sink is not None and dh_game:
            validated_history_sink.update(
                match_input=match_input, result=result, history=_history_after_validation(result))
        if state_sink is not None:
            state_sink.update(states)
        return result


_EVENT_WEIGHT_MODEL = MatchSimulator._event_weights
_WEIGHTED_CHOICE_MODEL = MatchSimulator._weighted_choice
_APPLY_EVENT_MODEL = MatchSimulator._apply_event
_RNG_FACTORY = rng_for


def _baserunning_moves(metadata, after, final) -> list[tuple]:
    """打席のあとの走塁の記録（advance・steal）を、打席の直後の塁（after）から再生する。

    返すのは順に ('play', 走者, 種類, 前の塁, 後の塁, 生還した走者)（暴投・捕逸・本盗の成功）、
    ('score', 走者)、('advance', 走者, 元の塁)、('out', 走者, 元の塁)。塁が final に一致しないと誤り。"""
    bases = list(after)
    moves: list[tuple] = []
    advance = metadata.get('advance')
    steal = metadata.get('steal')
    if advance is not None:
        kind, _ = advance.split('|')
        if kind not in ('wp', 'pb') or steal is not None or not any(bases):
            raise ValueError('invalid wild pitch / passed ball evidence')
        before = list(bases)
        scored = [bases[2]] if bases[2] is not None else []
        bases = [None, bases[0], bases[1]]
        moves.append(('play', '', 'wild_pitch' if kind == 'wp' else 'passed_ball', before, list(bases), scored))
        moves.extend(('score', runner) for runner in scored)
    for entry in (steal.split(';') if steal else ()):
        runner_id, from_base, result, _ = entry.split('|')
        from_index = int(from_base) - 1
        if result not in ('sb', 'cs', 'po', 'adv') or not 0 <= from_index <= 2 or bases[from_index] != runner_id:
            raise ValueError('invalid stolen base evidence')
        if result in ('sb', 'adv') and from_index == 2:
            before = list(bases)
            bases[2] = None
            moves.append(('play', '', 'stolen_base', before, list(bases), [runner_id]))
            moves.append(('score', runner_id))
            continue
        bases[from_index] = None
        if result in ('sb', 'adv'):
            if bases[from_index + 1] is not None:
                raise ValueError('stolen base target is occupied')
            bases[from_index + 1] = runner_id
            moves.append(('advance', runner_id, from_index))
        else:
            moves.append(('out', runner_id, from_index))
    if bases != final:
        raise ValueError('bases after the play differ from the baserunning evidence')
    return moves


def validate_run_accounting(result: MatchSimulationResult) -> None:
    """破棄前のDHイベントで既存の責任投手・自責点処理を再生する。"""
    runs, earned, batter_runs = Counter(), Counter(), Counter()
    previous_half = None
    previous_bases = [None, None, None]
    outs = 0
    for event in result.events:
        metadata = dict(event.metadata)
        try:
            before = [pid or None for pid in metadata['bases_before'].split('|')]
            final = [pid or None for pid in metadata['bases_after'].split('|')]
            # 打席のあとの盗塁は、打席の直後の塁（bases_after_play）から再生する
            after = [pid or None for pid in metadata.get('bases_after_play', metadata['bases_after']).split('|')]
            scored = [pid for pid in metadata['scored_runners'].split('|') if pid]
        except (KeyError, AttributeError) as exc:
            raise ValueError('DH strict validation requires scoring runner identities') from exc
        # 打席のあとの走塁（暴投・捕逸・盗塁）を、打席の直後の塁から順に確かめる
        moves = _baserunning_moves(metadata, after, final)
        baserunning_scored = [runner for kind, runner, *_ in moves if kind == 'score']
        steal_out = sum(kind == 'out' for kind, *_ in moves)
        if baserunning_scored != scored[len(scored) - len(baserunning_scored):]:
            raise ValueError('baserunning runs differ from scoring runners')
        play_scored = scored[:len(scored) - len(baserunning_scored)]
        half = (event.inning, event.half)
        if half != previous_half:
            responsibility = _RunnerResponsibilityTracker()
            reconstruction = _EarnedRunTracker()
            outs = 0
            if any(before):
                responsibility.seed_tiebreak(before, event.pitcher_id)
        else:
            for outgoing, incoming in zip(previous_bases, before, strict=True):
                if outgoing is not None and incoming is not None and outgoing != incoming:
                    responsibility.substitute_runner(outgoing, incoming)
                    reconstruction.substitute_runner(outgoing, incoming)
        if len(scored) != event.runs_scored:
            raise ValueError('scoring runner count differs from event runs')
        hit_before_finish = metadata.get('walkoff_hit', event.event_type)
        if 'walkoff_hit' in metadata:
            hits = ('single', 'double', 'triple')
            if (event.plate_appearance_no != len(result.events) or event.half != 'bottom'
                    or result.winner_id != result.team2_school_id or not scored
                    or event.event_type not in hits or hit_before_finish not in hits
                    or hits.index(hit_before_finish) <= hits.index(event.event_type)):
                raise ValueError('invalid walkoff hit evidence')
            winning_runner = scored[-1]
            if (winning_runner not in before or hits.index(event.event_type)+1
                    != min(hits.index(hit_before_finish)+1, 3-before.index(winning_runner))):
                raise ValueError('walkoff hit credit differs from winning runner advance')
        for pid in scored:
            batter_runs[event.offense_school_id, pid] += 1
        runners = list(responsibility.record_play(
            bases_before=before, bases_after=after, scored_runner_ids=play_scored,
            batter_id=event.batter_id, pitcher_id=event.pitcher_id,
            event_type=event.event_type, plate_appearance_no=event.plate_appearance_no))
        reconstruction.record_play(
            bases_before=before, bases_after=after, scored_runners=runners,
            batter_id=event.batter_id, pitcher_id=event.pitcher_id, event_type=hit_before_finish,
            plate_appearance_no=event.plate_appearance_no, outs_before=outs,
            outs_on_play=event.outs_on_play - steal_out)
        outs_after_play = outs + event.outs_on_play - steal_out
        for kind, runner_id, *rest in moves:
            if kind == 'play':
                event_type, move_before, move_after, move_scored = rest
                runners.extend(MatchSimulator._record_baserunning_play(
                    event_type, move_before, move_after, move_scored, responsibility, reconstruction,
                    event.pitcher_id, event.plate_appearance_no, outs_after_play))
            elif kind == 'out':
                responsibility.retire_runner(runner_id)
                reconstruction.record_baserunning(runner_id, rest[0], None)
                outs_after_play += 1
            elif kind == 'advance':
                reconstruction.record_baserunning(runner_id, rest[0], rest[0] + 1)
        outs += event.outs_on_play
        if outs > 3 or str(outs) != metadata.get('outs_after'):
            raise ValueError('event outs differ from inning reconstruction')
        for runner in runners:
            runs[event.defense_school_id, runner.responsible_pitcher_id] += 1
        # 無失策の再構成は半イニングの最後に確定する。
        next_index = event.plate_appearance_no
        if next_index == len(result.events) or (
                result.events[next_index].inning, result.events[next_index].half) != half:
            for pid, count in reconstruction.earned_runs().items():
                earned[event.defense_school_id, pid] += count
        previous_half, previous_bases = half, final
    for row in result.pitcher_stats:
        key = (row.school_id, row.player_id)
        if (row.runs_allowed, row.earned_runs) != (runs[key], earned[key]):
            raise ValueError('pitcher runs/earned runs differ from actual runner liability')
    for row in result.batter_stats:
        if row.runs != batter_runs[row.school_id, row.player_id]:
            raise ValueError('batter individual stats differ from actual scoring runners')


def synchronize_tournament_match(
    match,
    result: MatchSimulationResult,
) -> None:
    if match.match_id != result.match_id:
        raise ValueError("tournament sync: match_id mismatch")
    if match.competition_id != result.competition_id:
        raise ValueError("tournament sync: competition_id mismatch")
    if match.is_bye:
        raise ValueError("tournament sync: bye cannot receive simulation result")
    if match.team1 != result.team1_school_id:
        raise ValueError("tournament sync: team1 mismatch")
    if match.team2 != result.team2_school_id:
        raise ValueError("tournament sync: team2 mismatch")

    match.winner = result.winner_id
    match.loser = result.loser_id
    match.metadata["score_source"] = result.score_source
    match.metadata["team1_score"] = result.team1_score
    match.metadata["team2_score"] = result.team2_score
    match.metadata["last_inning"] = result.last_inning
    match.metadata["ending_half"] = result.ending_half
