from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .browse_gui_model import BrowseGuiModel
from .browse_gui_stage12u import Stage12UBrowseApp


BATTING_METRICS = (
    ("OPS", "ops"),
    ("打率", "batting_average"),
    ("出塁率", "on_base_percentage"),
    ("長打率", "slugging_percentage"),
    ("安打", "hits"),
    ("本塁打", "home_runs"),
    ("打点", "rbi"),
    ("得点", "runs"),
    ("四球", "walks"),
    ("盗塁", "stolen_bases"),
)

PITCHING_METRICS = (
    ("防御率", "earned_run_average"),
    ("WHIP", "whip"),
    ("奪三振", "strikeouts"),
    ("K/9", "strikeouts_per_9"),
    ("BB/9", "walks_per_9"),
    ("K/BB", "strikeout_walk_ratio"),
    ("K-BB%", "k_minus_bb_pct"),
)

POSITION_LABELS = {
    "P": "投手",
    "C": "捕手",
    "1B": "一塁",
    "2B": "二塁",
    "3B": "三塁",
    "SS": "遊撃",
    "LF": "左翼",
    "CF": "中堅",
    "RF": "右翼",
}


class Stage13D3BrowseApp(Stage12UBrowseApp):
    """Exploratory read-only GUI for player masters and individual stats."""

    def __init__(self, root: tk.Tk, model: BrowseGuiModel):
        self.player_search_var = tk.StringVar(master=root, value="")
        self.player_school_var = tk.StringVar(master=root, value="")
        self.player_position_var = tk.StringVar(master=root, value="")
        self.roster_school_var = tk.StringVar(master=root, value="")

        self.stats_competition_var = tk.StringVar(master=root, value="")
        self.batting_metric_var = tk.StringVar(
            master=root,
            value=BATTING_METRICS[0][0],
        )
        self.pitching_metric_var = tk.StringVar(
            master=root,
            value=PITCHING_METRICS[0][0],
        )
        self.stats_limit_var = tk.StringVar(master=root, value="20")
        self.player_profile_var = tk.StringVar(master=root, value="")
        self.player_batting_var = tk.StringVar(master=root, value="")
        self.player_pitching_var = tk.StringVar(master=root, value="")
        self.roster_summary_var = tk.StringVar(master=root, value="")
        self.rankings_summary_var = tk.StringVar(master=root, value="")

        self._player_rows: dict[str, dict] = {}
        self._roster_rows: dict[str, dict] = {}
        self._batting_ranking_rows: dict[str, dict] = {}
        self._pitching_ranking_rows: dict[str, dict] = {}
        self._stats_competition_id_by_label: dict[str, str] = {}
        self._batting_metric_by_label = dict(BATTING_METRICS)
        self._pitching_metric_by_label = dict(PITCHING_METRICS)

        super().__init__(root, model)
        root.geometry("1400x900")
        root.minsize(1120, 720)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        super()._build_layout()

        self.player_tab = ttk.Frame(self.notebook, padding=10)
        self.rankings_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.player_tab, text="選手・ロスター")
        self.notebook.add(self.rankings_tab, text="個人成績ランキング")

        self._build_player_tab()
        self._build_rankings_tab()

    def _build_competition_tab(self) -> None:
        super()._build_competition_tab()
        actions = ttk.Frame(self.competition_tab)
        actions.pack(fill="x", pady=(6, 0))
        ttk.Button(
            actions,
            text="この大会の個人成績ランキング",
            command=self._open_current_competition_rankings,
        ).pack(side="right")
        ttk.Button(
            actions,
            text="予選進行プレビュー（試験・別画面）",
            command=self._open_hiroshima_preview_pilot,
        ).pack(side="left")

    def _open_hiroshima_preview_pilot(self) -> None:
        # The preview consumes its own Stage32 contract/Stage34 read-model.
        # No browse SQLite tables, ranking events or main scheduler mutate.
        from .hiroshima_stage13e3g35_preview_gui import (
            open_hiroshima_preview_window,
        )
        try:
            open_hiroshima_preview_window(self.root, self.model.data_dir)
        except (OSError, ValueError, TypeError) as exc:
            from tkinter import messagebox

            messagebox.showerror(
                "予選進行プレビューの読込エラー",
                str(exc),
                parent=self.root,
            )

    def _build_school_tab(self) -> None:
        super()._build_school_tab()
        actions = ttk.Frame(self.school_tab)
        actions.pack(fill="x", pady=(6, 0))
        ttk.Button(
            actions,
            text="選択校のロスター・個人成績",
            command=self._open_selected_school_roster,
        ).pack(side="right")

    def _build_player_tab(self) -> None:
        self.player_notebook = ttk.Notebook(self.player_tab)
        self.player_notebook.pack(fill="both", expand=True)

        self.player_search_tab = ttk.Frame(
            self.player_notebook,
            padding=8,
        )
        self.roster_tab = ttk.Frame(
            self.player_notebook,
            padding=8,
        )
        self.player_notebook.add(
            self.player_search_tab,
            text="選手検索・詳細",
        )
        self.player_notebook.add(
            self.roster_tab,
            text="学校ロスター",
        )

        self._build_player_search_tab()
        self._build_roster_tab()

    def _build_player_search_tab(self) -> None:
        controls = ttk.Frame(self.player_search_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="選手名 / ID").pack(side="left")
        entry = ttk.Entry(
            controls,
            textvariable=self.player_search_var,
            width=24,
        )
        entry.pack(side="left", padx=(6, 12))
        entry.bind("<Return>", lambda _event: self._search_players())

        ttk.Label(controls, text="学校ID").pack(side="left")
        ttk.Entry(
            controls,
            textvariable=self.player_school_var,
            width=16,
        ).pack(side="left", padx=(6, 12))

        ttk.Label(controls, text="守備位置").pack(side="left")
        self.player_position_combo = ttk.Combobox(
            controls,
            textvariable=self.player_position_var,
            state="readonly",
            width=10,
            values=["", *POSITION_LABELS.keys()],
        )
        self.player_position_combo.pack(side="left", padx=(6, 12))

        ttk.Button(
            controls,
            text="検索",
            command=self._search_players,
        ).pack(side="left")
        ttk.Button(
            controls,
            text="条件クリア",
            command=self._clear_player_search,
        ).pack(side="left", padx=(6, 0))

        results = ttk.LabelFrame(
            self.player_search_tab,
            text="選手検索結果",
            padding=6,
        )
        results.pack(fill="both", expand=True, pady=(0, 8))
        self.player_tree = self._create_tree(
            results,
            [
                ("name", "選手名", 150, "w"),
                ("school", "学校", 210, "w"),
                ("grade", "学年", 55, "center"),
                ("position", "位置", 70, "center"),
                ("bats", "打", 45, "center"),
                ("throws", "投", 45, "center"),
                ("number", "番号", 55, "e"),
                ("player_id", "選手ID", 175, "w"),
            ],
        )
        self.player_tree.configure(height=8)
        self.player_tree.bind(
            "<<TreeviewSelect>>",
            self._load_selected_player,
        )
        self.player_tree.bind(
            "<Double-1>",
            self._load_selected_player,
        )

        detail = ttk.LabelFrame(
            self.player_search_tab,
            text="選手詳細 / シーズン成績",
            padding=10,
        )
        detail.pack(fill="x")
        ttk.Label(
            detail,
            textvariable=self.player_profile_var,
            font=("TkDefaultFont", 11, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 5))
        ttk.Label(
            detail,
            textvariable=self.player_batting_var,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 3))
        ttk.Label(
            detail,
            textvariable=self.player_pitching_var,
            anchor="w",
            justify="left",
        ).pack(fill="x")

    def _build_roster_tab(self) -> None:
        controls = ttk.Frame(self.roster_tab)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="学校ID").pack(side="left")
        entry = ttk.Entry(
            controls,
            textvariable=self.roster_school_var,
            width=18,
        )
        entry.pack(side="left", padx=(6, 8))
        entry.bind("<Return>", lambda _event: self._load_school_roster())
        ttk.Button(
            controls,
            text="ロスター表示",
            command=self._load_school_roster,
        ).pack(side="left")
        ttk.Label(
            controls,
            text="ダブルクリック: 選手詳細へ",
        ).pack(side="right")

        ttk.Label(
            self.roster_tab,
            textvariable=self.roster_summary_var,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        frame = ttk.LabelFrame(
            self.roster_tab,
            text="20人ロスター / 個人成績",
            padding=6,
        )
        frame.pack(fill="both", expand=True)
        self.roster_tree = self._create_tree(
            frame,
            [
                ("no", "番号", 48, "e"),
                ("name", "選手名", 130, "w"),
                ("grade", "学年", 48, "center"),
                ("pos", "位置", 55, "center"),
                ("games", "試合", 48, "e"),
                ("ab", "打数", 48, "e"),
                ("hits", "安打", 48, "e"),
                ("hr", "本塁打", 55, "e"),
                ("avg", "打率", 62, "e"),
                ("ops", "OPS", 62, "e"),
                ("ip", "投球回", 65, "e"),
                ("era", "防御率", 65, "e"),
                ("so", "奪三振", 55, "e"),
            ],
        )
        self.roster_tree.bind(
            "<Double-1>",
            self._on_roster_double_click,
        )

    def _build_rankings_tab(self) -> None:
        controls = ttk.Frame(self.rankings_tab)
        controls.pack(fill="x", pady=(0, 8))

        ttk.Label(controls, text="大会").pack(side="left")
        self.stats_competition_combo = ttk.Combobox(
            controls,
            textvariable=self.stats_competition_var,
            state="readonly",
            width=54,
        )
        self.stats_competition_combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(6, 12),
        )
        self.stats_competition_combo.bind(
            "<<ComboboxSelected>>",
            self._load_rankings,
        )

        ttk.Label(controls, text="打撃").pack(side="left")
        self.batting_metric_combo = ttk.Combobox(
            controls,
            textvariable=self.batting_metric_var,
            state="readonly",
            width=10,
            values=[label for label, _ in BATTING_METRICS],
        )
        self.batting_metric_combo.pack(side="left", padx=(6, 10))
        self.batting_metric_combo.bind(
            "<<ComboboxSelected>>",
            self._load_rankings,
        )

        ttk.Label(controls, text="投手").pack(side="left")
        self.pitching_metric_combo = ttk.Combobox(
            controls,
            textvariable=self.pitching_metric_var,
            state="readonly",
            width=10,
            values=[label for label, _ in PITCHING_METRICS],
        )
        self.pitching_metric_combo.pack(side="left", padx=(6, 10))
        self.pitching_metric_combo.bind(
            "<<ComboboxSelected>>",
            self._load_rankings,
        )

        ttk.Label(controls, text="件数").pack(side="left")
        ttk.Combobox(
            controls,
            textvariable=self.stats_limit_var,
            state="readonly",
            width=5,
            values=["10", "20", "50", "100"],
        ).pack(side="left", padx=(6, 10))

        ttk.Button(
            controls,
            text="表示",
            command=self._load_rankings,
        ).pack(side="left")

        ttk.Label(
            self.rankings_tab,
            textvariable=self.rankings_summary_var,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))
        ttk.Label(
            self.rankings_tab,
            text="ランキング行をダブルクリック → 選手詳細",
        ).pack(fill="x", pady=(0, 6))

        panes = ttk.Panedwindow(
            self.rankings_tab,
            orient="horizontal",
        )
        panes.pack(fill="both", expand=True)

        batting_frame = ttk.LabelFrame(
            panes,
            text="打撃ランキング",
            padding=6,
        )
        pitching_frame = ttk.LabelFrame(
            panes,
            text="投手ランキング",
            padding=6,
        )
        panes.add(batting_frame, weight=1)
        panes.add(pitching_frame, weight=1)

        self.batting_ranking_tree = self._create_tree(
            batting_frame,
            [
                ("rank", "順位", 48, "e"),
                ("name", "選手名", 125, "w"),
                ("school", "学校", 170, "w"),
                ("grade", "学年", 48, "center"),
                ("pos", "位置", 55, "center"),
                ("value", "記録", 72, "e"),
                ("games", "試合", 48, "e"),
                ("pa", "打席", 48, "e"),
            ],
        )
        self.batting_ranking_tree.bind(
            "<Double-1>",
            self._on_batting_ranking_double_click,
        )

        self.pitching_ranking_tree = self._create_tree(
            pitching_frame,
            [
                ("rank", "順位", 48, "e"),
                ("name", "選手名", 125, "w"),
                ("school", "学校", 170, "w"),
                ("grade", "学年", 48, "center"),
                ("value", "記録", 72, "e"),
                ("games", "試合", 48, "e"),
                ("ip", "投球回", 65, "e"),
            ],
        )
        self.pitching_ranking_tree.bind(
            "<Double-1>",
            self._on_pitching_ranking_double_click,
        )

    # ------------------------------------------------------------------
    # Year refresh
    # ------------------------------------------------------------------

    def _refresh_year_views(self) -> None:
        super()._refresh_year_views()
        self._refresh_player_views()
        self._refresh_rankings_competitions()

    def _refresh_player_views(self) -> None:
        self._clear_tree(self.player_tree)
        self._clear_tree(self.roster_tree)
        self._player_rows = {}
        self._roster_rows = {}
        self.player_profile_var.set("")
        self.player_batting_var.set("")
        self.player_pitching_var.set("")
        self.roster_summary_var.set("")

    def _refresh_rankings_competitions(self) -> None:
        year = self._current_year()
        self._clear_tree(self.batting_ranking_tree)
        self._clear_tree(self.pitching_ranking_tree)
        self._batting_ranking_rows = {}
        self._pitching_ranking_rows = {}
        self.rankings_summary_var.set("")
        if year is None:
            self.stats_competition_combo["values"] = []
            self.stats_competition_var.set("")
            return

        options = self.model.competition_options(year)
        self._stats_competition_id_by_label = {
            option.label: option.competition_id
            for option in options
        }
        labels = [option.label for option in options]
        self.stats_competition_combo["values"] = labels
        self.stats_competition_var.set(labels[0] if labels else "")

    # ------------------------------------------------------------------
    # Player search / detail
    # ------------------------------------------------------------------

    def _clear_player_search(self) -> None:
        self.player_search_var.set("")
        self.player_school_var.set("")
        self.player_position_var.set("")
        self._search_players()

    def _search_players(self) -> None:
        year = self._current_year()
        self._clear_tree(self.player_tree)
        self._player_rows = {}
        if year is None:
            return

        rows = self.model.search_players(
            year,
            text=self.player_search_var.get(),
            school_id=self.player_school_var.get(),
            position=self.player_position_var.get(),
        )
        for row in rows:
            player_id = str(row["player_id"])
            self._player_rows[player_id] = row
            self.player_tree.insert(
                "",
                "end",
                iid=player_id,
                values=(
                    row["display_name"],
                    row.get("school_name") or row["school_id"],
                    row["academic_year"],
                    POSITION_LABELS.get(
                        row["primary_position"],
                        row["primary_position"],
                    ),
                    row["bats"],
                    row["throws"],
                    row["roster_no"],
                    player_id,
                ),
            )

    def _load_selected_player(self, _event=None) -> None:
        selection = self.player_tree.selection()
        if not selection:
            return
        self._navigate_to_player(selection[0])

    def _navigate_to_player(self, player_id: str) -> None:
        year = self._current_year()
        if year is None or not player_id:
            return
        self.notebook.select(self.player_tab)
        self.player_notebook.select(self.player_search_tab)

        detail = self.model.player_detail(year, player_id)
        player = detail.get("player")
        if not player:
            self.player_profile_var.set(
                f"{player_id}: player masterなし"
            )
            self.player_batting_var.set("")
            self.player_pitching_var.set("")
            return

        self.player_search_var.set(player_id)
        self.player_school_var.set("")
        self.player_position_var.set("")
        self._search_players()
        if self.player_tree.exists(player_id):
            self.player_tree.selection_set(player_id)
            self.player_tree.focus(player_id)
            self.player_tree.see(player_id)

        self.player_profile_var.set(
            f"{player['display_name']} [{player_id}]  "
            f"{player.get('school_name') or player['school_id']}  "
            f"{player['academic_year']}年  "
            f"{POSITION_LABELS.get(player['primary_position'], player['primary_position'])}  "
            f"背番号 {player['roster_no']}  "
            f"{player['throws']}投 {player['bats']}打"
        )
        batter = detail.get("batter")
        if batter:
            self.player_batting_var.set(
                "打撃: "
                f"{batter['games']}試合  "
                f"{batter['plate_appearances']}打席 "
                f"{batter['at_bats']}打数 "
                f"{batter['hits']}安打 "
                f"{batter['home_runs']}本塁打 "
                f"{batter['rbi']}打点  "
                f"AVG {self._format_rate(batter['batting_average'])}  "
                f"OBP {self._format_rate(batter['on_base_percentage'])}  "
                f"SLG {self._format_rate(batter['slugging_percentage'])}  "
                f"OPS {self._format_rate(batter['ops'])}"
            )
        else:
            self.player_batting_var.set("打撃: 出場記録なし")

        pitcher = detail.get("pitcher")
        if pitcher:
            self.player_pitching_var.set(
                "投手: "
                f"{pitcher['games']}試合  "
                f"{pitcher['innings_pitched_display']}回 "
                f"{pitcher['earned_runs']}自責 "
                f"{pitcher['strikeouts']}奪三振  "
                f"ERA {self._format_rate(pitcher['earned_run_average'])}  "
                f"WHIP {self._format_rate(pitcher['whip'])}  "
                f"K/BB {self._format_rate(pitcher['strikeout_walk_ratio'])}"
            )
        else:
            self.player_pitching_var.set("投手: 登板記録なし")

    # ------------------------------------------------------------------
    # School roster
    # ------------------------------------------------------------------

    def _open_selected_school_roster(self) -> None:
        selection = self.school_tree.selection()
        if not selection:
            self.status_var.set("学校を選択してください")
            return
        self._navigate_to_school_roster(selection[0])

    def _navigate_to_school_roster(self, school_id: str) -> None:
        self.notebook.select(self.player_tab)
        self.player_notebook.select(self.roster_tab)
        self.roster_school_var.set(school_id)
        self._load_school_roster()

    def _load_school_roster(self) -> None:
        year = self._current_year()
        school_id = self.roster_school_var.get().strip()
        self._clear_tree(self.roster_tree)
        self._roster_rows = {}
        if year is None or not school_id:
            self.roster_summary_var.set("学校IDを指定してください")
            return

        rows = self.model.school_roster_stats(year, school_id)
        record = self.model.repository.school_record(year, school_id)
        if not rows:
            self.roster_summary_var.set(
                f"{school_id}: player master / rosterなし"
            )
            return

        school_name = (
            record.get("school_name")
            if record
            else rows[0]["player"].get("school_name")
        ) or school_id
        self.roster_summary_var.set(
            f"{school_name} [{school_id}] / {len(rows)}人"
        )

        for row in rows:
            player = row["player"]
            batter = row.get("batter")
            pitcher = row.get("pitcher")
            player_id = str(player["player_id"])
            self._roster_rows[player_id] = row
            self.roster_tree.insert(
                "",
                "end",
                iid=player_id,
                values=(
                    player["roster_no"],
                    player["display_name"],
                    player["academic_year"],
                    POSITION_LABELS.get(
                        player["primary_position"],
                        player["primary_position"],
                    ),
                    batter["games"] if batter else "-",
                    batter["at_bats"] if batter else "-",
                    batter["hits"] if batter else "-",
                    batter["home_runs"] if batter else "-",
                    self._format_rate(
                        batter["batting_average"]
                        if batter else None
                    ),
                    self._format_rate(
                        batter["ops"] if batter else None
                    ),
                    (
                        pitcher["innings_pitched_display"]
                        if pitcher else "-"
                    ),
                    self._format_rate(
                        pitcher["earned_run_average"]
                        if pitcher else None
                    ),
                    pitcher["strikeouts"] if pitcher else "-",
                ),
            )

    def _on_roster_double_click(self, _event=None) -> None:
        selection = self.roster_tree.selection()
        if selection:
            self._navigate_to_player(selection[0])

    # ------------------------------------------------------------------
    # Rankings
    # ------------------------------------------------------------------

    def _current_competition_id(self) -> str:
        return self._competition_id_by_label.get(
            self.competition_var.get(),
            "",
        )

    def _open_current_competition_rankings(self) -> None:
        competition_id = self._current_competition_id()
        if not competition_id:
            self.status_var.set("大会を選択してください")
            return
        self._navigate_to_rankings(competition_id)

    def _navigate_to_rankings(self, competition_id: str) -> None:
        target_label = next(
            (
                label
                for label, cid
                in self._stats_competition_id_by_label.items()
                if cid == competition_id
            ),
            "",
        )
        if target_label:
            self.stats_competition_var.set(target_label)
        self.notebook.select(self.rankings_tab)
        self._load_rankings()

    def _load_rankings(self, _event=None) -> None:
        year = self._current_year()
        competition_id = self._stats_competition_id_by_label.get(
            self.stats_competition_var.get(),
            "",
        )
        self._clear_tree(self.batting_ranking_tree)
        self._clear_tree(self.pitching_ranking_tree)
        self._batting_ranking_rows = {}
        self._pitching_ranking_rows = {}
        if year is None or not competition_id:
            self.rankings_summary_var.set("大会を選択してください")
            return

        try:
            limit = int(self.stats_limit_var.get())
        except ValueError:
            limit = 20
            self.stats_limit_var.set("20")

        batting_metric = self._batting_metric_by_label.get(
            self.batting_metric_var.get(),
            "ops",
        )
        pitching_metric = self._pitching_metric_by_label.get(
            self.pitching_metric_var.get(),
            "earned_run_average",
        )
        payload = self.model.competition_leaderboards(
            year,
            competition_id,
            batting_metric=batting_metric,
            pitching_metric=pitching_metric,
            limit=limit,
        )
        competition = payload.get("competition") or {}
        self.rankings_summary_var.set(
            f"{competition.get('competition_name') or competition_id}  "
            f"打撃: {self.batting_metric_var.get()}  "
            f"投手: {self.pitching_metric_var.get()}"
        )

        for index, row in enumerate(payload["batting"]):
            iid = f"b-{index}-{row['player_id']}"
            self._batting_ranking_rows[iid] = row
            stat = row["stat"]
            self.batting_ranking_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row["rank"],
                    row["player_name"],
                    row["school_name"],
                    row["academic_year"] or "-",
                    POSITION_LABELS.get(
                        row["primary_position"],
                        row["primary_position"],
                    ),
                    self._format_stat_value(row["value"]),
                    stat["games"],
                    stat["plate_appearances"],
                ),
            )

        for index, row in enumerate(payload["pitching"]):
            iid = f"p-{index}-{row['player_id']}"
            self._pitching_ranking_rows[iid] = row
            stat = row["stat"]
            self.pitching_ranking_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row["rank"],
                    row["player_name"],
                    row["school_name"],
                    row["academic_year"] or "-",
                    self._format_stat_value(row["value"]),
                    stat["games"],
                    stat["innings_pitched_display"],
                ),
            )

    def _on_batting_ranking_double_click(self, _event=None) -> None:
        selection = self.batting_ranking_tree.selection()
        if not selection:
            return
        row = self._batting_ranking_rows.get(selection[0])
        if row:
            self._navigate_to_player(row["player_id"])

    def _on_pitching_ranking_double_click(self, _event=None) -> None:
        selection = self.pitching_ranking_tree.selection()
        if not selection:
            return
        row = self._pitching_ranking_rows.get(selection[0])
        if row:
            self._navigate_to_player(row["player_id"])

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_rate(value) -> str:
        if value is None:
            return "-"
        return f"{float(value):.3f}"

    @staticmethod
    def _format_stat_value(value) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)
