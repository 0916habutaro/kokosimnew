"""Stage 43G-6: Kanagawa's *same-year* Senbatsu participant exception.

The 2026 structure says participation in the national invitational grants a
Kanagawa spring branch-qualifier bye. It does NOT say the previous autumn
rank determines that status, or that an absent record means zero participants.
Until an authenticated annual participation manifest exists, keep it blocked.
"""
from __future__ import annotations

from .repository import DataRepository

KANAGAWA_SPRING = "CMP000095"
NATIONAL_INVITATIONAL = "CMP000001"


def audit_kanagawa_spring_access(
    repo: DataRepository, *,
    year: int,
) -> dict:
    if not isinstance(year, int) or isinstance(year, bool) or not 2026 < year <= 9999:
        raise ValueError("invalid future game year")
    comp = repo.competition(KANAGAWA_SPRING)
    if (comp.get("prefecture_code") != "14"
            or comp.get("competition_type") != "spring_prefectural"):
        raise ValueError("Kanagawa spring competition graph changed")
    stages = repo.stages(KANAGAWA_SPRING)
    if {x["stage_code"] for x in stages} != {"BRANCH_QUALIFIER", "MAIN"}:
        raise ValueError("Kanagawa spring qualifier graph changed")
    rules = repo.access_rules(KANAGAWA_SPRING)
    if len(rules) != 1:
        raise ValueError("Kanagawa must have one Senbatsu access rule")
    rule = rules[0]
    needed = {
        "access_rule_id": "ACR000008",
        "source_event_kind": "national_invitational",
        "source_competition_type": "national_invitational",
        "source_competition_id_2026": NATIONAL_INVITATIONAL,
        "source_year_offset": "0",
        "source_result_selector": "participant_from_destination_prefecture",
        "quota_mode": "all_matches",
        "bypassed_stage_participation_policy": "excluded_from_bypassed_stage",
        "grants_main_entry": "yes",
        "action_type": "grant_main_entry_bypass_branch_qualifier",
    }
    if any(rule.get(k) != v for k, v in needed.items()):
        raise ValueError("Kanagawa Senbatsu access contract changed")
    if year < int(rule.get("effective_from_year") or 2026) or (
        rule.get("effective_to_year") and year > int(rule["effective_to_year"])
    ):
        raise ValueError("Senbatsu access rule not effective in requested year")
    if rule.get("seed_on_entry") != "destination_policy":
        raise ValueError("Kanagawa destination seed rights need separate verification")
    return {
        "year": year,
        "competition_id": KANAGAWA_SPRING,
        "source_competition_id": NATIONAL_INVITATIONAL,
        "source_year": year,
        "access_rule_id": rule["access_rule_id"],
        "status": "requires_same_year_verified_invitational_participants",
        "reason": "authenticated national invitational participant manifest missing",
        "direct_main_school_ids": [],
        "preliminary_exempt_school_ids": [],
        "automatic_bypass_enabled": False,
        "main_seed_school_ids": [],
        "no_record_interpreted_as_zero_participants": False,
        "source_may_include_multiple_kanagawa_schools": True,
        "future_official_participants_confirmed": False,
        "runtime_ready": False,
    }
