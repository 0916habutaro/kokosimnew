"""Stage43G-55: optional read-only Tk window for 2027 Tokai season history.

Run independently:
    python -m phase2_engine.career_tokai_season_gui_pilot \
        --data-root data --slot out/saves/<slot> --year 2027

The window operates on archived Option-A game records, never writes a save
or infers official future tournament entrants/champions from match counts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from .career_tokai_season_browse_model import (
    CareerTokaiSeasonBrowseModel, TokaiSeasonBrowseConflict,
)

APP_NAME = "ココシミュNew｜春季東海ゲーム記録（試験版・閲覧専用）"
PAGE_SIZE = 30


class TokaiSeasonScreenController:
    """Headless stable-ID navigation; failed actions never alter state."""

    def __init__(self, model: CareerTokaiSeasonBrowseModel, *, year: int):
        self.model = model
        self.target = {"screen": "tokai_season", "year": year}
        self.offset = 0
        self.history: list[tuple[dict, int]] = []
        self.page = model.open(self.target)

    def _read(self, target: dict, offset: int) -> dict:
        screen = target.get("screen")
        if screen == "competition":
            if set(target) != {"screen", "year", "competition_id"}:
                raise TokaiSeasonBrowseConflict("invalid competition link")
            return self.model.competition(
                target["year"], target["competition_id"],
                offset=offset, limit=PAGE_SIZE,
            )
        if screen == "school":
            if set(target) != {"screen", "year", "school_id"}:
                raise TokaiSeasonBrowseConflict("invalid school link")
            return self.model.school(
                target["year"], target["school_id"],
                offset=offset, limit=PAGE_SIZE,
            )
        if offset:
            raise TokaiSeasonBrowseConflict("screen is not paginated")
        return self.model.open(target)

    def open(self, target: dict) -> dict:
        if not isinstance(target, dict):
            raise TokaiSeasonBrowseConflict("invalid navigation link")
        requested = dict(target)
        # An old Treeview row must never jump back into a different year.
        # Year changes are explicit switch_year() operations.
        if requested.get("year") != self.target["year"] or (
            type(requested.get("year")) is not int
        ):
            raise TokaiSeasonBrowseConflict(
                "navigation link belongs to another saved year"
            )
        page = self._read(requested, 0)
        if requested != self.target:
            self.history.append((dict(self.target), self.offset))
        self.target = requested
        self.offset = 0
        self.page = page
        return page

    def switch_year(self, year: int) -> dict:
        """Year changes are atomic and clear old-school/player route stacks."""
        # Validate first: an absent year must not erase the current route.
        if type(year) is not int:
            raise TokaiSeasonBrowseConflict("invalid saved year")
        target = {"screen": "tokai_season", "year": year}
        page = self.model.open(target)
        self.target = target
        self.offset = 0
        self.history.clear()
        self.page = page
        return page

    def back(self) -> dict:
        if not self.history:
            return self.page
        target, offset = self.history[-1]
        page = self._read(target, offset)
        self.history.pop()
        self.target = target
        self.offset = offset
        self.page = page
        return page

    def change_page(self, delta: int) -> dict:
        if type(delta) is not int or delta not in (-1, 1):
            raise TokaiSeasonBrowseConflict("invalid page direction")
        if self.target["screen"] not in ("school", "competition"):
            raise TokaiSeasonBrowseConflict("this view has no paginated matches")
        count = self.page["matches"]["total"]
        requested = self.offset + PAGE_SIZE * delta
        if requested < 0 or (requested >= count and requested != 0):
            return self.page
        page = self._read(self.target, requested)
        self.offset = requested
        self.page = page
        return page


class CareerTokaiSeasonGuiPilot:
    """Separate opt-in Toplevel window using the verified read-only model."""

    def __init__(self, root: tk.Misc, model: CareerTokaiSeasonBrowseModel,
                 *, year: int):
        self.root = root
        self.controller = TokaiSeasonScreenController(model, year=year)
        self.status_var = tk.StringVar(
            master=root, value="架空ゲームの保存記録のみ／公式結果ではありません"
        )
        self.links: dict[str, dict] = {}
        self.year_var = tk.StringVar(master=root, value=str(year))
        self.available_years = model.available_years(limit=100)
        if year not in self.available_years:
            self.available_years = [year, *self.available_years]
        self.root.title(APP_NAME)
        self.root.geometry("1090x740")
        self.root.minsize(760, 520)
        self._layout()
        self._render(self.controller.page)

    def _layout(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="戻る", command=self._back).pack(side="left")
        ttk.Button(bar, text="東海大会一覧", command=self._home).pack(
            side="left", padx=(8, 0),
        )
        ttk.Label(bar, text="年度").pack(side="left", padx=(12, 3))
        year_picker = ttk.Combobox(
            bar, textvariable=self.year_var, state="readonly",
            width=8, values=[str(year) for year in self.available_years],
        )
        year_picker.pack(side="left")
        year_picker.bind("<<ComboboxSelected>>", self._change_year)
        ttk.Button(bar, text="前ページ", command=lambda: self._page(-1)).pack(
            side="left", padx=(16, 0),
        )
        ttk.Button(bar, text="次ページ", command=lambda: self._page(1)).pack(
            side="left", padx=(4, 0),
        )
        ttk.Label(bar, textvariable=self.status_var).pack(
            side="left", padx=(14, 0),
        )

        pane = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        pane.pack(fill="both", expand=True, padx=10, pady=8)
        listing = ttk.Frame(pane)
        pane.add(listing, weight=3)
        self.table = ttk.Treeview(
            listing, columns=("item", "value", "note"),
            show="headings", selectmode="browse",
        )
        for key, header, width in (
            ("item", "大会・学校・試合・選手", 340),
            ("value", "日付／勝敗・数値", 245),
            ("note", "詳細", 460),
        ):
            self.table.heading(key, text=header)
            self.table.column(key, width=width, minwidth=80, stretch=True)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(
            listing, orient="vertical", command=self.table.yview,
        )
        scrollbar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<Double-1>", self._open_selection)
        self.table.bind("<Return>", self._open_selection)

        pane2 = ttk.Frame(pane)
        pane.add(pane2, weight=2)
        self.details = tk.Text(pane2, height=12, wrap="word", state="disabled")
        self.details.pack(fill="both", expand=True)

    def _apply(self, func) -> None:
        try:
            page = func()
            self._render(page)
        except (ValueError, OSError) as exc:
            messagebox.showwarning("保存履歴を開けません", str(exc), parent=self.root)

    def _open(self, target: dict) -> None:
        self._apply(lambda: self.controller.open(target))

    def _back(self) -> None:
        self._apply(self.controller.back)

    def _home(self) -> None:
        self._open({
            "screen": "tokai_season", "year": self.controller.target["year"],
        })

    def _change_year(self, _event=None) -> None:
        try:
            year = int(self.year_var.get())
            page = self.controller.switch_year(year)
        except (ValueError, OSError) as exc:
            self.year_var.set(str(self.controller.target["year"]))
            messagebox.showwarning("保存年度を開けません", str(exc), parent=self.root)
        else:
            self._render(page)

    def _page(self, delta: int) -> None:
        self._apply(lambda: self.controller.change_page(delta))

    def _open_selection(self, _event=None) -> None:
        selected = self.table.selection()
        if selected and selected[0] in self.links:
            self._open(self.links[selected[0]])

    def _item(self, name: str, value: str, note: str,
              target: dict | None = None) -> None:
        iid = f"item_{len(self.table.get_children())}"
        self.table.insert("", "end", iid=iid, values=(name, value, note))
        if target is not None:
            self.links[iid] = dict(target)

    def _render(self, page: dict) -> None:
        for iid in self.table.get_children():
            self.table.delete(iid)
        self.links.clear()
        screen = page["screen"]
        if screen == "tokai_season":
            for item in page["events"]:
                self._item(
                    item["label"], f"{item['archived_match_count']}試合",
                    f"保存対戦校 {item['schools_seen_in_saved_games']}校 / "
                    f"最終 {item['latest_saved_game_date'] or '未保存'}",
                    item["competition_target"],
                )
        elif screen in ("tokai_competition", "tokai_school"):
            for item in page["matches"]["rows"]:
                self._item(
                    f"{item['team1_id']} - {item['team2_id']}",
                    item["match_date"],
                    f"{item['team1_score']} - {item['team2_score']} / "
                    f"{item['competition_id']} / {item['match_id']}",
                    item["match_target"],
                )
            for target in page.get("school_targets", []):
                self._item(
                    f"学校：{target['school_id']}", "学校戦績",
                    "学校別の保存済み試合へ", target,
                )
            for target in page.get("player_targets", []):
                self._item(
                    f"選手：{target['player_id']}", "選手記録",
                    "年度別・通算成績へ", target,
                )
        elif screen == "tokai_match":
            game = page["game"]
            self._item(
                f"{game['team1_id']} - {game['team2_id']}",
                f"{game['team1_score']} - {game['team2_score']}",
                f"{game['match_date']} / {page['match_id']}",
            )
            for target in page["school_targets"]:
                self._item(
                    f"学校：{target['school_id']}", "保存戦績",
                    "学校IDから閲覧", target,
                )
            for target in page["player_targets"]:
                self._item(
                    f"選手：{target['player_id']}", "個人成績",
                    "保存選手IDから閲覧", target,
                )
        elif screen == "tokai_player":
            target = page["school_target"]
            self._item(
                f"学校：{target['school_id']}", "所属校へ",
                "保存学校IDから閲覧", target,
            )
        else:
            raise ValueError("unsupported Tokai Tk screen")

        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert(
            "end", json.dumps(page, ensure_ascii=False, indent=2),
        )
        self.details.configure(state="disabled")
        self.status_var.set(
            f"2027年以降の架空ゲーム記録 / {page['year']}年度 / "
            f"{screen} / 参照専用・公式大会結果ではありません"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Readonly fictional Tokai career season Tk pilot",
    )
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--year", type=int, default=2027)
    args = parser.parse_args()
    model = CareerTokaiSeasonBrowseModel(
        Path(args.data_root), Path(args.slot),
    )
    root = tk.Tk()
    CareerTokaiSeasonGuiPilot(root, model, year=args.year)
    root.mainloop()


if __name__ == "__main__":
    main()
