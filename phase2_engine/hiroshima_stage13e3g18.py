"""Stage13E-3G-18: observed 2026 match-to-match participant continuity.

This is a result-derived DAG for schools or joint-team *display names*.
It is not an official draw graph or an annual-independent simulator rule:
we must not infer unplayed matches, unverified tournament edges, or optional
ranking matches from an observed sequence of played results.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE
from .hiroshima_stage13e3g16 import EVENT_FILE
from .hiroshima_stage13e3g17 import CROSSWALK_FILE, GROUP_CONTRACT_FILE

TRANSITION_FILE = "competitions/2026/hiroshima_observed_match_transitions_2026.csv"
SUMMARY_FILE = "competitions/2026/hiroshima_observed_transition_counts_2026.csv"
SECOND_CHANCE_FILE = "competitions/2026/hiroshima_repechage_second_chance_examples_2026.csv"
BLOCK_SOURCES = (
    "competitions/2026/hiroshima_award_game_evidence_stage13e3g12.csv",
    "competitions/2026/hiroshima_award_game_evidence_stage13e3g13.csv",
    "competitions/2026/hiroshima_nonaward_fixtures_stage13e3g14.csv",
    "competitions/2026/hiroshima_nonaward_fixtures_stage13e3g15.csv",
)
EXPECTED_FIXTURES = {
    ("spring","west"):24, ("spring","north"):24,
    ("spring","south"):33, ("spring","east"):31,
    ("autumn","west"):25, ("autumn","north"):22,
    ("autumn","south"):34, ("autumn","east"):30,
}
EXPECTED_FLOW = {
    "WIN_PRIMARY_TO_PRIMARY":83,
    "LOSS_PRIMARY_TO_REPECHAGE":121,
    "WIN_REPECHAGE_TO_REPECHAGE":77,
    "LOSS_REPECHAGE_TO_REPECHAGE":6,
}
SECOND_CHANCE_PAIRS = {
    ("spring","north","安西","HT20260032","HT20260067"),
    ("spring","east","総合技術","HT20260042","HT20260044"),
    ("autumn","south","呉三津田","HT20260023","HT20260020"),
    ("autumn","south","熊野","HT20260022","HT20260021"),
    ("autumn","east","神辺旭","HT20260061","HT20260037"),
    ("autumn","east","英数学館","HT20260057","HT20260037"),
}


def _phase(game: dict) -> str:
    value = game["round_label"]
    if value.startswith("予選敗者戦") or value == "anchor_verified_decider":
        return "REPECHAGE"
    if value.startswith("予選"):
        return "PRIMARY"
    raise ValueError(f"unrecognized match round: {game['match_id']}: {value}")


def _expected_rows(root: Path) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    errors: list[str] = []
    matches = _read(root, TIMELINE_FILE)
    events = _read(root, EVENT_FILE)
    crosswalk = _read(root, CROSSWALK_FILE)
    plans = _read(root, GROUP_CONTRACT_FILE)
    hints = {}
    for path in BLOCK_SOURCES:
        for r in _read(root, path):
            mid = r["match_id"]
            if mid in hints:
                errors.append(f"duplicate recorded block hint for {mid}")
            hints[mid] = r["route_block"]
    by_id = {m["match_id"]:m for m in matches}
    if len(matches) != 223 or len(by_id) != 223:
        errors.append("223 unique source-result matches required")
    if len(hints) != 186 or any(mid not in by_id for mid in hints):
        errors.append("186 unique legacy match block hints required")
    event_by_match = {r["matched_match_id"]:r for r in events}
    route_by_event = {
        r["matched_publisher_event_check_id"]:r
        for r in crosswalk if r["matched_publisher_event_check_id"]
    }
    if len(event_by_match) != 15 or len(route_by_event) != 15:
        errors.append("15 unique publisher event + FMT025 route mappings required")

    appearances: dict[tuple, list] = {}
    matched_teams: dict[tuple, set] = {}
    games_by_group: dict[tuple, list] = {}
    awards = Counter()
    award_phase = Counter()
    for game in matches:
        group = (game["season"],game["district_code"])
        games_by_group.setdefault(group,[]).append(game)
        matched_teams.setdefault(group,set()).update((game["team1_name"],game["team2_name"]))
        if game["winner_berth_status"] == "berth_award":
            awards[group] += 1
            award_phase[_phase(game)] += 1
        for role, team in (("winner",game["team1_name"]),("loser",game["team2_name"])):
            appearances.setdefault((*group,team),[]).append((game,role))

    if len(appearances) != 159 or sum(awards.values()) != 63:
        errors.append("159 seasonal team entries / 63 qualification awards required")
    if award_phase != {"PRIMARY":38,"REPECHAGE":25}:
        errors.append(f"2026 awarded PRIMARY/REPECHAGE split changed: {award_phase}")

    edges: list[dict] = []
    for (season,district,team), seen in appearances.items():
        seen.sort(key=lambda x:(x[0]["match_date"],x[0]["start_time"],x[0]["match_id"]))
        for i in range(len(seen)-1):
            previous, role = seen[i]
            following, _ = seen[i+1]
            fp, tp = _phase(previous), _phase(following)
            if previous["match_date"] >= following["match_date"]:
                errors.append(f"not strictly later calendar date: {season}/{district}/{team}")
            if fp == "REPECHAGE" and tp == "PRIMARY":
                errors.append(f"illegal backward phase sequence: {season}/{district}/{team}")
            if role == "winner" and previous["winner_berth_status"] == "berth_award":
                errors.append(f"already qualified team appears again: {season}/{district}/{team}")
            event = event_by_match.get(following["match_id"])
            route = route_by_event.get(event["check_id"]) if event else None
            if event and not route:
                errors.append(f"publisher result cannot link to known route: {following['match_id']}")
            previous_hint = hints.get(previous["match_id"],"")
            following_hint = hints.get(following["match_id"],"")
            edges.append({
                "transition_id":"HPTR2026"+str(len(edges)+1).zfill(4),
                "season":season, "district_code":district,
                "stage_group_id":previous["stage_group_id"],
                "school_display_name":team,
                "from_match_id":previous["match_id"],
                "from_match_date":previous["match_date"],
                "from_result":role,
                "from_phase":fp,
                "from_round_label":previous["round_label"],
                "to_match_id":following["match_id"],
                "to_match_date":following["match_date"],
                "to_phase":tp,
                "to_round_label":following["round_label"],
                "transition_kind":("WIN" if role=="winner" else "LOSS")+"_"+fp+"_TO_"+tp,
                "from_block_hint":previous_hint,
                "to_block_hint":following_hint,
                "block_hint_changed":(
                    "yes" if previous_hint and following_hint
                    and previous_hint != following_hint else "no"
                ),
                "target_publisher_event_check_id":event["check_id"] if event else "",
                "target_publisher_route_id":route["route_id"] if route else "",
                "from_result_source_url":previous["source_url"],
                "to_result_source_url":following["source_url"],
                "source_scope":"secondary_result_chronological_team_sequence",
                "official_pdf_draw_edge_verified":"no",
                "runtime_draw_transition_enabled":"no",
            })

    plans_by_group = {(r["season"],r["district_code"]):r for r in plans}
    if len(plans) != 8 or len(plans_by_group) != 8:
        errors.append("Stage17 eight group phase contracts required")
    summary = []
    for group, nfixtures in EXPECTED_FIXTURES.items():
        season, district = group
        fixture = games_by_group.get(group,[])
        related = [x for x in edges if (x["season"],x["district_code"])==group]
        p = plans_by_group.get(group)
        if len(fixture) != nfixtures:
            errors.append(f"secondary match count changed: {group}")
        if p is None or awards[group] != int(p["required_qualifier_awards"]):
            errors.append(f"Stage17 quota or Stage18 awarded match count changed: {group}")
        fph = sum(1 for g in fixture if g["winner_berth_status"]=="berth_award"
                  and _phase(g)=="PRIMARY")
        if p and fph != int(p["observed_first_place_event_slots"]):
            errors.append(f"observed first-place awards differ from Stage17 route counts: {group}")
        counter=Counter(r["transition_kind"] for r in related)
        summary.append({
            "season":season,"district_code":district,
            "stage_group_id":fixture[0]["stage_group_id"] if fixture else "",
            "fixture_count":str(len(fixture)),
            "distinct_team_or_joint_entry_count":str(len(matched_teams.get(group,()))),
            "observed_transitions":str(len(related)),
            "primary_winner_continuation":str(counter["WIN_PRIMARY_TO_PRIMARY"]),
            "primary_loser_to_repechage":str(counter["LOSS_PRIMARY_TO_REPECHAGE"]),
            "repechage_winner_continuation":str(counter["WIN_REPECHAGE_TO_REPECHAGE"]),
            "repechage_loser_continuation":str(counter["LOSS_REPECHAGE_TO_REPECHAGE"]),
            "observed_block_label_changes":str(sum(
                r["block_hint_changed"]=="yes" for r in related
            )),
            "qualification_award_wins":str(awards[group]),
            "source_scope":"secondary_result_chronological_team_sequence",
            "official_pdf_draw_graph_verified":"no",
        })
    second=[]
    for edge in edges:
        if edge["transition_kind"] != "LOSS_REPECHAGE_TO_REPECHAGE":
            continue
        f,t=by_id[edge["from_match_id"]],by_id[edge["to_match_id"]]
        second.append({
            "special_case_id":"HSR2026"+str(len(second)+1).zfill(3),
            "season":edge["season"],"district_code":edge["district_code"],
            "school_display_name":edge["school_display_name"],
            "first_qualification_decider_loss_id":edge["from_match_id"],
            "first_match_date":edge["from_match_date"],
            "first_match_winner":f["winner_name"],
            "first_match_score":f["team1_score"]+"-"+f["team2_score"],
            "second_qualification_decider_id":edge["to_match_id"],
            "second_match_date":edge["to_match_date"],
            "second_match_winner":t["winner_name"],
            "second_match_score":t["team1_score"]+"-"+t["team2_score"],
            "second_match_winner_has_berth_award":(
                "yes" if t["winner_berth_status"]=="berth_award" else "no"
            ),
            "evidence_transition_id":edge["transition_id"],
            "proven_same_team_next_game":"yes",
            "extra_gate_topology_from_pdf":"unverified",
            "source_url":t["source_url"],
        })
        if f["round_label"] not in ("予選敗者戦代表決定戦","anchor_verified_decider"):
            errors.append(f"second-chance case not a recorded representative decider: {f['match_id']}")
        if t["winner_berth_status"]!="berth_award":
            errors.append(f"second-chance game did not award a berth: {t['match_id']}")

    if {(
        x["season"],x["district_code"],x["school_display_name"],
        x["first_qualification_decider_loss_id"],x["second_qualification_decider_id"]
    ) for x in second} != SECOND_CHANCE_PAIRS:
        errors.append("six secondary-source after-loss representative-decider cases changed")
    return edges,summary,second,errors


def audit_2026_hiroshima_stage13e3g18(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    observed=_read(root,TRANSITION_FILE)
    totals=_read(root,SUMMARY_FILE)
    second_chances=_read(root,SECOND_CHANCE_FILE)
    expected,summary,special,errors=_expected_rows(root)
    for title,actual,want in (
        ("participant transition",observed,expected),
        ("district transition summary",totals,summary),
        ("after-loss second-chance",second_chances,special),
    ):
        if len(actual)!=len(want):
            errors.append(f"{title}: {len(actual)} records vs {len(want)} expected")
        for i,(got,correct) in enumerate(zip(actual,want),1):
            if got!=correct:
                wrong=[k for k in correct if got.get(k)!=correct[k]]
                errors.append(f"{title} row {i} mismatch: {wrong}")
                break

    counter=Counter(x["transition_kind"] for x in expected)
    if counter!=EXPECTED_FLOW:
        errors.append(f"223 source fixtures yielded unexpected observed transitions: {counter}")
    changed=sum(x["block_hint_changed"]=="yes" for x in expected)
    linked=sum(bool(x["target_publisher_route_id"]) for x in expected)
    if (len(expected)!=287 or len(summary)!=8 or len(special)!=6
        or changed!=10 or linked!=30):
        errors.append(f"transition topology count changed: {len(expected)}/{len(summary)}/{len(special)}, cross-block {changed}, event-linked {linked}")

    return {
        "ok":not errors, "errors":errors,
        "historical_secondary_fixture_count":223,
        "distinct_school_or_joint_team_seasonal_entries":159,
        "observed_match_to_match_transitions":len(expected),
        "transition_classification_counts":dict(counter),
        "loser_reaches_repechage_directly":counter["LOSS_PRIMARY_TO_REPECHAGE"],
        "loser_remains_in_repechage_after_decider_loss":counter["LOSS_REPECHAGE_TO_REPECHAGE"],
        "verified_after_loss_second_chance_examples":len(special),
        "annotated_publisher_event_transitions":linked,
        "block_display_label_changes":changed,
        "secondary_results_all_eight_districts_recorded":len(summary)==8,
        "official_federation_pdf_draw_edges_verified":0,
        "draw_accurate_runtime_transition_ready":False,
        "historical_games_pinned_to_simulation":False,
        "fmt025_optional_ranking_release_allowed":False,
        "verification_scope":"2026_secondary_result_observed_team_sequences_not_annual_draw",
    }
