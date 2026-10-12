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

    source_kind = LEGACY_SOURCE
    valid_verify_scopes = ("page", "filtered_window")
    min_year = 1
    max_year = 9999

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


def _year(value: str, *, min_year: int = 1,
          max_year: int | None = 9999) -> int:
    # No float/truncation, signed/Unicode numeric input or date conversion.
    if not value.isascii() or not value.isdecimal():
        raise ValueError("年度は半角整数で指定してください")
    year = int(value)
    if year < min_year or (max_year is not None and year > max_year):
        raise ValueError("選択中の保存方式で指定できない年度です")
    return year


class CareerLegacySchoolGamesTkPilot:
    """Child window opened only from a verified legacy school-year screen."""

    def __init__(self, parent: tk.Misc, pager):
        self.pager = pager
        self.is_v2 = pager.source_kind == "fictional_option_a_v2"
        if not (self.is_v2 or pager.source_kind == LEGACY_SOURCE):
            raise ValueError("unknown school match archive source")
        self.root = tk.Toplevel(parent)
        self.root.title(
            "ココシミュNew｜架空v2・学校別試合検索（試験版）"
            if self.is_v2 else WINDOW_TITLE
        )
        self.root.geometry("1060x580")
        self.start_var = tk.StringVar(self.root, str(pager.start_year))
        self.end_var = tk.StringVar(self.root, str(pager.end_year))
        self.competition_var = tk.StringVar(self.root, "")
        self.scope_var = tk.StringVar(self.root, "page")
        self.lookup_var = (
            tk.StringVar(self.root, pager.lookup_mode) if self.is_v2 else None
        )
        self.index_version_var = (
            tk.StringVar(
                self.root,
                pager.index_path.name if pager.index_path is not None else "",
            ) if self.is_v2 else None
        )
        self.index_version_status_var = (
            tk.StringVar(self.root, "索引版は未検証・手動選択のみ")
            if self.is_v2 else None
        )
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
            values=self.pager.valid_verify_scopes,
        )
        scope.pack(side="left", padx=6)
        ttk.Label(
            controls,
            text=(
                "page＝表示試合のみ／selected_years＝指定期間の保存済み全校・全大会"
                if self.is_v2 else
                "page＝表示ページのみ／filtered_window＝学校・年度・大会の絞込全件"
            ),
        ).pack(side="left")
        self.previous_button = ttk.Button(
            controls, text="前の30件", command=lambda: self._move(-1),
        )
        self.previous_button.pack(side="right", padx=4)
        self.next_button = ttk.Button(
            controls, text="次の30件", command=lambda: self._move(1),
        )
        self.next_button.pack(side="right", padx=4)
        if self.is_v2:
            lookup_bar = ttk.Frame(self.root, padding=(8, 0, 8, 8))
            lookup_bar.pack(fill="x")
            ttk.Label(lookup_bar, text="検索方式（手動切替）").pack(side="left")
            self.lookup_box = ttk.Combobox(
                lookup_bar, textvariable=self.lookup_var,
                state="readonly", width=20,
                values=("original_json1", "separate_index"),
            )
            self.lookup_box.pack(side="left", padx=(6, 10))
            self.lookup_box.bind("<<ComboboxSelected>>", self._change_lookup)
            ttk.Label(
                lookup_bar,
                text="original_json1＝原本検索 ／ separate_index＝事前作成した別SQLite索引（自動作成・自動切替なし）",
            ).pack(side="left")
            versions_bar = ttk.Frame(self.root, padding=(8, 0, 8, 8))
            versions_bar.pack(fill="x")
            ttk.Label(versions_bar, text="保存済み索引版").pack(side="left")
            self.index_version_box = ttk.Combobox(
                versions_bar, textvariable=self.index_version_var,
                state="readonly", width=49, values=(),
            )
            self.index_version_box.pack(side="left", padx=(6, 8))
            self.index_version_box.bind(
                "<<ComboboxSelected>>", self._change_index_version,
            )
            self.refresh_versions_button = ttk.Button(
                versions_bar, text="索引候補再読込",
                command=self._refresh_index_versions,
            )
            self.refresh_versions_button.pack(side="left")
            ttk.Label(
                versions_bar, textvariable=self.index_version_status_var,
            ).pack(side="left", padx=(8, 0))
            self._load_index_versions()
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
                item["year"],
                item["game_day_token"] if self.is_v2 else item["match_date"],
                item["competition_id"],
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
        if self.is_v2:
            scope = (
                "期間内に保存済みの全学校・全大会の試合SHA照合済み"
                if page["all_selected_year_payloads_verified"]
                else "表示ページのみSHA照合済み（他の原本や所属校の完全性は未検証）"
            )
            source = "架空v2（G{year}:MM-DD）"
            suffix = (
                "旧A方式対象外／独立SQLite学校索引を利用（表示原本SHA照合）"
                if self.pager.lookup_mode == "separate_index"
                else "旧A方式対象外／原本JSON1検索（学校索引なし）"
            )
        else:
            scope = (
                "指定した学校・年度・大会の範囲全件SHA照合済み"
                if page["all_filtered_window_checksums_verified"]
                else "表示ページのみSHA照合済み（ページ外は未検証）"
            )
            source = "旧A方式（ISO日付）"
            suffix = "v2対象外"
        self.status_var.set(
            f"{source}／学校 {self.pager.school_id}／計{page['total']}件／"
            f"表示 {len(page['records'])}件（先頭位置 {self.pager.offset}）／"
            f"{scope}／閲覧専用・{suffix}"
        )
        if self.is_v2:
            self.lookup_var.set(self.pager.lookup_mode)
            self.index_version_var.set(
                self.pager.index_path.name
                if self.pager.index_path is not None else ""
            )
        self.last_error = None

    def _operate(self, fn) -> None:
        try:
            fn()
            self._render()
        except (ValueError, OSError, sqlite3.DatabaseError) as exc:
            if self.is_v2:
                self.lookup_var.set(self.pager.lookup_mode)
                self.index_version_var.set(
                    self.pager.index_path.name
                    if self.pager.index_path is not None else ""
                )
            self.last_error = str(exc)
            self.status_var.set(
                f"検索できません：{exc}／直前の表示を維持・セーブは変更しません"
            )

    def _load_index_versions(self) -> tuple[str, ...]:
        """Refresh unverified names only; never create/activate an index."""
        if not self.is_v2:
            return ()
        versions = self.pager.available_index_versions()
        self.index_version_box.configure(values=versions)
        self.index_version_status_var.set(
            f"候補{len(versions)}件（一覧は未検証・手動選択で全件照合）"
        )
        return versions

    def _refresh_index_versions(self) -> None:
        if not self.is_v2:
            raise ValueError("legacy sources have no v2 index versions")
        try:
            self._load_index_versions()
            self.last_error = None
        except (ValueError, OSError, sqlite3.DatabaseError) as exc:
            self.last_error = str(exc)
            self.index_version_status_var.set(
                f"候補の再読込に失敗：{exc}"
            )

    def _change_index_version(self, _event=None) -> None:
        if not self.is_v2:
            raise ValueError("legacy sources have no v2 index versions")
        name = self.index_version_var.get()
        try:
            selected = self.pager.select_index_version(name)
            self._render()
            self.index_version_status_var.set(
                f"厳密検証済み・{len(selected['indexed_saved_years'])}年度"
                "（閲覧方式は手動切替）"
            )
        except (ValueError, OSError, sqlite3.DatabaseError) as exc:
            self.last_error = str(exc)
            self.index_version_var.set(
                self.pager.index_path.name
                if self.pager.index_path is not None else ""
            )
            self.index_version_status_var.set(f"索引版を拒否：{exc}")
            self.status_var.set(
                f"索引版を選べません：{exc}／直前の表示を維持・セーブは変更しません"
            )

    def _change_lookup(self, _event=None) -> None:
        if not self.is_v2:
            raise ValueError("legacy school game search cannot use v2 index")
        requested = self.lookup_var.get()
        self._operate(lambda: self.pager.select_lookup(requested))

    def _search(self) -> None:
        def run() -> None:
            start = _year(
                self.start_var.get().strip(),
                min_year=self.pager.min_year,
                max_year=self.pager.max_year,
            )
            end = _year(
                self.end_var.get().strip(),
                min_year=self.pager.min_year,
                max_year=self.pager.max_year,
            )
            competition_id = self.competition_var.get().strip() or None
            self.pager.apply_filters(
                start, end, competition_id, self.scope_var.get(),
            )
        self._operate(run)

    def _move(self, direction: int) -> None:
        self._operate(lambda: self.pager.move(direction))
