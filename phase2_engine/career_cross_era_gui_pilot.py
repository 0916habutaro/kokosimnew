"""Stage43G-33: opt-in Tkinter window for verified cross-era school/player years.

Run standalone:
    python -m phase2_engine.career_cross_era_gui_pilot \
        --slot /path/to/slot --school-id SCH000001 --years 2026,10000

This is a separate testing window, not the game's official GUI, and never
builds caches, changes archived matches or guesses a missing game season.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .career_cross_era_navigation import (
    CareerCrossEraNavigator, MAX_SELECTED_YEARS,
)
from .career_cross_era_display_labels import CareerCrossEraDisplayLabels

APP_NAME = "ココシミュNew｜新旧年度履歴（試験版・閲覧専用）"
PAGE_SIZE = 30


def available_sealed_years(slot_root: str | Path) -> list[int]:
    """Read actual saved year headers; never infer missing years or create DBs."""
    nav = CareerCrossEraNavigator(slot_root)
    legacy, future = nav.browse.gate._all_headers()
    return sorted(
        year for source in (legacy, future)
        for year, row in source.items() if row["status"] == "sealed"
    )


class CareerCrossEraScreenController:
    """Small headless state machine shared by Tk callbacks and CI tests."""

    def __init__(self, navigator: CareerCrossEraNavigator,
                 years: list[int], school_id: str, *, selected_year: int,
                 verify_source: bool = True):
        if type(verify_source) is not bool:
            raise ValueError("verification mode must be bool")
        self.navigator = navigator
        self.verify_source = verify_source
        self.target = navigator._school_target(years, selected_year, school_id)
        self.history: list[tuple[dict, int]] = []
        self.offset = 0
        self.page = self._read(self.target, 0)

    def _read(self, target: dict, offset: int) -> dict:
        if target.get("view") == "school":
            return self.navigator.school_page(
                target["years"], target["school_id"],
                selected_year=target["selected_year"],
                limit=PAGE_SIZE, offset=offset,
                verify_source=self.verify_source,
            )
        if target.get("view") in ("player", "match"):
            return self.navigator.follow(
                target, verify_source=self.verify_source,
            )
        raise ValueError("unknown history window target")

    def open(self, target: dict) -> dict:
        """Commit navigation only after the requested source is reverified."""
        resolved = self.navigator.follow(
            target, verify_source=self.verify_source,
        )
        # For a school target, use the same bounded page size as the GUI.
        if target["view"] == "school":
            resolved = self._read(target, 0)
        self.history.append((self.target, self.offset))
        self.target, self.offset, self.page = dict(target), 0, resolved
        return resolved

    def change_year(self, year: int) -> dict:
        if type(year) is not int:
            raise ValueError("invalid year")
        target = {**self.target, "selected_year": year}
        if target["view"] == "match":
            # Match IDs do not denote the same game in another year.
            target = self.navigator._school_target(
                target["years"], year, target["school_id"],
            )
        return self.open(target)

    def back(self) -> dict:
        if not self.history:
            return self.page
        target, offset = self.history[-1]
        resolved = self._read(target, offset)
        self.target, self.offset, self.page = target, offset, resolved
        self.history.pop()
        return resolved

    def change_page(self, delta: int) -> dict:
        if type(delta) is not int or delta not in (-1, 1):
            raise ValueError("invalid page direction")
        if self.target["view"] != "school":
            return self.page
        count = self.page["match_total"]
        offset = self.offset + PAGE_SIZE * delta
        if offset < 0 or offset >= count:
            return self.page
        new = self._read(self.target, offset)
        self.history.append((self.target, self.offset))
        self.offset, self.page = offset, new
        return new


class CareerCrossEraGuiPilot:
    """Tkinter shell: actual callbacks call the verified headless controller."""

    def __init__(self, root: tk.Misc, navigator: CareerCrossEraNavigator,
                 *, school_id: str, years: list[int],
                 selected_year: int | None = None,
                 verify_source: bool = True,
                 data_root: str | Path | None = None):
        if (type(years) is not list or not years
                or len(years) > MAX_SELECTED_YEARS):
            raise ValueError("choose 1–24 explicitly saved years")
        first = years[-1] if selected_year is None else selected_year
        # No Tk mutation until the initial archive navigation succeeds.
        self.controller = CareerCrossEraScreenController(
            navigator, years, school_id, selected_year=first,
            verify_source=verify_source,
        )
        self.root = root
        self.labels = CareerCrossEraDisplayLabels(
            data_root, navigator.browse.rosters, navigator.browse.attribution,
        )
        self.year_var = tk.StringVar(master=root, value=str(first))
        self.status_var = tk.StringVar(master=root, value="封印済み原本のみ／試験画面")
        self.links: dict[str, dict] = {}
        self.root.title(APP_NAME)
        self.root.geometry("1100x730")
        self.root.minsize(860, 520)
        self._layout()
        self._render(self.controller.page)

    def _layout(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="戻る", command=self._back).pack(side="left")
        ttk.Button(bar, text="前ページ", command=lambda: self._page(-1)).pack(
            side="left", padx=(8, 0),
        )
        ttk.Button(bar, text="次ページ", command=lambda: self._page(1)).pack(
            side="left",
        )
        ttk.Label(bar, text="封印済み年度").pack(side="left", padx=(18, 5))
        self.year_box = ttk.Combobox(
            bar, textvariable=self.year_var, state="readonly", width=10,
            values=[str(year) for year in self.controller.target["years"]],
        )
        self.year_box.pack(side="left")
        self.year_box.bind("<<ComboboxSelected>>", self._change_year)
        ttk.Label(bar, text="別年度は当該原本から再検証").pack(
            side="left", padx=(12, 0),
        )
        panel = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        panel.pack(fill="both", expand=True)
        self.table = ttk.Treeview(
            panel, columns=("identity", "value", "summary"),
            show="headings", selectmode="browse",
        )
        for name, label, size in (
            ("identity", "区分・保存済みID", 295),
            ("value", "年度・得点", 275),
            ("summary", "説明・参照元", 475),
        ):
            self.table.heading(name, text=label)
            self.table.column(name, width=size, minwidth=110)
        self.table.pack(side="left", fill="both", expand=True)
        scroller = ttk.Scrollbar(
            panel, orient="vertical", command=self.table.yview,
        )
        scroller.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroller.set)
        self.table.bind("<Double-1>", self._open_selection)
        self.table.bind("<Return>", self._open_selection)
        self.root.bind("<Alt-Left>", lambda _e: self._back())
        details_frame = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        details_frame.pack(fill="both", expand=False)
        self.details = tk.Text(
            details_frame, state="disabled", wrap="word", height=12,
            font=("Yu Gothic UI", 10),
        )
        self.details.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            details_frame, orient="vertical", command=self.details.yview,
        )
        scroll.pack(side="right", fill="y")
        self.details.configure(yscrollcommand=scroll.set)
        ttk.Label(
            self.root, textvariable=self.status_var, anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 8))

    def _warn(self, exc: Exception):
        messagebox.showwarning("履歴を表示できません", str(exc), parent=self.root)

    def _apply(self, fn):
        try:
            page = fn()
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.year_var.set(str(self.controller.target["selected_year"]))
            self._warn(exc)
            return
        self._render(page)

    def _open(self, target: dict):
        self._apply(lambda: self.controller.open(target))

    def _back(self):
        self._apply(self.controller.back)

    def _page(self, delta: int):
        self._apply(lambda: self.controller.change_page(delta))

    def _change_year(self, _event=None):
        try:
            requested = int(self.year_var.get())
        except ValueError:
            self.year_var.set(str(self.controller.target["selected_year"]))
            return
        self._apply(lambda: self.controller.change_year(requested))

    def _open_selection(self, _event=None):
        item = self.table.selection()
        if item and item[0] in self.links:
            self._open(self.links[item[0]])

    def _add(self, title: str, value: str, note: str,
             target: dict | None = None):
        iid = f"view_{len(self.table.get_children())}"
        self.table.insert("", "end", iid=iid, values=(title, value, note))
        if target is not None:
            self.links[iid] = target

    def _render(self, page: dict):
        for iid in self.table.get_children():
            self.table.delete(iid)
        self.links.clear()
        self.year_var.set(str(page["selected_year"]))
        current_names = self.labels.player_labels(
            page["selected_year"], page["school_id"],
        )
        if page["screen"] == "cross_era_school":
            for game, link, detail_link in zip(
                page["match_page"], page["opponent_school_targets"],
                page["match_detail_targets"],
            ):
                score = (
                    f"{self.labels.school(game['team1_id'])} "
                    f"{game['team1_score']} - {game['team2_score']} "
                    f"{self.labels.school(game['team2_id'])}"
                )
                self._add(
                    "対戦相手へ / " + self.labels.school(
                        link["target"]["school_id"],
                    ),
                    f"{game['date']} / {game['result_for_school']}",
                    f"{score} / {game['competition_id']}/{game['match_id']}",
                    link["target"],
                )
                self._add(
                    "試合詳細へ / " + game["match_id"],
                    f"{game['date']} / {game['team1_score']} - {game['team2_score']}",
                    f"{game['competition_id']} / 保存済み試合IDで参照",
                    detail_link["target"],
                )
            for item in page["player_targets"]:
                self._add(
                    "所属選手へ / " + self.labels.player(
                        item["player_id"], current_names,
                    ),
                    str(page["selected_year"]), "保存済み恒久IDで遷移",
                    item["target"],
                )
            meta = {
                "school_id": page["school_id"],
                "school_name": self.labels.school(page["school_id"]),
                "year": page["selected_year"],
                "date_kind": page["date_kind"],
                "source": page["source"],
                "match_total": page["match_total"],
                "match_page_offset": page["match_page_offset"],
                "match_wins_from_saved_games":
                    page["match_wins_from_saved_games"],
                "match_losses_from_saved_games":
                    page["match_losses_from_saved_games"],
                "annual_roster_state": page["annual_roster_state"],
                "unverified_intervening_year_intervals":
                    page["unverified_intervening_year_intervals"],
                "combined_career_stats_authorized": False,
            }
        elif page["screen"] == "cross_era_match":
            match = page["match"]
            detail = page["details"]
            self._add(
                "学校へ戻る", self.labels.school(page["school_id"]),
                "この年度の学校試合一覧",
                page["back_to_school_target"],
            )
            self._add(
                "対戦校へ", self.labels.school(
                    page["opponent_school_target"]["school_id"],
                ), "対戦校の保存済み年度履歴",
                page["opponent_school_target"],
            )
            for item in detail["inning_scores"] or []:
                self._add(
                    f"{item['inning']}回" + (
                        "表" if item["half"] == "top" else "裏"
                    ),
                    self.labels.school(item["batting_team_id"]),
                    str(item["runs"]) if item["was_played"] else "未実施",
                )
            for item in detail["team_stats"] or []:
                self._add(
                    "チーム成績 / " + self.labels.school(item["school_id"]),
                    f"得点 {item.get('runs', '未収録')}",
                    "その他項目は詳細ペインの保存済み値を参照",
                )
            for kind, title in (("batter_stats", "打撃"), ("pitcher_stats", "投手")):
                for item in detail[kind] or []:
                    self._add(
                        title + " / " + self.labels.player(
                            item.get("player_id", "未登録選手ID"),
                            current_names if item.get("school_id") ==
                            page["school_id"] else {},
                        ),
                        self.labels.school(item.get("school_id", "未登録校ID")),
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                    )
            meta = {
                "school_id": page["school_id"],
                "school_name": self.labels.school(page["school_id"]),
                "year": page["selected_year"],
                "source": page["source"],
                "competition_id": match["competition_id"],
                "match_id": match["match_id"],
                "date": match["date"],
                "date_kind": match["date_kind"],
                "team1": self.labels.school(match["team1_id"]),
                "team2": self.labels.school(match["team2_id"]),
                "team1_score": match["team1_score"],
                "team2_score": match["team2_score"],
                "detail_status": page["detail_status"],
                "missing_detail_fields": page["missing_detail_fields"],
                "saved_option_a_details": detail,
                "combined_career_stats_authorized": False,
            }
        else:
            for link in page["year_targets"]:
                self._add(
                    "選手の別年度へ / " + str(link["selected_year"]),
                    link["player_id"], "所属・成績を年度ごとに確認",
                    link,
                )
            self._add(
                "学校へ戻る", self.labels.school(page["school_id"]),
                "選択年度の学校試合一覧",
                page["back_to_school_target"],
            )
            meta = {
                "school_id": page["school_id"],
                "player_id": page["player_id"],
                "player_name": self.labels.player(
                    page["player_id"], current_names,
                ),
                "school_name": self.labels.school(page["school_id"]),
                "year": page["selected_year"],
                "status": page["selected_status"],
                "source": page["selected_source"],
                "statistics": page["selected_statistics"],
                "unverified_intervening_year_intervals":
                    page["unverified_intervening_year_intervals"],
                "combined_career_totals": None,
                "identity_continuity_proven": False,
            }
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert(
            "end", json.dumps(meta, ensure_ascii=False, indent=2),
        )
        self.details.configure(state="disabled")
        summary = (
            f"学校試合 {page['match_page_offset']+1 if page['match_page'] else 0}"
            f"～{page['match_page_offset']+len(page['match_page'])}"
            f" / {page['match_total']}件"
            if page["screen"] == "cross_era_school"
            else "試合詳細／保存済みの回別・打撃・投手記録"
            if page["screen"] == "cross_era_match"
            else "年度ごとの選手所属・個人成績"
        )
        self.status_var.set(
            f"{self.labels.school(page['school_id'])} / "
            f"{page['selected_year']}年度 / {summary} / 閲覧専用・試験版"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Opt-in cross-era Tk career history pilot (read-only)",
    )
    parser.add_argument("--slot", type=Path, required=True)
    parser.add_argument(
        "--data-root", type=Path, default=Path("data"),
        help="Directory containing the official schools.csv display master",
    )
    parser.add_argument("--school-id", required=True)
    parser.add_argument(
        "--years", required=True,
        help="1–24 comma-separated explicit years, e.g. 2026,10000",
    )
    args = parser.parse_args()
    try:
        selected = [int(s.strip()) for s in args.years.split(",")]
    except ValueError as exc:
        parser.error(f"invalid year list: {exc}")
    nav = CareerCrossEraNavigator(args.slot)
    root = tk.Tk()
    try:
        CareerCrossEraGuiPilot(
            root, nav, school_id=args.school_id, years=selected,
            data_root=args.data_root,
        )
    except Exception:
        root.destroy()
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
