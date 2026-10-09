"""Stage 13E-3G-34: isolated browse read-model for Stage33 FMT025 snapshots.

Do NOT coerce incomplete qualifier fixtures into browse_views.DatedMatchRow:
that type and its SQLite persistence were designed for scored, completed
season matches. This adapter builds three in-memory, immutable read models
with honest unknowns, plus confirmed qualification berths.

All caller data is revalidated through Stage32 + Stage33 before publishing
a view. No production database, Tkinter, scheduler or ranking mutation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .hiroshima_fmt025_input_preflight import HISTORICAL, SANDBOX
from .hiroshima_fmt025_incremental_preview import (
    MATCH_COMPLETED, MATCH_READY, MATCH_WAITING, PreviewCheckpoint,
    inspect_read_only_preview, _resolve_reference,
)
from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE

DATE_SECONDARY = "secondary_dated_result_only"
DATE_UNDATED = "undated_preview"
SCORE_UNAVAILABLE = "not_available"
VIEW_SCOPE = "read_only_sandbox_not_official_draw_or_live_fmt025"


@dataclass(frozen=True)
class QualifierBrowseMatch:
    competition_id: str
    competition_name: str
    season_segment: str
    match_id: str
    phase_code: str
    match_status: str
    match_date: str
    date_source: str
    team1_id: str
    team1_name: str
    team2_id: str
    team2_name: str
    team1_score: None
    team2_score: None
    winner_id: str
    winner_name: str
    loser_id: str
    loser_name: str
    result_text: str
    score_source: str = SCORE_UNAVAILABLE
    official_match_number: str = ""
    is_official_draw_verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QualifierBrowseCompetition:
    competition_id: str
    competition_name: str
    season_segment: str
    competition_type: str
    year: int | None
    group_id: str
    fixture_count: int
    completed_count: int
    ready_count: int
    waiting_count: int
    initial_entrant_count: int
    qualifier_quota: int
    confirmed_qualifier_count: int
    remaining_qualifier_slots: int
    direct_main_entry_count: int
    replay_completed: bool
    evidence_grade: str
    official_draw_verified: bool = False
    live_fmt025_enabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QualifierBrowseSchool:
    school_id: str
    school_name: str
    competition_id: str
    games: int
    wins: int
    losses: int
    ready_match_count: int
    played_match_ids: tuple[str, ...]
    ready_match_ids: tuple[str, ...]
    qualification_status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QualifierBrowseBerth:
    competition_id: str
    school_id: str
    school_name: str
    qualification_kind: str
    awarded_from_match_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QualifierBrowseViews:
    matches_by_date: tuple[QualifierBrowseMatch, ...]
    competition_results: tuple[QualifierBrowseCompetition, ...]
    school_records: tuple[QualifierBrowseSchool, ...]
    confirmed_berths: tuple[QualifierBrowseBerth, ...]
    proof_scope: str = VIEW_SCOPE
    live_fmt025_runtime_enabled: bool = False
    optional_ranking_enabled: bool = False

    def matches_for_date(self, match_date: str) -> tuple[QualifierBrowseMatch, ...]:
        if not isinstance(match_date, str):
            raise ValueError("date filter must be a string (empty for undated)")
        return tuple(row for row in self.matches_by_date if row.match_date == match_date)

    def matches_for_school(self, school_id: str) -> tuple[QualifierBrowseMatch, ...]:
        if not isinstance(school_id, str) or not school_id:
            raise ValueError("school ID must be a nonempty string")
        return tuple(row for row in self.matches_by_date
                     if row.team1_id == school_id or row.team2_id == school_id)

    def matches_for_competition(self, competition_id: str) -> tuple[QualifierBrowseMatch, ...]:
        if not isinstance(competition_id, str) or not competition_id:
            raise ValueError("competition ID must be a nonempty string")
        return tuple(row for row in self.matches_by_date
                     if row.competition_id == competition_id)


def _identity(payload: dict) -> tuple[str, str, str, str, int | None]:
    if payload["source_kind"] == SANDBOX:
        return ("SANDBOX", "架空地区予選（閲覧試作）", "", "fictional_preview", None)
    if payload["source_kind"] == HISTORICAL:
        return ("SGR000144", "2026年秋季広島西部地区予選（史実結果閲覧）",
                "autumn", "autumn_prefectural_qualifier", 2026)
    raise ValueError("unsupported source kind")


def _recorded_dates(payload: dict, checkpoint: PreviewCheckpoint,
                    data_dir: str | Path | None) -> dict[str,str]:
    if payload["source_kind"] != HISTORICAL:
        return {}
    if data_dir is None:
        raise ValueError("historical fixtures need checked-in Stage25 source")
    rows = _read(Path(data_dir), NODES_FILE)
    dates: dict[str,str] = {}
    for node in rows:
        mid, day = node["match_id"], node["match_date"]
        if mid in dates or not day:
            raise ValueError("historical date provenance is incomplete")
        dates[mid] = day
    if len(dates) != 25:
        raise ValueError("historical date ledger should cover 25 games")
    return dates


def build_fmt025_preview_browse_views(
    payload: dict, checkpoint: PreviewCheckpoint,
    *, data_dir: str | Path | None = None,
) -> QualifierBrowseViews:
    """Return GUI-ready *supplementary* read views; do not write to SQLite."""
    snapshot = inspect_read_only_preview(payload, checkpoint, data_dir=data_dir)
    # The separately validated full oracle stays internal: it is used only
    # for the explicit berth-awarding match flag, never to reveal an unplayed
    # result or a future entrant.
    _, reference, _, _ = _resolve_reference(payload, data_dir)
    comp_id, comp_name, season, comp_type, year = _identity(payload)
    if (snapshot.live_fmt025_runtime_enabled or snapshot.official_draw_verified
            or snapshot.optional_ranking_enabled):
        raise ValueError("unreviewed official live play cannot enter read model")
    dates = _recorded_dates(payload, checkpoint, data_dir)
    fixtures: list[QualifierBrowseMatch] = []
    played_by_school: dict[str,list[str]] = defaultdict(list)
    ready_by_school: dict[str,list[str]] = defaultdict(list)
    wins: dict[str,int] = defaultdict(int)
    losses: dict[str,int] = defaultdict(int)
    known_school_ids = set()
    berth_source: dict[str,str] = {}

    for item in snapshot.match_statuses:
        if item.status not in (MATCH_WAITING, MATCH_READY, MATCH_COMPLETED):
            raise ValueError("unknown fixture status")
        completed = item.status == MATCH_COMPLETED
        visible = item.status != MATCH_WAITING
        team1 = item.left_team_id or ""
        team2 = item.right_team_id or ""
        winner = item.winner_team_id or ""
        loser = item.loser_team_id or ""
        if not visible and (team1 or team2 or winner or loser):
            raise ValueError("future match entrants must not be disclosed")
        if visible and (not team1 or not team2 or team1 == team2):
            raise ValueError("ready and completed fixtures require two distinct teams")
        if not completed and (winner or loser):
            raise ValueError("unplayed fixture must not disclose outcomes")
        if completed and (winner not in (team1,team2) or
                          loser not in (team1,team2) or winner == loser):
            raise ValueError("completed fixture outcome is inconsistent")
        day = dates[item.match_id] if completed and dates else ""
        source = DATE_SECONDARY if day else DATE_UNDATED
        if completed:
            message = f"{winner} 勝利（得点未収録）"
        elif visible:
            message = "対戦カード確定・結果未記録"
        else:
            message = "対戦カード未確定"
        fixtures.append(QualifierBrowseMatch(
            competition_id=comp_id, competition_name=comp_name,
            season_segment=season, match_id=item.match_id, phase_code=item.phase,
            match_status=item.status, match_date=day, date_source=source,
            team1_id=team1, team1_name=team1, team2_id=team2, team2_name=team2,
            team1_score=None, team2_score=None,
            winner_id=winner, winner_name=winner, loser_id=loser, loser_name=loser,
            result_text=message,
        ))
        if visible:
            known_school_ids.update((team1,team2))
        if completed:
            for school in (team1,team2):
                played_by_school[school].append(item.match_id)
            wins[winner] += 1
            losses[loser] += 1
        elif visible:
            for school in (team1,team2):
                ready_by_school[school].append(item.match_id)

    if (len(fixtures) != len({r.match_id for r in fixtures})
            or len(fixtures) != len(snapshot.match_statuses)):
        raise ValueError("duplicate or missing match rows")
    if any(match_id not in {x.match_id for x in fixtures} for match_id in dates):
        raise ValueError("historical dates include unknown match IDs")
    if sum(wins.values()) != len(snapshot.played_match_ids) or sum(losses.values()) != len(snapshot.played_match_ids):
        raise ValueError("school win/loss aggregates mismatch completed fixtures")

    completed_ids = set(snapshot.played_match_ids)
    for trace in reference.match_traces:
        if trace.winner_awards_berth and trace.match_id in completed_ids:
            if trace.winner_id in berth_source:
                raise ValueError("duplicate confirmed qualifying gate")
            berth_source[trace.winner_id] = trace.match_id
    if set(berth_source) != set(snapshot.confirmed_qualifier_ids):
        raise ValueError("qualifier source consistency failed")
    if set(snapshot.direct_main_entry_ids) & known_school_ids:
        raise ValueError("direct exemptions cannot appear in qualifier fixtures")
    schools = []
    for school in sorted(known_school_ids | set(snapshot.direct_main_entry_ids)):
        played = tuple(played_by_school[school])
        ready = tuple(ready_by_school[school])
        status = ("qualified" if school in snapshot.confirmed_qualifier_ids
                  else "direct_exempt" if school in snapshot.direct_main_entry_ids
                  else "ready" if ready else "no_ready_game")
        schools.append(QualifierBrowseSchool(
            school_id=school, school_name=school, competition_id=comp_id,
            games=len(played), wins=wins[school], losses=losses[school],
            ready_match_count=len(ready), played_match_ids=played,
            ready_match_ids=ready, qualification_status=status,
        ))
    competition = QualifierBrowseCompetition(
        competition_id=comp_id, competition_name=comp_name,
        season_segment=season, competition_type=comp_type, year=year,
        group_id=comp_id, fixture_count=len(fixtures),
        completed_count=len(snapshot.played_match_ids),
        ready_count=len(snapshot.ready_match_ids),
        waiting_count=len(snapshot.waiting_match_ids),
        initial_entrant_count=(len(payload["entrant_ids"]) if payload["source_kind"] == SANDBOX else 18),
        qualifier_quota=payload["qualifier_slots"],
        confirmed_qualifier_count=len(snapshot.confirmed_qualifier_ids),
        remaining_qualifier_slots=snapshot.remaining_qualifier_slots,
        direct_main_entry_count=len(snapshot.direct_main_entry_ids),
        replay_completed=snapshot.replay_completed,
        evidence_grade=snapshot.evidence_grade,
    )
    berths = [
        QualifierBrowseBerth(comp_id, school, school, "earned_from_completed_match", berth_source[school])
        for school in snapshot.confirmed_qualifier_ids
    ]
    berths.extend(
        QualifierBrowseBerth(comp_id,school,school,"direct_exemption","")
        for school in snapshot.direct_main_entry_ids
    )
    # Sorting is stable and does not fabricate official dates for ready/waiting.
    fixtures.sort(key=lambda row:(row.match_date == "", row.match_date, row.match_id))
    return QualifierBrowseViews(
        matches_by_date=tuple(fixtures),
        competition_results=(competition,),
        school_records=tuple(schools),
        confirmed_berths=tuple(berths),
    )
