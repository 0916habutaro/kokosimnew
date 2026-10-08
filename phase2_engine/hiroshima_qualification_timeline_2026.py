"""Cautious 2026 Hiroshima district match timeline and evidence-limited berth locks.

The source fixture collection is a documented *sample*, not a complete
transcription of the eight federation PDFs. A missing lock is UNKNOWN:
not proof that the school has NOT qualified. Same-calendar-day fixtures
never count as post-lock merely on the basis of advertised start times.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .hiroshima_match_level_2026 import (
    ANCHOR_FILE, PRIOR_FILE, EXPECTED, SEASONS, _read,
    audit_2026_hiroshima_match_level_evidence,
)

TIMELINE_FILE = "competitions/2026/hiroshima_qualification_match_timeline_2026.csv"
VERIFICATION = "secondary_dated_result_page"
VALID_ROUNDS = {"anchor_verified_decider"}
STATES = ("proved_qualified_prior_day", "unknown_from_partial_inventory")


def _key(row: dict) -> tuple:
    return (row["season"], row["match_date"],
            frozenset((row["team1_name"], row["team2_name"])))


def audit_2026_hiroshima_qualification_timeline(data_dir: str | Path) -> dict:
    root = Path(data_dir)
    lines = _read(root, TIMELINE_FILE)
    anchors = _read(root, ANCHOR_FILE)
    previous = _read(root, PRIOR_FILE)
    earlier = audit_2026_hiroshima_match_level_evidence(root)
    errors: list[str] = list(earlier["errors"])
    seen_ids = set()
    seen_matches: dict[tuple, dict] = {}
    district_counts = Counter()
    awards: dict[tuple[str, str, str], tuple[date, str]] = {}

    for r in lines:
        ident = r["match_id"]
        key = _key(r)
        sd = (r["season"], r["district_code"])
        if not ident or ident in seen_ids or key in seen_matches:
            errors.append(f"duplicate fixture/ID: {ident}")
        seen_ids.add(ident)
        seen_matches[key] = r
        if sd not in EXPECTED or r["competition_id"] != SEASONS.get(r["season"]):
            errors.append(f"season/region/competition invalid: {ident}")
        stage_groups = {
            ("spring","west"): "SGR000140",
            ("spring","north"): "SGR000141",
            ("spring","south"): "SGR000142",
            ("spring","east"): "SGR000143",
            ("autumn","west"): "SGR000144",
            ("autumn","north"): "SGR000145",
            ("autumn","south"): "SGR000146",
            ("autumn","east"): "SGR000147",
        }
        if r["stage_group_id"] != stage_groups.get(sd):
            errors.append(f"wrong official stage group: {ident}")
        district_counts[sd] += 1
        try:
            on = date.fromisoformat(r["match_date"])
            lo, hi = (
                (date(2026,3,21), date(2026,4,12)) if r["season"] == "spring"
                else (date(2026,8,22), date(2026,9,13))
            )
            if not lo <= on <= hi:
                errors.append(f"fixture outside qualifier date scope: {ident}")
            s1, s2 = int(r["team1_score"]), int(r["team2_score"])
            if s1 == s2 or min(s1,s2) < 0 or r["winner_name"] != (
                r["team1_name"] if s1 > s2 else r["team2_name"]
            ):
                errors.append(f"fixture winner/score mismatch: {ident}")
        except (ValueError, KeyError):
            errors.append(f"date/score parse failure: {ident}")
            continue
        if (not r["team1_name"] or not r["team2_name"]
                or r["team1_name"] == r["team2_name"]):
            errors.append(f"invalid fixture teams: {ident}")
        if r["start_time"]:
            import re
            if not re.fullmatch(r"(?:0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]", r["start_time"]):
                errors.append(f"invalid scheduled time: {ident}")
        if r["verification_scope"] != VERIFICATION:
            errors.append(f"unsupported verification claim: {ident}")
        source = urlparse(r["source_url"])
        if source.scheme != "https" or not source.hostname:
            errors.append(f"unsourced timeline fixture: {ident}")
        status = r["winner_berth_status"]
        if status not in ("berth_award", "not_proven"):
            errors.append(f"cannot designate historical ranking event without proof: {ident}")
        elif status == "berth_award":
            if ("代表決定戦" not in r["round_label"]
                    and r["round_label"] not in VALID_ROUNDS):
                errors.append(f"missing berth-decider result evidence: {ident}")
            lockkey = (*sd, r["winner_name"])
            if lockkey in awards:
                errors.append(f"duplicated qualification lock for school: {ident}")
            else:
                awards[lockkey] = (on, ident)

    anchor_overlaps = 0
    for a in anchors:
        key = _key(a)
        evidence = seen_matches.get(key)
        if evidence is None:
            errors.append(f"missing prior Stage 3G-8 anchor: {a['anchor_id']}")
            continue
        anchor_overlaps += 1
        scores = {evidence["team1_name"]: evidence["team1_score"],
                  evidence["team2_name"]: evidence["team2_score"]}
        old_scores = {a["team1_name"]: a["team1_score"],
                      a["team2_name"]: a["team2_score"]}
        if (scores != old_scores or evidence["winner_name"] != a["winner_name"]
                or evidence["district_code"] != a["district_code"]
                or evidence["winner_berth_status"] != "berth_award"):
            errors.append(f"prior anchor changed or dequalified: {a['anchor_id']}")
    previous_overlap = 0
    for r in previous:
        evidence = seen_matches.get(_key(r))
        if evidence:
            previous_overlap += 1
            if (evidence["winner_name"] != r["winner_name"]
                    or evidence["district_code"] != r["district_code"]
                    or evidence["winner_berth_status"] != "berth_award"):
                errors.append(f"Stage 3G-7 qualifying game reclassified: {r['example_id']}")
            old_scores = {r["team1_name"]: r["team1_score"],
                          r["team2_name"]: r["team2_score"]}
            now_scores = {evidence["team1_name"]: evidence["team1_score"],
                          evidence["team2_name"]: evidence["team2_score"]}
            if old_scores != now_scores:
                errors.append(f"Stage 3G-7 score conflict: {r['example_id']}")

    # A lock is proven only for the strictly later calendar day, as match
    # completion time is not established by a scheduled start time alone.
    # Missing locks mean unknown, never an affirmative not-qualified state.
    observations = []
    both_lock_candidates = []
    for r in sorted(lines, key=lambda item: (item["match_date"], item["match_id"])):
        day = date.fromisoformat(r["match_date"])
        state = {}
        for field in ("team1_name", "team2_name"):
            team = r[field]
            previous_lock = awards.get((r["season"], r["district_code"], team))
            state[field] = (
                "proved_qualified_prior_day"
                if previous_lock is not None and previous_lock[0] < day
                else "unknown_from_partial_inventory"
            )
        is_both = all(value == "proved_qualified_prior_day" for value in state.values())
        observations.append({
            "match_id": r["match_id"],
            "team1_pre_match_state": state["team1_name"],
            "team2_pre_match_state": state["team2_name"],
            "both_previously_qualified": is_both,
        })
        if is_both:
            both_lock_candidates.append(r["match_id"])
            # Merely proving two earlier locks never establishes this
            # match was an official nonblocking ranking-only event.
            if r["winner_berth_status"] == "berth_award":
                errors.append(f"duplicate award after both teams qualified: {r['match_id']}")

    if set(district_counts) != EXPECTED:
        errors.append("sample must retain at least one verified fixture for each district-season")
    if anchor_overlaps != len(anchors) or anchor_overlaps != 8:
        errors.append(f"expected all eight protected anchors: {anchor_overlaps}")
    if len(lines) < 223 or len(awards) < 63:
        errors.append("unexpected loss of Stage 3G-12 cumulative match/qualification evidence")
    return {
        "ok": not errors,
        "errors": errors,
        "sampled_result_match_count": len(lines),
        "district_seasons_with_sampled_results": len(district_counts),
        "per_district_season_sample_count": {
            f"{s}_{d}": district_counts[(s,d)] for s,d in sorted(EXPECTED)
        },
        "evidenced_winner_berth_lock_count": len(awards),
        "prior_3g8_anchor_matches": anchor_overlaps,
        "prior_3g7_example_matches": previous_overlap,
        "potential_both_locked_match_ids": both_lock_candidates,
        "match_prequalification_observations": observations,
        "verified_optional_ranking_matches": 0,
        "full_pdf_match_transcription_complete": False,
        "missing_berth_lock_must_be_treated_as_unknown": True,
        "same_day_locks_must_not_be_inferred": True,
        "fmt025_release_allowed": False,
        "stage_scope": "dated_source_fixture_sample_not_official_pdf_census",
    }
