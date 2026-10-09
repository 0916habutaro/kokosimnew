"""Stage13E-3G-35: clearly separated experimental Tkinter qualifier preview.

Open from the existing Stage13D3 browse app, or run independently without
any SQLite database:
    python -m phase2_engine.hiroshima_stage13e3g35_preview_gui --data-dir data

The preview has only two whitelisted read-only scenarios. "Next result"
reveals the next already-recorded result, NOT a simulated match.
"""
from __future__ import annotations

import argparse
import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .hiroshima_stage13e3g35_preview_gui_model import (
    FICTIONAL, OBSERVED_2026_WEST, SCENARIOS, STATUS_LABELS,
    HiroshimaPreviewGuiModel, PilotGuiRender,
)

APP_TITLE = "ココシミュNew - 予選進行プレビュー（試験・閲覧専用）"
STATUS_ALL = "全状態"
SCHOOL_ALL = "全学校"


def _make_tree(parent: ttk.Frame, columns: tuple[tuple[str, str, int], ...]) -> ttk.Treeview:
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[x[0] for x in columns],
                        show="headings", selectmode="browse")
    for key, label, width in columns:
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=65, stretch=True)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    return tree


def _fill(tree: ttk.Treeview, values: tuple[tuple[str, ...], ...]) -> None:
    for iid in tree.get_children():
        tree.delete(iid)
    for row in values:
        tree.insert("", "end", values=row)


class HiroshimaPreviewWindow:
    """Toplevel pilot, never part of the scored SQLite BrowseRepository."""

    def __init__(self, parent: tk.Misc, data_dir: str | Path):
        # Verify the data before allocating any new window: a missing or
        # tampered fixture must not leave an orphan Tk Toplevel behind.
        self.model = HiroshimaPreviewGuiModel(data_dir)
        self.window = tk.Toplevel(parent)
        self.window.title(APP_TITLE)
        self.window.geometry("1180x780")
        self.window.minsize(900, 600)
        self._scenario_by_label = {label: value for value,label in SCENARIOS}
        self._label_by_scenario = {value: label for value,label in SCENARIOS}
        self.scenario_var = tk.StringVar(master=self.window)
        self.filter_var = tk.StringVar(master=self.window, value=STATUS_ALL)
        self.school_var = tk.StringVar(master=self.window, value=SCHOOL_ALL)
        self.school_search_var = tk.StringVar(master=self.window, value="")
        self.summary_var = tk.StringVar(master=self.window)
        self.source_var = tk.StringVar(master=self.window)
        self.evidence_var = tk.StringVar(master=self.window)
        self.last_action_var = tk.StringVar(master=self.window)
        self._build()
        self.scenario_var.set(self._label_by_scenario[self.model.scenario_id])
        self._render()

    def _build(self) -> None:
        top = ttk.Frame(self.window, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="試験表示 / 読み取り専用",
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(
            top, text="この画面の結果は架空例または二次史実です。公式抽選や本番ゲームの試合生成ではありません。",
        ).pack(anchor="w", pady=(4,8))
        options = ttk.Frame(top)
        options.pack(fill="x")
        ttk.Label(options, text="閲覧データ").pack(side="left")
        self.scenario_combo = ttk.Combobox(
            options, textvariable=self.scenario_var, state="readonly", width=39,
            values=[label for _,label in SCENARIOS],
        )
        self.scenario_combo.pack(side="left", padx=(6, 12))
        self.scenario_combo.bind("<<ComboboxSelected>>", self._change_scenario)
        ttk.Button(options, text="最初から表示", command=self._reset).pack(side="left", padx=3)
        self.next_button = ttk.Button(
            options, text="既登録の次の結果を表示", command=self._show_next_result,
        )
        self.next_button.pack(side="left", padx=3)
        ttk.Button(
            options, text="選択試合の結果を表示",
            command=self._show_selected_result,
        ).pack(side="left", padx=3)

        ttk.Label(top, textvariable=self.summary_var,
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(10,2))
        ttk.Label(top, textvariable=self.source_var, wraplength=1100).pack(anchor="w")
        ttk.Label(top, textvariable=self.evidence_var).pack(anchor="w")
        ttk.Label(top, textvariable=self.last_action_var).pack(anchor="w", pady=(2,4))

        selectors=ttk.Frame(top)
        selectors.pack(fill="x", pady=(6,0))
        ttk.Label(selectors, text="試合状況").pack(side="left")
        self.filter_combo=ttk.Combobox(
            selectors, textvariable=self.filter_var, state="readonly",
            values=(STATUS_ALL,*STATUS_LABELS.values()), width=17,
        )
        self.filter_combo.pack(side="left", padx=(6, 14))
        self.filter_combo.bind("<<ComboboxSelected>>", self._render)
        ttk.Label(selectors, text="学校").pack(side="left")
        self.school_combo=ttk.Combobox(
            selectors, textvariable=self.school_var, state="readonly", width=26,
        )
        self.school_combo.pack(side="left", padx=(6, 14))
        self.school_combo.bind("<<ComboboxSelected>>", self._render)
        ttk.Label(selectors, text="学校名検索").pack(side="left", padx=(5, 0))
        school_entry = ttk.Entry(selectors, textvariable=self.school_search_var, width=18)
        school_entry.pack(side="left", padx=(6, 4))
        school_entry.bind("<Return>", self._search_schools)
        ttk.Button(
            selectors, text="検索", command=self._search_schools,
        ).pack(side="left")
        ttk.Button(
            selectors, text="絞込解除", command=self._clear_filters,
        ).pack(side="left", padx=(4, 0))

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0,12))
        matches_tab = ttk.Frame(self.notebook, padding=8)
        schools_tab = ttk.Frame(self.notebook, padding=8)
        berths_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(matches_tab, text="大会別・試合進行")
        self.notebook.add(schools_tab, text="学校別戦績")
        self.notebook.add(berths_tab, text="県大会進出確定")
        self.match_tree = _make_tree(matches_tab, (
            ("id","試合ID",135), ("status","状態",120),
            ("phase","段階",175), ("a","学校1",150),
            ("score","得点",65), ("b","学校2",150),
            ("winner","勝者",150), ("date","日付",100), ("source","日付根拠",115),
        ))
        self.school_tree = _make_tree(schools_tab, (
            ("school","学校",190), ("games","試合",65),
            ("wins","勝",65), ("losses","敗",65),
            ("ready","次戦確定数",100), ("status","進出・待機状態",190),
        ))
        self.berth_tree = _make_tree(berths_tab, (
            ("school","代表校",220), ("type","種別",200),
            ("match","代表権確定試合",220),
        ))
        self.school_tree.bind("<Double-1>", self._choose_selected_school)
        self.berth_tree.bind("<Double-1>", self._choose_selected_berth)
        self.match_tree.bind("<Double-1>", self._choose_match_first_school)

    def _filters(self) -> tuple[str,str]:
        selected_status=self.filter_var.get()
        selected_school=self.school_var.get()
        reverse={label:key for key,label in STATUS_LABELS.items()}
        return (reverse.get(selected_status,""),
                "" if selected_school == SCHOOL_ALL else selected_school)

    def _render(self, _event=None) -> None:
        status, school=self._filters()
        # Validate the currently visible school choices BEFORE applying the
        # saved selector: source changes or search may make it stale.
        available=(SCHOOL_ALL,*self.model.search_visible_school_ids(
            self.school_search_var.get()
        ))
        self.school_combo["values"]=available
        if self.school_var.get() not in available:
            self.school_var.set(SCHOOL_ALL)
            school=""
        # Rebuild through Stage32 + Stage33 validation for every UI refresh.
        data=self.model.render(
            status_filter=status, school_filter=school,
            school_query=self.school_search_var.get(),
        )
        _fill(self.match_tree,data.match_rows)
        _fill(self.school_tree,data.school_rows)
        _fill(self.berth_tree,data.berth_rows)
        self.summary_var.set(data.summary)
        self.source_var.set(data.source_note)
        self.evidence_var.set(f"根拠区分: {data.evidence_grade} / 公式個別矢印: 未確認 / 得点: 未収録")
        self.next_button.configure(state="normal" if data.next_result_enabled else "disabled")

    def _change_scenario(self, _event=None) -> None:
        scenario=self._scenario_by_label.get(self.scenario_var.get())
        if scenario is None:
            return
        try:
            self.model.set_scenario(scenario)
        except (OSError, ValueError, TypeError) as exc:
            self.scenario_var.set(self._label_by_scenario[self.model.scenario_id])
            messagebox.showerror("プレビュー読込エラー", str(exc), parent=self.window)
            return
        self.filter_var.set(STATUS_ALL)
        self.school_var.set(SCHOOL_ALL)
        self.school_search_var.set("")
        self.last_action_var.set("表示データを切り替えました。途中結果はリセットされます。")
        self._render()

    def _reset(self) -> None:
        self.model.reset_preview()
        self.last_action_var.set("最初の未実施状態に戻しました。")
        self._render()

    def _show_next_result(self) -> None:
        try:
            mid=self.model.show_next_preapproved_result()
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("結果表示エラー", str(exc), parent=self.window)
            return
        self.last_action_var.set(
            f"既登録の結果を公開しました: {mid}" if mid else "公開可能な未実施結果はありません。"
        )
        self._render()

    def _show_selected_result(self) -> None:
        selection = self.match_tree.selection()
        if not selection:
            self.last_action_var.set("結果を表示する試合を一覧から選択してください。")
            return
        values = self.match_tree.item(selection[0], "values")
        if not values:
            return
        try:
            mid = self.model.show_preapproved_result_for_match(str(values[0]))
        except (OSError, ValueError, TypeError) as exc:
            self.last_action_var.set("試合を公開できません。対戦確定の未実施試合を選択してください。")
            messagebox.showerror("結果表示エラー", str(exc), parent=self.window)
            return
        self.last_action_var.set(f"選択試合の既登録結果を公開しました: {mid}")
        self._render()

    def _search_schools(self, _event=None) -> None:
        matches = self.model.search_visible_school_ids(self.school_search_var.get())
        self.school_var.set(matches[0] if len(matches) == 1 else SCHOOL_ALL)
        self.last_action_var.set(
            f"検索結果: {len(matches)}校（未確定の対戦校は検索対象外）"
        )
        self._render()

    def _clear_filters(self) -> None:
        self.filter_var.set(STATUS_ALL)
        self.school_var.set(SCHOOL_ALL)
        self.school_search_var.set("")
        self.last_action_var.set("試合状況・学校の絞り込みを解除しました。")
        self._render()

    def _choose_match_first_school(self, _event=None) -> None:
        selection = self.match_tree.selection()
        if not selection:
            return
        values = self.match_tree.item(selection[0], "values")
        if not values or values[3] == "未確定":
            return
        self.school_search_var.set("")
        self.school_var.set(values[3])
        self._render()
        self.notebook.select(1)

    def _choose_selected_school(self, _event=None) -> None:
        selection=self.school_tree.selection()
        if not selection:
            return
        values=self.school_tree.item(selection[0],"values")
        if values:
            self.school_search_var.set("")
            self.school_var.set(values[0])
            self._render()
            self.notebook.select(0)

    def _choose_selected_berth(self, _event=None) -> None:
        selection=self.berth_tree.selection()
        if not selection:
            return
        values=self.berth_tree.item(selection[0],"values")
        if values:
            self.school_search_var.set("")
            self.school_var.set(values[0])
            self._render()
            self.notebook.select(0)


def open_hiroshima_preview_window(
    parent: tk.Misc, data_dir: str | Path,
) -> HiroshimaPreviewWindow:
    return HiroshimaPreviewWindow(parent,data_dir)


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="FMT025 isolated pilot preview - no SQLite writes")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--scenario", choices=[value for value,_ in SCENARIOS],
                        default=FICTIONAL)
    parser.add_argument("--headless", action="store_true",
                        help="Print the safe read-only presenter data without Tk display")
    parser.add_argument("--steps",type=int,default=0,
                        help="Reveal this many previously recorded results")
    parser.add_argument("--school-query", default="",
                        help="Case-insensitive substring of a currently known school (headless)")
    parser.add_argument("--status", default="", choices=["", *STATUS_LABELS],
                        help="Only waiting, ready, or completed matches (headless)")
    return parser


def main(argv: list[str] | None=None) -> int:
    args=build_parser().parse_args(argv)
    if args.steps<0 or args.steps>25:
        raise SystemExit("--steps must be 0..25")
    if args.headless:
        model=HiroshimaPreviewGuiModel(args.data_dir,args.scenario)
        for _ in range(args.steps):
            if model.show_next_preapproved_result() is None:
                raise SystemExit("not that many previously recorded results")
        data=model.render(status_filter=args.status,school_query=args.school_query)
        print(json.dumps({
            "scenario":data.scenario_id,
            "summary":data.summary,
            "source_note":data.source_note,
            "school_query":args.school_query,
            "status_filter":args.status,
            "played":data.played_count, "ready":data.ready_count,
            "waiting":data.waiting_count,
            "qualifiers":data.qualifier_count,
            "matches":data.match_rows, "schools":data.school_rows,
            "berths":data.berth_rows,
            "live_fmt025_runtime_enabled":data.live_fmt025_runtime_enabled,
        },ensure_ascii=False,indent=2))
        return 0
    root=tk.Tk()
    root.withdraw()
    model_data=Path(args.data_dir)
    window=open_hiroshima_preview_window(root,model_data)
    window.model.set_scenario(args.scenario)
    window._render()
    for _ in range(args.steps):
        window._show_next_result()
    window.window.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
