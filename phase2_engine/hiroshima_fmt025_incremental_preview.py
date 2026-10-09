"""Stage13E-3G-33: incremental, resumable, READ-ONLY FMT025 results preview.

Consumes only contracts accepted by Stage32 and reveals their already-declared
match winners one at a time. It never generates fresh winners, pairings or
official policies; it cannot join the live FMT025 scheduler.

Checkpoints are content-addressed to both the Stage32 payload AND the
underlying match topology, including checked-in historical results. All
untrusted restored results are revalidated from genesis, in event order.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .hiroshima_fmt025_input_preflight import (
    HISTORICAL, SANDBOX, Fmt025PreflightError, preflight_fmt025_input,
    load_preflight_payload_json, _matches,
)
from .hiroshima_explicit_match_dag_sandbox import (
    replay_explicit_match_dag,
)
from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE, EDGES_FILE
from .hiroshima_stage13e3g31 import replay_stage25_historical_observations

CHECKPOINT_VERSION = "fmt025-read-only-checkpoint-v1"
MAX_EVENTS = 2000
MATCH_WAITING = "waiting"
MATCH_READY = "ready"
MATCH_COMPLETED = "completed"


class IncrementalPreviewError(ValueError):
    """Invalid checkpoint, attempt to invent a result, or blocked transition."""


@dataclass(frozen=True)
class PreviewCheckpoint:
    checkpoint_version: str
    payload_sha256: str
    topology_sha256: str
    source_kind: str
    applied_results: tuple[tuple[str, str], ...]
    official_draw_verified: bool = False
    live_fmt025_runtime_enabled: bool = False
    optional_ranking_enabled: bool = False


@dataclass(frozen=True)
class PreviewMatchStatus:
    match_id: str
    phase: str
    status: str
    left_team_id: str | None
    right_team_id: str | None
    winner_team_id: str | None
    loser_team_id: str | None


@dataclass(frozen=True)
class PreviewSnapshot:
    checkpoint: PreviewCheckpoint
    match_statuses: tuple[PreviewMatchStatus, ...]
    ready_match_ids: tuple[str, ...]
    waiting_match_ids: tuple[str, ...]
    played_match_ids: tuple[str, ...]
    confirmed_qualifier_ids: tuple[str, ...]
    direct_main_entry_ids: tuple[str, ...]
    replay_completed: bool
    remaining_qualifier_slots: int
    evidence_grade: str
    actual_source_kind: str
    official_draw_verified: bool = False
    live_fmt025_runtime_enabled: bool = False
    optional_ranking_enabled: bool = False


def _canonical_digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _resolve_reference(payload: dict, data_dir: str | Path | None):
    """Load the preapproved full recorded results without changing them."""
    result = preflight_fmt025_input(payload, data_dir=data_dir)
    if payload["source_kind"] == SANDBOX:
        supplied_matches = _matches(payload["matches"])
        full = replay_explicit_match_dag(
            entrant_ids=tuple(payload["entrant_ids"]), matches=supplied_matches,
            winners_by_match=payload["winners_by_match"],
            qualifier_slots=payload["qualifier_slots"],
            direct_main_entry_ids=tuple(payload["direct_main_entry_ids"]),
        )
        dependencies = {
            m.match_id: tuple(
                token.split(":", 1)[1]
                for token in (m.left_source, m.right_source)
                if token.startswith(("winner:", "loser:"))
            )
            for m in supplied_matches
        }
    elif payload["source_kind"] == HISTORICAL:
        root = Path(data_dir)
        nodes = _read(root, NODES_FILE)
        edges = _read(root, EDGES_FILE)
        full = replay_stage25_historical_observations(nodes, edges)
        dependencies = {trace.match_id: [] for trace in full.match_traces}
        for edge in edges:
            dependencies[edge["to_match_id"]].append(edge["from_match_id"])
        dependencies = {k: tuple(v) for k, v in dependencies.items()}
    else:
        raise IncrementalPreviewError("unknown source kind")
    traces = full.match_traces
    if (len(traces) > MAX_EVENTS or len(dependencies) != len(traces)
            or any(len(v) > 2 for v in dependencies.values())):
        raise IncrementalPreviewError("invalid or oversized explicit match topology")
    topology_hash = _canonical_digest({
        "payload_sha256": result.payload_sha256,
        "full_trace": [asdict(t) for t in traces],
        "dependencies": dependencies,
        "direct_main_entry_ids": full.direct_main_entry_ids,
        "qualifier_slots": payload["qualifier_slots"],
    })
    return result, full, dependencies, topology_hash


def _guard_checkpoint(checkpoint: PreviewCheckpoint, preflight, topology_hash: str) -> None:
    if type(checkpoint) is not PreviewCheckpoint:
        raise IncrementalPreviewError("typed checkpoint required")
    if (checkpoint.checkpoint_version != CHECKPOINT_VERSION
            or checkpoint.payload_sha256 != preflight.payload_sha256
            or checkpoint.topology_sha256 != topology_hash
            or checkpoint.source_kind != preflight.source_kind
            or checkpoint.official_draw_verified is not False
            or checkpoint.live_fmt025_runtime_enabled is not False
            or checkpoint.optional_ranking_enabled is not False):
        raise IncrementalPreviewError("checkpoint is incompatible or claims unauthorized release")
    if (type(checkpoint.applied_results) is not tuple
            or len(checkpoint.applied_results) > MAX_EVENTS
            or any(type(p) is not tuple or len(p) != 2 or
                   type(p[0]) is not str or type(p[1]) is not str
                   for p in checkpoint.applied_results)):
        raise IncrementalPreviewError("checkpoint event sequence is invalid")


def _inspect(payload, checkpoint, data_dir):
    try:
        preflight, full, dependencies, topology_hash = _resolve_reference(payload, data_dir)
    except (Fmt025PreflightError, ValueError, KeyError, TypeError, OSError) as exc:
        raise IncrementalPreviewError("Stage32 input preflight or history was rejected") from exc
    _guard_checkpoint(checkpoint, preflight, topology_hash)
    return _summarize(checkpoint, preflight, full, dependencies)


def _summarize(checkpoint, preflight, full, dependencies):
    oracle = {t.match_id: t for t in full.match_traces}
    completed: dict[str, str] = {}
    for match_id, winner in checkpoint.applied_results:
        if match_id not in oracle or match_id in completed:
            raise IncrementalPreviewError("repeated or unknown recorded match event")
        if not set(dependencies[match_id]).issubset(completed):
            raise IncrementalPreviewError("cannot record match before its incoming results")
        if winner != oracle[match_id].winner_id:
            raise IncrementalPreviewError("winner differs from the Stage32 preapproved result")
        completed[match_id] = winner
    status_rows, ready, waiting, played, qualifiers = [], [], [], [], []
    for trace in full.match_traces:
        mid = trace.match_id
        if mid in completed:
            status = MATCH_COMPLETED
            played.append(mid)
            if trace.winner_awards_berth:
                qualifiers.append(trace.winner_id)
        elif set(dependencies[mid]).issubset(completed):
            status = MATCH_READY
            ready.append(mid)
        else:
            status = MATCH_WAITING
            waiting.append(mid)
        visible = status != MATCH_WAITING
        status_rows.append(PreviewMatchStatus(
            match_id=mid, phase=trace.phase, status=status,
            left_team_id=trace.left_entrant_id if visible else None,
            right_team_id=trace.right_entrant_id if visible else None,
            winner_team_id=trace.winner_id if status == MATCH_COMPLETED else None,
            loser_team_id=trace.loser_id if status == MATCH_COMPLETED else None,
        ))
    if (len(qualifiers) > preflight.qualifier_count or
            len(set(qualifiers)) != len(qualifiers)):
        raise IncrementalPreviewError("duplicate or excess qualification awards")
    return PreviewSnapshot(
        checkpoint=checkpoint,
        match_statuses=tuple(status_rows),
        ready_match_ids=tuple(ready),
        waiting_match_ids=tuple(waiting),
        played_match_ids=tuple(played),
        confirmed_qualifier_ids=tuple(qualifiers),
        direct_main_entry_ids=full.direct_main_entry_ids,
        replay_completed=len(played) == len(oracle),
        remaining_qualifier_slots=preflight.qualifier_count - len(qualifiers),
        evidence_grade=preflight.evidence_grade,
        actual_source_kind=preflight.source_kind,
    )


def start_read_only_preview(payload: dict, *, data_dir: str | Path | None = None) -> PreviewSnapshot:
    try:
        preflight, full, dependencies, digest = _resolve_reference(payload, data_dir)
    except (Fmt025PreflightError, ValueError, KeyError, TypeError, OSError) as exc:
        raise IncrementalPreviewError("Stage32 preflight rejected preview") from exc
    checkpoint = PreviewCheckpoint(
        checkpoint_version=CHECKPOINT_VERSION,
        payload_sha256=preflight.payload_sha256,
        topology_sha256=digest,
        source_kind=preflight.source_kind,
        applied_results=(),
    )
    return _summarize(checkpoint, preflight, full, dependencies)


def inspect_read_only_preview(
    payload: dict, checkpoint: PreviewCheckpoint,
    *, data_dir: str | Path | None = None,
) -> PreviewSnapshot:
    return _inspect(payload, checkpoint, data_dir)


def record_preapproved_match_result(
    payload: dict, checkpoint: PreviewCheckpoint,
    *, match_id: str, recorded_winner_id: str,
    data_dir: str | Path | None = None,
) -> PreviewSnapshot:
    """Reveal a previously checked-in result, not a new simulated result."""
    if type(match_id) is not str or type(recorded_winner_id) is not str:
        raise IncrementalPreviewError("match and winner IDs must be strings")
    before = _inspect(payload, checkpoint, data_dir)
    if match_id not in before.ready_match_ids:
        raise IncrementalPreviewError("match is not ready, has been played, or is unknown")
    next_checkpoint = replace_checkpoint_results(
        checkpoint, checkpoint.applied_results + ((match_id, recorded_winner_id),)
    )
    return _inspect(payload, next_checkpoint, data_dir)


def replace_checkpoint_results(
    checkpoint: PreviewCheckpoint, events: tuple[tuple[str,str],...]
) -> PreviewCheckpoint:
    return PreviewCheckpoint(
        checkpoint_version=checkpoint.checkpoint_version,
        payload_sha256=checkpoint.payload_sha256,
        topology_sha256=checkpoint.topology_sha256,
        source_kind=checkpoint.source_kind,
        applied_results=events,
        official_draw_verified=checkpoint.official_draw_verified,
        live_fmt025_runtime_enabled=checkpoint.live_fmt025_runtime_enabled,
        optional_ranking_enabled=checkpoint.optional_ranking_enabled,
    )


def export_read_only_checkpoint(checkpoint: PreviewCheckpoint) -> str:
    if type(checkpoint) is not PreviewCheckpoint:
        raise IncrementalPreviewError("typed checkpoint required")
    return json.dumps(asdict(checkpoint), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def restore_read_only_checkpoint(
    payload: dict, raw_json: str, *, data_dir: str | Path | None = None,
) -> PreviewSnapshot:
    try:
        raw = load_preflight_payload_json(raw_json)
    except Fmt025PreflightError as exc:
        raise IncrementalPreviewError("checkpoint is not strict JSON") from exc
    names = frozenset((
        "checkpoint_version", "payload_sha256", "topology_sha256",
        "source_kind", "applied_results", "official_draw_verified",
        "live_fmt025_runtime_enabled", "optional_ranking_enabled",
    ))
    if not isinstance(raw, dict) or set(raw) != names:
        raise IncrementalPreviewError("checkpoint has unknown or missing fields")
    events = raw["applied_results"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS or any(
        not isinstance(pair, list) or len(pair) != 2 for pair in events
    ):
        raise IncrementalPreviewError("invalid checkpoint results payload")
    candidate = PreviewCheckpoint(
        checkpoint_version=raw["checkpoint_version"],
        payload_sha256=raw["payload_sha256"],
        topology_sha256=raw["topology_sha256"],
        source_kind=raw["source_kind"],
        applied_results=tuple(tuple(x) for x in events),
        official_draw_verified=raw["official_draw_verified"],
        live_fmt025_runtime_enabled=raw["live_fmt025_runtime_enabled"],
        optional_ranking_enabled=raw["optional_ranking_enabled"],
    )
    return _inspect(payload, candidate, data_dir)
