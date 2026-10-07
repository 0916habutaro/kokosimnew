from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from phase2_engine.randomness import rng_for

from .abilities import PlayerAbilitySnapshot
from .match_config import load_and_validate_match_configs
from .match_contract import (
    BatterGameStats,
    MatchEvent,
    MatchSimulationInput,
    MatchSimulationResult,
    PitcherGameStats,
    TeamGameStats,
    TeamMatchInput,
    match_contract_provenance,
    validate_match_simulation_input,
    validate_match_simulation_result,
)


class MatchSimulator:
    def __init__(
        self,
        config_dir: str | Path = "config/match",
    ):
        self.config_dir = Path(config_dir)
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
    def _lineup(team: TeamMatchInput) -> tuple[str, ...]:
        entries = sorted(
            team.team_strength.starting_lineup.entries,
            key=lambda entry: entry.batting_order,
        )
        return tuple(entry.player_id for entry in entries)

    @staticmethod
    def _pitcher_order(team: TeamMatchInput) -> tuple[str, ...]:
        entries = sorted(
            team.team_strength.pitching_staff.entries,
            key=lambda entry: entry.order,
        )
        return tuple(entry.player_id for entry in entries)

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
    ) -> bool:
        if not has_next:
            return False
        usage = self.params["pitching_usage"]
        minimum = int(usage["minimum_bf_before_change"])
        if stats["batters_faced"] < minimum:
            return False
        if stats["runs_allowed"] >= int(usage["runs_allowed_quick_hook"]):
            return True
        return stats["batters_faced"] >= self._pitcher_limit(
            pitcher,
            starter=starter,
        )

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
    ) -> MatchSimulationResult:
        validate_match_simulation_input(match_input)
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
        team1_id = match_input.team1.school_id
        team2_id = match_input.team2.school_id
        player_maps = {
            school_id: self._players(team)
            for school_id, team in teams.items()
        }
        lineups = {
            school_id: self._lineup(team)
            for school_id, team in teams.items()
        }
        pitcher_orders = {
            school_id: self._pitcher_order(team)
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
                for player_id in lineups[school_id]
            }
            for school_id in (team1_id, team2_id)
        }
        pitcher_rows: dict[str, dict[str, dict[str, int | str]]] = {
            team1_id: {},
            team2_id: {},
        }
        for school_id in (team1_id, team2_id):
            first_pitcher = pitcher_orders[school_id][0]
            pitcher_rows[school_id][first_pitcher] = (
                self._empty_pitcher_stats(first_pitcher, school_id)
            )

        team_runs = {team1_id: 0, team2_id: 0}
        team_hits = {team1_id: 0, team2_id: 0}
        team_errors = {team1_id: 0, team2_id: 0}

        events: list[MatchEvent] = []
        pa_no = 0
        event_no = 0
        last_inning = 1
        ending_half = "bottom"
        game_over = False

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
                    ending_half = "top"
                    game_over = True
                    break

                outs = 0
                bases: list[str | None] = [None, None, None]

                while outs < 3:
                    staff = pitcher_orders[defense_id]
                    current_index = pitcher_index[defense_id]
                    pitcher_id = staff[current_index]
                    if pitcher_id not in pitcher_rows[defense_id]:
                        pitcher_rows[defense_id][pitcher_id] = (
                            self._empty_pitcher_stats(
                                pitcher_id,
                                defense_id,
                            )
                        )
                    pitcher = player_maps[defense_id][pitcher_id]
                    pitcher_stat = pitcher_rows[defense_id][pitcher_id]

                    if self._should_change_pitcher(
                        pitcher=pitcher,
                        stats=pitcher_stat,
                        starter=current_index == 0,
                        has_next=current_index + 1 < len(staff),
                    ):
                        pitcher_index[defense_id] += 1
                        current_index = pitcher_index[defense_id]
                        pitcher_id = staff[current_index]
                        if pitcher_id not in pitcher_rows[defense_id]:
                            pitcher_rows[defense_id][pitcher_id] = (
                                self._empty_pitcher_stats(
                                    pitcher_id,
                                    defense_id,
                                )
                            )
                        pitcher = player_maps[defense_id][pitcher_id]
                        pitcher_stat = pitcher_rows[defense_id][pitcher_id]

                    lineup = lineups[offense_id]
                    batter_id = lineup[
                        lineup_index[offense_id] % len(lineup)
                    ]
                    lineup_index[offense_id] += 1
                    batter = player_maps[offense_id][batter_id]

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
                            teams[defense_id].team_strength.defense_strength,
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
                        defense_strength=teams[
                            defense_id
                        ].team_strength.defense_strength,
                        rng=event_rng,
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
                    pitcher_stat["outs_recorded"] = (
                        int(pitcher_stat["outs_recorded"])
                        + outs_on_play
                    )
                    pitcher_stat["runs_allowed"] = (
                        int(pitcher_stat["runs_allowed"])
                        + len(scored)
                    )
                    if event_type != "reached_on_error":
                        pitcher_stat["earned_runs"] = (
                            int(pitcher_stat["earned_runs"])
                            + len(scored)
                        )
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
                            ),
                        )
                    )

                    if (
                        half == "bottom"
                        and inning >= regulation
                        and team_runs[team2_id] > team_runs[team1_id]
                    ):
                        ending_half = "bottom"
                        game_over = True
                        break

                if game_over:
                    break

                ending_half = half
                if (
                    half == "top"
                    and inning >= regulation
                    and team_runs[team2_id] > team_runs[team1_id]
                ):
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
        )
        return result


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
