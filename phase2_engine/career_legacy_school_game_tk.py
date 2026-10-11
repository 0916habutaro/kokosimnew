"""Stage43G-75: legacy A saved-game filters in an optional Tk test window.

This intentionally does NOT merge v2 logical-year records into legacy ISO
matches, and it is not the final game UI. All payload verification belongs to
the Stage43G-74 read-only indexed API; no new match results are inferred.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import ttk

from .career_indexed_school_game_page import read_indexed_school_game_page

PAGE_SIZE = 30
LEGACY_SOURCE = "historical_matches_legacy_iso"
WINDOW_TITLE = "ココシミュNew｜旧A方式・学校別試合検索（試験版）"


class CareerLegacySchoolGamePager:
    """Atomic filters and bounded navigation over one legacy match archive."""

    def __init__(self, match_path: str | Path, school_id: str, selected_year: int):
        if (type(school_id) is not str or not school_id
                or type(selected_year) is not int
                or not 1 <= selected_year <= 9999):
            raise ValueError("legacy school and selected ISO year required")
        self.match_path = Path(match_path)
        self.school_id = school_id
        self.start_year = selected_year
        self.end_year = selected_year
        self.competition_id: str | None = None
        self.verify_scope = "page"
        self.offset = 0
        self.page = self._fetch(selected_year, selected_year, None, 0, "page")

    def _fetch(self, start: int, end: int, competition_id: str | None,
               offset: int, verify_scope: str) -> dict:
        data = read_indexed_school_game_page(
            self.match_path, self.school_id, start_year=start,
            end_year=end, competition_id=competition_id,
            limit=PAGE_SIZE, offset=offset, verify_scope=verify_scope,
        )
        if (data.get("school_id") != self.school_id
                or data.get("start_year") != start
                or data.get("end_year") != end
                or data.get("competition_id") != competition_id
                or data.get("offset") != offset
                or data.get("limit") != PAGE_SIZE
                or data.get("verification_scope") != verify_scope
                or data.get("visible_match_checksums_verified") is not True
                or data.get("source_records_not_modified") is not True
                or data.get("all_filtered_window_checksums_verified")
                is not (verify_scope == "filtered_window")):
            raise ValueError("unverified or mismatched saved game search response")
        return data

    def apply_filters(self, start: int, end: int,
                      competition_id: str | None = None,
                      verify_scope: str = "page") -> dict:
        # Validate and read first, then commit state; failures preserve the
        # existing visible page and selected filters unchanged.
        proposed = self._fetch(start, end, competition_id, 0, verify_scope)
        self.start_year, self.end_year = start, end
        self.competition_id, self.verify_scope = competition_id, verify_scope
        self.offset, self.page = 0, proposed
        return proposed

    def move(self, direction: int) -> dict:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("invalid page direction")
        new_offset = self.offset + direction * PAGE_SIZE
        if new_offset < 0 or new_offset >= self.page["total"]:
            return self.page
        proposed = self._fetch(
            self.start_year, self.end_year, self.competition_id,
            new_offset, self.verify_scope,
        )
        if not proposed["records"]:
            raise ValueError("saved matches changed during paging")
        self.offset, self.page = new_offset, proposed
        return proposed

    @property
    def can_previous(self) -> bool:
        return self.offset > 0

    @property
    def can_next(self) -> bool:
        return self.offset + PAGE_SIZE < self.page["total"]


def _year(value: str) -> int:
    # No float/truncation or guessed game calendar conversion.
    if not value.isascii() or not value.isdecimal():
        raise ValueError("年度は1〜9999の整数で指定してください")
    year = int(value)
    if not 1 <= year <= 9999:
        raise ValueError("旧A方式は年度1〜9999のみ指定できます")
    return year


class CareerLegacySchoolGamesTkPilot:
    """Child window opened only from a verified legacy school-year screen."""

    def __init__(self, parent: tk.Misc, pager: CareerLegacySchoolGamePager):
        self.pager = pager
        self.root = tk.Toplevel(parent)
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1060x580")
        self.start_var = tk.StringVar(self.root, str(pager.start_year))
        self.end_var = tk.StringVar(self.root, str(pager.end_year))
        self.competition_var = tk.StringVar(self.root, "")
        self.scope_var = tk.StringVar(self.root, "page")
        self.status_var = tk.StringVar(self.root, "")
        self.last_error: str | None = None
        self.rows_by_widget_id: dict[str, dict] = {}
        self._layout()
        self._render()

    def _layout(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="開始年度").pack(side="left")
        ttk.Entry(bar, textvariable=self.start_var, width=8).pack(
            side="left", padx=(3, 10),
        )
        ttk.Label(bar, text="終了年度").pack(side="left")
        ttk.Entry(bar, textvariable=self.end_var, width=8).pack(
            side="left", padx=(3, 10),
        )
        ttk.Label(bar, text="大会ID（空欄＝すべて）").pack(side="left")
        ttk.Entry(bar, textvariable=self.competition_var, width=22).pack(
            side="left", padx=(3, 10),
        )
        self.search_button = ttk.Button(
            bar, text="検索", command=self._search,
        )
        self.search_button.pack(side="left")
        controls = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        controls.pack(fill="x")
        ttk.Label(controls, text="SHA検証").pack(side="left")
        scope = ttk.Combobox(
            controls, textvariable=self.scope_var, state="readonly", width=22,
            values=("page", "filtered_window"),
        )
        scope.pack(side="left", padx=6)
        ttk.Label(controls, text="page＝表示ページのみ／filtered_window＝指定範囲の全件").pack(
            side="left",
        )
        self.previous_button = ttk.Button(
            controls, text="前の30件", command=lambda: self._move(-1),
        )
        self.previous_button.pack(side="right", padx=4)
        self.next_button = ttk.Button(
            controls, text="次の30件", command=lambda: self._move(1),
        )
        self.next_button.pack(side="right", padx=4)
        frame = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            frame, show="headings",
            columns=("year", "date", "competition", "match", "opponent", "score", "result"),
            selectmode="browse",
        )
        for col, label, width in (
            ("year", "年度", 65), ("date", "試合日", 105),
            ("competition", "大会ID", 160), ("match", "試合ID", 210),
            ("opponent", "対戦校ID", 190), ("score", "得点", 100),
            ("result", "結果", 60),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Label(self.root, textvariable=self.status_var, padding=8).pack(fill="x")

    def _render(self) -> None:
        page = self.pager.page
        self.tree.delete(*self.tree.get_children())
        self.rows_by_widget_id.clear()
        for item in page["records"]:
            widget_id = self.tree.insert("", "end", values=(
                item["year"], item["match_date"], item["competition_id"],
                item["match_id"], item["opponent_school_id"],
                f"{item['runs_for']}－{item['runs_against']}",
                "勝" if item["result_for_school"] == "win" else "敗",
            ))
            self.rows_by_widget_id[widget_id] = item
        self.previous_button.configure(
            state="normal" if self.pager.can_previous else "disabled",
        )
        self.next_button.configure(
            state="normal" if self.pager.can_next else "disabled",
        )
        scope = (
            "指定した年度・大会の範囲全件SHA照合済み"
            if page["all_filtered_window_checksums_verified"]
            else "表示ページのみSHA照合済み（ページ外は未検証）"
        )
        self.status_var.set(
            f"旧A方式／学校 {self.pager.school_id}／計{page['total']}件／"
            f"表示 {len(page['records'])}件（先頭位置 {self.pager.offset}）／"
            f"{scope}／閲覧専用・v2対象外"
        )
        self.last_error = None

    def _operate(self, fn) -> None:
        try:
            fn()
            self._render()
        except (ValueError, OSError, sqlite3.DatabaseError) as exc:
            self.last_error = str(exc)
            self.status_var.set(
                f"検索できません：{exc}／直前の表示を維持・セーブは変更しません"
            )

    def _search(self) -> None:
        def run() -> None:
            start = _year(self.start_var.get().strip())
            end = _year(self.end_var.get().strip())
            competition_id = self.competition_var.get().strip() or None
            self.pager.apply_filters(
                start, end, competition_id, self.scope_var.get(),
            )
        self._operate(run)

    def _move(self, direction: int) -> None:
        self._operate(lambda: self.pager.move(direction))
