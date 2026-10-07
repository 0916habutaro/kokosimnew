from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .browse_repository import BrowseRepository


@dataclass(frozen=True)
class BatterAggregate:
    player_id: str
    school_id: str
    school_name: str
    games: int
    team_games: int
    plate_appearances: int
    at_bats: int
    runs: int
    hits: int
    singles: int
    doubles: int
    triples: int
    home_runs: int
    rbi: int
    walks: int
    strikeouts: int
    hit_by_pitch: int
    sacrifice_flies: int
    sacrifice_bunts: int
    stolen_bases: int
    caught_stealing: int
    total_bases: int
    batting_average: float | None
    on_base_percentage: float | None
    slugging_percentage: float | None
    ops: float | None
    isolated_power: float | None
    qualified_for_rate_rankings: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PitcherAggregate:
    player_id: str
    school_id: str
    school_name: str
    games: int
    team_games: int
    outs_recorded: int
    innings_pitched_display: str
    batters_faced: int
    runs_allowed: int
    earned_runs: int
    hits_allowed: int
    home_runs_allowed: int
    walks: int
    strikeouts: int
    hit_batters: int
    earned_run_average: float | None
    whip: float | None
    strikeouts_per_9: float | None
    walks_per_9: float | None
    strikeout_walk_ratio: float | None
    k_minus_bb_pct: float | None
    qualified_for_rate_rankings: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RankingRow:
    rank: int
    metric: str
    value: float | int
    player_id: str
    school_id: str
    school_name: str
    qualified: bool
    stat: dict

    def to_dict(self) -> dict:
        return asdict(self)


class PlayerStatsReadModel:
    RATE_BATTER_METRICS = {
        "batting_average",
        "on_base_percentage",
        "slugging_percentage",
        "ops",
    }
    RATE_PITCHER_METRICS = {
        "earned_run_average",
        "whip",
        "strikeouts_per_9",
        "walks_per_9",
        "strikeout_walk_ratio",
        "k_minus_bb_pct",
    }

    def __init__(
        self,
        repository: BrowseRepository,
        *,
        config_path: str | Path = "config/stats/player_rankings_v1.json",
    ):
        self.repository = repository
        self.config_path = Path(config_path)
        self.config = self._load_and_validate_config(self.config_path)
        self.precision = int(self.config["rate_precision"])

    @staticmethod
    def _load_and_validate_config(path: Path) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("config_id") != "player_rankings_v1":
            raise ValueError("player stats config_id must be player_rankings_v1")
        revision = payload.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("player stats revision must be positive integer")
        if payload.get("status") not in {
            "design_default_not_tuned",
            "tuned",
        }:
            raise ValueError("player stats status invalid")
        precision = payload.get("rate_precision")
        if not isinstance(precision, int) or isinstance(precision, bool):
            raise ValueError("rate_precision must be integer")
        if not 0 <= precision <= 6:
            raise ValueError("rate_precision must be 0..6")

        batter = payload.get("batter_qualification")
        pitcher = payload.get("pitcher_qualification")
        if not isinstance(batter, dict) or not isinstance(pitcher, dict):
            raise ValueError("qualification blocks required")
        for block, per_game_key in (
            (batter, "plate_appearances_per_team_game"),
            (pitcher, "outs_recorded_per_team_game"),
        ):
            minimum_games = block.get("minimum_team_games")
            if (
                not isinstance(minimum_games, int)
                or isinstance(minimum_games, bool)
                or minimum_games < 1
            ):
                raise ValueError("minimum_team_games must be >= 1")
            value = block.get(per_game_key)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or float(value) < 0
            ):
                raise ValueError(f"{per_game_key} must be >= 0")

        batter_metrics = {
            "batting_average",
            "on_base_percentage",
            "slugging_percentage",
            "ops",
            "hits",
            "home_runs",
            "rbi",
            "runs",
            "walks",
            "stolen_bases",
        }
        pitcher_metrics = {
            "earned_run_average",
            "whip",
            "strikeouts",
            "strikeouts_per_9",
            "walks_per_9",
            "strikeout_walk_ratio",
            "k_minus_bb_pct",
        }
        if set(payload.get("batter_rankings", {})) != batter_metrics:
            raise ValueError("batter ranking metric set mismatch")
        if set(payload.get("pitcher_rankings", {})) != pitcher_metrics:
            raise ValueError("pitcher ranking metric set mismatch")
        for mapping_name in ("batter_rankings", "pitcher_rankings"):
            for metric, direction in payload[mapping_name].items():
                if direction not in {"asc", "desc"}:
                    raise ValueError(
                        f"{mapping_name}.{metric}: direction must be asc/desc"
                    )

        rules = payload.get("rules")
        if not isinstance(rules, dict):
            raise ValueError("rules required")
        for key in (
            "rate_stats_are_derived",
            "game_stats_counts_are_source_of_truth",
            "ranking_qualification_is_game_design_not_official_rule",
            "competition_filter_optional",
            "school_filter_optional",
        ):
            if rules.get(key) is not True:
                raise ValueError(f"rules.{key} must be true")
        return payload

    def _round(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(value, self.precision)

    @staticmethod
    def _safe_div(
        numerator: float,
        denominator: float,
    ) -> float | None:
        if denominator == 0:
            return None
        return numerator / denominator

    @staticmethod
    def innings_display(outs_recorded: int) -> str:
        if outs_recorded < 0:
            raise ValueError("outs_recorded must be non-negative")
        innings, remainder = divmod(outs_recorded, 3)
        return (
            str(innings)
            if remainder == 0
            else f"{innings} {remainder}/3"
        )

    def _batter_qualified(
        self,
        *,
        team_games: int,
        plate_appearances: int,
    ) -> bool:
        settings = self.config["batter_qualification"]
        if team_games < int(settings["minimum_team_games"]):
            return False
        required = math.ceil(
            team_games
            * float(settings["plate_appearances_per_team_game"])
        )
        return plate_appearances >= required

    def _pitcher_qualified(
        self,
        *,
        team_games: int,
        outs_recorded: int,
    ) -> bool:
        settings = self.config["pitcher_qualification"]
        if team_games < int(settings["minimum_team_games"]):
            return False
        required = math.ceil(
            team_games
            * float(settings["outs_recorded_per_team_game"])
        )
        return outs_recorded >= required

    def batter_aggregates(
        self,
        year: int,
        *,
        competition_id: str = "",
        school_id: str = "",
        player_id: str = "",
    ) -> list[BatterAggregate]:
        rows = self.repository.aggregate_batter_counts(
            year,
            competition_id=competition_id,
            school_id=school_id,
            player_id=player_id,
        )
        team_games = self.repository.team_game_counts(
            year,
            competition_id=competition_id,
            school_id=school_id,
        )
        out: list[BatterAggregate] = []
        for row in rows:
            ab = int(row["at_bats"])
            h = int(row["hits"])
            walks = int(row["walks"])
            hbp = int(row["hit_by_pitch"])
            sf = int(row["sacrifice_flies"])
            singles = int(row["singles"])
            doubles = int(row["doubles"])
            triples = int(row["triples"])
            home_runs = int(row["home_runs"])
            total_bases = (
                singles
                + doubles * 2
                + triples * 3
                + home_runs * 4
            )
            avg = self._safe_div(h, ab)
            obp = self._safe_div(
                h + walks + hbp,
                ab + walks + hbp + sf,
            )
            slg = self._safe_div(total_bases, ab)
            ops = (
                None
                if obp is None or slg is None
                else obp + slg
            )
            iso = (
                None
                if avg is None or slg is None
                else slg - avg
            )
            sid = str(row["school_id"])
            tg = int(team_games.get(sid, 0))
            out.append(BatterAggregate(
                player_id=str(row["player_id"]),
                school_id=sid,
                school_name=str(row["school_name"]),
                games=int(row["games"]),
                team_games=tg,
                plate_appearances=int(row["plate_appearances"]),
                at_bats=ab,
                runs=int(row["runs"]),
                hits=h,
                singles=singles,
                doubles=doubles,
                triples=triples,
                home_runs=home_runs,
                rbi=int(row["rbi"]),
                walks=walks,
                strikeouts=int(row["strikeouts"]),
                hit_by_pitch=hbp,
                sacrifice_flies=sf,
                sacrifice_bunts=int(row["sacrifice_bunts"]),
                stolen_bases=int(row["stolen_bases"]),
                caught_stealing=int(row["caught_stealing"]),
                total_bases=total_bases,
                batting_average=self._round(avg),
                on_base_percentage=self._round(obp),
                slugging_percentage=self._round(slg),
                ops=self._round(ops),
                isolated_power=self._round(iso),
                qualified_for_rate_rankings=self._batter_qualified(
                    team_games=tg,
                    plate_appearances=int(row["plate_appearances"]),
                ),
            ))
        return out

    def pitcher_aggregates(
        self,
        year: int,
        *,
        competition_id: str = "",
        school_id: str = "",
        player_id: str = "",
    ) -> list[PitcherAggregate]:
        rows = self.repository.aggregate_pitcher_counts(
            year,
            competition_id=competition_id,
            school_id=school_id,
            player_id=player_id,
        )
        team_games = self.repository.team_game_counts(
            year,
            competition_id=competition_id,
            school_id=school_id,
        )
        out: list[PitcherAggregate] = []
        for row in rows:
            outs = int(row["outs_recorded"])
            bf = int(row["batters_faced"])
            er = int(row["earned_runs"])
            hits = int(row["hits_allowed"])
            walks = int(row["walks"])
            strikeouts = int(row["strikeouts"])
            era = self._safe_div(er * 27.0, outs)
            whip = self._safe_div((hits + walks) * 3.0, outs)
            k9 = self._safe_div(strikeouts * 27.0, outs)
            bb9 = self._safe_div(walks * 27.0, outs)
            kbb = self._safe_div(strikeouts, walks)
            k_minus_bb_rate = self._safe_div(
                strikeouts - walks,
                bf,
            )
            k_minus_bb = (
                None
                if k_minus_bb_rate is None
                else k_minus_bb_rate * 100.0
            )
            sid = str(row["school_id"])
            tg = int(team_games.get(sid, 0))
            out.append(PitcherAggregate(
                player_id=str(row["player_id"]),
                school_id=sid,
                school_name=str(row["school_name"]),
                games=int(row["games"]),
                team_games=tg,
                outs_recorded=outs,
                innings_pitched_display=self.innings_display(outs),
                batters_faced=bf,
                runs_allowed=int(row["runs_allowed"]),
                earned_runs=er,
                hits_allowed=hits,
                home_runs_allowed=int(row["home_runs_allowed"]),
                walks=walks,
                strikeouts=strikeouts,
                hit_batters=int(row["hit_batters"]),
                earned_run_average=self._round(era),
                whip=self._round(whip),
                strikeouts_per_9=self._round(k9),
                walks_per_9=self._round(bb9),
                strikeout_walk_ratio=self._round(kbb),
                k_minus_bb_pct=self._round(k_minus_bb),
                qualified_for_rate_rankings=self._pitcher_qualified(
                    team_games=tg,
                    outs_recorded=outs,
                ),
            ))
        return out

    @staticmethod
    def _rank_rows(
        rows: Iterable[BatterAggregate | PitcherAggregate],
        *,
        metric: str,
        direction: str,
        rate_metrics: set[str],
        limit: int,
    ) -> list[RankingRow]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        prepared = []
        for row in rows:
            if not hasattr(row, metric):
                raise ValueError(f"unknown ranking metric: {metric}")
            value = getattr(row, metric)
            qualified = bool(
                getattr(row, "qualified_for_rate_rankings")
            )
            if metric in rate_metrics and not qualified:
                continue
            if value is None:
                continue
            prepared.append((row, value, qualified))

        if direction == "desc":
            prepared.sort(
                key=lambda item: (
                    -float(item[1]),
                    item[0].player_id,
                )
            )
        else:
            prepared.sort(
                key=lambda item: (
                    float(item[1]),
                    item[0].player_id,
                )
            )

        ranked: list[RankingRow] = []
        previous_value = None
        previous_rank = 0
        for index, (row, value, qualified) in enumerate(
            prepared[:limit],
            start=1,
        ):
            if previous_value is None or value != previous_value:
                previous_rank = index
                previous_value = value
            ranked.append(RankingRow(
                rank=previous_rank,
                metric=metric,
                value=value,
                player_id=row.player_id,
                school_id=row.school_id,
                school_name=row.school_name,
                qualified=qualified,
                stat=row.to_dict(),
            ))
        return ranked

    def batter_rankings(
        self,
        year: int,
        metric: str,
        *,
        competition_id: str = "",
        school_id: str = "",
        limit: int = 50,
    ) -> list[RankingRow]:
        directions = self.config["batter_rankings"]
        if metric not in directions:
            raise ValueError(f"unsupported batter ranking metric: {metric}")
        return self._rank_rows(
            self.batter_aggregates(
                year,
                competition_id=competition_id,
                school_id=school_id,
            ),
            metric=metric,
            direction=directions[metric],
            rate_metrics=self.RATE_BATTER_METRICS,
            limit=limit,
        )

    def pitcher_rankings(
        self,
        year: int,
        metric: str,
        *,
        competition_id: str = "",
        school_id: str = "",
        limit: int = 50,
    ) -> list[RankingRow]:
        directions = self.config["pitcher_rankings"]
        if metric not in directions:
            raise ValueError(f"unsupported pitcher ranking metric: {metric}")
        return self._rank_rows(
            self.pitcher_aggregates(
                year,
                competition_id=competition_id,
                school_id=school_id,
            ),
            metric=metric,
            direction=directions[metric],
            rate_metrics=self.RATE_PITCHER_METRICS,
            limit=limit,
        )

    def player_summary(
        self,
        year: int,
        player_id: str,
        *,
        competition_id: str = "",
    ) -> dict:
        batters = self.batter_aggregates(
            year,
            competition_id=competition_id,
            player_id=player_id,
        )
        pitchers = self.pitcher_aggregates(
            year,
            competition_id=competition_id,
            player_id=player_id,
        )
        return {
            "year": year,
            "competition_id": competition_id,
            "player_id": player_id,
            "batter": batters[0].to_dict() if batters else None,
            "pitcher": pitchers[0].to_dict() if pitchers else None,
        }
