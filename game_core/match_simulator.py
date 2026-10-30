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
from .match_state import ChangeMoment, CompletedPlateAppearanceMoment, TeamMatchState
from .team_strength import TeamStrengthGenerator


@dataclass(frozen=True)
class GameRules:
    """試合の規定（config/match/game_rules_v1.json）。

    ``tiebreak_start_inning``：この回から無死一・二塁で始める（None なら使わない）。
    ``mercy``：（回, 点差）。その回が終わった時点で点差がこれ以上なら試合終了。"""

    tiebreak_start_inning: int | None = None
    mercy: tuple[tuple[int, int], ...] = ()


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
        elif event == "sacrifice_fly":
            if self.bases[2] is not None:
                self.scored.add(self.bases[2])
                self.bases[2] = None
        elif event == "sacrifice_bunt":
            # The actual engine only bunts without a third-base runner. A runner
            # lagging on virtual third is held; do not invent a squeeze play.
            for index in (1, 0):
                if self.bases[index] is not None and self.bases[index + 1] is None:
                    self.bases[index + 1], self.bases[index] = self.bases[index], None
        elif event not in {"strikeout", "field_out"}:
            raise ValueError(f"unsupported earned-run event: {event}")


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

    def _game_staff(
        self,
        team: TeamMatchInput,
        allowances: Mapping[str, int] | None,
    ) -> tuple[tuple[str, ...], int]:
        """この試合で投げる順と、そのうち投手陣の人数。球数制限（``allowances``：
        あと何球投げられるか）があれば、残りの少ない投手は先発にせず、投げられない
        投手は外す。後ろに野手を並べ、球数制限で投手がいなくなったときだけ使う。"""
        staff = self._pitcher_order(team)
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

    def _strength_generator(self) -> TeamStrengthGenerator:
        if self._team_generator is None:
            self._team_generator = TeamStrengthGenerator()
        return self._team_generator

    def _initial_state(self, team: TeamMatchInput, actual_pitcher_id: str) -> TeamMatchState:
        """開始前にP配置を確定する。外れた先発予定選手は未出場の控えに戻す。"""
        lineup = team.team_strength.starting_lineup
        planned_pitcher = lineup.player_for_position("P")
        if actual_pitcher_id != planned_pitcher and lineup.designated_hitter_id is not None:
            lineup = self._strength_generator().select_starting_lineup(
                team.player_abilities, starting_pitcher_id=actual_pitcher_id,
                dh_mode='pitcher' if lineup.designated_hitter_id == planned_pitcher else 'normal')
        elif actual_pitcher_id != planned_pitcher:
            position = next((entry.defensive_position for entry in lineup.entries
                             if entry.player_id == actual_pitcher_id), None)
            if position is None:
                player = self._players(team)[actual_pitcher_id]
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
            strikeout=value, groundball=value, composure=value,
        )

    def _pitches(self, event_type: str, rng) -> int:
        minimum, extra = self.params["pitch_count"]["by_event"][event_type]
        return int(minimum) + rng.randint(0, int(extra))

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

    def _event_weights(
        self,
        batter: PlayerAbilitySnapshot,
        pitcher: PlayerAbilitySnapshot,
        defense_strength: float,
    ) -> dict[str, float]:
        model = self.params["plate_appearance_model"]
        base = model["base_probabilities"]
        scale = model["ability_effect_scale"]
        floor = float(model["probability_floor"])
        defense_center = float(model["defense_center"])

        p_stuff = (
            0.65 * float(pitcher.stuff or 50)
            + 0.35 * self._pitch_quality(pitcher)
        )
        p_control = float(pitcher.control or 50)
        p_strikeout = float(pitcher.strikeout or 50)
        p_groundball = float(pitcher.groundball or 50)

        so_exp = (
            (p_strikeout - float(batter.strikeout_resistance))
            * float(scale["strikeout"])
            + (p_stuff - float(batter.contact))
            * float(scale["strikeout"])
            * 0.45
        )
        walk_exp = (
            float(batter.plate_discipline) - p_control
        ) * float(scale["walk"])
        single_exp = (
            float(batter.contact) - p_stuff
        ) * float(scale["single"]) + (
            defense_center - defense_strength
        ) * float(scale["single"]) * 0.45

        extra_batter = (
            float(batter.contact) * 0.45
            + float(batter.power) * 0.55
        )
        extra_pitcher = p_stuff * 0.60 + p_groundball * 0.40
        xbh_exp = (
            extra_batter - extra_pitcher
        ) * float(scale["extra_base_hit"])
        hr_exp = (
            float(batter.power)
            - p_stuff * 0.55
            - p_groundball * 0.45
        ) * float(scale["home_run"])
        error_exp = (
            50.0 - defense_strength
        ) * float(scale["error"]) + (
            float(batter.speed) - 50.0
        ) * float(scale["error"]) * 0.25
        out_exp = (
            p_stuff * 0.45
            + p_groundball * 0.25
            + defense_strength * 0.30
            - float(batter.contact)
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

    def _should_sacrifice_bunt(
        self,
        batter: PlayerAbilitySnapshot,
        bases: list[str | None],
        outs: int,
        score_margin: int,
        rng,
    ) -> bool:
        settings = self.params["situational_events"]["sacrifice_bunt"]
        if not settings["enabled"]:
            return False
        if outs > int(settings["max_outs"]):
            return False
        if abs(score_margin) > int(settings["allowed_score_margin"]):
            return False
        if bases[2] is not None:
            return False
        if bases[0] is None and bases[1] is None:
            return False
        if batter.bunt < int(settings["minimum_bunt_ability"]):
            return False

        ability_factor = 0.5 + float(batter.bunt) / 100.0
        probability = min(
            0.20,
            float(settings["base_probability"]) * ability_factor,
        )
        return rng.random() < probability

    def _maybe_sacrifice_fly(
        self,
        event_type: str,
        bases: list[str | None],
        outs: int,
        batter: PlayerAbilitySnapshot,
        rng,
    ) -> str:
        if event_type != "field_out":
            return event_type
        settings = self.params["situational_events"]["sacrifice_fly"]
        if not settings["enabled"]:
            return event_type
        if outs > int(settings["max_outs"]):
            return event_type
        if bases[2] is None:
            return event_type

        contact_factor = 0.75 + float(batter.contact) / 200.0
        power_factor = 0.85 + float(batter.power) / 300.0
        probability = min(
            0.90,
            float(settings["base_probability"])
            * contact_factor
            * power_factor,
        )
        return "sacrifice_fly" if rng.random() < probability else event_type

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
    ) -> tuple[list[str], int, int]:
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
                    ),
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
                    ),
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
            outs = 1
            bases[:] = [
                None,
                batter_id if False else first,
                second,
            ]
            # batter is out; existing runners advance one base.
            bases[0] = None
            bases[1] = first
            bases[2] = second
            return scored, outs, 0

        if event_type == "sacrifice_fly":
            outs = 1
            if third is not None:
                scored.append(third)
                bases[2] = None
                rbi = 1
            return scored, outs, rbi

        if event_type in {"strikeout", "field_out"}:
            return scored, 1, 0

        raise ValueError(f"unsupported event_type: {event_type}")

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
        row["rbi"] = int(row["rbi"]) + rbi

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
    ) -> MatchSimulationResult:
        """``pitch_allowances``：選手 → この試合であと何球投げられるか（球数制限）。
        届いたら次の打者から投げない。None なら制限なし。
        state_sink指定時は、成功した試合の開始配置・最終状態・交代履歴を返す。
        lineup_changesは直接計算の明示交代。全国進行からは渡さない。
        validated_history_sinkは厳密検証した入力・結果そのものとA詳細を一時的に返す。
        この計算経路から永続保存は行わない。"""
        validate_match_simulation_input(match_input)
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
        policies = {sid: (tactics or {}).get(sid, CoachTactics()) for sid in teams}
        team1_id = match_input.team1.school_id
        team2_id = match_input.team2.school_id
        player_maps = {
            school_id: self._players(team)
            for school_id, team in teams.items()
        }
        game_staffs = {
            school_id: self._game_staff(team, pitch_allowances)
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
        states = {
            school_id: self._initial_state(team, pitcher_orders[school_id][0])
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

        def check_new_pitcher(school_id, incoming):
            if incoming in pitcher_rows[school_id] and int(pitcher_rows[school_id][incoming]['batters_faced']) > 0:
                raise ValueError(f'{school_id}: pitcher reentry is not supported: {incoming}')
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
                    current_index = pitcher_index[defense_id]
                    state = states[defense_id]
                    pitcher_id = state.current_pitcher_id
                    if pitcher_id not in pitcher_rows[defense_id]:
                        pitcher_rows[defense_id][pitcher_id] = (
                            self._empty_pitcher_stats(
                                pitcher_id,
                                defense_id,
                            )
                        )
                    pitcher = self._as_pitcher(player_maps[defense_id][pitcher_id])
                    pitcher_stat = pitcher_rows[defense_id][pitcher_id]

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
                    if limit_reached or self._should_change_pitcher(
                        pitcher=pitcher,
                        stats={**pitcher_stat, "runs_allowed": outing_runs[pitcher_id]},
                        starter=pitcher_id == state.initial_lineup.player_for_position('P'),
                        has_next=next_index < staff_sizes[defense_id],
                        tactics=policies[defense_id],
                    ):
                        current_index = next_index
                        pitcher_index[defense_id] = current_index
                        incoming = staff[current_index]
                        check_new_pitcher(defense_id, incoming)
                        old_pitcher = state.current_pitcher_id
                        extra_defense = {}
                        if state.designated_hitter_id is not None and old_pitcher != state.designated_hitter_id:
                            # 野手の緊急登板ではDHが空いた守備へ入り、旧投手は退く。
                            vacated = next((a.defensive_position for a in state.defensive_alignment
                                            if a.player_id == incoming and a.defensive_position != 'P'), None)
                            if vacated is not None:
                                extra_defense[vacated] = state.designated_hitter_id
                        state.change_pitcher(incoming, defensive_changes=extra_defense, moment=before_moment())
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
                    event_rng = rng_for(
                        match_input.generation_seed,
                        event_namespace,
                    )

                    bases_before = list(bases)
                    score_margin = (
                        team_runs[offense_id] - team_runs[defense_id]
                    )
                    if self._should_sacrifice_bunt(
                        batter,
                        bases,
                        outs,
                        score_margin,
                        pa_rng,
                    ):
                        event_type = "sacrifice_bunt"
                    else:
                        weights = self._event_weights(
                            batter,
                            pitcher,
                            defense_values[defense_id],
                        )
                        event_type = self._weighted_choice(pa_rng, weights)
                        event_type = self._maybe_sacrifice_fly(
                            event_type,
                            bases,
                            outs,
                            batter,
                            pa_rng,
                        )

                    scored, outs_on_play, rbi = self._apply_event(
                        event_type=event_type,
                        batter_id=batter_id,
                        bases=bases,
                        offense_players=player_maps[offense_id],
                        defense_strength=defense_values[defense_id],
                        rng=event_rng,
                    )
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
                        pitcher_id=pitcher_id, event_type=event_type,
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

                    pitcher_stat["batters_faced"] = (
                        int(pitcher_stat["batters_faced"]) + 1
                    )
                    pitches_on_play = self._pitches(
                        event_type,
                        rng_for(
                            match_input.generation_seed,
                            self.params["rng_namespace_policy"]["pitches"].format(
                                match_id=match_input.match_id,
                                plate_appearance_no=pa_no,
                            ),
                        ),
                    )
                    pitcher_stat['pitches'] = int(pitcher_stat['pitches']) + pitches_on_play
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
            after = [pid or None for pid in metadata['bases_after'].split('|')]
            scored = [pid for pid in metadata['scored_runners'].split('|') if pid]
        except (KeyError, AttributeError) as exc:
            raise ValueError('DH strict validation requires scoring runner identities') from exc
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
        for pid in scored:
            batter_runs[event.offense_school_id, pid] += 1
        runners = responsibility.record_play(
            bases_before=before, bases_after=after, scored_runner_ids=scored,
            batter_id=event.batter_id, pitcher_id=event.pitcher_id,
            event_type=event.event_type, plate_appearance_no=event.plate_appearance_no)
        reconstruction.record_play(
            bases_before=before, bases_after=after, scored_runners=runners,
            batter_id=event.batter_id, pitcher_id=event.pitcher_id, event_type=event.event_type,
            plate_appearance_no=event.plate_appearance_no, outs_before=outs, outs_on_play=event.outs_on_play)
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
        previous_half, previous_bases = half, after
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
