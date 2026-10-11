"""Stage43G-63: presentation-only projection for saved fictional A records.

This module knows no Tk widgets and cannot progress a game season. It formats
only the read-only Stage43G-62 bridge response, retaining original IDs and
the provenance distinction between header candidates and verified records.
"""
from __future__ import annotations

import json

SOURCE_LABELS = {
    "historical_matches_legacy_iso": "旧A方式（ISO日付）",
    "fictional_option_a_v2": "v2架空記録（ゲーム内論理日付）",
}
DETAIL_LABELS = {
    "inning_scores": "イニング別得点",
    "team_stats": "チーム成績",
    "batter_stats": "打撃成績",
    "pitcher_stats": "投手成績",
}
SCREENS = (
    "history_year_catalog", "history_school_catalog", "history_school",
    "history_match", "history_player",
)


class CareerHistoryViewConflict(ValueError):
    """Unrecognized / mismatched screen payload must not be rendered."""


def _row(kind: str, title: str, value: str, note: str, *,
         target: dict | None = None,
         year: int | None = None, school_id: str | None = None,
         payload: str | None = None) -> dict:
    return {
        "kind": kind, "title": title, "value": value, "note": note,
        "target": target, "year": year, "school_id": school_id,
        "payload": payload or note,
    }


def project_history_screen(page: dict, *, labels=None) -> dict:
    """Turn a verified bridge screen into a widget-agnostic Japanese view.

    The bridge enforces identity, source integrity and read-only browsing.
    Presentation does not manufacture missing innings or player records.
    """
    if type(page) is not dict or page.get("screen") not in SCREENS:
        raise CareerHistoryViewConflict("unknown historical page")
    screen = page["screen"]
    raw = page.get("data")
    if type(raw) is not dict:
        raise CareerHistoryViewConflict("missing history page data")
    verified = page.get("source_verified")
    if type(verified) is not bool or (
        screen == "history_year_catalog" and verified
    ) or (screen != "history_year_catalog" and not verified):
        raise CareerHistoryViewConflict("saved source verification differs")
    if page.get("allow_advance_year") is not False or (
        page.get("history_read_only") is not True
    ):
        raise CareerHistoryViewConflict("history must remain read-only")

    rows: list[dict] = []
    if screen == "history_year_catalog":
        if raw.get("screen") != "cross_era_year_catalog":
            raise CareerHistoryViewConflict("wrong saved-year catalog type")
        for item in raw["years"]:
            if (type(item.get("year")) is not int
                    or item.get("source") not in SOURCE_LABELS
                    or item.get("source_verified") is not False):
                raise CareerHistoryViewConflict("invalid saved year candidate")
            rows.append(_row(
                "year", f"{item['year']}年度",
                SOURCE_LABELS[item["source"]],
                "封印済年度のヘッダ候補（試合・成績は未検証）",
                year=item["year"],
            ))
        title = "保存済み年度一覧"
        summary = "旧A方式・v2は別々の原本から取得／年度候補は未検証"
        if not rows:
            rows.append(_row(
                "notice", "保存済み年度なし", "", "このページには封印済み年度がありません",
            ))
    elif screen == "history_school_catalog":
        if (raw.get("screen") != "history_school_catalog"
                or raw.get("source_payloads_rechecked") is not True
                or raw.get("only_saved_year_rosters_indexed") is not True):
            raise CareerHistoryViewConflict(
                "unverified saved-year school catalog"
            )
        year = raw["year"]
        title = f"{year}年度｜保存済み学校一覧"
        summary = (
            "当該年度の保存ロスターがある学校だけを表示／"
            "全国全校の収録を保証しません"
        )
        for item in raw["schools"]:
            if (item.get("year") != year
                    or item.get("school_name_digest_verified") is not True
                    or type(item.get("school_id")) is not str):
                raise CareerHistoryViewConflict(
                    "saved-year school identity or digest differs"
                )
            rows.append(_row(
                "school", item["label"], item["school_id"],
                "保存年度ロスターの校名／保存済みIDで選択",
                year=year, school_id=item["school_id"],
            ))
        if not rows:
            rows.append(_row(
                "notice", "保存済み学校ロスターなし", "",
                "この年度の学校が全国に存在しないという意味ではありません",
            ))
    elif screen == "history_school":
        if raw.get("screen") != "cross_era_school":
            raise CareerHistoryViewConflict("wrong school archive page type")
        year, school = raw["selected_year"], raw["school_id"]
        title = f"{year}年度｜学校 {school}"
        summary = (
            f"{SOURCE_LABELS[raw['source']]}／保存試合 "
            f"{raw['match_total']}件／{raw['annual_roster_state']}"
        )
        matches = {
            (row["competition_id"], row["match_id"]): row
            for row in raw["match_page"]
        }
        for link in raw["match_detail_targets"]:
            key = (link["competition_id"], link["match_id"])
            if key not in matches:
                raise CareerHistoryViewConflict("match link differs from page")
            game = matches[key]
            rows.append(_row(
                "link", f"試合 {key[1]}", game["date"],
                f"{game['team1_id']} {game['team1_score']}"
                f"－{game['team2_score']} {game['team2_id']}"
                f"／大会ID {key[0]}",
                target=link["target"],
            ))
        for link in raw["opponent_school_targets"]:
            t = link["target"]
            rows.append(_row(
                "link", f"対戦校 {t['school_id']}", "",
                "同じ保存年度の学校記録へ",
                target=t,
            ))
        for link in raw["player_targets"]:
            rows.append(_row(
                "link", f"選手 {link['player_id']}", "",
                "この年度の保存ロスターから選手記録へ",
                target=link["target"],
            ))
        if not rows:
            rows.append(_row(
                "notice", "表示できる試合・選手リンクなし", "",
                "記録の欠落を推測で補完しません",
            ))
    elif screen == "history_match":
        if raw.get("screen") != "cross_era_match":
            raise CareerHistoryViewConflict("wrong match archive page type")
        match = raw["match"]
        year = raw["selected_year"]
        title = f"{year}年度｜試合 {match['match_id']}"
        summary = (
            f"{SOURCE_LABELS[raw['source']]}／{match['date']}／"
            f"{match['team1_id']} {match['team1_score']}－"
            f"{match['team2_score']} {match['team2_id']}"
        )
        for label, key in (
            ("学校の試合一覧へ", "back_to_school_target"),
            ("対戦校へ", "opponent_school_target"),
        ):
            if key in raw:
                rows.append(_row(
                    "link", label, "", "保存済みIDで移動",
                    target=raw[key],
                ))
        for field, caption in DETAIL_LABELS.items():
            data = raw["details"].get(field)
            if data is None:
                rows.append(_row(
                    "notice", caption, "保存記録なし",
                    "該当項目を推測・生成しません",
                ))
                continue
            if type(data) is not list:
                raise CareerHistoryViewConflict("saved A detail has wrong type")
            if not data:
                rows.append(_row(
                    "notice", caption, "0行", "保存データに行がありません",
                ))
            for idx, record in enumerate(data, 1):
                # Preserve every saved field in the selectable row inspector.
                saved = json.dumps(record, ensure_ascii=False, sort_keys=True)
                rows.append(_row(
                    "detail", f"{caption} {idx}", f"{len(data)}行中 {idx}行",
                    "選択すると保存済みの全フィールドを下段へ表示",
                    payload=saved,
                ))
    else:
        if raw.get("screen") != "cross_era_player":
            raise CareerHistoryViewConflict("wrong player archive page type")
        title = (
            f"{raw['selected_year']}年度｜選手 {raw['player_id']}"
        )
        summary = (
            f"{SOURCE_LABELS[raw['selected_source']]}／"
            f"状態 {raw['selected_status']}"
        )
        rows.append(_row(
            "link", "学校へ戻る", raw["school_id"],
            "この選手の指定年度・所属校",
            target=raw["back_to_school_target"],
        ))
        stat = raw["selected_statistics"]
        if stat is None:
            rows.append(_row(
                "notice", "個人成績", "保存記録なし",
                "記録なし・未所属を推測で埋めません",
            ))
        else:
            rows.append(_row(
                "detail", "個人成績", "保存済み",
                "選択すると当該年度の全フィールドを表示",
                payload=json.dumps(stat, ensure_ascii=False, sort_keys=True),
            ))
    display = None
    if labels is not None and screen in (
        "history_school", "history_match", "history_player",
    ):
        year, school_id = raw["selected_year"], raw["school_id"]
        historical = labels.school(year, school_id)
        display = {
            "year": year, "school": historical,
            "label_source": historical["source"],
            "historical_school_name_proven":
                historical["historical_name_proven"],
        }
        if screen == "history_school":
            title = f"{year}年度｜{historical['label']}"
            source_note = (
                "当該年度の保存ロスターによる校名"
                if historical["historical_name_proven"] else
                "現行マスター等の代替名／当時の校名とは限りません"
            )
            summary += f"／{source_note}"
            for row in rows:
                target = row.get("target")
                if row["kind"] != "link" or target is None:
                    continue
                if target["view"] == "player":
                    player = labels.player(
                        year, school_id, target["player_id"],
                    )
                    row["title"] = f"選手 {player['label']}"
                elif target["view"] == "school":
                    other = labels.school(year, target["school_id"])
                    row["title"] = f"対戦校 {other['label']}"
            for row in rows:
                if row["kind"] == "link" and row["title"].startswith("試合 "):
                    # Original school IDs remain in the verified navigation
                    # target and in the raw read model, even if names evolve.
                    row["note"] += "／出典は指定年度の保存試合"
        elif screen == "history_match":
            game = raw["match"]
            a = labels.school(year, game["team1_id"])
            b = labels.school(year, game["team2_id"])
            summary = (
                f"{SOURCE_LABELS[raw['source']]}／{game['date']}／"
                f"{a['label']} {game['team1_score']}－"
                f"{game['team2_score']} {b['label']}"
            )
            display["teams"] = [a, b]
        elif screen == "history_player":
            player = labels.player(year, school_id, raw["player_id"])
            if raw["selected_status"] == "verified_box_score" and not (
                player["exact_year_roster_membership_verified"]
            ):
                raise CareerHistoryViewConflict(
                    "saved player stats have no verified exact-year roster"
                )
            title = f"{year}年度｜{player['label']}"
            display["player"] = player
            summary += f"／所属校 {historical['label']}"

    return {
        "screen": screen, "title": title, "summary": summary,
        "rows": rows, "source_verified": verified,
        "history_read_only": True,
        "allow_advance_year": False,
        "has_older": (
            raw.get("has_older", False)
            if screen in ("history_year_catalog", "history_school_catalog")
            else False
        ),
        "show_saved_candidate_warning": not verified,
        "saved_year_display": display,
    }
