from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .browse_gui import BrowseApp
from .browse_gui_model import (
    ALL_COMPETITIONS_LABEL,
    ALL_PREFECTURES_LABEL,
)


class EnhancedBrowseApp(BrowseApp):
    """Stage 12T read-only GUI enhancements over the Stage 12S base app."""

    def __init__(self, root: tk.Tk, model):
        self.date_comp_var = tk.StringVar(value=ALL_COMPETITIONS_LABEL)
        self.date_pref_var = tk.StringVar(value=ALL_PREFECTURES_LABEL)
        self._date_competition_id_by_label: dict[str, str] = {}
        self._date_rows: dict[str, dict] = {}
        self._competition_rows: dict[str, dict] = {}
        self._school_history_rows: dict[str, dict] = {}
        super().__init__(root, model)
        root.geometry("1240x820")
        root.minsize(980, 650)

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
        self._refresh_school_prefectures()
        self._search_schools()

    # ------------------------------------------------------------------
    # Date tab: date + competition + prefecture filters / navigation
    # ------------------------------------------------------------------

    def _build_date_tab(self) -> None:
        controls = ttk.Frame(self.date_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="試合日").pack(side="left")
        self.date_combo = ttk.Combobox(
            controls,
            textvariable=self.date_var,
            state="readonly",
            width=16,
        )
        self.date_combo.pack(side="left", padx=(6, 12))
        self.date_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Label(controls, text="大会").pack(side="left")
        self.date_comp_combo = ttk.Combobox(
            controls,
            textvariable=self.date_comp_var,
            state="readonly",
            width=35,
        )
        self.date_comp_combo.pack(side="left", padx=(6, 12))
        self.date_comp_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Label(controls, text="都道府県").pack(side="left")
        self.date_pref_combo = ttk.Combobox(
            controls,
            textvariable=self.date_pref_var,
            state="readonly",
            width=15,
        )
        self.date_pref_combo.pack(side="left", padx=(6, 12))
        self.date_pref_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Button(
            controls,
            text="再読込",
            command=self._load_date_matches,
        ).pack(side="left")

        self.date_summary = ttk.Label(controls, text="")
        self.date_summary.pack(side="right")

        ttk.Label(
            self.date_tab,
            text="ダブルクリック: 大会名→大会画面 / 学校名・勝者→学校画面",
        ).pack(fill="x", pady=(0, 6))

        self.date_tree = self._create_tree(
            self.date_tab,
            [
                ("competition", "大会", 220, "w"),
                ("round", "ラウンド", 90, "center"),
                ("team1", "チーム1", 155, "w"),
                ("score", "得点", 70, "center"),
                ("team2", "チーム2", 155, "w"),
                ("winner", "勝者", 155, "w"),
                ("source", "日付種別", 95, "center"),
            ],
        )
        self.date_tree.bind("<Double-1>", self._on_date_double_click)

    def _refresh_date_choices(self) -> None:
        year = self._current_year()
        self._clear_tree(self.date_tree)
        self.date_summary.configure(text="")
        self._date_rows = {}
        if year is None:
            return

        date_choices = self.model.date_choices(year)
        self.date_combo["values"] = date_choices
        self.date_var.set(date_choices[0] if date_choices else "")

        options = self.model.competition_options(year)
        self._date_competition_id_by_label = {
            option.label: option.competition_id
            for option in options
        }
        competition_labels = [
            ALL_COMPETITIONS_LABEL,
            *[option.label for option in options],
        ]
        self.date_comp_combo["values"] = competition_labels
        self.date_comp_var.set(ALL_COMPETITIONS_LABEL)

        prefectures = [
            ALL_PREFECTURES_LABEL,
            *self.model.prefecture_choices(year),
        ]
        self.date_pref_combo["values"] = prefectures
        self.date_pref_var.set(ALL_PREFECTURES_LABEL)

        if date_choices:
            self._load_date_matches()

    def _load_date_matches(self, _event=None) -> None:
        year = self._current_year()
        choice = self.date_var.get().strip()
        self._clear_tree(self.date_tree)
        self._date_rows = {}
        if year is None or not choice:
            return

        competition_id = self._date_competition_id_by_label.get(
            self.date_comp_var.get(),
            "",
        )
        prefecture_code = (
            ""
            if self.date_pref_var.get() == ALL_PREFECTURES_LABEL
            else self.date_pref_var.get()
        )
        rows = self.model.matches_for_date_choice(
            year,
            choice,
            competition_id=competition_id,
            prefecture_code=prefecture_code,
        )
        for index, row in enumerate(rows):
            iid = f"date-{index}"
            self._date_rows[iid] = row
            self.date_tree.insert(
                "",
                "end",
                iid=iid,
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
        self.date_summary.configure(
            text=f"{choice} / {len(rows)}試合"
        )

    def _on_date_double_click(self, event) -> None:
        iid = self.date_tree.identify_row(event.y)
        column = self.date_tree.identify_column(event.x)
        row = self._date_rows.get(iid)
        if not row:
            return
        if column == "#1":
            self._navigate_to_competition(row["competition_id"])
        elif column == "#3" and row.get("team1_id"):
            self._navigate_to_school(row["team1_id"])
        elif column == "#5" and row.get("team2_id"):
            self._navigate_to_school(row["team2_id"])
        elif column == "#6" and row.get("winner_id"):
            self._navigate_to_school(row["winner_id"])

    # ------------------------------------------------------------------
    # Competition tab: list + bracket / school navigation
    # ------------------------------------------------------------------

    def _build_competition_tab(self) -> None:
        controls = ttk.Frame(self.competition_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="大会").pack(side="left")
        self.competition_combo = ttk.Combobox(
            controls,
            textvariable=self.competition_var,
            state="readonly",
            width=58,
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

        ttk.Label(
            self.competition_tab,
            text="試合一覧で学校名をダブルクリック→学校画面",
        ).pack(fill="x", pady=(0, 6))

        self.competition_notebook = ttk.Notebook(self.competition_tab)
        self.competition_notebook.pack(fill="both", expand=True)

        list_tab = ttk.Frame(self.competition_notebook, padding=6)
        bracket_tab = ttk.Frame(self.competition_notebook, padding=6)
        self.competition_notebook.add(list_tab, text="試合一覧")
        self.competition_notebook.add(bracket_tab, text="トーナメント表")

        self.competition_tree = self._create_tree(
            list_tab,
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
        self.competition_tree.bind(
            "<Double-1>",
            self._on_competition_double_click,
        )

        holder = ttk.Frame(bracket_tab)
        holder.pack(fill="both", expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        self.bracket_canvas = tk.Canvas(
            holder,
            background="white",
            highlightthickness=0,
        )
        vertical = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.bracket_canvas.yview,
        )
        horizontal = ttk.Scrollbar(
            holder,
            orient="horizontal",
            command=self.bracket_canvas.xview,
        )
        self.bracket_canvas.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.bracket_canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

    def _refresh_competition_choices(self) -> None:
        year = self._current_year()
        self._clear_tree(self.competition_tree)
        self._competition_rows = {}
        self.bracket_canvas.delete("all")
        self._competition_id_by_label = {}
        if year is None:
            return

        options = self.model.competition_options(year)
        labels = [option.label for option in options]
        self._competition_id_by_label = {
            option.label: option.competition_id
            for option in options
        }
        self.competition_combo["values"] = labels
        self.competition_var.set(labels[0] if labels else "")
        if labels:
            self._load_competition()

    def _load_competition(self, _event=None) -> None:
        year = self._current_year()
        competition_id = self._competition_id_by_label.get(
            self.competition_var.get()
        )
        self._clear_tree(self.competition_tree)
        self._competition_rows = {}
        self.bracket_canvas.delete("all")
        if year is None or not competition_id:
            return

        result, matches = self.model.competition_detail(
            year,
            competition_id,
        )
        if not result:
            return

        self.competition_summary.configure(
            text=(
                f"{result['competition_name']}  "
                f"期間: {result['start_date'] or '-'} ～ {result['end_date'] or '-'}  "
                f"優勝: {result.get('champion_name') or '-'}  "
                f"準優勝: {result.get('runner_up_name') or '-'}  "
                f"実試合: {result['played_match_count']}  "
                f"不戦勝: {result['bye_count']}"
            )
        )

        for index, row in enumerate(matches):
            iid = f"comp-{index}"
            self._competition_rows[iid] = row
            self.competition_tree.insert(
                "",
                "end",
                iid=iid,
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
        self._draw_bracket(matches)

    def _draw_bracket(self, matches: list[dict]) -> None:
        canvas = self.bracket_canvas
        canvas.delete("all")
        rounds = self.model.bracket_rounds(matches)

        if not rounds:
            canvas.create_text(
                30,
                30,
                anchor="nw",
                text="トーナメント表示対象のラウンドがありません",
            )
            canvas.configure(scrollregion=(0, 0, 800, 500))
            return

        margin_x = 30
        top = 55
        card_w = 220
        card_h = 54
        round_gap = 75
        slot = 78
        max_count = max(len(round_.matches) for round_ in rounds)
        height = max(520, top + max_count * slot + 50)
        width = max(
            900,
            margin_x + len(rounds) * (card_w + round_gap) + 40,
        )
        centers: list[tuple[float, list[float]]] = []

        for round_index, round_ in enumerate(rounds):
            x = margin_x + round_index * (card_w + round_gap)
            canvas.create_text(
                x + card_w / 2,
                22,
                text=round_.round_name,
                font=("TkDefaultFont", 11, "bold"),
            )
            y_centers: list[float] = []
            count = max(1, len(round_.matches))

            for match_index, row in enumerate(round_.matches):
                y_center = top + (
                    match_index + 0.5
                ) * (max_count / count) * slot
                y_centers.append(y_center)
                y1 = y_center - card_h / 2
                y2 = y_center + card_h / 2
                canvas.create_rectangle(
                    x,
                    y1,
                    x + card_w,
                    y2,
                    fill="#f7f7f7",
                    outline="#777",
                )

                team1 = row.get("team1_name") or "-"
                team2 = row.get("team2_name") or "BYE"
                score1 = row.get("team1_score")
                score2 = row.get("team2_score")
                score1_text = "" if score1 is None else str(score1)
                score2_text = "" if score2 is None else str(score2)

                canvas.create_text(
                    x + 8,
                    y_center - 13,
                    anchor="w",
                    text=f"{team1}  {score1_text}",
                    font=(
                        "TkDefaultFont",
                        9,
                        "bold"
                        if row.get("winner_id") == row.get("team1_id")
                        else "normal",
                    ),
                )
                canvas.create_text(
                    x + 8,
                    y_center + 13,
                    anchor="w",
                    text=f"{team2}  {score2_text}",
                    font=(
                        "TkDefaultFont",
                        9,
                        "bold"
                        if row.get("winner_id") == row.get("team2_id")
                        else "normal",
                    ),
                )
            centers.append((x, y_centers))

        # Draw connectors only when a round has an exact 2 -> 1 shape.
        # This avoids inventing bracket links for group/irregular formats.
        for index in range(len(rounds) - 1):
            x1, previous = centers[index]
            x2, next_round = centers[index + 1]
            if len(previous) != 2 * len(next_round):
                continue
            for target_index, target_y in enumerate(next_round):
                first_y = previous[2 * target_index]
                second_y = previous[2 * target_index + 1]
                mid_x = (x1 + card_w + x2) / 2
                for source_y in (first_y, second_y):
                    canvas.create_line(
                        x1 + card_w,
                        source_y,
                        mid_x,
                        source_y,
                        fill="#999",
                    )
                canvas.create_line(
                    mid_x,
                    first_y,
                    mid_x,
                    second_y,
                    fill="#999",
                )
                canvas.create_line(
                    mid_x,
                    target_y,
                    x2,
                    target_y,
                    fill="#999",
                )

        canvas.configure(scrollregion=(0, 0, width, height))

    def _on_competition_double_click(self, event) -> None:
        iid = self.competition_tree.identify_row(event.y)
        column = self.competition_tree.identify_column(event.x)
        row = self._competition_rows.get(iid)
        if not row:
            return
        if column == "#3" and row.get("team1_id"):
            self._navigate_to_school(row["team1_id"])
        elif column == "#5" and row.get("team2_id"):
            self._navigate_to_school(row["team2_id"])
        elif column == "#6" and row.get("winner_id"):
            self._navigate_to_school(row["winner_id"])

    def _navigate_to_competition(self, competition_id: str) -> None:
        for label, value in self._competition_id_by_label.items():
            if value != competition_id:
                continue
            self.competition_var.set(label)
            self.notebook.select(self.competition_tab)
            self._load_competition()
            return

    # ------------------------------------------------------------------
    # School tab: history -> competition / opponent navigation
    # ------------------------------------------------------------------

    def _build_school_tab(self) -> None:
        super()._build_school_tab()
        self.school_history_tree.bind(
            "<Double-1>",
            self._on_school_history_double_click,
        )

    def _refresh_school_prefectures(self) -> None:
        year = self._current_year()
        prefectures = (
            ["", *self.model.prefecture_choices(year)]
            if year is not None
            else [""]
        )
        self.prefecture_combo["values"] = prefectures
        if self.prefecture_var.get() not in prefectures:
            self.prefecture_var.set("")

    def _load_selected_school(self, _event=None) -> None:
        selection = self.school_tree.selection()
        year = self._current_year()
        if year is None or not selection:
            return

        school_id = selection[0]
        record, matches = self.model.school_detail(year, school_id)
        self._clear_tree(self.school_history_tree)
        self._school_history_rows = {}
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
                f"優勝 {record['titles']}  "
                f"準優勝 {record['runner_up_finishes']}"
            )
        )

        for index, row in enumerate(matches):
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

            iid = f"hist-{index}"
            self._school_history_rows[iid] = row
            self.school_history_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row["match_date"] or "未定",
                    row["competition_name"],
                    row.get("round_name") or row.get("phase_code") or "",
                    self.model.result_symbol(
                        row.get("school_result", "")
                    ),
                    row.get("opponent_name", ""),
                    score,
                    row["date_source"],
                ),
            )

    def _on_school_history_double_click(self, event) -> None:
        iid = self.school_history_tree.identify_row(event.y)
        column = self.school_history_tree.identify_column(event.x)
        row = self._school_history_rows.get(iid)
        if not row:
            return
        if column == "#2":
            self._navigate_to_competition(row["competition_id"])
        elif column == "#5" and row.get("opponent_id"):
            self._navigate_to_school(row["opponent_id"])

    def _navigate_to_school(self, school_id: str) -> None:
        self.notebook.select(self.school_tab)
        self.school_search_var.set(school_id)
        self.prefecture_var.set("")
        self._search_schools()
        if self.school_tree.exists(school_id):
            self.school_tree.selection_set(school_id)
            self.school_tree.focus(school_id)
            self.school_tree.see(school_id)
            self._load_selected_school()
