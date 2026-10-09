"""Stage13E-3G-38: strictly reviewed name->master aliases for Hiroshima west.

Stage37's exact federation-name or previously vetted alias mapping stays
unchanged. An evidence row reviewed for a *specific official school name*
may resolve an otherwise unmapped observation ONLY when that unique
2026 active Hiroshima hardball school is in the checked-in master.

No fuzzy matching, name similarity, guessable school IDs, or FMT025 release.
A master name mismatch remains unresolved, never upgraded by assertion.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g37_school_master import (
    SCHOOL_MASTER_FILE, PROGRAM_MASTER_FILE, SCHOOL_LEDGER_FILE,
    SchoolMasterPreviewLink, SchoolMasterPreviewError,
    PREFECTURE_CODE, REFERENCE_YEAR,
    load_2026_hiroshima_west_school_links,
    observed_autumn_west_names, NODES_FILE,
    audit_2026_hiroshima_stage13e3g37,
)

EVIDENCE_FILE = "research/2026/hiroshima_west_reviewed_official_name_candidates_stage13e3g38.csv"
STAGE38_MATCH = "externally_reviewed_unique_official_name_2026"
CANDIDATE_SCOPE = "not_2026_federation_draw_confirmation"
DECISION = "reviewed_official_name_candidate_only"
HOLD = "unresolved_candidate_master_name_or_program"
EXPECTED_NAMES = (
    "修大協創", "広島工大", "宮島工", "広島商", "広島国泰寺",
)
EXPECTED_SOURCES = {
    "修大協創": (
        "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ",
        "https://www.shudo-u.ac.jp/fuzoku/news/2026OS2_high.html",
        "広島修道大学ひろしま協創高等学校",
    ),
    "広島工大": (
        "https://www.hb-nippon.com/teams/3737/games",
        "https://www.kodaikoko.ed.jp/zennichi/",
        "広島工業大学高等学校",
    ),
    "宮島工": (
        "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ",
        "https://www.pref.hiroshima.lg.jp/site/kyouiku/14map-koukoumap-fr-katei.html",
        "広島県立宮島工業高等学校",
    ),
    "広島商": (
        "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ",
        "https://www.pref.hiroshima.lg.jp/site/kyouiku/14map-koukoumap-fr-katei.html",
        "広島県立広島商業高等学校",
    ),
    "広島国泰寺": (
        "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ",
        "https://www.hiroshima-koup.org/member-school/",
        "広島県立広島国泰寺高等学校",
    ),
}


@dataclass(frozen=True)
class Stage38ReviewedMasterReport:
    links: dict[str, SchoolMasterPreviewLink]
    reviewed_name_count: int
    newly_resolved_by_review: tuple[str, ...]
    candidate_names_not_found_in_master: tuple[str, ...]


def resolve_stage38_reviewed_master_links(
    *,
    prior_links: dict[str, SchoolMasterPreviewLink],
    review_rows: list[dict[str, str]],
    school_master: list[dict[str, str]],
    hardball_programs: list[dict[str, str]],
) -> Stage38ReviewedMasterReport:
    """Overlay only verifiable unique active hardball school names."""
    if set(prior_links) == set() or len(prior_links) != 18:
        raise SchoolMasterPreviewError("must start with 18 Stage37 observed names")
    if len(review_rows) != len(EXPECTED_NAMES):
        raise SchoolMasterPreviewError("five independently reviewed school-name candidates required")
    checked: dict[str, dict[str, str]] = {}
    for row in review_rows:
        name = row.get("observed_name","")
        if name in checked or name not in EXPECTED_SOURCES or name not in prior_links:
            raise SchoolMasterPreviewError("duplicate, invented or out-of-scope alias candidate")
        pub, official, official_name = EXPECTED_SOURCES[name]
        if any((
            row.get("proposed_master_official_name") != official_name,
            row.get("prefecture_code") != PREFECTURE_CODE,
            row.get("reference_year") != REFERENCE_YEAR,
            row.get("publication_alias_url") != pub,
            row.get("school_official_url") != official,
            row.get("decision") != DECISION,
            row.get("proof_scope") != CANDIDATE_SCOPE,
        )):
            raise SchoolMasterPreviewError("candidate's 2026 provenance or approved official name changed")
        checked[name] = row
    if set(checked) != set(EXPECTED_NAMES):
        raise SchoolMasterPreviewError("not all five reviewed candidates are present")

    by_official: dict[str, list[dict[str, str]]] = {}
    school_ids: set[str] = set()
    for school in school_master:
        sid = school.get("school_id","")
        if not sid or sid in school_ids:
            raise SchoolMasterPreviewError("duplicate/empty school_id in official master")
        school_ids.add(sid)
        if school.get("prefecture_code") == PREFECTURE_CODE:
            by_official.setdefault(school.get("official_name",""),[]).append(school)
    programs: dict[str, list[dict[str,str]]] = {}
    for program in hardball_programs:
        if (program.get("reference_year") == REFERENCE_YEAR
                and program.get("discipline") == "hardball"
                and program.get("membership_status") == "active"):
            programs.setdefault(program["school_id"], []).append(program)
    out = dict(prior_links)
    newly = []
    pending = []
    used = {link.school_id for link in prior_links.values() if link.school_id}
    for name in EXPECTED_NAMES:
        # Preverified Stage37 link always takes precedence. Stage38 cannot
        # silently replace it even if a reviewed candidate suggests another.
        if prior_links[name].authorized_for_read_only_detail:
            candidate = prior_links[name]
            if candidate.official_name != checked[name]["proposed_master_official_name"]:
                raise SchoolMasterPreviewError("reviewed candidate differs from existing verified school")
            continue
        matches = by_official.get(checked[name]["proposed_master_official_name"], [])
        if len(matches) != 1:
            pending.append(name)
            continue
        master = matches[0]
        sid = master["school_id"]
        p = programs.get(sid, [])
        if len(p) != 1 or sid in used or not p[0].get("program_id"):
            pending.append(name)
            continue
        # No database mutation: this is a view-time school link.
        link = SchoolMasterPreviewLink(
            observed_name=name, resolution_status=STAGE38_MATCH,
            school_id=sid,
            official_name=master["official_name"],
            federation_name=master.get("federation_name",""),
            program_id=p[0]["program_id"], prefecture_code=PREFECTURE_CODE,
            source=checked[name]["school_official_url"],
            authorized_for_read_only_detail=True,
        )
        out[name] = link
        used.add(sid)
        newly.append(name)
    if len(used) != sum(bool(link.school_id) for link in out.values()):
        raise SchoolMasterPreviewError("duplicate resolved master link")
    return Stage38ReviewedMasterReport(
        links=out,
        reviewed_name_count=len(checked),
        newly_resolved_by_review=tuple(newly),
        candidate_names_not_found_in_master=tuple(pending),
    )


def load_2026_hiroshima_west_school_links_stage38(
    data_dir: str | Path,
) -> Stage38ReviewedMasterReport:
    root=Path(data_dir)
    return resolve_stage38_reviewed_master_links(
        prior_links=load_2026_hiroshima_west_school_links(root),
        review_rows=_read(root,EVIDENCE_FILE),
        school_master=_read(root,SCHOOL_MASTER_FILE),
        hardball_programs=_read(root,PROGRAM_MASTER_FILE),
    )


def audit_2026_hiroshima_stage13e3g38(data_dir: str | Path) -> dict:
    root=Path(data_dir)
    prev=audit_2026_hiroshima_stage13e3g37(root)
    errors=[] if prev["ok"] else ["Stage37 strict baseline school ID evidence failed"]
    reviewed=load_2026_hiroshima_west_school_links_stage38(root)
    links=reviewed.links
    verified={name:link.school_id for name,link in links.items()
              if link.authorized_for_read_only_detail}
    if len(links)!=18 or len(set(verified.values()))!=len(verified):
        errors.append("wrong school counts or duplicated IDs after Stage38 overlay")
    if len(verified)<prev["resolved_unique_school_ids"]:
        errors.append("Stage38 regressed previously verified school identities")
    for name,sid in prev["links"].items():
        if verified.get(name)!=sid:
            errors.append("Stage38 modified an already verified Stage37 school")
    if (not all(not link.official_2026_draw_verified and
                not link.live_fmt025_runtime_enabled for link in links.values())):
        errors.append("master link cannot authorize a federation bracket")
    return {
        "ok":not errors, "errors":errors,
        "observed_school_count":len(links),
        "prior_verified_count":prev["resolved_unique_school_ids"],
        "reviewed_new_official_name_candidates":reviewed.reviewed_name_count,
        "newly_resolved_names":list(reviewed.newly_resolved_by_review),
        "candidate_names_not_found_in_master":list(reviewed.candidate_names_not_found_in_master),
        "total_verified_master_ids":len(verified),
        "still_unresolved_names":sorted(set(links)-set(verified)),
        "verified_map":verified,
        "master_or_program_mutated":False,
        "sqlite_written":False,
        "official_2026_west_numbered_arrows_verified":0,
        "official_2026_eight_group_route_claims_unresolved":48,
        "live_fmt025_enabled":False,
        "optional_ranking_enabled":False,
        "windows_native_gui_visual_checked":False,
    }
