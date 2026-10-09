"""Stage 13E-3G-35: headless presenter for the isolated FMT025 pilot GUI.

The real browse GUI reads scored SQLite records. This presenter instead
consumes the Stage32/33/34 read-only preview and exposes only observed or
fictional pre-approved results, one click at a time. No scheduling, new
winners, generated official draws or writes to SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .hiroshima_fmt025_input_preflight import (
    load_preflight_payload_json, HISTORICAL, SANDBOX,
)
from .hiroshima_fmt025_incremental_preview import (
    PreviewSnapshot, start_read_only_preview, record_preapproved_match_result,
    export_read_only_checkpoint, restore_read_only_checkpoint,
)
from .hiroshima_fmt025_preview_browse_model import (
    QualifierBrowseViews, build_fmt025_preview_browse_views,
)
from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from .hiroshima_stage13e3g31 import replay_stage25_historical_observations
from .hiroshima_stage13e3g32 import EXAMPLE_SANDBOX_FILE, EXAMPLE_OBSERVED_FILE

FICTIONAL = "fictional"
OBSERVED_2026_WEST = "observed_2026_autumn_west"
SCENARIOS = (
    (FICTIONAL, "架空4校（3試合）"),
    (OBSERVED_2026_WEST, "2026秋季 広島西部（史実25試合）"),
)
STATUS_LABELS = {
    "waiting": "対戦校待ち",
    "ready": "対戦校確定",
    "completed": "結果確定",
}
QUALIFICATION_LABELS = {
    "qualified": "県大会進出確定",
    "direct_exempt": "県大会直接出場",
    "ready": "次の試合確定",
    "no_ready_game": "次の試合未確定",
}
SOURCE_NOTE = {
    FICTIONAL: "架空の試験データです。実在の公式抽選・試合結果ではありません。",
    OBSERVED_2026_WEST: (
        "2026秋季広島西部の二次資料に基づく結果閲覧です。"
        "公式の試合番号25件・進行矢印32件の独立確認は未完了です。"
    ),
}


class PreviewGuiModelError(ValueError):
    """Unsupported scenario, UI filter or invalid read-only state."""


@dataclass(frozen=True)
class PilotGuiRender:
    scenario_id: str
    source_note: str
    summary: str
    evidence_grade: str
    played_count: int
    ready_count: int
    waiting_count: int
    qualifier_count: int
    qualifier_quota: int
    replay_completed: bool
    match_rows: tuple[tuple[str, ...], ...]
    school_rows: tuple[tuple[str, ...], ...]
    berth_rows: tuple[tuple[str, ...], ...]
    school_choices: tuple[str, ...]
    next_result_enabled: bool
    live_fmt025_runtime_enabled: bool = False
    official_draw_verified: bool = False
    optional_ranking_enabled: bool = False


class HiroshimaPreviewGuiModel:
    """Only 2 explicitly whitelisted preview fixtures are selectable."""

    def __init__(self, data_dir: str | Path, scenario_id: str = FICTIONAL):
        self.data_dir = Path(data_dir)
        self.scenario_id = ""
        self.payload: dict = {}
        self.snapshot: PreviewSnapshot | None = None
        self._source_winners: dict[str, str] = {}
        self._view: QualifierBrowseViews | None = None
        self.set_scenario(scenario_id)

    def _source_root(self) -> Path | None:
        return self.data_dir if self.scenario_id == OBSERVED_2026_WEST else None

    def set_scenario(self, scenario_id: str) -> None:
        if scenario_id not in (FICTIONAL, OBSERVED_2026_WEST):
            raise PreviewGuiModelError("only the fictional and checked-in 2026 west previews are allowed")
        path = (
            EXAMPLE_SANDBOX_FILE if scenario_id == FICTIONAL
            else EXAMPLE_OBSERVED_FILE
        )
        payload = load_preflight_payload_json(
            (self.data_dir / path).read_text(encoding="utf-8")
        )
        if (scenario_id == FICTIONAL and payload.get("source_kind") != SANDBOX
                or scenario_id == OBSERVED_2026_WEST
                and payload.get("source_kind") != HISTORICAL):
            raise PreviewGuiModelError("scenario provenance does not match the fixture")

        source_root = self.data_dir if scenario_id == OBSERVED_2026_WEST else None
        snapshot = start_read_only_preview(payload, data_dir=source_root)
        if scenario_id == FICTIONAL:
            winners = dict(payload["winners_by_match"])
        else:
            replay = replay_stage25_historical_observations(
                _read(self.data_dir, NODES_FILE), _read(self.data_dir, EDGES_FILE)
            )
            winners = {trace.match_id: trace.winner_id for trace in replay.match_traces}
        if len(winners) != len(snapshot.match_statuses):
            raise PreviewGuiModelError("not all games have approved read-only results")
        view = build_fmt025_preview_browse_views(
            payload, snapshot.checkpoint, data_dir=source_root
        )
        self.scenario_id, self.payload = scenario_id, payload
        self.snapshot, self._source_winners, self._view = snapshot, winners, view

    def show_next_preapproved_result(self) -> str | None:
        """Button action: reveal one pre-existing result; never compute games."""
        assert self.snapshot is not None
        if not self.snapshot.ready_match_ids:
            return None
        match_id = self.snapshot.ready_match_ids[0]
        new_snapshot = record_preapproved_match_result(
            self.payload,
            self.snapshot.checkpoint,
            match_id=match_id,
            recorded_winner_id=self._source_winners[match_id],
            data_dir=self._source_root(),
        )
        view = build_fmt025_preview_browse_views(
            self.payload, new_snapshot.checkpoint, data_dir=self._source_root()
        )
        self.snapshot, self._view = new_snapshot, view
        return match_id

    def reset_preview(self) -> None:
        self.set_scenario(self.scenario_id)

    def export_checkpoint(self) -> str:
        assert self.snapshot is not None
        return export_read_only_checkpoint(self.snapshot.checkpoint)

    def restore_checkpoint(self, raw_json: str) -> None:
        restored = restore_read_only_checkpoint(
            self.payload, raw_json, data_dir=self._source_root()
        )
        view = build_fmt025_preview_browse_views(
            self.payload, restored.checkpoint, data_dir=self._source_root()
        )
        self.snapshot, self._view = restored, view

    def render(
        self, *, status_filter: str = "", school_filter: str = "",
    ) -> PilotGuiRender:
        if status_filter not in ("", *STATUS_LABELS):
            raise PreviewGuiModelError("unknown fixture status filter")
        assert self.snapshot is not None and self._view is not None
        view = build_fmt025_preview_browse_views(
            self.payload, self.snapshot.checkpoint, data_dir=self._source_root()
        )
        choices = tuple(s.school_id for s in view.school_records)
        if school_filter and school_filter not in choices:
            raise PreviewGuiModelError("unknown/hidden school filter")

        rows = []
        for m in view.matches_by_date:
            if status_filter and m.match_status != status_filter:
                continue
            if school_filter and school_filter not in (m.team1_id, m.team2_id):
                continue
            # No fake dates/score. Waiting entrants are hidden upstream.
            rows.append((
                m.match_id,
                STATUS_LABELS[m.match_status],
                m.phase_code,
                m.team1_name or "未確定",
                "－",  # no score in Stage25
                m.team2_name or "未確定",
                m.winner_name or "－",
                m.match_date or "未定",
                "二次結果日付" if m.match_date else "日付未定",
            ))
        school_rows = tuple((
            s.school_name, str(s.games), str(s.wins), str(s.losses),
            str(s.ready_match_count), QUALIFICATION_LABELS[s.qualification_status],
        ) for s in view.school_records
            if not school_filter or s.school_id == school_filter)
        berth_rows = tuple((
            berth.school_name,
            "県大会直接出場" if berth.qualification_kind == "direct_exemption"
            else "県大会進出確定",
            berth.awarded_from_match_id or "予選免除",
        ) for berth in view.confirmed_berths
            if not school_filter or berth.school_id == school_filter)
        comp = view.competition_results[0]
        summary = (
            f"{comp.competition_name}  "
            f"全{comp.fixture_count}試合 / 結果確定{comp.completed_count} / "
            f"対戦確定{comp.ready_count} / 待機{comp.waiting_count}  "
            f"県大会進出{comp.confirmed_qualifier_count}/{comp.qualifier_quota}"
        )
        if (view.live_fmt025_runtime_enabled or view.optional_ranking_enabled
                or any(m.is_official_draw_verified for m in view.matches_by_date)):
            raise PreviewGuiModelError("preview data was promoted to official or live runtime")
        return PilotGuiRender(
            scenario_id=self.scenario_id,
            source_note=SOURCE_NOTE[self.scenario_id],
            summary=summary,
            evidence_grade=comp.evidence_grade,
            played_count=comp.completed_count,
            ready_count=comp.ready_count,
            waiting_count=comp.waiting_count,
            qualifier_count=comp.confirmed_qualifier_count,
            qualifier_quota=comp.qualifier_quota,
            replay_completed=comp.replay_completed,
            match_rows=tuple(rows), school_rows=school_rows,
            berth_rows=berth_rows, school_choices=choices,
            next_result_enabled=bool(self.snapshot.ready_match_ids),
        )
