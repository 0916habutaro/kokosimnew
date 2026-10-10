"""Stage 43F-6: explicit prior-autumn access vs. MAIN-seed capability audit.

All six 2026-based autumn-top-N rules can be understood as *entry rights*.
Only four destinations currently have a safe FMT001 sandbox connector.
A source finish order is not evidence of a destination seed order.
"""
from __future__ import annotations

from typing import Any

from .repository import DataRepository


SUPPORTED_MODEL = "FMT001"
DIRECT_ACTION = "grant_main_entry_bypass_branch_qualifier"


def audit_future_autumn_access_capabilities(
    repo: DataRepository, *, year: int
) -> dict[str, Any]:
    """Inspect effective cross-year top-N access contracts, without RNG/games.

    This does not claim that the following year's structure or school groups
    are officially confirmed, or that the full career runtime is operational.
    """
    if (not isinstance(year, int) or isinstance(year, bool)
            or not 2026 < year <= 9999):
        raise ValueError("year must be a future supported calendar year")
    entries: list[dict] = []
    for cid in sorted(repo.competitions):
        for rule in sorted(
            repo.access_rules(cid), key=lambda r: r["access_rule_id"]
        ):
            if (rule.get("source_year_offset") != "-1"
                    or rule.get("source_event_kind") != "autumn_prefectural"
                    or rule.get("source_result_selector") != "top_n"):
                continue
            effective_from = int(rule.get("effective_from_year") or 2026)
            effective_to = int(rule["effective_to_year"]) if rule.get("effective_to_year") else None
            if year < effective_from or (effective_to is not None and year > effective_to):
                continue

            stages = repo.stages(cid)
            nonmain = [s for s in stages if s["stage_code"] != "MAIN"]
            stage_code = nonmain[0]["stage_code"] if len(nonmain) == 1 else ""
            assignment = (
                repo.assignments_by_stage.get(nonmain[0]["stage_id"], {})
                if len(nonmain) == 1 else {}
            )
            model = assignment.get("default_format_model_id", "")
            linked_seed_rules = sorted(
                sr["seed_rule_id"] for sr in repo.seed_rules(cid)
                if sr.get("linked_access_rule_id") == rule["access_rule_id"]
                and int(sr.get("effective_from_year") or 2026) <= year
                and (
                    not sr.get("effective_to_year")
                    or year <= int(sr["effective_to_year"])
                )
            )
            if (len(stages) == 2
                    and stage_code == "BRANCH_QUALIFIER"
                    and model == SUPPORTED_MODEL
                    and rule.get("action_type") == DIRECT_ACTION
                    and rule.get("grants_main_entry") == "yes"
                    and rule.get("bypassed_stage_participation_policy")
                    == "excluded_from_bypassed_stage"
                    and not linked_seed_rules):
                state = "sandbox_fmt001_supported"
            elif linked_seed_rules:
                state = "linked_seed_rule_requires_separate_validation"
            elif stage_code == "PRELIMINARY_QUALIFIER":
                state = "preliminary_qualifier_adapter_required"
            elif model != SUPPORTED_MODEL:
                state = "non_fmt001_adapter_required"
            else:
                state = "unsupported_competition_graph"

            entries.append({
                "year": year,
                "competition_id": cid,
                "access_rule_id": rule["access_rule_id"],
                "source_year": year - 1,
                "source_event_kind": "autumn_prefectural",
                "source_selector": "top_n",
                "direct_main_entry_count": int(
                    rule.get("quota") or rule.get("observed_2026_count") or 0
                ),
                "access_status": state,
                "first_stage": stage_code,
                "qualifier_model": model,
                "grants_main_entry": rule.get("grants_main_entry") == "yes",
                "excludes_from_qualifier": (
                    rule.get("bypassed_stage_participation_policy")
                    == "excluded_from_bypassed_stage"
                ),
                "seed_on_entry": rule.get("seed_on_entry", ""),
                "linked_seed_rule_ids": linked_seed_rules,
                "main_seed_assignment_status": (
                    "separate_destination_seed_contract_required"
                ),
                "main_seed_school_ids": [],
                "official_future_year_membership_verified": False,
            })
    return {
        "year": year,
        "source_structure_year": 2026,
        "official_future_year_rules_verified": False,
        "live_runtime_ready": False,
        "access_rule_count": len(entries),
        "sandbox_fmt001_supported_count": sum(
            x["access_status"] == "sandbox_fmt001_supported" for x in entries
        ),
        "main_seed_order_auto_assigned": False,
        "access_rules": entries,
    }
