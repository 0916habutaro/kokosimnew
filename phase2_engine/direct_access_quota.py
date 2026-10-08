"""Quota-group mechanism for direct access counted inside a district's quota.

Use only for stage groups explicitly marked by the format parameter
"group_quota_includes_direct_access". No school names are hardcoded.
"""
from __future__ import annotations

from typing import Sequence

from .models import AnnualCompetitionInput
from .repository import DataRepository


def effective_qualifier_group_output_slots(
    repo: DataRepository,
    annual: AnnualCompetitionInput,
    group: dict,
    nominal_slots: int,
    direct_school_ids: Sequence[str],
) -> int:
    gid = group["stage_group_id"]
    inclusive = repo.param(
        group["stage_id"], "group_quota_includes_direct_access", gid, False
    )
    if not inclusive:
        return nominal_slots
    if not isinstance(nominal_slots, int) or nominal_slots <= 0:
        raise ValueError(f"{gid}: invalid inclusive quota")
    direct = set(direct_school_ids)
    eligible_direct = direct & repo.group_school_ids(group, annual.year)
    remaining = nominal_slots - len(eligible_direct)
    if remaining <= 0:
        raise ValueError(f"{gid}: direct entries exhaust district qualifier quota")
    return remaining
