"""前の年度のゲーム内の結果を、翌年度の春季大会の入力にする（game_definition.md §8）。

最初の年度は実際の結果（``initial_state.py``）を使う。2年目からは、
前の年度の次の結果を使う。

- 選抜の出場校（秋季地区大会の後に選んだもの。試合は3月）
- 秋季県大会の順位（東京・北海道は都道府県が1つだけの秋季地区大会の順位）
- 秋季地区大会の出場校

翌年度の大会表は秋の大会が終わった時点でつくるので、そのときには
すべて決まっている。
"""
from __future__ import annotations

from .initial_state import PriorResults
from .season_catalog import rules_year


AUTUMN_PREFECTURAL = "autumn_prefectural"
AUTUMN_REGIONAL = "autumn_regional"


def _school_prefecture(repo, school_id: str) -> str:
    return repo.schools.get(school_id, {}).get("prefecture_code", "")


def _region_prefectures(state) -> dict[str, set[str]]:
    rows = state._read_csv(
        state.repo.data_dir,
        "prefecture_region_memberships.csv",
    )
    regions: dict[str, set[str]] = {}
    for row in rows:
        if row.get("season_segment") == "autumn" and row.get(
            "effective_year"
        ) == str(rules_year(state.year)):
            regions.setdefault(row["region_id"], set()).add(
                row["prefecture_code"]
            )
    return regions


def invitational_entrants(state) -> list[str]:
    """その年度の選抜の出場校（選考が終わっていなければ空）。"""
    for item in reversed(state.history):
        if item.get("action") == "select_invitational":
            return list(item["entrant_school_ids"])
    return []


def prior_results_from_season(state) -> PriorResults:
    """``state``（前の年度）の結果を、翌年度の ``PriorResults`` にする。"""
    repo = state.repo
    region_prefectures = _region_prefectures(state)
    rankings: dict[str, tuple[str, ...]] = {}
    regional_entrants: dict[str, list[str]] = {}
    for cid, scheduled in state.competitions.items():
        competition = repo.competitions.get(cid, {})
        kind = competition.get("competition_type")
        if kind not in (AUTUMN_PREFECTURAL, AUTUMN_REGIONAL):
            continue
        if not scheduled.is_complete:
            raise ValueError(
                f"{cid}: autumn competition is not complete"
            )
        run = scheduled.to_competition_run()
        ranking = tuple(run.outcome.final_ranking_school_ids)
        if kind == AUTUMN_PREFECTURAL:
            rankings[competition["prefecture_code"]] = ranking
            continue
        prefectures = region_prefectures.get(competition["region_id"], set())
        if len(prefectures) == 1:
            rankings.setdefault(next(iter(prefectures)), ranking)
        for school_id in run.entrant_school_ids:
            regional_entrants.setdefault(
                _school_prefecture(repo, school_id), []
            ).append(school_id)
    return PriorResults(
        year=state.year + 1,
        senbatsu_entrants=tuple(
            (school_id, _school_prefecture(repo, school_id))
            for school_id in invitational_entrants(state)
        ),
        autumn_prefectural_rankings=rankings,
        autumn_regional_entrants={
            pcode: tuple(ids) for pcode, ids in regional_entrants.items()
        },
    )
