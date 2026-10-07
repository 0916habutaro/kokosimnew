from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from phase2_engine.randomness import rng_for
from phase2_engine.repository import DataRepository

from .match_contract import MatchSimulationInput, TeamMatchInput
from .match_simulator import MatchSimulator
from .players import PlayerRosterGenerator
from .school_intake import SchoolAwarePlayerAbilityGenerator
from .team_strength import TeamStrengthGenerator


@dataclass(frozen=True)
class Stage13C2AuditRow:
    seed: int
    school_count: int
    game_count: int
    mean_total_runs: float
    p50_total_runs: float
    p95_total_runs: float
    max_total_runs: int
    mean_winner_runs: float
    mean_loser_runs: float
    one_run_game_rate: float
    shutout_rate: float
    extra_innings_rate: float
    team2_win_rate: float
    stronger_team_win_rate: float
    stronger_win_rate_edge_0_2: float
    stronger_win_rate_edge_2_5: float
    stronger_win_rate_edge_5_10: float
    stronger_win_rate_edge_10_plus: float
    plate_appearance_count: int
    strikeout_rate: float
    walk_rate: float
    hit_by_pitch_rate: float
    hit_rate: float
    home_run_rate: float
    reached_on_error_rate: float
    sacrifice_bunt_rate: float
    sacrifice_fly_rate: float
    mean_pitchers_used_per_team: float

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return (
        float(ordered[lower])
        + (
            float(ordered[upper]) - float(ordered[lower])
        )
        * fraction
    )


def _team_overall(team: TeamMatchInput) -> float:
    strength = team.team_strength
    return (
        float(strength.batting_strength) * 0.45
        + float(strength.pitching_strength) * 0.45
        + float(strength.defense_strength) * 0.10
    )


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _build_teams(
    *,
    repo: DataRepository,
    config_dir: str | Path,
    reference_year: int,
    seed: int,
    school_count: int,
) -> list[TeamMatchInput]:
    roster_generator = PlayerRosterGenerator()
    ability_generator = SchoolAwarePlayerAbilityGenerator(config_dir)
    team_generator = TeamStrengthGenerator(config_dir)

    school_ids = [
        school_id
        for school_id in sorted(repo.schools)
        if school_id in repo.school_to_program
    ]
    selection_rng = rng_for(
        seed,
        f"stage13c2_audit_v1:{reference_year}:school_selection",
    )
    selection_rng.shuffle(school_ids)
    selected = school_ids[:school_count]
    if len(selected) < school_count:
        raise ValueError(
            f"requested {school_count} schools, only {len(selected)} available"
        )

    teams: list[TeamMatchInput] = []
    for school_id in selected:
        roster = roster_generator.generate_for_school_id(
            repo,
            school_id,
            reference_year,
            seed,
        )
        abilities = tuple(
            ability_generator.iter_roster(
                roster.players,
                reference_year,
                seed,
            )
        )
        teams.append(
            TeamMatchInput(
                school_id=school_id,
                team_strength=team_generator.generate(abilities),
                player_abilities=abilities,
            )
        )
    return teams


def run_audit(
    *,
    data_dir: str | Path,
    ability_config_dir: str | Path,
    match_config_dir: str | Path,
    reference_year: int,
    seed: int,
    school_count: int,
    game_count: int,
) -> Stage13C2AuditRow:
    if school_count < 2:
        raise ValueError("school_count must be >= 2")
    if game_count < 1:
        raise ValueError("game_count must be >= 1")

    repo = DataRepository(data_dir)
    teams = _build_teams(
        repo=repo,
        config_dir=ability_config_dir,
        reference_year=reference_year,
        seed=seed,
        school_count=school_count,
    )
    simulator = MatchSimulator(match_config_dir)
    pair_rng = rng_for(
        seed,
        f"stage13c2_audit_v1:{reference_year}:pairings",
    )

    total_runs: list[float] = []
    winner_runs: list[float] = []
    loser_runs: list[float] = []
    one_run = 0
    shutouts = 0
    extras = 0
    team2_wins = 0
    stronger_total = 0
    stronger_wins = 0
    edge_bins = {
        "0_2": [0, 0],
        "2_5": [0, 0],
        "5_10": [0, 0],
        "10_plus": [0, 0],
    }
    event_counts: dict[str, int] = {}
    pa_count = 0
    pitchers_used_total = 0

    for index in range(game_count):
        left_index = pair_rng.randrange(len(teams))
        right_index = pair_rng.randrange(len(teams) - 1)
        if right_index >= left_index:
            right_index += 1

        # Alternate orientation to avoid fixing the stronger side to one half.
        if index % 2 == 0:
            team1 = teams[left_index]
            team2 = teams[right_index]
        else:
            team1 = teams[right_index]
            team2 = teams[left_index]

        match_input = MatchSimulationInput(
            match_id=f"AUDIT-{seed}-{index + 1:05d}",
            competition_id="CMP_STAGE13C2_AUDIT",
            reference_year=reference_year,
            generation_seed=seed,
            team1=team1,
            team2=team2,
        )
        result = simulator.simulate(match_input)

        scores = [result.team1_score, result.team2_score]
        total_runs.append(float(sum(scores)))
        winner_runs.append(float(max(scores)))
        loser_runs.append(float(min(scores)))
        if abs(result.team1_score - result.team2_score) == 1:
            one_run += 1
        if min(scores) == 0:
            shutouts += 1
        if result.last_inning > 9:
            extras += 1
        if result.winner_id == team2.school_id:
            team2_wins += 1

        strength1 = _team_overall(team1)
        strength2 = _team_overall(team2)
        edge = abs(strength1 - strength2)
        if edge > 1e-9:
            stronger_total += 1
            stronger_id = (
                team1.school_id
                if strength1 > strength2
                else team2.school_id
            )
            won = result.winner_id == stronger_id
            if won:
                stronger_wins += 1
            if edge < 2:
                key = "0_2"
            elif edge < 5:
                key = "2_5"
            elif edge < 10:
                key = "5_10"
            else:
                key = "10_plus"
            edge_bins[key][1] += 1
            if won:
                edge_bins[key][0] += 1

        pa_count += len(result.events)
        for event in result.events:
            event_counts[event.event_type] = (
                event_counts.get(event.event_type, 0) + 1
            )
        pitchers_used_total += sum(
            row.batters_faced > 0
            for row in result.pitcher_stats
        )

    hit_count = sum(
        event_counts.get(event_type, 0)
        for event_type in ("single", "double", "triple", "home_run")
    )

    return Stage13C2AuditRow(
        seed=seed,
        school_count=school_count,
        game_count=game_count,
        mean_total_runs=round(statistics.fmean(total_runs), 4),
        p50_total_runs=round(_percentile(total_runs, 0.50), 2),
        p95_total_runs=round(_percentile(total_runs, 0.95), 2),
        max_total_runs=int(max(total_runs)),
        mean_winner_runs=round(statistics.fmean(winner_runs), 4),
        mean_loser_runs=round(statistics.fmean(loser_runs), 4),
        one_run_game_rate=round(_rate(one_run, game_count), 4),
        shutout_rate=round(_rate(shutouts, game_count), 4),
        extra_innings_rate=round(_rate(extras, game_count), 4),
        team2_win_rate=round(_rate(team2_wins, game_count), 4),
        stronger_team_win_rate=round(
            _rate(stronger_wins, stronger_total),
            4,
        ),
        stronger_win_rate_edge_0_2=round(
            _rate(*edge_bins["0_2"]),
            4,
        ),
        stronger_win_rate_edge_2_5=round(
            _rate(*edge_bins["2_5"]),
            4,
        ),
        stronger_win_rate_edge_5_10=round(
            _rate(*edge_bins["5_10"]),
            4,
        ),
        stronger_win_rate_edge_10_plus=round(
            _rate(*edge_bins["10_plus"]),
            4,
        ),
        plate_appearance_count=pa_count,
        strikeout_rate=round(
            _rate(event_counts.get("strikeout", 0), pa_count),
            4,
        ),
        walk_rate=round(
            _rate(event_counts.get("walk", 0), pa_count),
            4,
        ),
        hit_by_pitch_rate=round(
            _rate(event_counts.get("hit_by_pitch", 0), pa_count),
            4,
        ),
        hit_rate=round(_rate(hit_count, pa_count), 4),
        home_run_rate=round(
            _rate(event_counts.get("home_run", 0), pa_count),
            4,
        ),
        reached_on_error_rate=round(
            _rate(event_counts.get("reached_on_error", 0), pa_count),
            4,
        ),
        sacrifice_bunt_rate=round(
            _rate(event_counts.get("sacrifice_bunt", 0), pa_count),
            4,
        ),
        sacrifice_fly_rate=round(
            _rate(event_counts.get("sacrifice_fly", 0), pa_count),
            4,
        ),
        mean_pitchers_used_per_team=round(
            pitchers_used_total / (game_count * 2),
            4,
        ),
    )


def write_audit_csv(
    rows: list[Stage13C2AuditRow],
    path: str | Path,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(Stage13C2AuditRow.__dataclass_fields__),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage 13C-2 ability-model match distribution audit"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--ability-config-dir",
        default="config/abilities",
    )
    parser.add_argument(
        "--match-config-dir",
        default="config/match",
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--seeds",
        default="2026100701,2026100702,2026100703",
    )
    parser.add_argument("--school-count", type=int, default=240)
    parser.add_argument("--game-count", type=int, default=1000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    seeds = [
        int(value.strip())
        for value in args.seeds.split(",")
        if value.strip()
    ]
    if not seeds:
        parser.error("--seeds must contain at least one integer")

    rows = [
        run_audit(
            data_dir=args.data_dir,
            ability_config_dir=args.ability_config_dir,
            match_config_dir=args.match_config_dir,
            reference_year=args.year,
            seed=seed,
            school_count=args.school_count,
            game_count=args.game_count,
        )
        for seed in seeds
    ]
    write_audit_csv(rows, args.output)
    print(json.dumps(
        {
            "reference_year": args.year,
            "seeds": seeds,
            "school_count_per_seed": args.school_count,
            "game_count_per_seed": args.game_count,
            "total_games": args.game_count * len(seeds),
            "output": args.output,
        },
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
