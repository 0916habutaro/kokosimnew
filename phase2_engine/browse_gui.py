from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .browse_gui_model import BrowseGuiModel, UNDATED_LABEL


APP_TITLE = "ココシミュNew - 大会・試合閲覧"


class BrowseApp:
    def __init__(self, root: tk.Tk, model: BrowseGuiModel):
        self.root = root
        self.model = model
        self.root.title(APP_TITLE)
        self.root.geometry("1180x760")
        self.root.minsize(920, 620)

        self.year_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.competition_var = tk.StringVar()
        self.school_search_var = tk.StringVar()
        self.prefecture_var = tk.StringVar()
        self.status_var = tk.StringVar(value="")

        self._competition_id_by_label: dict[str, str] = {}

        self._build_layout()
        self._load_years()

    def _build_layout(self) -> None:
        top = ttk.Frame(self.root, padding=(12, 10))
        top.pack(fill="x")

        ttk.Label(top, text="年度").pack(side="left")
        self.year_combo = ttk.Combobox(
            top,
            textvariable=self.year_var,
            state="readonly",
            width=10,
        )
        self.year_combo.pack(side="left", padx=(6, 16))
        self.year_combo.bind("<<ComboboxSelected>>", self._on_year_changed)

        ttk.Label(
            top,
            text="閲覧専用 / SQLite",
        ).pack(side="left")

        ttk.Label(
            top,
            textvariable=self.status_var,
        ).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.date_tab = ttk.Frame(self.notebook, padding=10)
        self.competition_tab = ttk.Frame(self.notebook, padding=10)
        self.school_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.date_tab, text="日付別試合")
        self.notebook.add(self.competition_tab, text="大会結果")
        self.notebook.add(self.school_tab, text="学校戦績")

        self._build_date_tab()
        self._build_competition_tab()
        self._build_school_tab()

    @staticmethod
    def _create_tree(
        parent: ttk.Frame,
        columns: list[tuple[str, str, int, str]],
    ) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)

        ids = [column[0] for column in columns]
        tree = ttk.Treeview(
            holder,
            columns=ids,
            show="headings",
            selectmode="browse",
        )

        for column_id, heading, width, anchor in columns:
            tree.heading(column_id, text=heading)
            tree.column(
                column_id,
                width=width,
                minwidth=60,
                anchor=anchor,
                stretch=True,
            )

        vertical = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=tree.yview,
        )
        horizontal = ttk.Scrollbar(
            holder,
            orient="horizontal",
            command=tree.xview,
        )
        tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return tree

    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _current_year(self) -> int | None:
        value = self.year_var.get().strip()
        return int(value) if value else None

    def _load_years(self) -> None:
        years = self.model.available_years()
        self.year_combo["values"] = [str(year) for year in years]
        if not years:
            self.status_var.set("SQLiteに年度データがありません")
            return
        self.year_var.set(str(years[0]))
        self._refresh_year_views()

    def _on_year_changed(self, _event=None) -> None:
        self._refresh_year_views()

    def _refresh_year_views(self) -> None:
        year = self._current_year()
        if year is None:
            return
        meta = self.model.repository.season_meta(year)
        if meta:
            self.status_var.set(
                f"{year}年 / 試合 {meta['match_count']} / "
                f"大会 {meta['competition_count']} / 学校 {meta['school_count']}"
            )
        self._refresh_date_choices()
        self._refresh_competition_choices()
        self._search_schools()

    # ------------------------------------------------------------------
    # Date tab
    # ------------------------------------------------------------------

    def _build_date_tab(self) -> None:
        controls = ttk.Frame(self.date_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="試合日").pack(side="left")
        self.date_combo = ttk.Combobox(
            controls,
            textvariable=self.date_var,
            state="readonly",
            width=18,
        )
        self.date_combo.pack(side="left", padx=(6, 8))
        self.date_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Button(
            controls,
            text="再読込",
            command=self._load_date_matches,
        ).pack(side="left")

        self.date_summary = ttk.Label(controls, text="")
        self.date_summary.pack(side="right")

        self.date_tree = self._create_tree(
            self.date_tab,
            [
                ("competition", "大会", 210, "w"),
                ("round", "ラウンド", 90, "center"),
                ("team1", "チーム1", 150, "w"),
                ("score", "得点", 70, "center"),
                ("team2", "チーム2", 150, "w"),
                ("winner", "勝者", 150, "w"),
                ("source", "日付種別", 95, "center"),
            ],
        )

    def _refresh_date_choices(self) -> None:
        year = self._current_year()
        self._clear_tree(self.date_tree)
        self.date_summary.configure(text="")
        if year is None:
            self.date_combo["values"] = []
            self.date_var.set("")
            return

        choices = self.model.date_choices(year)
        self.date_combo["values"] = choices
        if choices:
            self.date_var.set(choices[0])
            self._load_date_matches()
        else:
            self.date_var.set("")
            self.date_summary.configure(text="試合日なし")

    def _load_date_matches(self, _event=None) -> None:
        year = self._current_year()
        choice = self.date_var.get().strip()
        self._clear_tree(self.date_tree)
        if year is None or not choice:
            return

        rows = self.model.matches_for_date_choice(year, choice)
        for row in rows:
            self.date_tree.insert(
                "",
                "end",
                values=(
                    row["competition_name"],
                    row.get("round_name") or row.get("phase_code") or "",
                    row["team1_name"],
                    self.model.score_text(row),
                    row["team2_name"],
                    row["winner_name"],
                    row["date_source"],
                ),
            )
        label = "日付未定" if choice == UNDATED_LABEL else choice
        self.date_summary.configure(text=f"{label} / {len(rows)}試合")

    # ------------------------------------------------------------------
    # Competition tab
    # ------------------------------------------------------------------

    def _build_competition_tab(self) -> None:
        controls = ttk.Frame(self.competition_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="大会").pack(side="left")
        self.competition_combo = ttk.Combobox(
            controls,
            textvariable=self.competition_var,
            state="readonly",
            width=52,
        )
        self.competition_combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(6, 8),
        )
        self.competition_combo.bind(
            "<<ComboboxSelected>>",
            self._load_competition,
        )

        ttk.Button(
            controls,
            text="表示",
            command=self._load_competition,
        ).pack(side="left")

        self.competition_summary = ttk.Label(
            self.competition_tab,
            text="",
            anchor="w",
            justify="left",
        )
        self.competition_summary.pack(fill="x", pady=(0, 8))

        self.competition_tree = self._create_tree(
            self.competition_tab,
            [
                ("date", "日付", 95, "center"),
                ("round", "ラウンド", 90, "center"),
                ("team1", "チーム1", 155, "w"),
                ("score", "得点", 70, "center"),
                ("team2", "チーム2", 155, "w"),
                ("winner", "勝者", 155, "w"),
                ("source", "日付種別", 95, "center"),
            ],
        )

    def _refresh_competition_choices(self) -> None:
        year = self._current_year()
        self._clear_tree(self.competition_tree)
        self.competition_summary.configure(text="")
        self._competition_id_by_label = {}

        if year is None:
            self.competition_combo["values"] = []
            self.competition_var.set("")
            return

        options = self.model.competition_options(year)
        labels = [option.label for option in options]
        self._competition_id_by_label = {
            option.label: option.competition_id
            for option in options
        }
        self.competition_combo["values"] = labels

        if labels:
            self.competition_var.set(labels[0])
            self._load_competition()
        else:
            self.competition_var.set("")
            self.competition_summary.configure(text="大会データなし")

    def _load_competition(self, _event=None) -> None:
        year = self._current_year()
        label = self.competition_var.get()
        competition_id = self._competition_id_by_label.get(label)
        self._clear_tree(self.competition_tree)
        if year is None or not competition_id:
            return

        result, matches = self.model.competition_detail(
            year,
            competition_id,
        )
        if not result:
            self.competition_summary.configure(text="大会結果なし")
            return

        champion = result.get("champion_name") or "-"
        runner_up = result.get("runner_up_name") or "-"
        self.competition_summary.configure(
            text=(
                f"{result['competition_name']}  "
                f"期間: {result['start_date'] or '-'} ～ {result['end_date'] or '-'}  "
                f"優勝: {champion}  準優勝: {runner_up}  "
                f"実試合: {result['played_match_count']}  "
                f"不戦勝: {result['bye_count']}"
            )
        )

        for row in matches:
            self.competition_tree.insert(
                "",
                "end",
                values=(
                    row["match_date"] or "未定",
                    row.get("round_name") or row.get("phase_code") or "",
                    row["team1_name"],
                    self.model.score_text(row),
                    row["team2_name"],
                    row["winner_name"],
                    row["date_source"],
                ),
            )

    # ------------------------------------------------------------------
    # School tab
    # ------------------------------------------------------------------

    def _build_school_tab(self) -> None:
        controls = ttk.Frame(self.school_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="学校名").pack(side="left")
        entry = ttk.Entry(
            controls,
            textvariable=self.school_search_var,
            width=28,
        )
        entry.pack(side="left", padx=(6, 12))
        entry.bind("<Return>", lambda _event: self._search_schools())

        ttk.Label(controls, text="都道府県コード").pack(side="left")
        self.prefecture_combo = ttk.Combobox(
            controls,
            textvariable=self.prefecture_var,
            state="readonly",
            width=8,
            values=["", *[f"{value:02d}" for value in range(1, 48)]],
        )
        self.prefecture_combo.pack(side="left", padx=(6, 12))

        ttk.Button(
            controls,
            text="検索",
            command=self._search_schools,
        ).pack(side="left")
        ttk.Button(
            controls,
            text="条件クリア",
            command=self._clear_school_search,
        ).pack(side="left", padx=(6, 0))

        school_list_frame = ttk.LabelFrame(
            self.school_tab,
            text="学校検索結果",
            padding=6,
        )
        school_list_frame.pack(fill="both", expand=False, pady=(0, 8))

        self.school_tree = self._create_tree(
            school_list_frame,
            [
                ("school_id", "学校ID", 110, "center"),
                ("name", "学校名", 220, "w"),
                ("pref", "県", 55, "center"),
                ("games", "試合", 55, "e"),
                ("wins", "勝", 55, "e"),
                ("losses", "敗", 55, "e"),
                ("pct", "勝率", 65, "e"),
                ("titles", "優勝", 55, "e"),
            ],
        )
        self.school_tree.configure(height=8)
        self.school_tree.bind("<<TreeviewSelect>>", self._load_selected_school)

        self.school_detail_label = ttk.Label(
            self.school_tab,
            text="学校を選択してください",
            anchor="w",
            justify="left",
        )
        self.school_detail_label.pack(fill="x", pady=(0, 8))

        history_frame = ttk.LabelFrame(
            self.school_tab,
            text="試合履歴",
            padding=6,
        )
        history_frame.pack(fill="both", expand=True)

        self.school_history_tree = self._create_tree(
            history_frame,
            [
                ("date", "日付", 95, "center"),
                ("competition", "大会", 210, "w"),
                ("round", "ラウンド", 90, "center"),
                ("result", "結果", 65, "center"),
                ("opponent", "対戦相手", 170, "w"),
                ("score", "得点", 70, "center"),
                ("date_source", "日付種別", 95, "center"),
            ],
        )

    def _clear_school_search(self) -> None:
        self.school_search_var.set("")
        self.prefecture_var.set("")
        self._search_schools()

    def _search_schools(self) -> None:
        year = self._current_year()
        self._clear_tree(self.school_tree)
        self._clear_tree(self.school_history_tree)
        self.school_detail_label.configure(text="学校を選択してください")
        if year is None:
            return

        rows = self.model.search_schools(
            year,
            text=self.school_search_var.get(),
            prefecture_code=self.prefecture_var.get(),
        )
        for row in rows:
            iid = row["school_id"]
            self.school_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row["school_id"],
                    row["school_name"],
                    row["prefecture_code"],
                    row["games"],
                    row["wins"],
                    row["losses"],
                    f"{float(row['win_pct']):.3f}",
                    row["titles"],
                ),
            )

    def _load_selected_school(self, _event=None) -> None:
        selection = self.school_tree.selection()
        year = self._current_year()
        if year is None or not selection:
            return
        school_id = selection[0]

        record, matches = self.model.school_detail(year, school_id)
        self._clear_tree(self.school_history_tree)
        if not record:
            self.school_detail_label.configure(text="学校戦績なし")
            return

        self.school_detail_label.configure(
            text=(
                f"{record['school_name']} [{record['school_id']}]  "
                f"試合 {record['games']}  "
                f"{record['wins']}勝 {record['losses']}敗  "
                f"勝率 {float(record['win_pct']):.3f}  "
                f"得失点 {record['runs_for']}-{record['runs_against']}  "
                f"優勝 {record['titles']}  準優勝 {record['runner_up_finishes']}"
            )
        )

        for row in matches:
            if row["team1_id"] == school_id:
                own_score = row.get("team1_score")
                opponent_score = row.get("team2_score")
            else:
                own_score = row.get("team2_score")
                opponent_score = row.get("team1_score")

            if int(row.get("is_bye") or 0):
                score = "不戦勝"
            elif own_score is None or opponent_score is None:
                score = "-"
            else:
                score = f"{own_score}-{opponent_score}"

            self.school_history_tree.insert(
                "",
                "end",
                values=(
                    row["match_date"] or "未定",
                    row["competition_name"],
                    row.get("round_name") or row.get("phase_code") or "",
                    self.model.result_symbol(row.get("school_result", "")),
                    row.get("opponent_name", ""),
                    score,
                    row["date_source"],
                ),
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KokoSimNew read-only SQLite browser GUI"
    )
    parser.add_argument(
        "--db",
        default="out/kokosim_browse.sqlite3",
        help="Stage 12R SQLite browse database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model = BrowseGuiModel(args.db, args.data_dir)

    try:
        model.ensure_database_exists()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Example: python -m phase2_engine.season_cli "
            "--data-dir data --year 2026 --seed 2026100501 "
            "--sqlite-db out/kokosim_browse.sqlite3",
            file=sys.stderr,
        )
        return 2

    from .browse_gui_stage13d3 import Stage13D3BrowseApp

    root = tk.Tk()
    Stage13D3BrowseApp(root, model)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
