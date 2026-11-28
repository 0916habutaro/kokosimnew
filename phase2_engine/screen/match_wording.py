"""試合の画面の「経過」と「交代」の文言（game_definition.md §9）。

文言は ``config/screen/match_wording_v1.json`` の対応表から作り、コードには書かない。

- 経過：得点（「適時打で2点」「内野ゴロの間に1点」「押し出し四球で1点」）、併殺（打った学校と打者）、
  作戦（「スクイズ成功」「エンドラン失敗：飛球で併殺（走者戻れず）」）、盗塁、暴投・捕逸、投手交代
- 交代：場面（「7回表・3番打者の前」。打順は試合の打席の数から出す）、理由ごとの文言、同じ場面の
  交代を1つの枠にまとめる（``group_changes``）
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

CONFIG_PATH = Path("screen") / "match_wording_v1.json"


def load_wording(config_root: str | Path) -> dict:
    data = json.loads((Path(config_root) / CONFIG_PATH).read_text(encoding="utf-8"))
    if data.get("config_id") != "match_wording_v1":
        raise ValueError("match wording config_id mismatch")
    return data


@lru_cache(maxsize=1)
def default_wording() -> dict:
    """リポジトリ（EXE なら展開先）の ``config/`` の対応表。"""
    return load_wording(Path(__file__).resolve().parents[2] / "config")


def event_label(wording: Mapping, event: str) -> str:
    return wording["event_labels"].get(event, event)


def score_text(wording: Mapping, event: str, runs: int) -> str:
    """得点の行（「適時打で2点」）。"""
    template = wording["score"].get(event) or wording["score"]["other"]
    return template.format(runs=runs, label=event_label(wording, event))


def wild_pitch_text(wording: Mapping, kind: str, runs: int) -> str:
    """暴投・捕逸（点が入ったら「暴投で1点」。「（1点）」は付けない）。"""
    label = wording["wild_pitch"][kind]
    return wording["wild_pitch"]["with_runs"].format(label=label, runs=runs) if runs else label


def steal_text(wording: Mapping, result: str, base: int) -> str:
    return wording["steal"][f"{result}:{base}"]


def tactic_text(wording: Mapping, tactic: str, result: str) -> tuple[str, bool]:
    """作戦の文言と成功したか。"""
    if tactic == "hit_and_run":
        rule = wording["hit_and_run"]
        success = result in rule["success"]
        label = rule["ground_out_label"] if result == "ground_out" else event_label(wording, result)
        return (rule["success_format"] if success else rule["failure_format"]).format(label=label), success
    text = wording["tactic"].get(f"{tactic}:{result}", f"{tactic}:{result}")
    return text, (tactic, result) == ("squeeze", "ok")


def reason_text(wording: Mapping, reason: str | None, kind: str | None = None) -> str:
    """交代の理由の文言。理由がなければ交代の種類（投手交代・守備変更・選手交代）。"""
    if reason:
        return wording["change_reasons"].get(reason, wording["change_reasons"]["none"])
    return wording["change_kinds"].get(kind or "", wording["change_reasons"]["none"])


def plate_appearance_orders(inning_scores: Sequence[Mapping]) -> dict[int, int]:
    """試合を通した打席の番号 → その打席の打者の打順（1〜9）。打順は回をまたいで続く。"""
    out: dict[int, int] = {}
    number = 1
    count = {"top": 0, "bottom": 0}
    for row in inning_scores:
        half = row.get("half")
        for _ in range(int(row.get("plate_appearances") or 0)):
            out[number] = count[half] % 9 + 1
            count[half] += 1
            number += 1
    return out


def change_moment(wording: Mapping, inning: int, half: str, order: int | None) -> str:
    """「7回表・3番打者の前」（打順が分からなければ「7回表」）。"""
    if order:
        return wording["change_moment"].format(inning=inning, half=half, order=order)
    return wording["change_moment_unknown"].format(inning=inning, half=half)


def group_changes(changes: Iterable[Mapping]) -> list[dict]:
    """同じ回・同じ打席の前の同じ学校の交代を1つの枠にまとめる（出てきた順）。

    枠の ``fully_exited`` は、打順の交代で退いた選手（交代の行でわかる）を除いた、完全に退いた選手
    （DH 解除などで交代の行に出ない選手だけ）。"""
    groups: list[dict] = []
    index: dict[tuple, dict] = {}
    for change in changes:
        key = (change["inning"], change["half"], change["next_plate_appearance_no"], change["school_id"])
        group = index.get(key)
        if group is None:
            group = {key_: change.get(key_) for key_ in (
                "inning", "half", "next_plate_appearance_no", "school_id", "school_name", "moment")}
            group["changes"] = []
            group["exited"] = []
            index[key] = group
            groups.append(group)
        group["changes"].append(change)
        group["exited"] += list(change.get("fully_exited") or ())
    for group in groups:
        shown = {
            person["player_id"]
            for change in group["changes"]
            for person in (
                [change.get("outgoing")]
                + [b.get("outgoing") for b in change.get("batting_changes") or ()]
                + [(change.get("pitcher_change") or {}).get("outgoing")]
            )
            if person
        }
        seen = set()
        group["fully_exited"] = [
            person for person in group.pop("exited")
            if person["player_id"] not in shown and not (person["player_id"] in seen or seen.add(person["player_id"]))
        ]
    return groups
