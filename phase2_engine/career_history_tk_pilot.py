"""Stage43G-63: optional read-only Tk shell on the headless history bridge.

Run on a real display (or Xvfb):
  python -m phase2_engine.career_history_tk_pilot \
      --slot /path/to/saved/slot --school-id SCH000001

This is NOT the official game GUI. It has no save write, game-year advance,
or synthetic claim about actual national tournament progression.
"""
from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from .career_history_gui_bridge import CareerHistoryGuiBridge
from .career_history_slot_session import CareerHistorySlotSession
from .career_saved_year_display_labels import CareerSavedYearDisplayLabels
from .career_history_view_projection import project_history_screen
from .career_legacy_school_game_tk import (
    LEGACY_SOURCE, CareerLegacySchoolGamePager, CareerLegacySchoolGamesTkPilot,
)

APP_NAME = "ココシミュNew｜保存履歴ビューア（試験版・閲覧専用）"


class CareerHistoryTkPilot:
    """Minimal Tk wiring; all source verification is owned by the bridge."""

    def __init__(self, root: tk.Misc, bridge: CareerHistoryGuiBridge,
                 *, school_id: str = "", slot_session=None,
                 data_root: str | Path | None = None):
        if slot_session is not None and slot_session.bridge is not bridge:
            raise ValueError("selected slot bridge differs")
        self.root = root
        self.bridge = bridge
        self.slot_session = slot_session
        self.data_root = data_root
        self.labels = CareerSavedYearDisplayLabels(bridge, data_root)
        self.slot_var = tk.StringVar(
            master=root,
            value=slot_session.slot_id if slot_session is not None else "",
        )
        self.school_var = tk.StringVar(master=root, value=school_id)
        self.status_var = tk.StringVar(master=root, value="")
        self.heading_var = tk.StringVar(master=root, value="")
        self.rows_by_widget_id: dict[str, dict] = {}
        self.view: dict = {}
        self.last_error: str | None = None
        self.legacy_window: CareerLegacySchoolGamesTkPilot | None = None
        root.title(APP_NAME)
        root.geometry("1120x760")
        root.minsize(780, 540)
        self._layout()
        self._render()

    def _layout(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        self.back_button = ttk.Button(
            bar, text="戻る", command=self._back,
        )
        self.back_button.pack(side="left")
        self.older_button = ttk.Button(
            bar, text="古い年度候補", command=self._older,
        )
        self.older_button.pack(side="left", padx=(6, 0))
        self.school_list_button = ttk.Button(
            bar, text="選択年度の学校候補",
            command=self._show_schools,
        )
        self.school_list_button.pack(side="left", padx=(6, 0))
        if self.slot_session is not None:
            ttk.Label(bar, text="セーブ").pack(
                side="left", padx=(10, 3),
            )
            self.slot_box = ttk.Combobox(
                bar, textvariable=self.slot_var,
                state="readonly", width=18,
                values=self.slot_session.available_slots(),
            )
            self.slot_box.pack(side="left")
            self.slot_box.bind("<<ComboboxSelected>>", self._change_slot)
        ttk.Label(bar, text="学校ID").pack(side="left", padx=(16, 4))
        self.school_entry = ttk.Entry(
            bar, textvariable=self.school_var, width=19,
        )
        self.school_entry.pack(side="left")
        self.open_button = ttk.Button(
            bar, text="選択項目を開く", command=self._open_selected,
        )
        self.open_button.pack(side="left", padx=(6, 0))
        self.refresh_button = ttk.Button(
            bar, text="再読込", command=self._refresh,
        )
        self.refresh_button.pack(side="left", padx=(6, 0))

        legacy_bar = ttk.Frame(self.root, padding=(8, 0))
        legacy_bar.pack(fill="x")
        self.legacy_games_button = ttk.Button(
            legacy_bar, text="旧A方式：学校の過去試合を検索",
            command=self._open_legacy_games,
        )
        self.legacy_games_button.pack(side="left")
        ttk.Label(
            self.root, textvariable=self.heading_var, padding=(12, 8),
        ).pack(fill="x")
        container = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        container.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            container, columns=("title", "value", "note"),
            show="headings", selectmode="browse", height=15,
        )
        for name, heading, width in (
            ("title", "年度・記録", 245),
            ("value", "保存値・出典", 275),
            ("note", "内容・備考", 560),
        ):
            self.tree.heading(name, text=heading)
            self.tree.column(name, width=width, anchor="w")
        scroller = ttk.Scrollbar(
            container, orient="vertical", command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=scroller.set)
        self.tree.pack(side="left", expand=True, fill="both")
        scroller.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._open_selected)
        self.tree.bind("<Return>", self._open_selected)
        self.tree.bind("<<TreeviewSelect>>", self._selected_detail)

        ttk.Label(
            self.root, text="選択した保存済みレコードの詳細",
            padding=(12, 4),
        ).pack(fill="x")
        panel = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        panel.pack(fill="both", expand=False)
        self.detail_text = tk.Text(
            panel, height=10, wrap="word", state="disabled",
        )
        detail_scroll = ttk.Scrollbar(
            panel, orient="vertical", command=self.detail_text.yview,
        )
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        ttk.Label(
            self.root, textvariable=self.status_var,
            padding=(12, 6),
        ).pack(fill="x")

    def _detail(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def _selected_row(self) -> dict | None:
        selected = self.tree.selection()
        return self.rows_by_widget_id.get(selected[0]) if selected else None

    def _selected_detail(self, _event=None) -> None:
        item = self._selected_row()
        self._detail(item["payload"] if item else self.view.get("summary", ""))

    def _render(self) -> None:
        view = project_history_screen(self.bridge.page, labels=self.labels)
        self.tree.delete(*self.tree.get_children())
        self.rows_by_widget_id.clear()
        for item in view["rows"]:
            widget_id = self.tree.insert(
                "", "end",
                values=(item["title"], item["value"], item["note"]),
            )
            self.rows_by_widget_id[widget_id] = item
        self.view = view
        self.heading_var.set(view["title"])
        label = (
            "年度候補・ヘッダ未検証"
            if view["show_saved_candidate_warning"]
            else "原本SHA・年度の検証済み"
        )
        self.status_var.set(
            f"{view['summary']}　/　{label}　/　閲覧専用・年度進行不可"
        )
        self.last_error = None
        self._detail(view["summary"])
        self.older_button.configure(
            text=(
                "次の学校候補" if view["screen"] == "history_school_catalog"
                else "古い年度候補"
            ),
            state="normal" if view["has_older"] else "disabled",
        )
        self.school_list_button.configure(
            state="normal" if view["screen"] == "history_year_catalog"
            else "disabled",
        )
        self.back_button.configure(
            state="normal" if self.bridge.history else "disabled",
        )
        self.legacy_games_button.configure(
            state="normal" if (
                self.bridge.page["screen"] == "history_school"
                and self.bridge.page["source_verified"] is True
                and self.bridge.page["data"].get("source") == LEGACY_SOURCE
            ) else "disabled",
        )

    def _action(self, operation) -> None:
        try:
            operation()
            self._close_legacy_games()
            # Reformat only after the verified bridge transition succeeds.
            self._render()
        except (ValueError, OSError) as exc:
            self.last_error = str(exc)
            self.status_var.set(f"閲覧できません：{exc} / 保存データは変更しません")

    def _change_slot(self, _event=None) -> None:
        if self.slot_session is None:
            return
        requested = self.slot_var.get()
        original = self.slot_session.slot_id
        if requested == original:
            return
        try:
            # No current row, school selection or back stack is transferred.
            proposed = self.slot_session.select(requested)
            labels = CareerSavedYearDisplayLabels(
                proposed, self.data_root,
            )
            project_history_screen(proposed.page, labels=labels)
            self._close_legacy_games()
            self.bridge = proposed
            self.labels = labels
            self._render()
        except (ValueError, OSError) as exc:
            self.slot_var.set(original)
            self.last_error = str(exc)
            self.status_var.set(
                f"セーブを変更できません：{exc} / 元の画面を維持"
            )

    def _close_legacy_games(self) -> None:
        if self.legacy_window is not None:
            if self.legacy_window.root.winfo_exists():
                self.legacy_window.root.destroy()
            self.legacy_window = None

    def _open_legacy_games(self) -> None:
        try:
            page = self.bridge.page
            if (page["screen"] != "history_school"
                    or page["source_verified"] is not True
                    or page["data"].get("source") != LEGACY_SOURCE):
                raise ValueError("verified legacy school-year screen required")
            year = page["data"]["selected_year"]
            school_id = page["data"]["school_id"]
            pager = CareerLegacySchoolGamePager(
                self.bridge.catalog.slot_root / "historical_matches.sqlite3",
                school_id, year,
            )
            # Create the child only after its first source page is verified.
            self._close_legacy_games()
            self.legacy_window = CareerLegacySchoolGamesTkPilot(
                self.root, pager,
            )
            self.last_error = None
        except (ValueError, OSError) as exc:
            self.last_error = str(exc)
            self.status_var.set(
                f"旧A方式の試合検索を開けません：{exc}／元画面を維持"
            )

    def _open_selected(self, _event=None) -> None:
        item = self._selected_row()
        if item is None:
            return
        if item["kind"] == "year":
            year = item["year"]
            school = self.school_var.get().strip()
            if school:
                self._action(lambda: self.bridge.open_school(year, school))
            else:
                self._action(lambda: self.bridge.open_year(year))
        elif item["kind"] == "school":
            self._action(lambda: self.bridge.open_school(
                item["year"], item["school_id"],
            ))
        elif item["kind"] == "link":
            self._action(lambda: self.bridge.open_link(item["target"]))
        else:
            self._detail(item["payload"])

    def _show_schools(self) -> None:
        item = self._selected_row()
        if item is None or item["kind"] != "year":
            self.last_error = "保存済み年度を先に選択してください"
            self.status_var.set(self.last_error)
            return
        self._action(lambda: self.bridge.open_year(item["year"]))

    def _older(self) -> None:
        if self.bridge.page["screen"] == "history_school_catalog":
            self._action(self.bridge.older_schools)
        else:
            self._action(self.bridge.older_years)

    def _back(self) -> None:
        self._action(self.bridge.back)

    def _refresh(self) -> None:
        self._action(self.bridge.refresh)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage43G-63 standalone read-only saved-history pilot",
    )
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--slot", type=Path)
    sources.add_argument("--saves-root", type=Path)
    parser.add_argument(
        "--slot-id", help="required with --saves-root; direct slot folder name",
    )
    parser.add_argument("--school-id", required=True)
    parser.add_argument(
        "--data-root", type=Path,
        help="optional current school master for clearly labeled fallback",
    )
    parser.add_argument(
        "--year-page-size", type=int, default=24,
        help="maximum saved-year candidate entries per page (1 to 24)",
    )
    args = parser.parse_args()
    # The GUI must NOT construct the first root until the bridge has
    # validated the read-only year catalog.
    if args.saves_root is not None:
        if not args.slot_id:
            parser.error("--saves-root requires --slot-id")
        session = CareerHistorySlotSession(
            args.saves_root, args.slot_id,
            year_page_size=args.year_page_size,
        )
        bridge = session.bridge
    else:
        if args.slot_id:
            parser.error("--slot-id requires --saves-root")
        session = None
        bridge = CareerHistoryGuiBridge(
            args.slot, year_page_size=args.year_page_size,
        )
    root = tk.Tk()
    try:
        CareerHistoryTkPilot(
            root, bridge, school_id=args.school_id,
            slot_session=session, data_root=args.data_root,
        )
    except Exception:
        root.destroy()
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
