"""Native readonly Stage108 lab, deliberately separate from national GUI."""
from dataclasses import asdict
from tkinter import ttk

from .yamanashi_tournament_store import TournamentLabReader
from .joint_tournament_oracle import player_totals


class YamanashiTournamentTk:
    def __init__(self, root):
        self.reader = self.snapshot = self.result = None
        self.status = ttk.Label(root, text='大会結果なし')
        self.status.pack()
        self.pickers = {}
        for key, label, handler in (
            ('tournament', '年大会（架空32チーム大会）', self._reload),
            ('team', '参加チーム・チーム順位', self._team),
            ('match', '試合・スコア', self._match),
            ('school', '構成学校（合同参加は学校単独勝敗へ集計しません）', self._school),
            ('player', '永久選手ID・元学校（試合別／累計）', self._player),
        ):
            ttk.Label(root, text=label).pack()
            picker = ttk.Combobox(root, state='readonly')
            picker.pack(fill='x')
            picker.bind('<<ComboboxSelected>>', handler)
            self.pickers[key] = picker
        self.tables = {}
        book = ttk.Notebook(root)
        book.pack(fill='both', expand=True)
        for key, title, columns in (
            ('ranks', 'チーム順位', ('rank', 'team', 'wins', 'losses', 'reached_round')),
            ('ledger', '勝上り（BYEなし）', ('sequence', 'match', 'source', 'team')),
            ('members', '当時の登録・学校参加', ('team', 'school', 'player', 'slot')),
            ('scores', '試合スコア', ('match', 'team1', 'score1', 'team2', 'score2')),
            ('innings', '全イニング', ('match', 'inning', 'half', 'team', 'runs')),
            ('stats', '試合別・累計個人成績', ('match', 'team', 'origin', 'player', 'kind', 'stats')),
        ):
            frame = ttk.Frame(book)
            book.add(frame, text=title)
            tree = ttk.Treeview(frame, columns=columns, show='headings')
            for col in columns:
                tree.heading(col, text=col)
                tree.column(col, width=120)
            scroll = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
            tree.configure(xscrollcommand=scroll.set)
            scroll.pack(side='bottom', fill='x')
            vertical = ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
            tree.configure(yscrollcommand=vertical.set)
            vertical.pack(side='right',fill='y')
            tree.pack(fill='both', expand=True)
            self.tables[key] = tree

    def _clear(self):
        self.reader = self.snapshot = self.result = None
        for picker in self.pickers.values():
            picker.set('')
            picker['values'] = ()
        for tree in self.tables.values():
            tree.delete(*tree.get_children())

    def open_saved(self, db_path):
        self._clear()
        try:
            reader = TournamentLabReader(db_path)
            snapshot = reader.tournament()  # close native connection before rendering
            self.reader, self.snapshot = reader, snapshot
            self.pickers['tournament']['values'] = (f'{snapshot.plan.year}/{snapshot.plan.competition_id}',)
            self.pickers['tournament'].current(0)
            self.pickers['team']['values'] = tuple(t.team_id for t in snapshot.registration.teams)
            self.pickers['team'].current(0)
            self._team()
            for rank in snapshot.ranks:
                self.tables['ranks'].insert('', 'end', values=tuple(asdict(rank).values()))
            for row in snapshot.ledger:
                self.tables['ledger'].insert('', 'end', values=tuple(asdict(row).values()))
            self.status.config(text=f'架空大会{len(snapshot.results)}試合完了・チーム順位（学校単独順位ではありません）')
        except Exception:
            self._clear()
            self.status.config(text='未完了・欠損・読取検証拒否：大会結果なし')
            raise

    def _reload(self, event=None):
        if self.reader is not None:
            self.open_saved(self.reader.db_path)

    def _checked(self):
        if self.reader is None:
            raise ValueError('no saved tournament')
        try:
            self.snapshot = self.reader.tournament()
            return self.snapshot
        except Exception:
            self._clear()
            self.status.config(text='読取検証拒否：大会結果なし')
            raise

    def _team(self, event=None):
        snapshot = self._checked()
        tid = self.pickers['team'].get()
        team = next(t for t in snapshot.registration.teams if t.team_id == tid)
        matches = tuple(r for r in snapshot.results if tid in (r.team1_id, r.team2_id))
        self.pickers['match']['values'] = tuple(r.match_id for r in matches)
        self.pickers['match'].current(0)
        self.pickers['school']['values'] = ('全構成学校',) + team.school_ids
        self.pickers['school'].current(0)
        self.status.config(text=f'架空大会{len(snapshot.results)}試合・{team.label}（学校単独順位ではありません）')
        self._school(snapshot=snapshot)

    def _school(self, event=None, *, snapshot=None):
        snapshot = snapshot or self._checked()
        tid, school = self.pickers['team'].get(), self.pickers['school'].get()
        team = next(t for t in snapshot.registration.teams if t.team_id == tid)
        people = tuple(p for roster in snapshot.rosters for p in roster.players
                       if p.school_id in team.school_ids and (school == '全構成学校' or p.school_id == school))
        self.pickers['player']['values'] = ('全登録選手',) + tuple(p.player_id for p in people)
        self.pickers['player'].current(0)
        self._player(snapshot=snapshot)

    def _match(self, event=None):
        self._player()

    def _player(self, event=None, *, snapshot=None):
        snapshot = snapshot or self._checked()
        tid, mid = self.pickers['team'].get(), self.pickers['match'].get()
        school, pid = self.pickers['school'].get(), self.pickers['player'].get()
        team = next(t for t in snapshot.registration.teams if t.team_id == tid)
        result = next(r for r in snapshot.results if r.match_id == mid and tid in (r.team1_id, r.team2_id))
        self.result = result
        for name in ('members', 'scores', 'innings', 'stats'):
            tree = self.tables[name]
            tree.delete(*tree.get_children())
        self.tables['scores'].insert('', 'end', values=(mid, result.team1_id, result.team1_score,
                                                         result.team2_id, result.team2_score))
        for row in result.inning_scores:
            self.tables['innings'].insert('', 'end', values=(mid, row.inning, row.half, row.team_id,
                                                            row.runs if row.was_played else 'X'))
        people = tuple(p for p in team.players if (school == '全構成学校' or p.origin_school_id == school)
                       and (pid == '全登録選手' or p.player_id == pid))
        allowed = {p.player_id for p in people}
        if pid != '全登録選手' and pid not in allowed:
            original = next(p for roster in snapshot.rosters for p in roster.players if p.player_id == pid)
            self.tables['members'].insert('', 'end', values=(tid,original.school_id,pid,'未登録'))
        for p in people:
            self.tables['members'].insert('', 'end', values=(tid, p.origin_school_id, p.player_id, p.team_slot))
        keys = ('year', 'competition_id', 'match_id', 'team_id', 'origin_school_id', 'player_id')
        for game in snapshot.results:
            for kind, rows in (('打撃', game.batter_stats), ('投手', game.pitcher_stats)):
                for row in rows:
                    if row.team_id == tid and row.player_id in allowed:
                        stats = {k: v for k, v in asdict(row).items() if k not in keys}
                        self.tables['stats'].insert('', 'end', values=(game.match_id, tid,
                            row.origin_school_id, row.player_id, kind, str(stats)))
        for p in people:
            for kind, stats in player_totals(snapshot.results, p.player_id).items():
                if stats:
                    self.tables['stats'].insert('', 'end', values=('累計', tid, p.origin_school_id,
                                                                 p.player_id, kind, str(stats)))
