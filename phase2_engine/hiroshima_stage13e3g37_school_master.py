"""Stage 13E-3G-37: fail-closed read-only school master bridge for pilot GUI.

The Stage25 dated match record contains *school name strings*, not durable
school IDs. Resolve only an unambiguous exact 2026 Hiroshima federation
name or an already reviewed official-name alias with a matching current
master record and 2026 active hardball membership. Otherwise quarantine.

The resulting ID is an existing master key and is never inferred from a
substring, spelling similarity, prefecture-neutral match, or school order.
No annual FMT025 draw is authorized by this bridge.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .hiroshima_match_level_2026 import _read
from .hiroshima_stage13e3g25 import NODES_FILE, audit_2026_hiroshima_stage13e3g25

SCHOOL_LEDGER_FILE = "research/2026/hiroshima_autumn_west_school_master_review_stage13e3g37.csv"
SCHOOL_MASTER_FILE = "master/schools.csv"
PROGRAM_MASTER_FILE = "master/baseball_programs.csv"
REVIEWED_ALIASES_FILE = "competitions/2026/post_qualification_rank_school_aliases.csv"
PREFECTURE_CODE = "34"
REFERENCE_YEAR = "2026"
EXACT = "exact_2026_federation_name"
REVIEWED = "existing_reviewed_alias"
UNRESOLVED = "unresolved_no_safe_unique_2026_master_link"
AMBIGUOUS = "ambiguous_do_not_link"
WRONG_MASTER = "invalid_reviewed_alias_do_not_link"


@dataclass(frozen=True)
class SchoolMasterPreviewLink:
    observed_name: str
    resolution_status: str
    school_id: str
    official_name: str
    federation_name: str
    program_id: str
    prefecture_code: str
    source: str
    authorized_for_read_only_detail: bool
    official_2026_draw_verified: bool = False
    live_fmt025_runtime_enabled: bool = False


class SchoolMasterPreviewError(ValueError):
    """Source was modified, school had no verified key, or mapping is unsafe."""


def _unique_index(rows: list[dict], key: str, source: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for item in rows:
        value = item[key]
        if not value or value in index:
            raise SchoolMasterPreviewError(f"missing/duplicate {key} in {source}: {value}")
        index[value] = item
    return index


def observed_autumn_west_names(nodes: list[dict]) -> tuple[str, ...]:
    if len(nodes) != 25:
        raise SchoolMasterPreviewError("exactly 25 secondary observations required")
    names: set[str] = set()
    for record in nodes:
        if (record.get("competition_id") != "CMP000136"
                or record.get("stage_group_id") != "SGR000144"
                or record.get("season") != "autumn"
                or record.get("district_code") != "west"):
            raise SchoolMasterPreviewError("school name observation from another season/group")
        for field in ("team1_name", "team2_name"):
            name = record[field]
            if not name:
                raise SchoolMasterPreviewError("empty observed school name")
            names.add(name)
    if len(names) != 18:
        raise SchoolMasterPreviewError("2026 autumn west requires 18 distinct observed schools")
    return tuple(sorted(names))


def resolve_2026_hiroshima_school_links(
    *,
    observations: tuple[str, ...],
    school_master: list[dict],
    hardball_programs: list[dict],
    reviewed_aliases: list[dict],
    evidence_rows: list[dict],
) -> dict[str, SchoolMasterPreviewLink]:
    """Pure resolver; ambiguous, stale or nonmember candidates stay unlinked."""
    if (not observations or len(set(observations)) != len(observations)
            or any(not isinstance(n,str) or not n for n in observations)):
        raise SchoolMasterPreviewError("observed names must be unique nonempty strings")
    schools = _unique_index(school_master, "school_id", "master schools")
    reviews: dict[str, dict] = {}
    for review in evidence_rows:
        observed = review.get("observed_name","")
        if observed in reviews or not observed:
            raise SchoolMasterPreviewError("duplicate/empty observed name in Stage37 ledger")
        if (review.get("prefecture_code") != PREFECTURE_CODE
                or review.get("reference_year") != REFERENCE_YEAR
                or review.get("master_identity_status") not in (
                    "previously_reviewed_alias_reference",
                    "require_exact_federation_name_or_unresolved"
                )):
            raise SchoolMasterPreviewError("Stage37 year/prefecture/review type was altered")
        expected_alias = review.get("reviewed_alias_school_id","")
        expected_source = review.get("reviewed_alias_source","")
        if expected_alias and (
            expected_source != "post_qualification_rank_school_aliases.csv"
            or review["master_identity_status"] != "previously_reviewed_alias_reference"
        ):
            raise SchoolMasterPreviewError("alias ID lacks explicit prior-reviewed provenance")
        if not expected_alias and (expected_source or
                                  review["master_identity_status"] != "require_exact_federation_name_or_unresolved"):
            raise SchoolMasterPreviewError("unreviewed mapping attempted to claim alias")
        reviews[observed] = review
    if set(reviews) != set(observations):
        raise SchoolMasterPreviewError("18 observed schools and review ledger differ")

    relevant_aliases: dict[str, dict] = {}
    for alias in reviewed_aliases:
        if alias.get("prefecture_code") != PREFECTURE_CODE:
            continue
        observed = alias["observed_name"]
        if observed in relevant_aliases:
            raise SchoolMasterPreviewError("duplicated reviewed Hiroshima aliases")
        relevant_aliases[observed] = alias
    allowed_programs: dict[str, list[dict]] = {}
    for program in hardball_programs:
        if (program.get("reference_year") == REFERENCE_YEAR
                and program.get("discipline") == "hardball"
                and program.get("membership_status") == "active"):
            allowed_programs.setdefault(program["school_id"], []).append(program)
    for sid, members in allowed_programs.items():
        if len(members) != 1:
            raise SchoolMasterPreviewError(f"nonunique 2026 hardball program for {sid}")

    direct: dict[str,list[dict]] = {}
    for school in school_master:
        if school.get("prefecture_code") != PREFECTURE_CODE:
            continue
        fedname = school.get("federation_name","")
        if fedname:
            direct.setdefault(fedname, []).append(school)

    results = {}
    for name in observations:
        review = reviews[name]
        alias = relevant_aliases.get(name)
        reviewed_id = review["reviewed_alias_school_id"]
        exact_candidates = direct.get(name, [])
        source = ""
        candidates = []
        broken_review = False
        if reviewed_id:
            if (not alias or alias.get("school_id") != reviewed_id
                    or not reviewed_id.startswith("SCH")):
                broken_review = True
            else:
                item = schools.get(reviewed_id)
                if (not item or item.get("prefecture_code") != PREFECTURE_CODE
                        or item.get("official_name") != alias["master_official_name"]):
                    broken_review = True
                else:
                    candidates.append(item)
                    source = REVIEWED_ALIASES_FILE
        elif alias:
            # The alias is approved in the existing proof store, but it
            # cannot silently bypass the explicit Stage37 review ledger.
            broken_review = True
        if not broken_review:
            candidates.extend(exact_candidates)
        unique = {x["school_id"]:x for x in candidates}
        status = UNRESOLVED
        accepted = None
        if broken_review:
            status = WRONG_MASTER
        elif len(unique) > 1:
            status = AMBIGUOUS
        elif len(unique) == 1:
            candidate = next(iter(unique.values()))
            if candidate["school_id"] in allowed_programs:
                accepted = candidate
                status = (
                    EXACT if candidate.get("federation_name") == name
                    else REVIEWED
                )
            else:
                status = UNRESOLVED
        if accepted is None:
            results[name] = SchoolMasterPreviewLink(
                observed_name=name, resolution_status=status,
                school_id="", official_name="", federation_name="",
                program_id="", prefecture_code=PREFECTURE_CODE,
                source=source if broken_review else "", authorized_for_read_only_detail=False,
            )
            continue
        results[name] = SchoolMasterPreviewLink(
            observed_name=name, resolution_status=status,
            school_id=accepted["school_id"],
            official_name=accepted["official_name"],
            federation_name=accepted.get("federation_name",""),
            program_id=allowed_programs[accepted["school_id"]][0]["program_id"],
            prefecture_code=PREFECTURE_CODE,
            source=(SCHOOL_MASTER_FILE if status == EXACT else REVIEWED_ALIASES_FILE),
            authorized_for_read_only_detail=True,
        )
    # Never associate distinct observed schools with the same master ID:
    # aliases and exact names could collide on a name change.
    grouped: dict[str,list[str]] = {}
    for n, result in results.items():
        if result.school_id:
            grouped.setdefault(result.school_id,[]).append(n)
    for school_id, observed_names in grouped.items():
        if len(observed_names)>1:
            for n in observed_names:
                results[n]=SchoolMasterPreviewLink(
                    observed_name=n, resolution_status=AMBIGUOUS, school_id="",
                    official_name="", federation_name="", program_id="",
                    prefecture_code=PREFECTURE_CODE, source="",
                    authorized_for_read_only_detail=False,
                )
    return results


def load_2026_hiroshima_west_school_links(
    data_dir: str | Path,
) -> dict[str, SchoolMasterPreviewLink]:
    root = Path(data_dir)
    return resolve_2026_hiroshima_school_links(
        observations=observed_autumn_west_names(_read(root,NODES_FILE)),
        school_master=_read(root,SCHOOL_MASTER_FILE),
        hardball_programs=_read(root,PROGRAM_MASTER_FILE),
        reviewed_aliases=_read(root,REVIEWED_ALIASES_FILE),
        evidence_rows=_read(root,SCHOOL_LEDGER_FILE),
    )


def audit_2026_hiroshima_stage13e3g37(data_dir: str | Path) -> dict:
    root=Path(data_dir)
    previous=audit_2026_hiroshima_stage13e3g25(root)
    errors=[]
    if not previous["ok"]:
        errors.append("Stage25 dated secondary observations changed")
    nodes=_read(root,NODES_FILE)
    names=observed_autumn_west_names(nodes)
    rows=_read(root,SCHOOL_LEDGER_FILE)
    # Only two explicitly prior-reviewed aliases have been verified for
    # these 18 names. All other candidates must be exact master federation
    # names, otherwise they remain unlinked.
    known={"山陽":"SCH001774","広島城北":"SCH001777"}
    if len(rows)!=18:
        errors.append("Stage37 must review exactly 18 observed school names")
    for row in rows:
        want=known.get(row.get("observed_name"),"")
        if row.get("reviewed_alias_school_id") != want:
            errors.append("unexpected, missing or silently changed reviewed alias ID")
    links=load_2026_hiroshima_west_school_links(root)
    status_counts=Counter(x.resolution_status for x in links.values())
    eligible={name:link.school_id for name,link in links.items()
              if link.authorized_for_read_only_detail}
    if set(links)!=set(names):
        errors.append("observed schools do not match mapping review ledger")
    if len(set(eligible.values())) != len(eligible):
        errors.append("one official school ID was assigned to multiple observed names")
    if any(x.official_2026_draw_verified or x.live_fmt025_runtime_enabled for x in links.values()):
        errors.append("mapping must not unlock official draw or the runtime")
    for name, sid in known.items():
        if links[name].school_id != sid or not links[name].authorized_for_read_only_detail:
            errors.append(f"previously approved alias lost: {name}")
    return {
        "ok": not errors, "errors":errors,
        "observed_2026_west_schools":len(links),
        "resolved_unique_school_ids":len(eligible),
        "unresolved_or_ambiguous_school_names":sorted(set(links)-set(eligible)),
        "status_counts":dict(status_counts),
        "verified_prior_alias_ids":known,
        "links":eligible,
        "browse_sqlite_written":False,
        "future_waiting_school_ids_revealed":False,
        "official_individual_draw_verified":False,
        "live_fmt025_runtime_enabled":False,
        "optional_ranking_unlocked":False,
    }
