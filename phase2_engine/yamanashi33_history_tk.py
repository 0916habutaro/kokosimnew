"""Read-only presentation for the explicitly labelled Stage102 game fixture.

No game writer, slot selection, restore, national scope or next-year action.
The existing history shell supplies paginated school/inning/player browsing.
"""
from contextlib import closing
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .career_history_browse_model import CareerHistoryBrowseModel
from .career_history_gui_bridge import CareerHistoryGuiBridge
from .career_history_tk_pilot import CareerHistoryTkPilot
from .career_option_a_storage_profile import _read_only
from .live_game_service import Yamanashi33FixturePersistence as Authority


class Yamanashi33HistoryTkPilot(CareerHistoryTkPilot):
    def __init__(self, root, slot, *, data_root):
        slot = Path(slot)
        with closing(_read_only(slot / "historical_matches.sqlite3")) as conn:
            raw = conn.execute("SELECT metadata_json FROM archive_identity WHERE id=1").fetchone()
        identity = json.loads(raw[0]) if raw else {}
        if (identity.get("resolver_contract") != Authority.RESOLVER_CONTRACT
                or identity.get("plan_fingerprint") != Authority.APPROVED_PLAN):
            raise ValueError("33校検証fixture専用の保存履歴を選択してください")
        self.ranking = Authority.sealed_results(slot)
        self.competition = CareerHistoryBrowseModel(data_root, slot).competition_page(
            2026, Authority.COMPETITION_ID)
        self.tournament_window = None
        super().__init__(root, CareerHistoryGuiBridge(slot), data_root=data_root)
        root.title("ココシミュNew｜ゲーム内検証用33校大会・閲覧専用")
        ttk.Label(root, text=Authority.WARNING).pack(fill="x")
        self.tournament_button = ttk.Button(root, text="検証大会の詳細・ゲーム内順位",
            command=self._show_tournament)
        self.tournament_button.pack(fill="x")

    def _show_tournament(self):
        if self.tournament_window is not None and self.tournament_window.winfo_exists():
            self.tournament_window.lift()
            return
        window = self.tournament_window = tk.Toplevel(self.root)
        window.title("ゲーム内検証大会｜公式結果・出場資格ではありません")
        ttk.Label(window, text=Authority.WARNING).pack(fill="x")
        table = ttk.Treeview(window, columns=("rank", "school"), show="headings", height=15)
        table.heading("rank", text="ゲーム内順位（同ラウンド内はseedによる表示順）")
        table.heading("school", text="学校ID・マスター学校名")
        for n, sid in enumerate(self.ranking["ranked_school_ids"], 1):
            table.insert("", "end", values=(n, self.labels.school(2026, sid)["label"]))
        table.pack(fill="both", expand=True)
        self.ranking_table = table
        text = tk.Text(window, width=100, height=12)
        lines = ["ゲーム内の32試合｜イニング・個人成績は学校の過去試合から閲覧"]
        for game in self.competition["matches"]["rows"]:
            lines.append(f'{game["match_date"]}  {game["team1_id"]} '
                f'{game["team1_score"]}–{game["team2_score"]} {game["team2_id"]}')
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

    def _close_game_windows(self):
        if self.tournament_window is not None and self.tournament_window.winfo_exists():
            self.tournament_window.destroy()
        super()._close_game_windows()
