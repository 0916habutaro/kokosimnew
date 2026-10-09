"""Stage13E-3G-25: 2026 Hiroshima autumn west 25-result / 32-edge graph.

All 25 played fixtures are classified into 9 named events and all 32
team-specific continuations are linked. This is an *observed* fixture graph.
The 2026 official federation diagram establishes the event-level structure,
but the small numbered slots and the individual draw arrows have not been
independently transcribed. Do not treat this graph as an annual selector or
activate the FMT025 production runtime.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from .hiroshima_match_level_2026 import _read
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from .hiroshima_stage13e3g18 import TRANSITION_FILE
from .hiroshima_stage13e3g22 import PUBLISHER_GROUPS_FILE, PRIOR_YEAR_PDF_FILE
from .hiroshima_stage13e3g24 import GRAPH_FILE, PREVIEW_FILE, OFFICIAL_SOURCE

NODES_FILE = "competitions/2026/hiroshima_autumn_west_match_nodes_stage13e3g25.csv"
EDGES_FILE = "competitions/2026/hiroshima_autumn_west_observed_edges_stage13e3g25.csv"
SCOPE_NODE = "secondary_dated_results_with_official_phase_macro_only"
SCOPE_EDGE = "secondary_dated_team_sequence_not_official_numbered_arrows"
SPEC = (
    ("A", "PRIMARY", "HT20260068 HT20260173 HT20260175 HT20260176"),
    ("A", "REPECHAGE_ZONE", "HT20260035 HT20260172 HT20260174"),
    ("B", "PRIMARY", "HT20260069 HT20260178 HT20260180 HT20260181"),
    ("B", "REPECHAGE_ZONE", "HT20260070 HT20260177 HT20260179"),
    ("C", "PRIMARY", "HT20260071 HT20260187 HT20260189"),
    ("C", "REPECHAGE_ZONE", "HT20260182 HT20260185"),
    ("D", "PRIMARY", "HT20260073 HT20260186 HT20260188"),
    ("D", "REPECHAGE_ZONE", "HT20260183 HT20260184"),
    ("C;D", "REPECHAGE_CROSS_ZONE_GATE", "HT20260072"),
)
EXPECTED_COUNTS = {"PRIMARY": 14, "REPECHAGE_ZONE": 10,
                   "REPECHAGE_CROSS_ZONE_GATE": 1}
EXPECTED_PREVIEW_SCOPE = "federation_pdf_visual_render_macro_graph_not_raw_pdf_or_complete_edges"


def audit_2026_hiroshima_stage13e3g25(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    nodes = _read(root, NODES_FILE)
    edges = _read(root, EDGES_FILE)
    history = [r for r in _read(root, TIMELINE_FILE)
               if (r["season"], r["district_code"]) == ("autumn", "west")]
    observation = [r for r in _read(root, TRANSITION_FILE)
                   if (r["season"], r["district_code"]) == ("autumn", "west")]
    events = _read(root, PUBLISHER_GROUPS_FILE)
    phases = _read(root, GRAPH_FILE)
    preview = _read(root, PREVIEW_FILE)
    prior_year = _read(root, PRIOR_YEAR_PDF_FILE)
    errors: list[str] = []

    history_by_id = {r["match_id"]: r for r in history}
    node_by_id = {r["match_id"]: r for r in nodes}
    observation_by_id = {r["transition_id"]: r for r in observation}
    event_by_key = {(r["zone_scope"], r["phase_execution_role"]): r for r in events}
    phase_by_event = {r["event_audit_id"]: r for r in phases}
    spec = {}
    role_counts = Counter()
    for zone, role, fixture_ids in SPEC:
        event = event_by_key.get((zone, role))
        if event is None:
            errors.append(f"missing published route {zone}/{role}")
            continue
        for match_id in fixture_ids.split():
            if match_id in spec:
                errors.append(f"double-mapped match in specification: {match_id}")
            spec[match_id] = (zone, role, event)
            role_counts[role] += 1
    if role_counts != EXPECTED_COUNTS:
        errors.append("14 primary, 10 secondary, 1 C/D cross expected")
    if (len(history) != 25 or len(history_by_id) != 25
            or len(nodes) != 25 or len(node_by_id) != 25
            or set(node_by_id) != set(history_by_id) or set(spec) != set(history_by_id)):
        errors.append("exactly 25 unique dated games mapped once to nine named events required")
    if len(events) != 9 or len(event_by_key) != 9 or len(phases) != 9 or len(phase_by_event) != 9:
        errors.append("existing nine phase events must remain unique")
    if (len(preview) != 1
            or preview[0]["document_year"] != "2026"
            or preview[0]["source_official_pdf_url"] != OFFICIAL_SOURCE
            or preview[0]["source_scope"] != EXPECTED_PREVIEW_SCOPE
            or preview[0]["all_pairings_and_loser_arrows_reviewed"] != "no"
            or preview[0]["source_pdf_bytes_downloaded"] != "no"):
        errors.append("2026 visual preview is only macro-level primary evidence")
    if (len(prior_year) != 1 or prior_year[0]["prior_year"] != "2025"
            or prior_year[0]["prior_year_graph_reusable_for_2026"] != "no"):
        errors.append("prior-year 2025 bracket cannot justify 2026 arrows")

    for index, record in enumerate(sorted(nodes, key=lambda r: (r["match_date"], r["match_id"])), 1):
        match_id = record["match_id"]
        upstream = history_by_id.get(match_id)
        entry = spec.get(match_id)
        if not upstream or not entry:
            continue
        zone, role, publisher = entry
        phase = phase_by_event.get(publisher["event_audit_id"])
        expected = {
            "node_audit_id": f"HGN2026{index:03d}",
            "competition_id": "CMP000136", "stage_group_id": "SGR000144",
            "season": "autumn", "district_code": "west",
            "match_id": match_id,
            "match_date": upstream["match_date"],
            "start_time": upstream["start_time"],
            "zone_scope": zone,
            "phase_execution_role": role,
            "publisher_route_id": publisher["published_route_id"],
            "publisher_event_audit_id": publisher["event_audit_id"],
            "round_label": upstream["round_label"],
            "team1_name": upstream["team1_name"],
            "team1_score": upstream["team1_score"],
            "team2_name": upstream["team2_name"],
            "team2_score": upstream["team2_score"],
            "observed_winner": upstream["winner_name"],
            "winner_berth_status": upstream["winner_berth_status"],
            "secondary_result_url": upstream["source_url"],
            "official_2026_image_url": OFFICIAL_SOURCE,
            "official_match_number": "",
            "official_match_number_verified": "no",
            "official_pairings_verified": "no",
            "official_individual_loser_arrow_verified": "no",
            "source_scope": SCOPE_NODE,
            "fmt025_live_allowed": "no",
        }
        for field, value in expected.items():
            if record.get(field) != value:
                errors.append(f"25-match historical evidence mismatch {match_id}/{field}")
        names = set(publisher["normalized_real_team_names"].split(";"))
        if not {upstream["team1_name"], upstream["team2_name"]} <= names:
            errors.append(f"match school not in published event: {match_id}")
        if (not phase or phase["route_id"] != publisher["published_route_id"]
                or phase["fmt025_live_route_approved"] != "no"
                or phase["complete_pairing_edges_transcribed"] != "no"):
            errors.append(f"cannot silently unlock annual route by fixture record: {match_id}")
        if role == "PRIMARY" and (not upstream["round_label"].startswith("予選")
                                  or "敗者" in upstream["round_label"]):
            errors.append(f"non-primary round misclassified: {match_id}")
        if role == "REPECHAGE_ZONE" and not (
                upstream["round_label"].startswith("予選敗者戦")
                or upstream["round_label"] == "anchor_verified_decider"):
            errors.append(f"non-repechage round misclassified: {match_id}")
        if role == "REPECHAGE_CROSS_ZONE_GATE" and (
                match_id != "HT20260072" or upstream["winner_name"] != "広島工大"):
            errors.append("C/D cross-zone match identity changed")

    counts = Counter(n["phase_execution_role"] for n in nodes)
    if counts != EXPECTED_COUNTS:
        errors.append(f"25 event role counts changed: {counts}")
    if len(observation) != 32 or len(observation_by_id) != 32:
        errors.append("32 observed transitions required")
    if len(edges) != 32 or len(set(x["transition_id"] for x in edges)) != 32:
        errors.append("32 unique independently indexed continuation rows required")
    occurrences = defaultdict(list)
    for game in history:
        for school in (game["team1_name"], game["team2_name"]):
            occurrences[school].append(game["match_id"])
    indegree = Counter()
    outdegree = Counter()
    kinds = Counter()
    for index, edge in enumerate(sorted(edges, key=lambda e: e["transition_id"]), 1):
        old = observation_by_id.get(edge["transition_id"])
        first = spec.get(edge["from_match_id"])
        second = spec.get(edge["to_match_id"])
        if old is None or first is None or second is None:
            errors.append(f"unmatched historical continuation: {edge['transition_id']}")
            continue
        if edge["from_match_id"] == edge["to_match_id"]:
            errors.append("source and destination must differ")
        expected = {
            "trace_id": f"HGE2026{index:03d}",
            "transition_id": old["transition_id"],
            "season": "autumn", "district_code": "west",
            "stage_group_id": "SGR000144",
            "school_display_name": old["school_display_name"],
            "from_match_id": old["from_match_id"],
            "from_result": old["from_result"],
            "to_match_id": old["to_match_id"],
            "from_phase": old["from_phase"],
            "to_phase": old["to_phase"],
            "transition_kind": old["transition_kind"],
            "from_route_id": first[2]["published_route_id"],
            "to_route_id": second[2]["published_route_id"],
            "from_match_date": old["from_match_date"],
            "to_match_date": old["to_match_date"],
            "official_2026_image_url": OFFICIAL_SOURCE,
            "official_number_from": "",
            "official_number_to": "",
            "official_number_and_arrow_verified": "no",
            "source_scope": SCOPE_EDGE,
            "fmt025_live_allowed": "no",
        }
        for field, value in expected.items():
            if edge.get(field) != value:
                errors.append(f"32-edge historical evidence mismatch {edge['transition_id']}/{field}")
        school = old["school_display_name"]
        a = history_by_id.get(old["from_match_id"])
        b = history_by_id.get(old["to_match_id"])
        if not a or not b:
            errors.append(f"continuation has nonexistent played game: {edge['transition_id']}")
            continue
        if (school not in {a["team1_name"], a["team2_name"]}
                or school not in {b["team1_name"], b["team2_name"]}
                or a["match_date"] >= b["match_date"]
                or (old["from_result"] == "winner") != (a["winner_name"] == school)):
            errors.append(f"team/outcome/date continuation invalid: {edge['transition_id']}")
        indegree[(school, old["to_match_id"])] += 1
        outdegree[(school, old["from_match_id"])] += 1
        kinds[old["transition_kind"]] += 1

    if len(occurrences) != 18 or sum(map(len, occurrences.values())) != 50:
        errors.append("18 distinct entrants / 50 appearances required")
    start_nodes = 0
    for school, games_played in occurrences.items():
        heads = sum(indegree[(school, game)] == 0 for game in games_played)
        tails = sum(outdegree[(school, game)] == 0 for game in games_played)
        if (heads != 1 or tails != 1
                or any(indegree[(school, game)] > 1 for game in games_played)
                or any(outdegree[(school, game)] > 1 for game in games_played)):
            errors.append(f"team appearance has fork, loop, or missing transition: {school}")
        start_nodes += heads
    if start_nodes != 18 or sum(indegree.values()) != 32 or sum(outdegree.values()) != 32:
        errors.append("18 entrants and 32 chronological connected edges required")
    if kinds != {"WIN_PRIMARY_TO_PRIMARY": 10, "LOSS_PRIMARY_TO_REPECHAGE": 14,
                 "WIN_REPECHAGE_TO_REPECHAGE": 8}:
        errors.append(f"expected 10 primary wins, 14 primary losses, 8 repechage advances: {kinds}")
    if set(edge["transition_id"] for edge in edges) != set(observation_by_id):
        errors.append("32 observed transition IDs do not match Stage18 ledger")

    return {
        "ok": not errors, "errors": errors,
        "historical_played_games": len(history),
        "mapped_phase_nodes": len(nodes),
        "role_counts": dict(counts),
        "school_continuation_edges": len(edges),
        "transition_kinds": dict(kinds),
        "distinct_first_entry_schools": len(occurrences),
        "historical_berth_awards": sum(x["winner_berth_status"] == "berth_award" for x in history),
        "official_numbered_match_arrows_verified": 0,
        "raw_2026_official_pdf_acquired": False,
        "season_independent_loser_selector_verified": False,
        "live_fmt025_runtime_changed": False,
    }
