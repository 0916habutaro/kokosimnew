"""Read-only lab result viewer. Receives only in-memory self-generated data."""
import tkinter as tk
from tkinter import ttk
from .registered_full_a_oracle import validate_registered_full_a


class RegisteredFullATk:
    def __init__(self, root):
        self.result = None
        self.status = ttk.Label(root, text='実行結果なし')
        self.status.pack()
        self.innings = ttk.Treeview(root, columns=('inning', 'half', 'team', 'runs'), show='headings')
        self.players = ttk.Treeview(root, columns=('team', 'origin', 'player', 'kind', 'stats'), show='headings')
        for tree in (self.innings, self.players):
            for col in tree['columns']:
                tree.heading(col, text=col)
            tree.pack(fill=tk.BOTH, expand=True)

    def show(self, result, match, registration, repo, rosters):
        self.result = None
        for tree in (self.innings, self.players):
            tree.delete(*tree.get_children())
        self.status.config(text='検証中')
        try:
            validate_registered_full_a(result, match, registration, repo, rosters)
            for row in result.inning_scores:
                self.innings.insert('', 'end', values=(row.inning, row.half, row.team_id,
                                                       row.runs if row.was_played else 'X'))
            for kind, rows in (('打撃', result.batter_stats), ('投手', result.pitcher_stats)):
                for row in rows:
                    from dataclasses import asdict
                    stats = {k: v for k, v in asdict(row).items()
                             if k not in ('year', 'competition_id', 'match_id', 'team_id', 'origin_school_id', 'player_id')}
                    self.players.insert('', 'end', values=(row.team_id, row.origin_school_id,
                                                           row.player_id, kind, str(stats)))
            self.status.config(text=f'ゲーム内架空試合 {result.team1_score}–{result.team2_score}（独立検証済み）')
            self.result = result
        except Exception:
            for tree in (self.innings, self.players):
                tree.delete(*tree.get_children())
            self.status.config(text='検証拒否・結果なし')
            raise
