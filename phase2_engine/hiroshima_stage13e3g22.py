"""Stage13E-3G-22: one-district evidence audit for 2026 Hiroshima autumn west.

SportsOnline lists the members of all nine child events; secondary dated
results list all 25 matches. These jointly prove 2026 participant continuity
and actual award winners, but do not prove a 2026 federation-authored draw.
A readable original 2025 west federation draw is a *different year*, with a
different repechage gate topology; its routes must NEVER be silently imported.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g17 import CROSSWALK_FILE, GROUP_CONTRACT_FILE
from .hiroshima_stage13e3g18 import TRANSITION_FILE
from .hiroshima_qualification_timeline_2026 import TIMELINE_FILE

PUBLISHER_GROUPS_FILE = "competitions/2026/hiroshima_autumn_west_publisher_team_groups_2026.csv"
PRIOR_YEAR_PDF_FILE = "research/2026/hiroshima_west_official_2025_bracket_comparison.csv"
_GROUP = ("autumn", "west")
_SOURCE = "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ"
_PRIOR_PDF = "https://hiroshima-hbf1950.com/img/file509.pdf"
_PRIMARY_MATCHES = {
    "A":("HR20260044","HT20260068","広島商"),
    "B":("HR20260046","HT20260069","山陽"),
    "C":("HR20260048","HT20260071","広島国泰寺"),
    "D":("HR20260050","HT20260073","崇徳"),
}
_SECONDARY_MATCHES = {
    "A":("HR20260045","HT20260035","広島井口",True),
    "B":("HR20260047","HT20260070","基町",True),
    "C":("HR20260049","HT20260182","広島工大",False),
    "D":("HR20260051","HT20260183","広島城北",False),
}
_CROSS_MATCH = ("HR20260052","HT20260072","広島工大")
_CANONICAL_ALIASES = {
    "広島商業":"広島商", "宮島工業":"宮島工", "工大高":"広島工大",
}
_EXPECTED_ZONE_SIZES = {"A":5,"B":5,"C":4,"D":4}


def _canonical(label: str) -> str:
    return _CANONICAL_ALIASES.get(label,label)


def audit_2026_hiroshima_stage13e3g22(data_dir: str | Path) -> dict:
    root=Path(data_dir)
    roster=_read(root,PUBLISHER_GROUPS_FILE)
    previous=_read(root,PRIOR_YEAR_PDF_FILE)
    games=_read(root,TIMELINE_FILE)
    named_routes=_read(root,CROSSWALK_FILE)
    stages=_read(root,GROUP_CONTRACT_FILE)
    observed=_read(root,TRANSITION_FILE)
    errors: list[str]=[]

    west_games=[x for x in games if (x["season"],x["district_code"])==_GROUP]
    by_game={x["match_id"]:x for x in west_games}
    by_route={x["route_id"]:x for x in named_routes}
    west_roster=[x for x in roster if (x["season"],x["district_code"])==_GROUP]
    group={x["phase_execution_role"]+":"+x["zone_scope"]:x for x in west_roster}
    if len(west_games)!=25 or len(by_game)!=25:
        errors.append("2026 autumn west historical 25 fixtures required")
    if len(roster)!=9 or len(west_roster)!=9 or len(group)!=9:
        errors.append("nine unique SportsOnline autumn west child events required")
    if len(previous)!=1:
        errors.append("one prior-year official PDF evidence record required")
    all_primary=set()
    all_secondaries=set()
    primary_winners=set()
    secondary_winners={}
    placeholder_total=0

    for idx,row in enumerate(roster,1):
        key=row["phase_execution_role"]+":"+row["zone_scope"]
        source=by_route.get(row["published_route_id"])
        if (
            row["event_audit_id"]!="HAW2026"+str(idx).zfill(3)
            or row["competition_id"]!="CMP000136"
            or row["stage_group_id"]!="SGR000144"
            or not source
            or (source["season"],source["district_code"])!=_GROUP
            or source["phase_execution_role"]!=row["phase_execution_role"]
            or row["publisher_participants_display"]==""
            or row["source_url"]!=_SOURCE
            or row["source_role"]!="secondary_tournament_publisher_event_index"
            or row["official_2026_federation_pdf_body_checked"]!="no"
            or row["annual_generic_transfer_rule_proven"]!="no"
            or row["live_runtime_enabled"]!="no"
        ):
            errors.append(f"wrong publisher identity, provenance or release status: {key}")
        originals=row["publisher_participants_display"].split(";")
        normalized=row["normalized_real_team_names"].split(";")
        real=[_canonical(s) for s in originals if s!="ダミー"]
        dummy=sum(s=="ダミー" for s in originals)
        placeholder_total+=dummy
        if (
            real!=normalized
            or any(not x for x in real)
            or len(set(real))!=len(real)
            or len(real)!=int(row["real_participant_count"])
            or dummy!=int(row["publisher_placeholder_count"])
            or dummy not in (0,1)
            or row["published_window_start"]>row["published_window_end"]
        ):
            errors.append(f"alias/dummy normalization or window changed: {key}")
        match=by_game.get(row["observed_decider_match_id"])
        if match is None:
            errors.append(f"publisher decisive match not in 25 results: {key}")
        elif not ({match["team1_name"],match["team2_name"]} <= set(normalized)):
            errors.append(f"publisher child final participants not in child event roster: {key}")

    for z,(route_id,match_id,winner) in _PRIMARY_MATCHES.items():
        r=group.get("PRIMARY:"+z)
        if not r or r["published_route_id"]!=route_id or r["observed_decider_match_id"]!=match_id:
            errors.append(f"primary route missing or reassigned: {z}")
            continue
        teams=set(r["normalized_real_team_names"].split(";"))
        if len(teams)!=_EXPECTED_ZONE_SIZES[z] or all_primary & teams:
            errors.append(f"initial entrants repeat across primary zones: {z}")
        all_primary |= teams
        result=by_game.get(match_id)
        if not result or result["winner_name"]!=winner or result["winner_berth_status"]!="berth_award":
            errors.append(f"historical one-place qualifier winner changed: {z}")
        primary_winners.add(winner)
    if len(all_primary)!=18 or len(primary_winners)!=4:
        errors.append("2026 west four primary zones should contain 18 unique entrants and 4 champions")

    for z,(route_id,match_id,winner,award) in _SECONDARY_MATCHES.items():
        r=group.get("REPECHAGE_ZONE:"+z)
        p=group.get("PRIMARY:"+z)
        if not r or not p or r["published_route_id"]!=route_id or r["observed_decider_match_id"]!=match_id:
            errors.append(f"second-place route missing or reassigned: {z}")
            continue
        second=set(r["normalized_real_team_names"].split(";"))
        primary=set(p["normalized_real_team_names"].split(";"))
        primary_champion=_PRIMARY_MATCHES[z][2]
        if second!=primary-{primary_champion} or second & all_secondaries:
            errors.append(f"published losing cohort differs from exactly primary nonwinners: {z}")
        all_secondaries |= second
        result=by_game.get(match_id)
        if not result or result["winner_name"]!=winner or (result["winner_berth_status"]=="berth_award")!=award:
            errors.append(f"2026 observed second-place winner or award status changed: {z}")
        secondary_winners[z]=winner
    if len(all_secondaries)!=14 or all_secondaries!=all_primary-primary_winners:
        errors.append("four runnerup rosters must contain all and only the 14 primary nonwinners")

    cross=group.get("REPECHAGE_CROSS_ZONE_GATE:C;D")
    rid,mid,winner=_CROSS_MATCH
    if not cross or cross["published_route_id"]!=rid or cross["observed_decider_match_id"]!=mid:
        errors.append("sole 2026 C/D cross-zone berth game missing")
    elif set(cross["normalized_real_team_names"].split(";"))!={secondary_winners.get("C"),secondary_winners.get("D")}:
        errors.append("2026 C/D cross game should contain the two observed second-place winners")
    game=by_game.get(mid)
    if not game or game["winner_name"]!=winner or game["winner_berth_status"]!="berth_award":
        errors.append("2026 C/D observed final berth award changed")
    recorded_awards={x["winner_name"] for x in west_games if x["winner_berth_status"]=="berth_award"}
    expected_awards=primary_winners | {secondary_winners.get("A"),secondary_winners.get("B"),winner}
    if recorded_awards!=expected_awards or len(recorded_awards)!=7:
        errors.append("2026 autumn west must award exactly 4 primary + 2 direct runnerup + 1 C/D final")

    west=next((r for r in stages if r["stage_group_id"]=="SGR000144"),None)
    if not west or west["required_qualifier_awards"]!="7" or west["direct_main_exempt_slots"]!="0":
        errors.append("existing 2026 autumn west quota changed")
    actual_first_loser={r["school_display_name"] for r in observed if (
        r["season"],r["district_code"],r["transition_kind"]
    )==("autumn","west","LOSS_PRIMARY_TO_REPECHAGE")}
    if len(actual_first_loser)!=14 or actual_first_loser!=all_secondaries:
        errors.append("2026 all 14 primary losers must have observed continued game")

    if previous:
        doc=previous[0]
        fields={
            "prior_year":"2025","prior_season":"autumn","district_code":"west",
            "federation_document_url":_PRIOR_PDF,
            "pdf_body_inspected":"yes",
            "official_2025_primary_zone_count":"4",
            "official_2025_second_place_zone_count":"4",
            "official_2025_cross_zone_gate_27":"winner_A2_vs_winner_B2",
            "official_2025_cross_zone_gate_28":"winner_C2_vs_winner_D2",
            "official_2025_final_seventh_berth_gate_29":"loser_27_vs_loser_28",
            "prior_year_source_scope":"official_2025_draw_pdf_image_and_text",
            "comparison_year":"2026",
            "publisher_2026_cross_zone_decider_events":"1",
            "observed_2026_ab_second_place_direct_awards":"2",
            "observed_2026_cd_cross_zone_berth_awards":"1",
            "prior_year_graph_reusable_for_2026":"no",
            "same_draw_topology_between_years":"no",
            "target_year_official_2026_pdf_body_inspected":"no",
            "runtime_full_graph_release_allowed":"no",
        }
        for k,v in fields.items():
            if doc.get(k)!=v:
                errors.append(f"prior-year official bracket evidence claim is unsupported: {k}")

    return {
        "ok":not errors,"errors":errors,
        "2026_autumn_west_pub_child_events":len(roster),
        "2026_autumn_west_source_games":len(west_games),
        "2026_initial_publisher_team_entries":len(all_primary),
        "2026_published_primary_losers_in_second_place_events":len(all_secondaries),
        "2026_primary_losers_with_observed_next_game":len(actual_first_loser),
        "2026_publisher_placeholder_entries":placeholder_total,
        "2026_primary_awards":len(primary_winners),
        "2026_secondary_direct_awards":2,
        "2026_secondary_cd_cross_awards":1,
        "2026_total_qualified":len(recorded_awards),
        "2025_official_bracket_pdf_checked":len(previous)==1,
        "2025_official_cross_gate_count":3,
        "2026_publisher_named_cross_gate_count":1,
        "2025_draw_same_as_2026":False,
        "2026_official_bracket_pdf_body_inspected":0,
        "2026_official_draw_edges_confirmed":0,
        "2026_actual_team_trail_reconstructed":True,
        "annual_independent_fmt025_rules_approved":False,
        "active_fmt025_runtime_changed":False,
        "fmt025_optional_ranking_unlocked":False,
    }
