from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .browse_gui_enhanced import EnhancedBrowseApp
from .browse_gui_model import (
    ALL_COMPETITIONS_LABEL,
    ALL_PREFECTURES_LABEL,
    ALL_SEASONS_LABEL,
    ALL_TYPES_LABEL,
    SEASON_SEGMENT_LABELS,
)


class Stage12UBrowseApp(EnhancedBrowseApp):
    """Stage 12U GUI: home, Japanese filters and bracket navigation."""

    def __init__(self, root: tk.Tk, model):
        self.date_segment_var = tk.StringVar(master=root, value=ALL_SEASONS_LABEL)
        self.date_type_var = tk.StringVar(master=root, value=ALL_TYPES_LABEL)
        self.comp_segment_var = tk.StringVar(master=root, value=ALL_SEASONS_LABEL)
        self.comp_type_var = tk.StringVar(master=root, value=ALL_TYPES_LABEL)

        self.home_title_var = tk.StringVar(master=root, value="")
        self.home_counts_var = tk.StringVar(master=root, value="")
        self.home_today_var = tk.StringVar(master=root, value="")
        self.home_segments_var = tk.StringVar(master=root, value="")
        self._home_summary: dict = {}

        self._date_segment_by_label: dict[str, str] = {}
        self._date_type_by_label: dict[str, str] = {}
        self._date_prefecture_by_label: dict[str, str] = {}
        self._comp_segment_by_label: dict[str, str] = {}
        self._comp_type_by_label: dict[str, str] = {}
        self._school_prefecture_by_label: dict[str, str] = {}

        super().__init__(root, model)
        root.geometry("1320x860")
        root.minsize(1040, 680)
        self.notebook.select(self.home_tab)

    # ------------------------------------------------------------------
    # Layout / home
    # ------------------------------------------------------------------

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

        ttk.Label(top, text="閲覧専用 / SQLite").pack(side="left")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.home_tab = ttk.Frame(self.notebook, padding=18)
        self.date_tab = ttk.Frame(self.notebook, padding=10)
        self.competition_tab = ttk.Frame(self.notebook, padding=10)
        self.school_tab = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.home_tab, text="ホーム")
        self.notebook.add(self.date_tab, text="日付別試合")
        self.notebook.add(self.competition_tab, text="大会結果")
        self.notebook.add(self.school_tab, text="学校戦績")

        self._build_home_tab()
        self._build_date_tab()
        self._build_competition_tab()
        self._build_school_tab()

    def _build_home_tab(self) -> None:
        ttk.Label(
            self.home_tab,
            textvariable=self.home_title_var,
            font=("TkDefaultFont", 18, "bold"),
        ).pack(anchor="w", pady=(4, 16))

        summary = ttk.LabelFrame(
            self.home_tab,
            text="シーズン概要",
            padding=16,
        )
        summary.pack(fill="x", pady=(0, 14))
        ttk.Label(
            summary,
            textvariable=self.home_counts_var,
            font=("TkDefaultFont", 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            summary,
            textvariable=self.home_segments_var,
        ).pack(anchor="w")

        today_frame = ttk.LabelFrame(
            self.home_tab,
            text="試合日ナビゲーション",
            padding=16,
        )
        today_frame.pack(fill="x", pady=(0, 14))
        ttk.Label(
            today_frame,
            textvariable=self.home_today_var,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))
        self.home_date_button = ttk.Button(
            today_frame,
            text="今日 / 次の試合日を開く",
            command=self._open_home_date,
        )
        self.home_date_button.pack(side="left")
        ttk.Button(
            today_frame,
            text="大会一覧を開く",
            command=lambda: self.notebook.select(self.competition_tab),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            today_frame,
            text="学校検索を開く",
            command=lambda: self.notebook.select(self.school_tab),
        ).pack(side="left", padx=(8, 0))

        note = ttk.LabelFrame(
            self.home_tab,
            text="表示上の注意",
            padding=16,
        )
        note.pack(fill="x")
        ttk.Label(
            note,
            text=(
                "試合日の date_source が projected_v1 の場合は表示用の推定配置です。"
                " override は実日付差替え、undated は日付未定を示します。"
            ),
            wraplength=1050,
            justify="left",
        ).pack(anchor="w")

    def _refresh_home(self) -> None:
        year = self._current_year()
        if year is None:
            return
        summary = self.model.home_summary(year)
        self._home_summary = summary

        self.home_title_var.set(f"{year}年 シーズン")
        self.home_counts_var.set(
            f"試合 {summary['match_count']}   "
            f"大会 {summary['competition_count']}   "
            f"学校 {summary['school_count']}"
        )

        counts = summary["segment_counts"]
        segment_text = "   ".join(
            f"{SEASON_SEGMENT_LABELS.get(key, key)} {counts.get(key, 0)}大会"
            for key in ("spring", "summer", "autumn")
        )
        self.home_segments_var.set(segment_text)

        today = summary["today"]
        today_count = summary["today_match_count"]
        previous = summary["previous_match_date"] or "-"
        next_date = summary["next_match_date"] or "-"
        self.home_today_var.set(
            f"基準日: {today}   当日: {today_count}試合\n"
            f"直前の試合日: {previous}   次の試合日: {next_date}"
        )
        self.home_date_button.configure(
            state="normal" if next_date != "-" or today_count else "disabled"
        )

    def _open_home_date(self) -> None:
        year = self._current_year()
        if year is None:
            return
        summary = self._home_summary or self.model.home_summary(year)
        target = (
            summary["today"]
            if summary["today_match_count"]
            else summary["next_match_date"]
        )
        if not target:
            self.notebook.select(self.date_tab)
            return

        values = list(self.date_combo["values"])
        if target not in values:
            self.notebook.select(self.date_tab)
            return

        self._reset_date_filters(load=False)
        self.date_var.set(target)
        self.notebook.select(self.date_tab)
        self._load_date_matches()

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
        self._refresh_home()
        self._refresh_date_choices()
        self._refresh_competition_choices()
        self._refresh_school_prefectures()
        self._search_schools()

    # ------------------------------------------------------------------
    # Date tab: season/type/competition/prefecture filters
    # ------------------------------------------------------------------

    def _build_date_tab(self) -> None:
        row1 = ttk.Frame(self.date_tab)
        row1.pack(fill="x", pady=(0, 6))
        row2 = ttk.Frame(self.date_tab)
        row2.pack(fill="x", pady=(0, 8))

        ttk.Label(row1, text="試合日").pack(side="left")
        self.date_combo = ttk.Combobox(
            row1,
            textvariable=self.date_var,
            state="readonly",
            width=16,
        )
        self.date_combo.pack(side="left", padx=(6, 14))
        self.date_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Label(row1, text="季節").pack(side="left")
        self.date_segment_combo = ttk.Combobox(
            row1,
            textvariable=self.date_segment_var,
            state="readonly",
            width=14,
        )
        self.date_segment_combo.pack(side="left", padx=(6, 14))
        self.date_segment_combo.bind(
            "<<ComboboxSelected>>",
            self._on_date_segment_changed,
        )

        ttk.Label(row1, text="大会種別").pack(side="left")
        self.date_type_combo = ttk.Combobox(
            row1,
            textvariable=self.date_type_var,
            state="readonly",
            width=20,
        )
        self.date_type_combo.pack(side="left", padx=(6, 14))
        self.date_type_combo.bind(
            "<<ComboboxSelected>>",
            self._on_date_type_changed,
        )

        self.date_summary = ttk.Label(row1, text="")
        self.date_summary.pack(side="right")

        ttk.Label(row2, text="大会").pack(side="left")
        self.date_comp_combo = ttk.Combobox(
            row2,
            textvariable=self.date_comp_var,
            state="readonly",
            width=45,
        )
        self.date_comp_combo.pack(side="left", padx=(6, 14))
        self.date_comp_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Label(row2, text="都道府県").pack(side="left")
        self.date_pref_combo = ttk.Combobox(
            row2,
            textvariable=self.date_pref_var,
            state="readonly",
            width=16,
        )
        self.date_pref_combo.pack(side="left", padx=(6, 14))
        self.date_pref_combo.bind("<<ComboboxSelected>>", self._load_date_matches)

        ttk.Button(
            row2,
            text="条件クリア",
            command=self._reset_date_filters,
        ).pack(side="left")

        ttk.Label(
            self.date_tab,
            text="ダブルクリック: 大会名→大会画面 / 学校名・勝者→学校画面",
        ).pack(fill="x", pady=(0, 6))

        self.date_tree = self._create_tree(
            self.date_tab,
            [
                ("competition", "大会", 230, "w"),
                ("round", "ラウンド", 90, "center"),
                ("team1", "チーム1", 160, "w"),
                ("score", "得点", 70, "center"),
                ("team2", "チーム2", 160, "w"),
                ("winner", "勝者", 160, "w"),
                ("source", "日付種別", 95, "center"),
            ],
        )
        self.date_tree.bind("<Double-1>", self._on_date_double_click)

    @staticmethod
    def _option_maps(options) -> tuple[list[str], dict[str, str]]:
        labels = [option.label for option in options]
        return labels, {option.label: option.value for option in options}

    def _refresh_date_choices(self) -> None:
        year = self._current_year()
        self._clear_tree(self.date_tree)
        self._date_rows = {}
        if year is None:
            return

        dates = self.model.date_choices(year)
        self.date_combo["values"] = dates
        self.date_var.set(dates[0] if dates else "")

        segment_options = self.model.season_segment_options(year)
        segment_labels, segment_map = self._option_maps(segment_options)
        self._date_segment_by_label = segment_map
        self.date_segment_combo["values"] = [
            ALL_SEASONS_LABEL,
            *segment_labels,
        ]
        self.date_segment_var.set(ALL_SEASONS_LABEL)

        prefecture_options = self.model.prefecture_options(year)
        prefecture_labels, prefecture_map = self._option_maps(prefecture_options)
        self._date_prefecture_by_label = prefecture_map
        self.date_pref_combo["values"] = [
            ALL_PREFECTURES_LABEL,
            *prefecture_labels,
        ]
        self.date_pref_var.set(ALL_PREFECTURES_LABEL)

        self._refresh_date_type_options()
        self._refresh_date_competition_options()
        if dates:
            self._load_date_matches()

    def _selected_date_segment(self) -> str:
        return self._date_segment_by_label.get(
            self.date_segment_var.get(),
            "",
        )

    def _selected_date_type(self) -> str:
        return self._date_type_by_label.get(
            self.date_type_var.get(),
            "",
        )

    def _refresh_date_type_options(self) -> None:
        year = self._current_year()
        if year is None:
            return
        options = self.model.competition_type_options(
            year,
            season_segment=self._selected_date_segment(),
        )
        labels, mapping = self._option_maps(options)
        self._date_type_by_label = mapping
        self.date_type_combo["values"] = [ALL_TYPES_LABEL, *labels]
        if self.date_type_var.get() not in self.date_type_combo["values"]:
            self.date_type_var.set(ALL_TYPES_LABEL)
        if not self.date_type_var.get():
            self.date_type_var.set(ALL_TYPES_LABEL)

    def _refresh_date_competition_options(self) -> None:
        year = self._current_year()
        if year is None:
            return
        options = self.model.competition_options(
            year,
            season_segment=self._selected_date_segment(),
            competition_type=self._selected_date_type(),
        )
        self._date_competition_id_by_label = {
            option.label: option.competition_id
            for option in options
        }
        labels = [ALL_COMPETITIONS_LABEL, *[
            option.label for option in options
        ]]
        self.date_comp_combo["values"] = labels
        if self.date_comp_var.get() not in labels:
            self.date_comp_var.set(ALL_COMPETITIONS_LABEL)
        if not self.date_comp_var.get():
            self.date_comp_var.set(ALL_COMPETITIONS_LABEL)

    def _on_date_segment_changed(self, _event=None) -> None:
        self.date_type_var.set(ALL_TYPES_LABEL)
        self.date_comp_var.set(ALL_COMPETITIONS_LABEL)
        self._refresh_date_type_options()
        self._refresh_date_competition_options()
        self._load_date_matches()

    def _on_date_type_changed(self, _event=None) -> None:
        self.date_comp_var.set(ALL_COMPETITIONS_LABEL)
        self._refresh_date_competition_options()
        self._load_date_matches()

    def _reset_date_filters(self, *, load: bool = True) -> None:
        self.date_segment_var.set(ALL_SEASONS_LABEL)
        self.date_type_var.set(ALL_TYPES_LABEL)
        self.date_comp_var.set(ALL_COMPETITIONS_LABEL)
        self.date_pref_var.set(ALL_PREFECTURES_LABEL)
        self._refresh_date_type_options()
        self._refresh_date_competition_options()
        if load:
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
        prefecture_code = self._date_prefecture_by_label.get(
            self.date_pref_var.get(),
            "",
        )
        rows = self.model.matches_for_date_choice(
            year,
            choice,
            competition_id=competition_id,
            prefecture_code=prefecture_code,
            season_segment=self._selected_date_segment(),
            competition_type=self._selected_date_type(),
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
        self.date_summary.configure(text=f"{choice} / {len(rows)}試合")

    # ------------------------------------------------------------------
    # Competition tab: season/type filters + bracket
    # ------------------------------------------------------------------

    def _build_competition_tab(self) -> None:
        filters = ttk.Frame(self.competition_tab)
        filters.pack(fill="x", pady=(0, 6))
        selector = ttk.Frame(self.competition_tab)
        selector.pack(fill="x", pady=(0, 8))

        ttk.Label(filters, text="季節").pack(side="left")
        self.comp_segment_combo = ttk.Combobox(
            filters,
            textvariable=self.comp_segment_var,
            state="readonly",
            width=14,
        )
        self.comp_segment_combo.pack(side="left", padx=(6, 14))
        self.comp_segment_combo.bind(
            "<<ComboboxSelected>>",
            self._on_comp_segment_changed,
        )

        ttk.Label(filters, text="大会種別").pack(side="left")
        self.comp_type_combo = ttk.Combobox(
            filters,
            textvariable=self.comp_type_var,
            state="readonly",
            width=20,
        )
        self.comp_type_combo.pack(side="left", padx=(6, 14))
        self.comp_type_combo.bind(
            "<<ComboboxSelected>>",
            self._on_comp_type_changed,
        )

        ttk.Button(
            filters,
            text="条件クリア",
            command=self._reset_comp_filters,
        ).pack(side="left")

        ttk.Label(selector, text="大会").pack(side="left")
        self.competition_combo = ttk.Combobox(
            selector,
            textvariable=self.competition_var,
            state="readonly",
            width=64,
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
            selector,
            text="表示",
            command=self._load_competition,
        ).pack(side="left")

        self.competition_summary = ttk.Label(
            self.competition_tab,
            text="",
            anchor="w",
            justify="left",
        )
        self.competition_summary.pack(fill="x", pady=(0, 6))

        ttk.Label(
            self.competition_tab,
            text=(
                "試合一覧: 学校名をダブルクリック / "
                "トーナメント表: 学校名をクリック → 学校画面"
            ),
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
                ("team1", "チーム1", 160, "w"),
                ("score", "得点", 70, "center"),
                ("team2", "チーム2", 160, "w"),
                ("winner", "勝者", 160, "w"),
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
        if year is None:
            return

        segment_options = self.model.season_segment_options(year)
        segment_labels, segment_map = self._option_maps(segment_options)
        self._comp_segment_by_label = segment_map
        self.comp_segment_combo["values"] = [
            ALL_SEASONS_LABEL,
            *segment_labels,
        ]
        self.comp_segment_var.set(ALL_SEASONS_LABEL)
        self._refresh_comp_type_options()
        self._refresh_competition_list()

    def _selected_comp_segment(self) -> str:
        return self._comp_segment_by_label.get(
            self.comp_segment_var.get(),
            "",
        )

    def _selected_comp_type(self) -> str:
        return self._comp_type_by_label.get(
            self.comp_type_var.get(),
            "",
        )

    def _refresh_comp_type_options(self) -> None:
        year = self._current_year()
        if year is None:
            return
        options = self.model.competition_type_options(
            year,
            season_segment=self._selected_comp_segment(),
        )
        labels, mapping = self._option_maps(options)
        self._comp_type_by_label = mapping
        values = [ALL_TYPES_LABEL, *labels]
        self.comp_type_combo["values"] = values
        if self.comp_type_var.get() not in values:
            self.comp_type_var.set(ALL_TYPES_LABEL)
        if not self.comp_type_var.get():
            self.comp_type_var.set(ALL_TYPES_LABEL)

    def _refresh_competition_list(
        self,
        *,
        preserve_id: str = "",
    ) -> None:
        year = self._current_year()
        if year is None:
            return

        options = self.model.competition_options(
            year,
            season_segment=self._selected_comp_segment(),
            competition_type=self._selected_comp_type(),
        )
        labels = [option.label for option in options]
        self._competition_id_by_label = {
            option.label: option.competition_id
            for option in options
        }
        self.competition_combo["values"] = labels

        target_label = next(
            (
                option.label
                for option in options
                if option.competition_id == preserve_id
            ),
            "",
        )
        if target_label:
            self.competition_var.set(target_label)
        elif labels:
            self.competition_var.set(labels[0])
        else:
            self.competition_var.set("")
            self.competition_summary.configure(text="")
            self._clear_tree(self.competition_tree)
            self.bracket_canvas.delete("all")
            return
        self._load_competition()

    def _on_comp_segment_changed(self, _event=None) -> None:
        self.comp_type_var.set(ALL_TYPES_LABEL)
        self._refresh_comp_type_options()
        self._refresh_competition_list()

    def _on_comp_type_changed(self, _event=None) -> None:
        self._refresh_competition_list()

    def _reset_comp_filters(self) -> None:
        self.comp_segment_var.set(ALL_SEASONS_LABEL)
        self.comp_type_var.set(ALL_TYPES_LABEL)
        self._refresh_comp_type_options()
        self._refresh_competition_list()

    def _navigate_to_competition(self, competition_id: str) -> None:
        self.comp_segment_var.set(ALL_SEASONS_LABEL)
        self.comp_type_var.set(ALL_TYPES_LABEL)
        self._refresh_comp_type_options()
        self._refresh_competition_list(preserve_id=competition_id)
        self.notebook.select(self.competition_tab)

    # ------------------------------------------------------------------
    # Bracket: clickable school names
    # ------------------------------------------------------------------

    def _bind_bracket_school(
        self,
        item_id: int,
        school_id: str,
    ) -> None:
        if not school_id:
            return
        self.bracket_canvas.tag_bind(
            item_id,
            "<Button-1>",
            lambda _event, sid=school_id: self._navigate_to_school(sid),
        )
        self.bracket_canvas.tag_bind(
            item_id,
            "<Enter>",
            lambda _event: self.bracket_canvas.configure(cursor="hand2"),
        )
        self.bracket_canvas.tag_bind(
            item_id,
            "<Leave>",
            lambda _event: self.bracket_canvas.configure(cursor=""),
        )

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
        card_w = 235
        card_h = 58
        round_gap = 80
        slot = 82
        max_count = max(len(round_.matches) for round_ in rounds)
        height = max(540, top + max_count * slot + 50)
        width = max(
            930,
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

                team1_item = canvas.create_text(
                    x + 8,
                    y_center - 14,
                    anchor="w",
                    text=f"{team1}  {score1_text}",
                    fill="#145ea8" if row.get("team1_id") else "#222",
                    font=(
                        "TkDefaultFont",
                        9,
                        "bold"
                        if row.get("winner_id") == row.get("team1_id")
                        else "normal",
                    ),
                )
                self._bind_bracket_school(
                    team1_item,
                    row.get("team1_id") or "",
                )

                team2_item = canvas.create_text(
                    x + 8,
                    y_center + 14,
                    anchor="w",
                    text=f"{team2}  {score2_text}",
                    fill="#145ea8" if row.get("team2_id") else "#222",
                    font=(
                        "TkDefaultFont",
                        9,
                        "bold"
                        if row.get("winner_id") == row.get("team2_id")
                        else "normal",
                    ),
                )
                self._bind_bracket_school(
                    team2_item,
                    row.get("team2_id") or "",
                )
            centers.append((x, y_centers))

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

    # ------------------------------------------------------------------
    # School tab: prefecture names
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

        ttk.Label(controls, text="都道府県").pack(side="left")
        self.prefecture_combo = ttk.Combobox(
            controls,
            textvariable=self.prefecture_var,
            state="readonly",
            width=16,
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
                ("name", "学校名", 230, "w"),
                ("pref", "都道府県", 100, "center"),
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
                ("competition", "大会", 220, "w"),
                ("round", "ラウンド", 90, "center"),
                ("result", "結果", 65, "center"),
                ("opponent", "対戦相手", 180, "w"),
                ("score", "得点", 70, "center"),
                ("date_source", "日付種別", 95, "center"),
            ],
        )
        self.school_history_tree.bind(
            "<Double-1>",
            self._on_school_history_double_click,
        )

    def _refresh_school_prefectures(self) -> None:
        year = self._current_year()
        if year is None:
            return
        options = self.model.prefecture_options(year)
        labels, mapping = self._option_maps(options)
        self._school_prefecture_by_label = mapping
        values = [ALL_PREFECTURES_LABEL, *labels]
        self.prefecture_combo["values"] = values
        if self.prefecture_var.get() not in values:
            self.prefecture_var.set(ALL_PREFECTURES_LABEL)

    def _clear_school_search(self) -> None:
        self.school_search_var.set("")
        self.prefecture_var.set(ALL_PREFECTURES_LABEL)
        self._search_schools()

    def _search_schools(self) -> None:
        year = self._current_year()
        self._clear_tree(self.school_tree)
        self._clear_tree(self.school_history_tree)
        self.school_detail_label.configure(text="学校を選択してください")
        if year is None:
            return

        prefecture_code = self._school_prefecture_by_label.get(
            self.prefecture_var.get(),
            "",
        )
        rows = self.model.search_schools(
            year,
            text=self.school_search_var.get(),
            prefecture_code=prefecture_code,
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
                    self.model.prefecture_label(row["prefecture_code"]),
                    row["games"],
                    row["wins"],
                    row["losses"],
                    f"{float(row['win_pct']):.3f}",
                    row["titles"],
                ),
            )

    def _navigate_to_school(self, school_id: str) -> None:
        self.notebook.select(self.school_tab)
        self.school_search_var.set(school_id)
        self.prefecture_var.set(ALL_PREFECTURES_LABEL)
        self._search_schools()
        if self.school_tree.exists(school_id):
            self.school_tree.selection_set(school_id)
            self.school_tree.focus(school_id)
            self.school_tree.see(school_id)
            self._load_selected_school()
