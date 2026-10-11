"""Stage43G-75: read-only legacy-A filtered match browser for the Tk pilot.

The filter window is opt-in. It never silently reads other years than the
explicitly selected saved/SEALED legacy year. Year 10000+ uses the separate
fictional-v2 archive and is not silently converted to ISO year 9999.

The default page verification authenticates visible A matches only; deep
full-window SHA verification is an explicit, slower separate choice.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .career_indexed_school_game_page import read_indexed_school_game_page
from .career_option_a_storage_profile import _read_only

FILTER_PAGE_SIZE = 30
MAX_LEGACY_SELECTION_YEARS = 24
ALL_COMPETITIONS = "全大会"


class CareerLegacyFilteredSchoolController:
    """Headless state shared by the test Tk window and unit tests."""

    def __init__(
        self, slot_root: str | Path, school_id: str, years: list[int],
        *, selected_year: int | None = None,
        verify_scope: str = "page",
    ):
        if (type(school_id) is not str or not school_id
                or type(years) is not list
                or not 1 <= len(years) <= MAX_LEGACY_SELECTION_YEARS
                or any(type(y) is not int or not 1 <= y <= 9999 for y in years)
                or years != sorted(set(years))
                or verify_scope not in ("page", "filtered_window")
                or type(verify_scope) is not str):
            raise ValueError("valid sorted saved legacy years and school ID required")
        self.slot = Path(slot_root)
        self.source = self.slot / "historical_matches.sqlite3"
        if self.source.is_symlink() or not self.source.is_file():
            raise FileNotFoundError("saved legacy A match database missing")
        self.school_id = school_id
        self.years = list(years)
        self.selected_year = years[-1] if selected_year is None else selected_year
        if type(self.selected_year) is not int or self.selected_year not in years:
            raise ValueError("selected year outside explicitly requested legacy save years")
        self.verify_scope = verify_scope
        self.competition_id: str | None = None
        self.offset = 0
        for year in years:
            self._require_sealed(year)
        self.competitions = self._competitions(self.selected_year)
        self.page = self._read()

    def _require_sealed(self, year: int) -> None:
        with closing(_read_only(self.source)) as conn:
            row = conn.execute(
                "SELECT status FROM career_years WHERE year=?", (year,),
            ).fetchone()
        if row is None or row[0] != "sealed":
            raise ValueError("only explicitly saved sealed legacy years can be viewed")

    def _competitions(self, year: int) -> list[str]:
        """Only index projections for this school/year, not A payload JSON."""
        with closing(_read_only(self.source)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT competition_id FROM ("
                "SELECT competition_id FROM historical_matches "
                "WHERE team1_id=? AND year=? "
                "UNION ALL "
                "SELECT competition_id FROM historical_matches "
                "WHERE team2_id=? AND year=?"
                ") ORDER BY competition_id",
                (self.school_id, year, self.school_id, year),
            ).fetchall()
        return [row[0] for row in rows]

    def _read(self) -> dict:
        # Check header every time so a saved year cannot be substituted with
        # an active year during filter changes or page navigation.
        self._require_sealed(self.selected_year)
        saved = read_indexed_school_game_page(
            self.source, self.school_id, start_year=self.selected_year,
            end_year=self.selected_year,
            competition_id=self.competition_id,
            limit=FILTER_PAGE_SIZE, offset=self.offset,
            verify_scope=self.verify_scope,
        )
        return {
            **saved,
            "screen": "legacy_filtered_school_match_page",
            "selected_year": self.selected_year,
            "available_years": list(self.years),
            "available_competition_ids": list(self.competitions),
            "year_header_sealed": True,
            "v2_games_included": False,
            "year_window_source": "explicit_sealed_legacy_selection",
            "official_gui_connected": False,
            "read_only": True,
        }

    def change_year(self, year: int) -> dict:
        if type(year) is not int or year not in self.years:
            raise ValueError("unsaved legacy year is not selectable")
        self._require_sealed(year)
        new_competitions = self._competitions(year)
        previous = (
            self.selected_year, self.competitions,
            self.competition_id, self.offset, self.page,
        )
        try:
            self.selected_year = year
            self.competitions = new_competitions
            self.competition_id = None
            self.offset = 0
            next_page = self._read()
        except Exception:
            (self.selected_year, self.competitions,
             self.competition_id, self.offset, self.page) = previous
            raise
        self.page = next_page
        return next_page

    def change_competition(self, competition_id: str | None) -> dict:
        if competition_id is not None and (
            type(competition_id) is not str
            or competition_id not in self.competitions
        ):
            raise ValueError("competition not found in this saved school year")
        old = self.competition_id, self.offset, self.page
        try:
            self.competition_id = competition_id
            self.offset = 0
            next_page = self._read()
        except Exception:
            self.competition_id, self.offset, self.page = old
            raise
        self.page = next_page
        return next_page

    def change_page(self, delta: int) -> dict:
        if type(delta) is not int or delta not in (-1, 1):
            raise ValueError("page step must be -1 or 1")
        target = self.offset + delta * FILTER_PAGE_SIZE
        if target < 0 or target >= self.page["total"]:
            return self.page
        self._require_sealed(self.selected_year)
        old_offset = self.offset
        self.offset = target
        try:
            next_page = self._read()
        except Exception:
            self.offset = old_offset
            raise
        self.page = next_page
        return next_page

    def select_visible_match(self, match_id: str,
                             competition_id: str) -> tuple[int, str, str]:
        if type(match_id) is not str or type(competition_id) is not str:
            raise ValueError("saved match identifiers required")
        if not any(
            row["match_id"] == match_id
            and row["competition_id"] == competition_id
            for row in self.page["records"]
        ):
            raise ValueError("not a currently visible verified saved match")
        # Caller MUST use its normal cross-era exact-ID navigation again
        # (the game can change while a filter window remains open).
        return self.selected_year, competition_id, match_id


class CareerLegacyFilteredSchoolPilot:
    """Optional Tk Toplevel attached to the existing cross-era test GUI."""

    def __init__(
        self, root: tk.Misc,
        controller: CareerLegacyFilteredSchoolController,
        *, open_match: Callable[[int, str, str], None],
        school_label: Callable[[str], str] | None = None,
    ):
        self.root = root
        self.controller = controller
        self.open_match = open_match
        self.school_label = school_label or (lambda school_id: school_id)
        self.year_var = tk.StringVar(master=root, value=str(controller.selected_year))
        self.competition_var = tk.StringVar(master=root, value=ALL_COMPETITIONS)
        self.scope_var = tk.StringVar(master=root, value="表示中の試合SHAを検証")
        self.status_var = tk.StringVar(master=root)
        self.row_ids: dict[str, tuple[str, str]] = {}
        root.title("ココシミュNew｜学校の過去試合絞り込み（旧A・試験版）")
        root.geometry("1000x540")
        root.minsize(720, 400)
        self._layout()
        self._render()

    def _layout(self):
        controls = ttk.Frame(self.root, padding=10)
        controls.pack(fill="x")
        ttk.Label(controls, text="封印済み年度").pack(side="left")
        self.year_box = ttk.Combobox(
            controls, state="readonly", textvariable=self.year_var,
            values=[str(y) for y in self.controller.years], width=8,
        )
        self.year_box.pack(side="left", padx=(6, 12))
        self.year_box.bind("<<ComboboxSelected>>", self._year_selected)
        ttk.Label(controls, text="大会").pack(side="left")
        self.comp_box = ttk.Combobox(
            controls, state="readonly", textvariable=self.competition_var,
            width=28,
        )
        self.comp_box.pack(side="left", padx=(6, 12))
        self.comp_box.bind("<<ComboboxSelected>>", self._comp_selected)
        ttk.Button(
            controls, text="前ページ", command=lambda: self._step(-1),
        ).pack(side="left", padx=(8, 2))
        ttk.Button(
            controls, text="次ページ", command=lambda: self._step(1),
        ).pack(side="left", padx=(2, 0))
        audit = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        audit.pack(fill="x")
        ttk.Label(
            audit, textvariable=self.scope_var,
        ).pack(side="left")
        ttk.Button(
            audit, text="選択範囲の全試合をSHA監査",
            command=self._deep_verify,
        ).pack(side="left", padx=(12, 0))
        table_host = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        table_host.pack(fill="both", expand=True)
        cols = ("date", "competition", "opponent", "score", "result", "saved_id")
        labels = ("試合日", "大会ID", "対戦校", "得点", "勝敗", "保存済み試合ID")
        self.table = ttk.Treeview(
            table_host, columns=cols, show="headings", selectmode="browse",
        )
        for name, label, width in zip(
            cols, labels, (110, 130, 210, 95, 85, 200),
        ):
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=70)
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_host, command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<Double-1>", self._open_selection)
        self.table.bind("<Return>", self._open_selection)
        ttk.Label(
            self.root, textvariable=self.status_var, padding=(10, 0, 10, 12),
        ).pack(fill="x")

    def _warn(self, exc: Exception):
        messagebox.showwarning(
            "保存試合の閲覧に失敗", str(exc), parent=self.root,
        )

    def _run(self, callback):
        try:
            callback()
        except (ValueError, OSError, RuntimeError, KeyError) as exc:
            self._warn(exc)
        self._render()

    def _year_selected(self, _event=None):
        self._run(lambda: self.controller.change_year(int(self.year_var.get())))

    def _comp_selected(self, _event=None):
        selected = self.competition_var.get()
        self._run(lambda: self.controller.change_competition(
            None if selected == ALL_COMPETITIONS else selected
        ))

    def _step(self, delta: int):
        self._run(lambda: self.controller.change_page(delta))

    def _deep_verify(self):
        def check():
            # Keep the strict-window mode opt-in; do not turn every ordinary
            # GUI page refresh into a full history scan.
            previous = self.controller.verify_scope
            try:
                self.controller.verify_scope = "filtered_window"
                self.controller.page = self.controller._read()
            finally:
                self.controller.verify_scope = previous
        self._run(check)

    def _open_selection(self, _event=None):
        selected = self.table.selection()
        if not selected or selected[0] not in self.row_ids:
            return
        competition, match = self.row_ids[selected[0]]
        try:
            year, comp, match_id = self.controller.select_visible_match(
                match, competition,
            )
            self.open_match(year, comp, match_id)
        except (ValueError, OSError, RuntimeError) as exc:
            self._warn(exc)

    def _render(self):
        page = self.controller.page
        self.year_var.set(str(page["selected_year"]))
        self.comp_box.configure(
            values=[ALL_COMPETITIONS, *page["available_competition_ids"]],
        )
        self.competition_var.set(
            page["competition_id"] or ALL_COMPETITIONS
        )
        self.scope_var.set(
            "選択した範囲の全試合SHA照合済み"
            if page["all_filtered_window_checksums_verified"]
            else "表示ページのみSHA照合（範囲全件は未監査）"
        )
        for item in self.table.get_children():
            self.table.delete(item)
        self.row_ids.clear()
        for i, match in enumerate(page["records"]):
            iid = f"game_{i}"
            self.table.insert("", "end", iid=iid, values=(
                match["match_date"], match["competition_id"],
                self.school_label(match["opponent_school_id"]),
                f'{match["runs_for"]} - {match["runs_against"]}',
                "勝" if match["result_for_school"] == "win" else "敗",
                match["match_id"],
            ))
            self.row_ids[iid] = (
                match["competition_id"], match["match_id"],
            )
        first = page["offset"] + 1 if page["records"] else 0
        last = page["offset"] + len(page["records"])
        self.status_var.set(
            f'{self.school_label(page["school_id"])} / {page["selected_year"]}年 '
            f'/ 保存試合 {first}～{last} / {page["total"]}件 '
            '/ 閲覧専用・試験版（旧Aのみ）'
        )
