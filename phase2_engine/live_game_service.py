from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable
from contextlib import closing
import hashlib
import json
import sqlite3

from .career_option_a_storage_profile import _read_only

from .historical_match_archive import HistoricalMatchArchive, _history_payload
from .school_year import in_school_year
from .year_transition import require_year_end, year_end_readiness
from .live_season_planner import (
    LiveSeasonGraphPlanner,
)
from .live_season_save import (
    DEFAULT_RESOLVER_CONTRACT,
    plan_fingerprint,
)
from .repository import DataRepository
from .save_slots import (
    SAVE_KIND_AUTOSAVE,
    SAVE_KIND_MANUAL,
    SaveSlotManager,
)


@dataclass
class LiveGameSession:
    slot_id: str
    plan: object
    state: object
    resolver_contract: str

    def summary(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "resolver_contract": (
                self.resolver_contract
            ),
            "plan": self.plan.summary(),
            "runtime": self.state.summary(),
        }


class InitialCareerPersistence:
    """Explicit opt-in for the reviewed 2026 eight-school MAIN pilot only.

    The plan and engine are bound before runtime creation/replay. Independent
    JSON/DB commits are retryable, not one transaction. No migration, feeder or
    future-year authority is granted by this contract.
    """

    RESOLVER_CONTRACT = "initial_ability_career_v1"
    COMPETITION_ID = "CMP000029"
    SCHOOL_IDS = tuple(f"SCH{i:06d}" for i in range(1862, 1870))

    def __init__(self, plan, resolver):
        from game_core.tournament_bridge import AbilityMatchResolver
        if (type(resolver) is not AbilityMatchResolver
                or plan.repo is not resolver.repo or plan.year != 2026
                or set(plan.entries) != {self.COMPETITION_ID}
                or set(plan.annual_templates) != {self.COMPETITION_ID}
                or plan.topological_order != [self.COMPETITION_ID]
                or plan.dependency_edges or plan.external_bootstrap_resolutions
                or tuple(plan.annual_templates[self.COMPETITION_ID].entrant_school_ids)
                != self.SCHOOL_IDS):
            raise ValueError("未対応の初年度保存条件です。8校単大会の出典を確認してください")
        self.resolver = resolver
        self.year, self.seed = plan.year, plan.rng_seed
        self.roster_seed = self.seed
        self.competition_school_ids = {self.COMPETITION_ID: self.SCHOOL_IDS}
        self.expected_match_count = 7
        self.fingerprint = plan_fingerprint(plan)

    def prepare(self, plan, engine, contract):
        from .engine import TournamentEngine
        if (contract != self.RESOLVER_CONTRACT
                or plan_fingerprint(plan) != self.fingerprint
                or plan.repo is not self.resolver.repo
                or type(engine) is not TournamentEngine
                or engine.repo is not self.resolver.repo
                or engine.main_match_resolver is not self.resolver
                or engine.pre_main_match_resolver is not self.resolver):
            raise ValueError("保存plan・engine・resolverの出典が一致しません")
        self.resolver.prepare_initial_rosters(reference_year=self.year,
            generation_seed=self.roster_seed, school_ids=self.SCHOOL_IDS)

    def _snapshot(self, session):
        self.prepare(session.plan, session.state.engine, session.resolver_contract)
        if ((session.state.year, session.state.rng_seed) != (self.year, self.seed)
                or set(session.state.competitions) != {self.COMPETITION_ID}):
            raise ValueError("年度・対象大会が保存契約と一致しません")
        matches = session.state.competitions[self.COMPETITION_ID].matches.values()
        # Future rounds are added lazily; initial runtime contains four games.
        if not 0 < len(session.state.competitions[self.COMPETITION_ID].matches) <= 7 or any(
                m.stage_code != 'MAIN' for m in matches):
            raise ValueError("未対応の試合構造です。8校MAIN単大会を確認してください")
        return self.resolver.initial_roster_snapshot(reference_year=self.year,
            generation_seed=self.roster_seed, school_ids=self.SCHOOL_IDS)

    def validate(self, session, slot):
        """Preflight all sources and existing records before replacing JSON.

        Missing commits may be retried from a checkpoint of this contract.
        Divergent records and stale checkpoints fail closed, never overwrite.
        """
        from .career_roster_archive import _identity
        from .career_competition_outcomes import CareerCompetitionOutcomes, _main_result
        from game_core.match_contract import (
            BatterGameStats, PitcherGameStats, TeamGameStats,
            validate_batter_game_stats, validate_pitcher_game_stats,
            validate_team_game_stats,
        )
        rosters = self._snapshot(session)
        members = {p.player_id: p for r in rosters for p in r.players}
        if len(members) != 20 * len(self.SCHOOL_IDS):
            raise ValueError("選手IDの重複・ロスター欠落があります")
        normalized = {}
        for competition in session.state.competitions.values():
            for match in competition.matches.values():
                if match.status != "completed":
                    continue
                row = _history_payload(self.year, match.__dict__)
                detail = match.ability_detail or {}
                cid = row['competition_id']
                if (cid not in self.competition_school_ids
                        or row['stage_code'] != 'MAIN'
                        or detail.get('team_generation_seed') != self.roster_seed
                        or detail.get('generation_seed')
                        != session.plan.annual_templates[cid].rng_seed
                        or detail.get('winner_id') != row['winner_id']
                        or detail.get('loser_id') != row['loser_id']
                        or row['score_source'] != 'ability_model_v1'
                        or any(not row[k] for k in ('inning_scores', 'team_stats',
                                                   'batter_stats', 'pitcher_stats'))):
                    raise ValueError("完全Option Aの試合出典が欠落・不一致です")
                opponents = {row['team1_id'], row['team2_id']}
                if not opponents.issubset(set(self.competition_school_ids[cid])):
                    raise ValueError("対象外の所属校です")
                for key, model, validator in (
                    ('batter_stats', BatterGameStats, validate_batter_game_stats),
                    ('pitcher_stats', PitcherGameStats, validate_pitcher_game_stats),
                ):
                    seen = set()
                    for stats in row[key]:
                        player = members.get(stats.get('player_id'))
                        if (player is None or player.school_id != stats.get('school_id')
                                or player.school_id not in opponents
                                or player.player_id in seen):
                            raise ValueError("個人成績の選手ID・所属が一致しません")
                        if key == 'pitcher_stats' and player.primary_position != 'P':
                            raise ValueError("投手成績の選手出典が一致しません")
                        seen.add(player.player_id)
                        values = {k: v for k, v in stats.items() if k != 'singles'}
                        if set(values) != set(model.__dataclass_fields__):
                            raise ValueError("個人成績の項目が欠落しています")
                        decoded = model(**values)
                        validator(decoded)
                        if decoded.to_dict() != stats:
                            raise ValueError("個人成績の内容が一致しません")
                    if {s['school_id'] for s in row[key]} != opponents:
                        raise ValueError("片方の学校の個人成績が欠落しています")
                events = detail.get('events')
                if (not isinstance(events, list) or not events
                        or not {e['batter_id'] for e in events}.issubset(
                            {s['player_id'] for s in row['batter_stats']})
                        or not {e['pitcher_id'] for e in events}.issubset(
                            {s['player_id'] for s in row['pitcher_stats']})):
                    raise ValueError("実試合参加選手の個人成績が欠落しています")
                for stats in row['team_stats']:
                    validator_team = TeamGameStats(**stats)
                    validate_team_game_stats(validator_team)
                    sid = stats['school_id']
                    batters = [s for s in row['batter_stats'] if s['school_id'] == sid]
                    pitchers = [s for s in row['pitcher_stats'] if s['school_id'] != sid]
                    if (sum(s['runs'] for s in batters) != stats['runs']
                            or sum(s['hits'] for s in batters) != stats['hits']
                            or sum(s['runs_allowed'] for s in pitchers) != stats['runs']
                            or sum(s['hits_allowed'] for s in pitchers) != stats['hits']):
                        raise ValueError("個人成績とチーム成績が一致しません")
                if row['match_id'] in normalized:
                    raise ValueError("大会間で試合IDが衝突しています")
                normalized[row['match_id']] = row

        roster_path = slot / 'career_rosters.sqlite3'
        if roster_path.is_file():
            expected = {r.school_id: r.to_dict() for r in rosters}
            with closing(_read_only(roster_path)) as conn:
                for year, sid, raw, digest in conn.execute(
                    'SELECT year,school_id,payload_json,content_sha256 FROM career_school_rosters'
                ):
                    if (year != self.year or sid not in expected
                            or hashlib.sha256(raw.encode()).hexdigest() != digest
                            or json.loads(raw) != expected[sid]):
                        raise ValueError("既存ロスターと出典が衝突しています。上書きできません")
                identities = set()
                for pid, sid, entry, raw, digest in conn.execute(
                    'SELECT player_id,school_id,entry_year,identity_json,identity_sha256 '
                    'FROM career_player_identities'
                ):
                    player = members.get(pid)
                    if (player is None or (sid, entry) != (player.school_id, player.entry_year)
                            or raw != _identity(player)
                            or hashlib.sha256(raw.encode()).hexdigest() != digest):
                        raise ValueError("既存選手履歴と出典が衝突しています")
                    identities.add(pid)
                for sid, in conn.execute('SELECT school_id FROM career_school_rosters'):
                    if not {p.player_id for p in members.values() if p.school_id == sid}.issubset(identities):
                        raise ValueError("既存選手履歴が欠落しています")

        archive = HistoricalMatchArchive(slot / 'historical_matches.sqlite3')
        sealed = False
        if archive.db_path.is_file():
            with closing(_read_only(archive.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                identity = conn.execute('SELECT metadata_json FROM archive_identity WHERE id=1').fetchone()
                if identity is None or identity[0] != archive._identity(
                        self.year, self.seed, session.resolver_contract, self.fingerprint):
                    raise ValueError("既存試合履歴のplan・出典が一致しません")
                year = conn.execute('SELECT status FROM career_years WHERE year=?', (self.year,)).fetchone()
                sealed = year is not None and year[0] == 'sealed'
                stored = {}
                for record in conn.execute('SELECT * FROM historical_matches'):
                    raw, digest = record['payload_json'], record['record_sha256']
                    row = json.loads(raw)
                    if (hashlib.sha256(raw.encode()).hexdigest() != digest
                            or any(record[key] != row.get(key) for key in (
                                'year', 'competition_id', 'match_id', 'match_date', 'date_source',
                                'team1_id', 'team2_id', 'team1_score', 'team2_score', 'score_source'))
                            or row != normalized.get(row.get('match_id'))):
                        raise ValueError("保存元と試合履歴が一致しません。進行せず保存元を確認してください")
                    stored[row['match_id']] = row
                if sealed:
                    CareerCompetitionOutcomes._check_seal(conn, self.year)
                    if stored != normalized or len(normalized) != self.expected_match_count:
                        raise ValueError("封印済年度の完全なcheckpointが必要です")
        runs = session.state.completed_runs()
        if runs:
            if not set(runs).issubset(self.competition_school_ids):
                raise ValueError("対象外の確定大会です")
            for cid, run in runs.items():
                result, matches = _main_result(run)
                entrants = set(self.competition_school_ids[cid])
                if (result['year'] != self.year
                        or result['competition_id'] != cid
                        or run.rng_seed != session.plan.annual_templates[cid].rng_seed
                        or set(run.entrant_school_ids) != entrants
                        or set(result['main_entrant_school_ids']) != entrants
                        or {m.match_id for m in matches}
                        != {mid for mid, row in normalized.items() if row['competition_id'] == cid}):
                    raise ValueError("大会MAIN結果と試合保存出典が一致しません")
                for m in matches:
                    row = normalized[m.match_id]
                    if ((m.team1, m.team2, m.metadata.get('team1_score'), m.metadata.get('team2_score'), m.winner, m.loser)
                            != (row['team1_id'], row['team2_id'], row['team1_score'],
                                row['team2_score'], row['winner_id'], row['loser_id'])):
                        raise ValueError("大会MAIN結果とスコアが一致しません")
            if sealed and set(runs) != set(self.competition_school_ids):
                raise ValueError("封印済年度に未完了の大会があります")
        elif sealed:
            raise ValueError("封印済年度の確定大会結果がありません")
        return rosters, sealed

    def sync_rosters(self, rosters, slot):
        from .career_roster_archive import CareerRosterArchive
        archive = CareerRosterArchive(slot / 'career_rosters.sqlite3')
        return [archive.save_initial_roster(r) for r in rosters]

    def sync_outcomes(self, session, slot):
        from .career_competition_outcomes import CareerCompetitionOutcomes
        _, sealed = self.validate(session, slot)
        if not sealed or not session.state.completed_runs():
            raise ValueError("年度封印と確定MAIN結果を確認してから大会結果を保存してください")
        outcomes = CareerCompetitionOutcomes(slot / 'historical_matches.sqlite3')
        return [outcomes.record_completed(run) for run in session.state.completed_runs().values()]

    @classmethod
    def sealed_results(cls, slot):
        """Read the pilot's saved ranking with a native read-only connection."""
        from .career_competition_outcomes import CareerCompetitionOutcomes, _canonical, _sha
        with closing(_read_only(Path(slot) / 'historical_matches.sqlite3')) as conn:
            conn.row_factory = sqlite3.Row
            ledger = CareerCompetitionOutcomes._check_seal(conn, 2026)
            rows = conn.execute('SELECT payload_json,record_sha256 FROM historical_competition_outcomes '
                                'WHERE year=2026 AND competition_id=?', (cls.COMPETITION_ID,)).fetchall()
            if len(rows) != 1:
                raise ValueError("確定大会結果が不足しています。保存整合性を確認してください")
            raw, digest = rows[0]
            result = json.loads(raw)
            manifest = []
            for mid, payload, sha in conn.execute('SELECT match_id,payload_json,record_sha256 '
                    'FROM historical_matches WHERE year=2026 AND competition_id=? ORDER BY match_id',
                    (cls.COMPETITION_ID,)):
                if _sha(payload) != sha:
                    raise ValueError("大会順位の元試合が変更されています")
                manifest.append([mid, sha])
            ranking = result.get('ranked_school_ids', [])
            if (_sha(raw) != digest or result.get('year') != 2026
                    or result.get('competition_id') != cls.COMPETITION_ID
                    or result.get('status') != 'completed' or result.get('source') != 'game_result'
                    or len(ranking) != len(cls.SCHOOL_IDS) or set(ranking) != set(cls.SCHOOL_IDS)
                    or result.get('champion_school_id') != ranking[0]
                    or result.get('runner_up_school_id') != ranking[1]
                    or len(manifest) != len(cls.SCHOOL_IDS) - 1
                    or result.get('main_match_count') != len(cls.SCHOOL_IDS) - 1
                    or result.get('source_year_ledger_sha256') != ledger
                    or result.get('source_match_sha256') != _sha(_canonical(manifest))):
                raise ValueError("確定大会順位と封印台帳が一致しません")
            return result


class SharedSchoolYearPersistence(InitialCareerPersistence):
    """Opt-in authority for a labelled, self-generated two-MAIN fixture.

    This is not an entrant/qualification authority for the real competitions.
    Only the reviewed fixture fingerprint is accepted; no arbitrary plan, feeder,
    provider, same-day competition or future-year scope can be enabled here.
    The fixed roster recipe has a seed independent of the season/match seeds.
    """

    RESOLVER_CONTRACT = "shared_school_year_fixture_v1"
    SEASON_SEED = 2026101201
    ROSTER_SEED = 430101
    MAX_MAIN_MATCHES = 3
    COMPETITION_IDS = ("CMP000105", "CMP000041")
    SCHOOL_IDS = tuple(f"SCH{i:06d}" for i in range(196, 202))
    FIXTURE_ENTRANTS = (
        ("SCH000196", "SCH000197", "SCH000198", "SCH000199"),
        ("SCH000196", "SCH000197", "SCH000200", "SCH000201"),
    )

    @classmethod
    def verification_plan(cls, repo, data_dir):
        """Build only the declared fixture, never imply real cross-prefecture access."""
        from dataclasses import replace
        from .live_season_planner import LiveSeasonGraphPlan
        full = LiveSeasonGraphPlanner(repo, data_dir, cls.SEASON_SEED, year=2026).build_plan()
        for cid, strategy, status in zip(cls.COMPETITION_IDS,
                ("structural", "summer_area"),
                ("structure_pending_verification", "verified_structure")):
            entry = full.entries[cid]
            if (entry.dependency_family != "root" or entry.strategy != strategy
                    or entry.has_pre_main or entry.dependency_source_competition_ids
                    or entry.external_bootstrap_rule_ids
                    or repo.competitions[cid]["data_status"] != status
                    or {s["stage_code"] for s in repo.stages(cid)} != {"MAIN"}):
                raise ValueError("2大会の独立MAIN出典が変更されています")
        if (tuple(full.annual_templates[cls.COMPETITION_IDS[0]].entrant_school_ids[:4])
                != cls.FIXTURE_ENTRANTS[0]
                or tuple(full.annual_templates[cls.COMPETITION_IDS[1]].entrant_school_ids[:6])
                != cls.SCHOOL_IDS):
            raise ValueError("自己生成fixtureの学校出典が変更されています")
        return LiveSeasonGraphPlan(repo=repo, data_dir=Path(data_dir), year=2026,
            rng_seed=cls.SEASON_SEED,
            entries={cid: full.entries[cid] for cid in cls.COMPETITION_IDS},
            annual_templates={cid: replace(full.annual_templates[cid],
                entrant_school_ids=list(entrants))
                for cid, entrants in zip(cls.COMPETITION_IDS, cls.FIXTURE_ENTRANTS)},
            annual_build_strategies={cid: full.annual_build_strategies[cid] for cid in cls.COMPETITION_IDS},
            calendar_rows=[r for r in full.calendar_rows if r["competition_id"] in cls.COMPETITION_IDS],
            # Repository stage coverage validator requires the complete reviewed
            # stage calendar; runtime still instantiates only these two MAINs.
            stage_calendar_rows=full.stage_calendar_rows,
            topological_order=list(cls.COMPETITION_IDS),
            warnings=["自己生成検証fixture: 山梨春の資格未確認。4校入力は実大会正史ではありません"])

    def __init__(self, plan, resolver):
        from game_core.tournament_bridge import AbilityMatchResolver
        if (type(resolver) is not AbilityMatchResolver or plan.repo is not resolver.repo
                or plan_fingerprint(plan) != plan_fingerprint(
                    self.verification_plan(plan.repo, plan.data_dir))):
            raise ValueError("未対応の共有年度ロスター条件です。固定検証fixtureを確認してください")
        self.resolver = resolver
        self.year, self.seed, self.roster_seed = 2026, self.SEASON_SEED, self.ROSTER_SEED
        self.competition_school_ids = dict(zip(self.COMPETITION_IDS, self.FIXTURE_ENTRANTS))
        self.expected_match_count = 6
        self.fingerprint = plan_fingerprint(plan)

    def prepare(self, plan, engine, contract):
        from game_core.players import PlayerRosterGenerator
        generator = self.resolver.roster_generator
        if (type(generator) is not PlayerRosterGenerator
                or generator.name_provider is not PlayerRosterGenerator().name_provider):
            raise ValueError("未証明の初年度生成recipeは共有保存契約外です")
        super().prepare(plan, engine, contract)

    def _snapshot(self, session):
        from dataclasses import asdict
        self.prepare(session.plan, session.state.engine, session.resolver_contract)
        state = session.state
        if ((state.year, state.rng_seed) != (self.year, self.seed)
                or set(state.competitions) != set(self.COMPETITION_IDS)
                or set(state.status_by_competition) != set(self.COMPETITION_IDS)
                or {cid: asdict(a) for cid, a in state.annual_templates.items()}
                != {cid: asdict(a) for cid, a in session.plan.annual_templates.items()}):
            raise ValueError("年度・大会・runtime入力が共有保存契約と一致しません")
        dates = {}
        for cid, scheduled in state.competitions.items():
            runtime = scheduled.runtime
            if (not 0 < len(scheduled.matches) <= self.MAX_MAIN_MATCHES
                    or runtime.reference_year != self.year
                    or runtime.generation_seed != session.plan.annual_templates[cid].rng_seed
                    or tuple(runtime.entrant_school_ids) != self.competition_school_ids[cid]
                    or (state.status_by_competition[cid] == "completed") != scheduled.is_complete):
                raise ValueError("未対応の共有MAIN試合構造です")
            for match in scheduled.matches.values():
                if match.competition_id != cid or match.stage_code != "MAIN":
                    raise ValueError("pre-MAIN・依存大会は共有保存契約外です")
                if match.match_date:
                    other = dates.setdefault(match.match_date, cid)
                    if other != cid:
                        raise ValueError("複数大会同日の入力は共有保存契約外です")
        return self.resolver.initial_roster_snapshot(reference_year=self.year,
            generation_seed=self.roster_seed, school_ids=self.SCHOOL_IDS)

    def validate(self, session, slot):
        """Preflight existing outcomes too, before JSON or any other commit."""
        from .career_competition_outcomes import (
            CareerCompetitionOutcomes, _canonical, _main_result, _sha,
        )
        rosters, sealed = super().validate(session, slot)
        path = slot / "historical_matches.sqlite3"
        if sealed:
            require_year_end(session.state)
        if path.is_file():
            with closing(_read_only(path)) as conn:
                conn.row_factory = sqlite3.Row
                if conn.execute("SELECT name FROM sqlite_master WHERE name="
                        "'historical_competition_outcomes'").fetchone():
                    rows = conn.execute("SELECT * FROM historical_competition_outcomes").fetchall()
                    if rows and not sealed:
                        raise ValueError("未封印年度に確定大会結果があります")
                    runs = session.state.completed_runs()
                    for row in rows:
                        cid = row["competition_id"]
                        if row["year"] != self.year or cid not in runs:
                            raise ValueError("対象外の確定大会結果があります")
                        result, matches = _main_result(runs[cid])
                        result["source_year_ledger_sha256"] = CareerCompetitionOutcomes._check_seal(conn, self.year)
                        result["source_match_sha256"] = _sha(_canonical(
                            CareerCompetitionOutcomes._check_source_matches(conn, self.year, cid, matches)))
                        raw = _canonical(result)
                        if row["payload_json"] != raw or row["record_sha256"] != _sha(raw):
                            raise ValueError("既存大会結果と確定MAINが衝突しています")
        return rosters, sealed

    def sync_outcomes(self, session, slot):
        require_year_end(session.state)
        if set(session.state.completed_runs()) != set(self.COMPETITION_IDS):
            raise ValueError("全対象大会のMAIN完了を確認してください")
        return super().sync_outcomes(session, slot)


class Yamanashi33FixturePersistence(SharedSchoolYearPersistence):
    """Reviewed master-scale game fixture, NOT the official 32-team event.

    No entrant reduction, official seeding, joint-team identity or advancement
    rights are inferred. Only this pinned 2026 MAIN plan and input version are
    allowed. Existing Stage100/101 and unspecified services retain their scope.
    """

    RESOLVER_CONTRACT = "yamanashi33_game_fixture_v1"
    COMPETITION_ID = "CMP000041"
    COMPETITION_IDS = (COMPETITION_ID,)
    SCHOOL_IDS = tuple(f"SCH{i:06d}" for i in range(196, 229))
    FIXTURE_ENTRANTS = (SCHOOL_IDS,)
    ROSTER_SEED = 430102
    MAX_MAIN_MATCHES = 32
    APPROVED_PLAN = "0859a698ee2e99096897dbc38b7d7a13c003287be155313c1f3e52a992d717ab"
    APPROVED_INPUTS = "8db8a2a5a7f202ba3fb012c404d2c9b7dac909bf9c2e502c63f5a63338dc8992"
    WARNING = "ゲーム内検証用33校大会。公式参加32チーム・合同チーム・公式組合せを再現しません"

    @classmethod
    def verification_plan(cls, repo, data_dir):
        from .live_season_planner import LiveSeasonGraphPlan
        full = LiveSeasonGraphPlanner(repo, data_dir, cls.SEASON_SEED, year=2026).build_plan()
        cid = cls.COMPETITION_ID
        plan = LiveSeasonGraphPlan(repo=repo, data_dir=Path(data_dir), year=2026,
            rng_seed=cls.SEASON_SEED, entries={cid: full.entries[cid]},
            annual_templates={cid: full.annual_templates[cid]},
            annual_build_strategies={cid: full.annual_build_strategies[cid]},
            calendar_rows=[r for r in full.calendar_rows if r["competition_id"] == cid],
            stage_calendar_rows=full.stage_calendar_rows, topological_order=[cid],
            warnings=[cls.WARNING])
        if plan_fingerprint(plan) != cls.APPROVED_PLAN:
            raise ValueError("33校fixtureの確認済planと一致しません。入力を再監査してください")
        return plan

    def __init__(self, plan, resolver):
        super().__init__(plan, resolver)
        self.expected_match_count = self.MAX_MAIN_MATCHES
        self._check_input_version(plan)

    def _check_input_version(self, plan):
        # Aggregate version only; no public per-file digest or private save input.
        from game_core.tournament_bridge import AbilityMatchResolver
        data = Path(plan.data_dir).resolve()
        root = data.parent
        files = sorted([p for p in data.rglob("*") if p.is_file()]
            + list((root / "config/abilities").glob("*.json"))
            + list((root / "config/match").glob("*.json")))
        manifest = [[p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()]
                    for p in files]
        digest = hashlib.sha256(json.dumps(manifest, ensure_ascii=False,
            separators=(",", ":")).encode()).hexdigest()
        if digest != self.APPROVED_INPUTS:
            raise ValueError("33校fixtureの外部データ版が一致しません")
        # Check the actual in-memory repository and config consumers too.
        reviewed = DataRepository(data)
        if self.resolver.repo.__dict__ != reviewed.__dict__:
            raise ValueError("33校fixtureの読み込み済マスターが変更されています")
        expected = AbilityMatchResolver(reviewed,
            ability_config_dir=root / "config/abilities", match_config_dir=root / "config/match",
            team_generation_seed=self.ROSTER_SEED)
        for name in ("ability_generator", "team_generator", "simulator"):
            actual, baseline = getattr(self.resolver, name), getattr(expected, name)
            if type(actual) is not type(baseline) or Path(actual.config_dir).resolve() != Path(baseline.config_dir).resolve():
                raise ValueError("未証明の33校fixture生成providerです")
            if actual.params != baseline.params:
                raise ValueError("33校fixture生成設定が変更されています")
            if name != "ability_generator" and (
                    {k: v for k, v in vars(actual).items() if k != "config_dir"}
                    != {k: v for k, v in vars(baseline).items() if k != "config_dir"}):
                raise ValueError("33校fixture試合生成recipeが変更されています")
        ability = self.resolver.ability_generator
        if (ability.base_generator.__dict__ != expected.ability_generator.base_generator.__dict__
                or ability.intake_model.__dict__ != expected.ability_generator.intake_model.__dict__):
            raise ValueError("33校fixture能力生成recipeが変更されています")

    def prepare(self, plan, engine, contract):
        if plan_fingerprint(plan) != self.APPROVED_PLAN:
            raise ValueError("33校fixtureの保存planが変更されています")
        self._check_input_version(plan)
        super().prepare(plan, engine, contract)


class LiveGameService:
    """Facade used by future GUI/CLI for new/load/save and day progression."""

    # Preserve the opt-out default for existing lightweight facade fixtures too.
    career_persistence: InitialCareerPersistence | None = None

    def __init__(
        self,
        repo: DataRepository,
        data_dir: str | Path,
        *,
        save_root: str | Path = "out/saves",
        year: int = 2026,
        resolver_contract: str = (
            DEFAULT_RESOLVER_CONTRACT
        ),
        max_backups: int = 3,
        autosave_after_action: bool = True,
        planner_factory: (
            Callable[
                [
                    DataRepository,
                    Path,
                    int,
                    int,
                ],
                object,
            ]
            | None
        ) = None,
        career_persistence: InitialCareerPersistence | None = None,
    ):
        if not resolver_contract:
            raise ValueError(
                "resolver_contract is required"
            )
        self.repo = repo
        self.career_persistence = career_persistence
        self.data_dir = Path(data_dir)
        self.year = year
        self.resolver_contract = (
            resolver_contract
        )
        self.autosave_after_action = (
            autosave_after_action
        )
        self.planner_factory = (
            planner_factory
        )
        self.slots = SaveSlotManager(
            save_root,
            max_backups=max_backups,
        )

    def _planner(
        self,
        rng_seed: int,
        *,
        year: int | None = None,
    ):
        target_year = (
            self.year
            if year is None
            else int(year)
        )
        if self.planner_factory is not None:
            return self.planner_factory(
                self.repo,
                self.data_dir,
                int(rng_seed),
                target_year,
            )
        return LiveSeasonGraphPlanner(
            self.repo,
            self.data_dir,
            int(rng_seed),
            year=target_year,
        )

    def new_game(
        self,
        slot_id: str,
        *,
        rng_seed: int,
        start_date: str | None = None,
        title: str | None = None,
        engine=None,
        save_initial: bool = True,
    ) -> LiveGameSession:
        slot = (
            self.slots.validate_slot_id(
                slot_id
            )
        )
        planner = self._planner(
            rng_seed,
            year=self.year,
        )
        plan = planner.build_plan()
        if self.career_persistence is not None:
            if self.slots.slot_dir(slot).exists():
                raise ValueError("既存セーブへ新規ゲームを上書きできません")
            self.career_persistence.prepare(plan, engine, self.resolver_contract)
        state = plan.build_runtime(
            engine=engine,
            start_date=start_date,
        )
        session = LiveGameSession(
            slot_id=slot,
            plan=plan,
            state=state,
            resolver_contract=(
                self.resolver_contract
            ),
        )
        if title is not None:
            self.slots.write_user_metadata(
                slot,
                title=title,
            )
        if save_initial:
            self.save_game(
                session,
                kind=SAVE_KIND_MANUAL,
            )
        return session

    def load_game(
        self,
        slot_id: str,
        *,
        source: str = "latest",
        engine=None,
    ) -> LiveGameSession:
        metadata = self.slots.inspect(
            slot_id,
            source=source,
        )
        if metadata[
            "resolver_contract"
        ] != self.resolver_contract:
            raise ValueError(
                "save resolver contract differs "
                "from game service"
            )
        planner = self._planner(
            metadata["rng_seed"],
            year=metadata["year"],
        )
        if self.career_persistence is not None:
            self.career_persistence.prepare(planner.build_plan(), engine, self.resolver_contract)
        plan, state = self.slots.load(
            slot_id,
            planner,
            source=source,
            engine=engine,
            resolver_contract=(
                self.resolver_contract
            ),
        )
        session = LiveGameSession(
            slot_id=(
                self.slots.validate_slot_id(
                    slot_id
                )
            ),
            plan=plan,
            state=state,
            resolver_contract=(
                self.resolver_contract
            ),
        )
        # Repair a crash between the JSON save and archive commit.
        # Older backup loads never delete matches written by newer saves.
        self._sync_history(session)
        return session

    def _history_archive(self, slot_id: str) -> HistoricalMatchArchive:
        return HistoricalMatchArchive(
            self.slots.slot_dir(slot_id) / "historical_matches.sqlite3"
        )

    def _sync_history(self, session: LiveGameSession) -> dict:
        slot = self.slots.slot_dir(session.slot_id)
        persistence = self.career_persistence
        rosters, sealed = persistence.validate(session, slot) if persistence else ((), False)
        roster_result = persistence.sync_rosters(rosters, slot) if persistence else None
        completed = (
            match.__dict__
            for scheduled in session.state.competitions.values()
            for match in scheduled.matches.values()
            if match.status == "completed"
        )
        result = self._history_archive(session.slot_id).sync(
            year=session.state.year,
            rng_seed=session.state.rng_seed,
            resolver_contract=session.resolver_contract,
            plan_fingerprint=plan_fingerprint(session.plan),
            completed=completed,
        )
        if persistence:
            result['career_rosters'] = roster_result
            result['career_outcomes'] = persistence.sync_outcomes(session, slot) if sealed else []
        return result

    def save_game(
        self,
        session: LiveGameSession,
        *,
        kind: str = SAVE_KIND_MANUAL,
    ) -> dict:
        # JSON first: if the archive operation fails or the process exits,
        # a later load deterministically replays and retries the archive.
        if self.career_persistence is not None:
            self.career_persistence.validate(session, self.slots.slot_dir(session.slot_id))
        saved = self.slots.save(
            session.slot_id,
            session.plan,
            session.state,
            kind=kind,
            resolver_contract=session.resolver_contract,
        )
        return {**saved, "historical_archive": self._sync_history(session)}

    def autosave_game(self, session: LiveGameSession) -> dict:
        return self.save_game(session, kind=SAVE_KIND_AUTOSAVE)

    def year_end_status(self, session: LiveGameSession) -> dict:
        """Report blockers to sealing the finished year's match history."""
        return year_end_readiness(session.state)

    def finalize_season(self, session: LiveGameSession) -> dict:
        """Commit current-year history and seal it against later additions.

        Does not build or start the next season. The underlying live runtime
        is still restricted to its existing annual competition graph.
        """
        readiness = require_year_end(session.state)
        # The JSON save is the replayable checkpoint. Then the archive syncs
        # and checks an exact completed-match count before sealing.
        saved = self.save_game(session, kind=SAVE_KIND_MANUAL)
        sealed = self._history_archive(session.slot_id).seal_year(
            session.state.year,
            expected_match_count=readiness["completed_match_count"],
        )
        career_outcomes = None
        if self.career_persistence is not None:
            career_outcomes = self.career_persistence.sync_outcomes(
                session, self.slots.slot_dir(session.slot_id))
        return {
            "action": "finalize_season",
            "year": session.state.year,
            "next_year": session.state.year + 1,
            "archive_sealed": True,
            "year_end_readiness": readiness,
            "save": saved,
            "archive": sealed,
            "next_year_gameplay_started": False,
            **({'career_outcomes': career_outcomes} if career_outcomes is not None else {}),
        }

    def career_history_years(self, slot_id: str) -> list[dict]:
        return self._history_archive(slot_id).list_years()

    def historical_match(
        self, slot_id: str, year: int, competition_id: str, match_id: str
    ) -> dict | None:
        return self._history_archive(slot_id).get_match(
            year, competition_id, match_id
        )

    def historical_matches(
        self, slot_id: str, year: int, *, school_id: str = "",
        limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        return self._history_archive(slot_id).list_matches(
            year, school_id=school_id, limit=limit, offset=offset,
        )

    def _maybe_autosave(
        self,
        session: LiveGameSession,
        enabled: bool | None,
    ) -> dict | None:
        should_save = (
            self.autosave_after_action
            if enabled is None
            else bool(enabled)
        )
        if not should_save:
            return None
        return self.autosave_game(
            session
        )

    def play_today(
        self,
        session: LiveGameSession,
        *,
        autosave: bool | None = None,
    ) -> dict:
        results = (
            session.state.play_today()
        )
        save = self._maybe_autosave(
            session,
            autosave,
        )
        return {
            "action": "play_today",
            "current_date": (
                session.state.current_date
                .isoformat()
            ),
            "played_match_count": len(
                results
            ),
            "results": results,
            "autosave": save,
        }

    def next_day(
        self,
        session: LiveGameSession,
        *,
        autosave: bool | None = None,
    ) -> dict:
        result = (
            session.state.next_day()
        )
        save = self._maybe_autosave(
            session,
            autosave,
        )
        return {
            "action": "next_day",
            **result,
            "autosave": save,
        }

    def _advance_with_checkpoints(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None,
        through: bool,
    ) -> dict:
        """Checkpoint completed match days during a long calendar jump.

        A single save at the end of a multi-day advance loses every game
        simulated since the previous save if the process stops mid-jump.
        Save the replayable JSON first and then sync the append-only history
        after each day that actually completed a match. Calendar-only days
        need no intermediate checkpoint. Explicit autosave=False retains
        the caller's manual-save contract.
        """
        enabled = (
            self.autosave_after_action
            if autosave is None
            else bool(autosave)
        )
        action = "advance_through" if through else "advance_to"
        if not enabled:
            result = (
                session.state.advance_through(target)
                if through else session.state.advance_to(target)
            )
            return {"action": action, **result, "autosave": None}

        target_date = (
            target if isinstance(target, date)
            else date.fromisoformat(target)
        )
        if not in_school_year(session.state.year, target_date):
            raise ValueError("target_date must be inside school year")
        if target_date < session.state.current_date:
            raise ValueError("season runtime cannot move backward")

        advanced_days = 0
        played_match_count = 0
        last_save = None
        checkpoint_date = None
        while session.state.current_date < target_date:
            step = session.state.next_day()
            advanced_days += 1
            new_matches = int(step["played_match_count"])
            played_match_count += new_matches
            if new_matches:
                last_save = self.autosave_game(session)
                checkpoint_date = session.state.current_date

        result = {
            "current_date": session.state.current_date.isoformat(),
            "advanced_days": advanced_days,
            "played_match_count": played_match_count,
        }
        if through:
            # Include games on the target day in the final replayable save.
            result["played_match_count"] += len(session.state.play_today())
            result["processed_through"] = (
                session.state.current_date.isoformat()
            )

        if through or checkpoint_date != session.state.current_date:
            last_save = self.autosave_game(session)
        return {"action": action, **result, "autosave": last_save}

    def advance_to(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None = None,
    ) -> dict:
        return self._advance_with_checkpoints(
            session, target, autosave=autosave, through=False,
        )

    def advance_through(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None = None,
    ) -> dict:
        return self._advance_with_checkpoints(
            session, target, autosave=autosave, through=True,
        )

    def list_games(self) -> list[dict]:
        return [
            summary.to_dict()
            for summary in self.slots.list_slots()
        ]

    def recovery_sources(
        self,
        slot_id: str,
    ) -> list[dict]:
        return self.slots.recovery_sources(
            slot_id
        )

    def rename_game(
        self,
        slot_id: str,
        title: str,
    ) -> dict:
        return (
            self.slots.rename_slot(
                slot_id,
                title,
            ).to_dict()
        )

    def recover_game(
        self,
        slot_id: str,
        *,
        source: str,
        promote_kind: str = SAVE_KIND_MANUAL,
        engine=None,
    ) -> LiveGameSession:
        session = self.load_game(
            slot_id,
            source=source,
            engine=engine,
        )
        self.save_game(
            session,
            kind=promote_kind,
        )
        return session

    def delete_game(
        self,
        slot_id: str,
    ) -> None:
        self.slots.delete_slot(
            slot_id
        )
