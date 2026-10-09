"""Stage 13E-3G-39: separately evidenced 2026 Hiroshima west final 11 names.

The stage37/38 confirmed links remain immutable. A missing observation is
linked only via a reviewed, founder-aware legal school name to one active
2026 Hiroshima hardball program. Mere substring similarity cannot assign a
school ID. An unresolved candidate is left unlinked, not fabricated.

This validates identity of schools, NOT the 2026 official tournament draw,
loser arrows, ranking gates or eligibility for production FMT025 execution.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g37_school_master import (
    PREFECTURE_CODE, REFERENCE_YEAR,
    SCHOOL_MASTER_FILE, PROGRAM_MASTER_FILE,
    SchoolMasterPreviewError, SchoolMasterPreviewLink,
)
from .hiroshima_stage13e3g38_reviewed_aliases import (
    audit_2026_hiroshima_stage13e3g38,
    load_2026_hiroshima_west_school_links_stage38,
)

REVIEW_FILE = "research/2026/hiroshima_west_remaining11_official_name_candidates_stage13e3g39.csv"
VERIFIED_IDS_FILE = "research/2026/hiroshima_west_verified_school_master_ids_stage13e3g39.csv"
OUTCOME = "externally_reviewed_unique_official_name_2026_stage39"
DECISION = "reviewed_official_name_candidate_only"
PROOF_SCOPE = "not_2026_federation_draw_confirmation"
MATCH_URL = "https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ"
PREF_URL = "https://www.pref.hiroshima.lg.jp/site/kyouiku/14map-koukoumap-fr-tiku.html"
CITY_URL = "https://www.city.hiroshima.lg.jp/kikaku/houki/reiki_int/reiki_honbun/r500RG00000672.html"
PRIVATE_URL = "https://www.pref.hiroshima.lg.jp/soshiki/44/jugyouryoukeigen.html"
EXPECTED = {
    "五日市": ("広島県立五日市高等学校", "prefectural", PREF_URL),
    "修道": ("修道高等学校", "private", PRIVATE_URL),
    "基町": ("広島市立基町高等学校", "municipal", CITY_URL),
    "大竹": ("広島県立大竹高等学校", "prefectural", PREF_URL),
    "崇徳": ("崇徳高等学校", "private", PRIVATE_URL),
    "広島井口": ("広島県立広島井口高等学校", "prefectural", PREF_URL),
    "広島観音": ("広島県立広島観音高等学校", "prefectural", PREF_URL),
    "廿日市": ("広島県立廿日市高等学校", "prefectural", PREF_URL),
    "廿日市西": ("広島県立廿日市西高等学校", "prefectural", PREF_URL),
    "美鈴が丘": ("広島市立美鈴が丘高等学校", "municipal", CITY_URL),
    "舟入": ("広島市立舟入高等学校", "municipal", CITY_URL),
}


@dataclass(frozen=True)
class Stage39SchoolMasterReport:
    links: dict[str, SchoolMasterPreviewLink]
    evidence_reviewed: int
    newly_matched: tuple[str, ...]
    candidates_unmatched: tuple[str, ...]


def resolve_stage39_reviewed_master_links(
    *,
    prior_links: dict[str, SchoolMasterPreviewLink],
    evidence_rows: list[dict[str, str]],
    school_master: list[dict[str, str]],
    hardball_programs: list[dict[str, str]],
) -> Stage39SchoolMasterReport:
    """Fail closed for forged evidence; hold unmatched/ambiguous schools."""
    if len(prior_links) != 18 or set(EXPECTED) - set(prior_links):
        raise SchoolMasterPreviewError("Stage39 requires Stage38's full 18 observed school identities")
    if len(evidence_rows) != len(EXPECTED):
        raise SchoolMasterPreviewError("exactly eleven reviewed school names required")
    keyed = {}
    required = {
        "observed_name", "proposed_master_official_name",
        "prefecture_code", "reference_year", "founder_category",
        "publication_alias_url", "school_authority_url",
        "decision", "proof_scope",
    }
    for row in evidence_rows:
        name = row.get("observed_name")
        if name not in EXPECTED or name in keyed or set(row) != required:
            raise SchoolMasterPreviewError("unexpected, duplicate or incomplete school review")
        legal, founder, source = EXPECTED[name]
        expected = {
            "observed_name":name,
            "proposed_master_official_name":legal,
            "prefecture_code":PREFECTURE_CODE,
            "reference_year":REFERENCE_YEAR,
            "founder_category":founder,
            "publication_alias_url":MATCH_URL,
            "school_authority_url":source,
            "decision":DECISION,
            "proof_scope":PROOF_SCOPE,
        }
        if row != expected:
            raise SchoolMasterPreviewError("year/founder/legal school name/source changed")
        keyed[name] = row
    if set(keyed) != set(EXPECTED):
        raise SchoolMasterPreviewError("incomplete evidence coverage for 11 observations")

    ids = set()
    official_to_rows: dict[str, list[dict[str, str]]] = {}
    for row in school_master:
        school_id = row.get("school_id","")
        if not school_id or school_id in ids:
            raise SchoolMasterPreviewError("school master has duplicate or empty ID")
        ids.add(school_id)
        if row.get("prefecture_code") == PREFECTURE_CODE:
            official_to_rows.setdefault(row.get("official_name",""),[]).append(row)
    program_by_school: dict[str,list[dict[str,str]]] = {}
    for p in hardball_programs:
        if (p.get("reference_year") == REFERENCE_YEAR
                and p.get("discipline") == "hardball"
                and p.get("membership_status") == "active"):
            program_by_school.setdefault(p["school_id"],[]).append(p)

    out = dict(prior_links)
    used_ids = {p.school_id for p in prior_links.values() if p.school_id}
    if len(used_ids) != sum(bool(p.school_id) for p in prior_links.values()):
        raise SchoolMasterPreviewError("Stage38 prior confirmed IDs collide")
    matched,held=[],[]
    for name,(legal,founder,url) in EXPECTED.items():
        prior = prior_links[name]
        if prior.authorized_for_read_only_detail:
            if (prior.official_name != legal or prior.school_id not in used_ids
                    or prior.prefecture_code != PREFECTURE_CODE):
                raise SchoolMasterPreviewError("Stage39 cannot override an existing verified name")
            continue
        matches = official_to_rows.get(legal,[])
        if len(matches) != 1:
            held.append(name)
            continue
        school = matches[0]
        school_id = school["school_id"]
        programs = program_by_school.get(school_id,[])
        if (school_id in used_ids or len(programs) != 1
                or not programs[0].get("program_id")):
            held.append(name)
            continue
        out[name]=SchoolMasterPreviewLink(
            observed_name=name,
            resolution_status=OUTCOME,
            school_id=school_id,
            official_name=legal,
            federation_name=school.get("federation_name",""),
            program_id=programs[0]["program_id"],
            prefecture_code=PREFECTURE_CODE,
            source=url,
            authorized_for_read_only_detail=True,
        )
        used_ids.add(school_id)
        matched.append(name)
    if len(used_ids) != sum(bool(link.school_id) for link in out.values()):
        raise SchoolMasterPreviewError("resolved IDs collided after Stage39 overlay")
    return Stage39SchoolMasterReport(
        links=out,
        evidence_reviewed=len(keyed),
        newly_matched=tuple(matched),
        candidates_unmatched=tuple(held),
    )


def load_2026_hiroshima_west_school_links_stage39(
    data_dir: str | Path,
) -> Stage39SchoolMasterReport:
    root = Path(data_dir)
    return resolve_stage39_reviewed_master_links(
        prior_links=load_2026_hiroshima_west_school_links_stage38(root).links,
        evidence_rows=_read(root,REVIEW_FILE),
        school_master=_read(root,SCHOOL_MASTER_FILE),
        hardball_programs=_read(root,PROGRAM_MASTER_FILE),
    )


def audit_2026_hiroshima_stage13e3g39(data_dir: str | Path) -> dict:
    root=Path(data_dir)
    previous=audit_2026_hiroshima_stage13e3g38(root)
    errors=[] if previous["ok"] else ["Stage38 previously verified school linkage failed"]
    record=load_2026_hiroshima_west_school_links_stage39(root)
    links=record.links
    verified={key:value.school_id for key,value in links.items()
              if value.authorized_for_read_only_detail}
    if len(links)!=18 or len(set(verified.values()))!=len(verified):
        errors.append("Stage39 missing schools or duplicate IDs")
    for name,sid in previous["verified_map"].items():
        if verified.get(name) != sid:
            errors.append(f"Stage39 altered previously verified school: {name}")
    if (len(set(record.newly_matched)&set(previous["verified_map"])) != 0
            or len(record.newly_matched)+len(record.candidates_unmatched) != len(EXPECTED)):
        errors.append("Stage39 new-vs-held school counts inconsistent")
    if any(x.official_2026_draw_verified or x.live_fmt025_runtime_enabled
           for x in links.values()):
        errors.append("school identity evidence cannot unblock production FMT025")
    registered = _read(root, VERIFIED_IDS_FILE)
    indexed = {row["observed_name"]: row for row in registered}
    prior37 = {"山陽","広島城北"}
    prior38 = {"修大協創","広島工大","宮島工","広島商","広島国泰寺"}
    if len(registered) != 18 or len(indexed) != 18 or set(indexed) != set(links):
        errors.append("all 18 distinct school identities must be recorded")
    for name, sid in verified.items():
        row = indexed.get(name,{})
        expected_stage = (
            "stage37" if name in prior37 else
            "stage38" if name in prior38 else "stage39"
        )
        if (row.get("school_id") != sid
                or row.get("verification_stage") != expected_stage
                or row.get("reference_year") != REFERENCE_YEAR
                or row.get("verification_basis") !=
                    "ci_verified_unique_2026_active_hardball_master"):
            errors.append(f"verified ID record changed for {name}")
    if set(verified) != set(indexed):
        errors.append("verified master list cannot omit or invent a school")
    return {
        "ok":not errors,"errors":errors,
        "2026_west_observed_names":len(links),
        "previously_verified_school_ids":previous["total_verified_master_ids"],
        "reviewed_11_name_candidates":record.evidence_reviewed,
        "newly_verified_names":list(record.newly_matched),
        "candidate_names_held":list(record.candidates_unmatched),
        "total_uniquely_verified_master_ids":len(verified),
        "remaining_unverified_names":sorted(set(links)-set(verified)),
        "verified_school_id_map":verified,
        "original_master_modified":False,
        "sqlite_written":False,
        "windows_gui_visual_verified":False,
        "official_2026_west_match_numbers_verified":0,
        "official_2026_west_loser_transfer_arrows_verified":0,
        "official_2026_8_region_season_route_requirements_unverified":48,
        "live_fmt025_enabled":False,
        "optional_ranking_enabled":False,
    }
