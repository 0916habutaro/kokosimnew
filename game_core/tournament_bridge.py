from __future__ import annotations

import json
from pathlib import Path
import re
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from typing import Callable

from phase2_engine.models import MatchResolution
from phase2_engine.randomness import rng_for
from phase2_engine.repository import DataRepository

from .match_contract import MatchSimulationInput, TeamMatchInput, validated_match_history
from .coaches import CoachTactics
from .highlights import game_highlights
from .match_simulator import GameRules, MatchSimulator
from .membership import CompetitionMembers
from .players import PlayerRosterGenerator, SchoolRoster, validate_school_roster
from .school_intake import SchoolAwarePlayerAbilityGenerator
from .team_strength import TeamStrengthGenerator


class AbilityMatchResolver:
    """Bridge Phase 2 tournament matches to the Stage 13 ability model.

    Phase 2 remains responsible for tournament structure and progression. This resolver
    owns each non-bye game's score/winner by constructing Stage 13 team inputs and
    delegating the game itself to MatchSimulator.
    """

    def __init__(
        self,
        repo: DataRepository,
        *,
        ability_config_dir: str | Path = "config/abilities",
        match_config_dir: str | Path = "config/match",
        team_generation_seed: int | None = None,
        roster_provider: Callable[[int, str], SchoolRoster | None] | None = None,
        member_provider: Callable[[str, str], CompetitionMembers] | None = None,
    ):
        self.repo = repo
        self.roster_generator = PlayerRosterGenerator()
        # Explicit opt-in. Prevent future-year seasons from silently
        # creating entirely new identities for existing school members.
        self.roster_provider = roster_provider
        # 大会ごとの出場メンバー（大会開始時点の部員）。指定すると名簿より優先する。
        self.member_provider = member_provider
        # 指定すると、試合の記録（スコア・個人成績）は大会の進行には持たせず
        # ここに「competition_id:match_id」で置く。履歴に保存したら消す
        # （全国の試合でセーブを小さく保つ。1打席ごとの記録は残さない）。
        self.detail_sink: dict[str, dict] | None = None
        self.ability_generator = SchoolAwarePlayerAbilityGenerator(
            ability_config_dir
        )
        self.team_generator = TeamStrengthGenerator(ability_config_dir)
        self.simulator = MatchSimulator(match_config_dir, team_generator=self.team_generator)
        # 試合の規定（タイブレーク・コールド）。ファイルがなければ使わない
        rules_path = Path(match_config_dir) / "game_rules_v1.json"
        self.game_rules = (
            json.loads(rules_path.read_text(encoding="utf-8"))
            if rules_path.is_file() else None
        )
        # 進行中の年度の状態（本大会の何回戦か・あと何回戦かを見る）。
        # live_members.PlayerSeason.attach で入れる
        self.season_state = None
        # 球数の記録の古い日を消した（記録, 日）。1日に1回だけ消す
        self._pitch_log_pruned = None
        self._fixed_team_generation_seed = team_generation_seed
        self._season_reference_year: int | None = None
        self._season_team_generation_seed: int | None = None
        self._team_cache: dict[
            tuple[int, int, str],
            TeamMatchInput,
        ] = {}
        self._roster_cache: dict[
            tuple[int, int, str],
            SchoolRoster,
        ] = {}
        # Explicitly prepared initial sources outlive the performance caches.
        # Default resolvers never create this persistence authority implicitly.
        self._initial_roster_source: dict[str, SchoolRoster] = {}
        self._competition_teams: dict[
            tuple,
            TeamMatchInput,
        ] = {}
        self._abilities: dict[tuple, object] = {}
        self._source_version = None
        self._initial_roster_scope = None

    def prepare_initial_rosters(self, *, reference_year: int,
                                generation_seed: int, school_ids: tuple[str, ...]) -> None:
        """Pin deterministic bootstrap inputs BEFORE any game/replay consumes them.

        Historical providers and custom generators are separate contracts. This
        narrow source is only the reviewed built-in initial generator with a
        fixed season seed; it is not a snapshot of whichever cache happens to exist.
        """
        scope = (reference_year, generation_seed, school_ids)
        if (type(reference_year) is not int or reference_year < 1
                or type(generation_seed) is not int
                or self.roster_provider is not None
                or type(self.roster_generator) is not PlayerRosterGenerator
                or self._fixed_team_generation_seed != generation_seed
                or len(school_ids) != len(set(school_ids)) or not school_ids):
            raise ValueError("unsupported initial roster source")
        if self._initial_roster_scope is not None:
            if self._initial_roster_scope != scope:
                raise ValueError("initial roster source scope changed")
            self.initial_roster_snapshot(reference_year=reference_year,
                generation_seed=generation_seed, school_ids=school_ids)
            return
        if self._team_cache or self._roster_cache:
            raise ValueError("initial roster source must precede match inputs")
        sources = {sid: self.roster_generator.generate_for_school_id(
            self.repo, sid, reference_year, generation_seed) for sid in school_ids}
        self._initial_roster_source = deepcopy(sources)
        self._initial_roster_scope = scope

    def initial_roster_snapshot(self, *, reference_year: int,
                               generation_seed: int, school_ids: tuple[str, ...]) -> tuple[SchoolRoster, ...]:
        """Return detached, provenance-checked inputs, never generate missing sources."""
        if (self._initial_roster_scope != (reference_year, generation_seed, school_ids)
                or set(self._initial_roster_source) != set(school_ids)
                or self.roster_provider is not None
                or type(self.roster_generator) is not PlayerRosterGenerator
                or self._fixed_team_generation_seed != generation_seed):
            raise ValueError("missing or changed initial roster source")
        for sid in school_ids:
            roster = self._initial_roster_source[sid]
            expected = self.roster_generator.generate_for_school_id(
                self.repo, sid, reference_year, generation_seed)
            if roster.to_dict() != expected.to_dict():
                raise ValueError("initial roster source provenance mismatch")
            key = (reference_year, generation_seed, sid)
            if key in self._roster_cache and self._roster_cache[key].to_dict() != roster.to_dict():
                raise ValueError("cached roster disagrees with initial source")
            if key in self._team_cache:
                expected_abilities = tuple(self.ability_generator.iter_roster(
                    roster.players, reference_year, generation_seed))
                expected_team = TeamMatchInput(school_id=sid,
                    team_strength=self.team_generator.generate(expected_abilities),
                    player_abilities=expected_abilities)
                if self._team_cache[key] != expected_team:
                    raise ValueError("cached match input disagrees with initial source")
        return tuple(deepcopy(self._initial_roster_source[sid]) for sid in school_ids)

    def clear_cache(self) -> None:
        self._team_cache.clear()
        self._roster_cache.clear()
        self._competition_teams.clear()
        self._abilities.clear()

    def begin_season(
        self,
        reference_year: int,
        season_generation_seed: int,
    ) -> None:
        if reference_year < 1:
            raise ValueError("reference_year must be positive")
        if (
            not isinstance(season_generation_seed, int)
            or isinstance(season_generation_seed, bool)
        ):
            raise ValueError("season_generation_seed must be integer")
        self.clear_cache()
        self._season_reference_year = reference_year
        self._season_team_generation_seed = season_generation_seed

    def _effective_team_generation_seed(
        self,
        *,
        reference_year: int,
        match_generation_seed: int,
    ) -> int:
        if self._fixed_team_generation_seed is not None:
            return self._fixed_team_generation_seed
        if (
            self._season_reference_year == reference_year
            and self._season_team_generation_seed is not None
        ):
            return self._season_team_generation_seed
        return match_generation_seed

    def player_master_records(self) -> dict[str, dict]:
        records: dict[str, dict] = {}
        for (reference_year, generation_seed, school_id), roster in sorted(
            self._roster_cache.items()
        ):
            for player in roster.players:
                row = {
                    "reference_year": reference_year,
                    **player.to_dict(),
                    "school_name": roster.school_name,
                }
                existing = records.get(player.player_id)
                if existing is not None and existing != row:
                    raise ValueError(
                        f"{player.player_id}: conflicting player master rows"
                    )
                records[player.player_id] = row
        return records

    @property
    def cache_size(self) -> int:
        return len(self._team_cache)

    def team_input(
        self,
        *,
        school_id: str,
        reference_year: int,
        generation_seed: int,
        competition_id: str = "",
    ) -> TeamMatchInput:
        team_seed = self._effective_team_generation_seed(
            reference_year=reference_year,
            match_generation_seed=generation_seed,
        )
        if self.member_provider is not None:
            return self._competition_team_input(
                competition_id, school_id, reference_year, team_seed
            )
        key = (reference_year, team_seed, school_id)
        cached = self._team_cache.get(key)
        if cached is not None:
            return cached

        if self._initial_roster_scope is not None:
            year, seed, schools = self._initial_roster_scope
            if (reference_year, team_seed) != (year, seed) or school_id not in schools:
                raise ValueError("match outside prepared initial roster scope")
            roster = deepcopy(self._initial_roster_source[school_id])
        elif self.roster_provider is None:
            roster = self.roster_generator.generate_for_school_id(
                self.repo, school_id, reference_year, team_seed,
            )
        else:
            roster = self.roster_provider(reference_year, school_id)
            if roster is None:
                raise ValueError(
                    f"missing historical roster: {school_id}/{reference_year}"
                )
            validate_school_roster(roster)
            if (roster.school_id != school_id
                    or roster.reference_year != reference_year):
                raise ValueError("historical roster year/school mismatch")
        self._roster_cache[key] = roster
        abilities = tuple(
            self.ability_generator.iter_roster(
                roster.players,
                reference_year,
                team_seed,
            )
        )
        team = TeamMatchInput(
            school_id=school_id,
            team_strength=self.team_generator.generate(abilities),
            player_abilities=abilities,
        )
        self._team_cache[key] = team
        return team

    def _competition_team_input(
        self,
        competition_id: str,
        school_id: str,
        reference_year: int,
        team_seed: int,
    ) -> TeamMatchInput:
        # 成長で能力が変わったら作り直す（試合はその日の能力で行う）
        version = getattr(self.ability_generator.source, "version", None)
        if version != self._source_version:
            self._competition_teams.clear()
            self._abilities.clear()
            self._source_version = version
        members = self.member_provider(competition_id, school_id).players
        registered_ids = frozenset(p.player_id for p in members)
        # 怪我で休んでいる選手は出ない（9人に足りなければ出る）。復帰直後の選手は
        # 能力が少し下がる。その日の状態ごとにつくり直す
        source = self.ability_generator.source
        day = self._match_day()
        tactics = self._coach_tactics(school_id, day)
        condition = ()
        if source is not None and day is not None and hasattr(source, "condition"):
            states = {p.player_id: source.condition(p, day) for p in members}
            healthy = tuple(p for p in members if not states[p.player_id][0])
            if len(healthy) >= 9:
                members = healthy
            condition = tuple(sorted(
                (pid, state) for pid, state in states.items() if state != (False, 0)
            ))
        key = (competition_id, team_seed, school_id, condition, tactics.selection_grade_bias)
        cached = self._competition_teams.get(key)
        if cached is not None:
            return cached
        # 能力はその大会の年度のもの（3月に始まる大会も、大会の年度で揃える）。
        # 同じ選手が年度内のいくつもの大会に出るので、一度つくった能力を使い回す。
        abilities = tuple(
            self._player_ability(player, reference_year, team_seed)
            for player in members
        )
        team = TeamMatchInput(
            school_id=school_id,
            team_strength=self.team_generator.generate(
                abilities, selection_grade_bias=tactics.selection_grade_bias),
            player_abilities=abilities,
            registered_player_ids=registered_ids,
        )
        self._competition_teams[key] = team
        return team

    def _coach_tactics(self, school_id, day):
        source = self.ability_generator.source
        coaches = getattr(source, "coaches", None)
        return (coaches.tactics_for(school_id, day)
                if coaches is not None and day is not None else CoachTactics())

    def _player_ability(self, player, reference_year: int, team_seed: int):
        source = self.ability_generator.source
        day = self._match_day()
        step = (
            source.condition(player, day)[1]
            if source is not None and day is not None and hasattr(source, "condition")
            else 0
        )
        key = (player, reference_year, team_seed, step)
        snapshot = self._abilities.get(key)
        if snapshot is None:
            snapshot = self.ability_generator.generate(
                player, reference_year, team_seed
            )
            self._abilities[key] = snapshot
        return snapshot

    def _record_games(self, competition_id: str, result) -> None:
        """公式戦に出た選手を名簿に記録する（毎月の成長で少し伸びる）。"""
        source = self.ability_generator.source
        if source is None or self.member_provider is None:
            return
        batting_or_pitching = {
            s.player_id for s in result.batter_stats if s.plate_appearances > 0
        } | {
            s.player_id for s in result.pitcher_stats if s.batters_faced > 0
        }
        played = batting_or_pitching | {
            player_id for team in result.team_participation for player_id in team.fielding_player_ids
        }
        day = self._match_day()
        pitched = {s.player_id: s.pitches for s in result.pitcher_stats if s.batters_faced > 0}
        log = getattr(self.season_state, "pitch_log", None) or {}
        appearances = []
        fielding_only_appearances = []
        for school_id in (result.team1_school_id, result.team2_school_id):
            members = self.member_provider(competition_id, school_id).players
            # 和集合とID単位の重複排除で、1試合につき最大1回。名簿の順序は維持する。
            appeared = list({p.player_id: p for p in members if p.player_id in played}.values())
            source.record_games(school_id, appeared)
            for player in appeared:
                if player.player_id not in batting_or_pitching:
                    fielding_only_appearances.append((player, 0, 0, 0))
                    continue
                pitches = pitched.get(player.player_id, 0)
                load7 = consecutive = 0
                if pitches and day is not None:
                    days = log.get(player.player_id, {})
                    first = (day - timedelta(days=6)).isoformat()
                    load7 = sum(n for on, n in days.items() if first <= on <= day.isoformat())
                    while (day - timedelta(days=consecutive + 1)).isoformat() in days:
                        consecutive += 1
                appearances.append((player, pitches, load7, consecutive))
        if day is not None and hasattr(source, "after_game"):
            # 両校の従来対象を先に抽選し、その後で守備のみの選手を抽選する。
            # 試合ごとに独立した乱数なので、追加分は従来対象の怪我結果を変えない。
            source.after_game(
                appearances + fielding_only_appearances, day=day,
                rng=rng_for(
                    getattr(source, "career_seed", 0),
                    f"injuries_v1:match:{competition_id}:{result.match_id}",
                ),
            )

    def rules_for(self, competition_id: str, match_id: str) -> GameRules:
        """その試合の規定。タイブレークはすべての試合。コールドは都道府県大会・
        地区大会で、本大会の決勝（神奈川は準決勝から）を除く。"""
        config = self.game_rules
        if not config:
            return GameRules()
        tiebreak = config.get("tiebreak") or {}
        mercy_rule = config.get("mercy_rule") or {}
        competition = self.repo.competitions.get(competition_id, {})
        mercy: tuple[tuple[int, int], ...] = ()
        if competition.get("competition_level") in mercy_rule.get("levels", ()):
            exclude = int(mercy_rule.get("exclude_rounds_from_end", 1))
            if competition.get("competition_level") == "local":
                exclude = int(
                    (mercy_rule.get("prefecture_exclude_rounds_from_end") or {}).get(
                        competition.get("prefecture_code", ""), exclude,
                    )
                )
            rounds_left = self._rounds_left(competition_id, match_id)
            if rounds_left is None or rounds_left >= exclude:
                mercy = tuple(
                    (int(inning), int(margin))
                    for inning, margin in mercy_rule.get("thresholds", ())
                )
        return GameRules(
            tiebreak_start_inning=(
                int(tiebreak["start_inning"]) if tiebreak.get("start_inning") else None
            ),
            mercy=mercy,
        )

    def _match_day(self):
        """試合の日（進行中の年度の今日）。状態につないでいなければ None。"""
        return getattr(self.season_state, "current_date", None)

    def _pitch_rule(self) -> tuple[int, int] | None:
        rule = (self.game_rules or {}).get("pitch_limit")
        if not rule:
            return None
        return int(rule["pitches"]), int(rule["days"])

    def _pitch_allowances(self, teams, day) -> dict[str, int] | None:
        """選手 → この試合であと何球投げられるか（その日を含む直近の日数で上限まで）。"""
        rule = self._pitch_rule()
        log = getattr(self.season_state, "pitch_log", None)
        if rule is None or day is None or log is None:
            return None
        limit, days = rule
        first = (day - timedelta(days=days - 1)).isoformat()
        last = day.isoformat()
        return {
            player.player_id: max(0, limit - sum(
                count for on, count in log.get(player.player_id, {}).items()
                if first <= on <= last
            ))
            for team in teams
            for player in team.player_abilities
        }

    def _record_pitches(self, result, day) -> None:
        """投げた球数を日ごとに残す。上限の日数より前の記録は消す。"""
        rule = self._pitch_rule()
        log = getattr(self.season_state, "pitch_log", None)
        if rule is None or day is None or log is None:
            return
        first = (day - timedelta(days=rule[1] - 1)).isoformat()
        if self._pitch_log_pruned != (id(log), day):
            for player_id in list(log):
                kept = {on: n for on, n in log[player_id].items() if on >= first}
                if kept:
                    log[player_id] = kept
                else:
                    del log[player_id]
            self._pitch_log_pruned = (id(log), day)
        for stat in result.pitcher_stats:
            if stat.pitches:
                days = log.setdefault(stat.player_id, {})
                days[day.isoformat()] = days.get(day.isoformat(), 0) + stat.pitches

    def _rounds_left(self, competition_id: str, match_id: str) -> int | None:
        """本大会の試合なら、決勝まであと何回戦か（決勝は0）。分からなければ None。"""
        found = re.search(r"-MAIN-R(\d+)-", match_id)
        state = self.season_state
        if found is None or state is None:
            return None
        scheduled = state.competitions.get(competition_id)
        runtime = getattr(scheduled, "runtime", None)
        main = getattr(runtime, "main_runtime", runtime)
        total = getattr(main, "total_rounds", None)
        if not total:
            return None
        return int(total) - int(found.group(1))

    def __call__(
        self,
        *,
        match_id: str,
        competition_id: str,
        reference_year: int,
        generation_seed: int,
        team1: str,
        team2: str,
    ) -> MatchResolution:
        if not team1 or not team2:
            raise ValueError(
                "ability MAIN resolver requires two non-bye teams"
            )
        if team1 == team2:
            raise ValueError(
                "ability MAIN resolver requires two distinct teams"
            )

        team1_input = self.team_input(
            school_id=team1,
            reference_year=reference_year,
            generation_seed=generation_seed,
            competition_id=competition_id,
        )
        team2_input = self.team_input(
            school_id=team2,
            reference_year=reference_year,
            generation_seed=generation_seed,
            competition_id=competition_id,
        )
        team_generation_seed = team1_input.team_strength.generation_seed
        if (
            team2_input.team_strength.generation_seed
            != team_generation_seed
        ):
            raise ValueError(
                "ability resolver team generation seed mismatch"
            )
        match_input = MatchSimulationInput(
            match_id=match_id,
            competition_id=competition_id,
            reference_year=reference_year,
            generation_seed=generation_seed,
            team1=team1_input,
            team2=team2_input,
            team_generation_seed=team_generation_seed,
        )
        day = self._match_day()
        tactics = {sid: self._coach_tactics(sid, day) for sid in (team1, team2)}
        result = self.simulator.simulate(
            match_input,
            rules=self.rules_for(competition_id, match_id),
            pitch_allowances=self._pitch_allowances(
                (team1_input, team2_input), day,
            ),
            **({"tactics": tactics} if any(t != CoachTactics() for t in tactics.values()) else {}),
        )
        dh_detail = None
        if (any(r.starting_designated_hitter_id is not None for r in result.team_participation)
                or any(t.team_strength.starting_lineup.designated_hitter_id is not None
                       for t in (team1_input, team2_input))):
            dh_detail = validated_match_history(result, match_input)
        self._record_pitches(result, day)
        self._record_games(competition_id, result)
        highlights = game_highlights(result.events)
        if self.detail_sink is not None:
            # 確定した開始配置・交代履歴・守備出場IDも結果からそのまま履歴へ渡す。
            full = dh_detail if dh_detail is not None else replace(result, events=()).to_dict()
            full["team_generation_seed"] = team_generation_seed
            full["highlights"] = highlights
            self.detail_sink[f"{competition_id}:{match_id}"] = full
            detail = {"team_generation_seed": team_generation_seed}
        else:
            detail = dh_detail if dh_detail is not None else result.to_dict()
            detail["team_generation_seed"] = team_generation_seed
            detail["highlights"] = highlights
        return MatchResolution(
            winner_id=result.winner_id,
            loser_id=result.loser_id,
            team1_score=result.team1_score,
            team2_score=result.team2_score,
            score_source=result.score_source,
            detail=detail,
        )


# Backward-compatible Stage 13C-3 name.
AbilityMainMatchResolver = AbilityMatchResolver
