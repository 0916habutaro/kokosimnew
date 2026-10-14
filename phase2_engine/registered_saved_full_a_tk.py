"""Stage106 native lab viewer. Opens saved facts through the verified ro reader."""
from tkinter import ttk
from .registered_full_a_tk import RegisteredFullATk
from .registered_full_a_lab_store import RegisteredFullALabReader
from .joint_team_registration_lab import match_input_from_registration


class RegisteredSavedFullATk(RegisteredFullATk):
    def __init__(self, root):
        super().__init__(root)
        self.snapshot = None
        self.team_picker = ttk.Combobox(root, state='readonly')
        self.school_picker = ttk.Combobox(root, state='readonly')
        self.player_picker = ttk.Combobox(root, state='readonly')
        for label, picker, handler in (
            ('大会チームID', self.team_picker, self._team),
            ('構成学校ID（合同参加・単独勝敗集計なし）', self.school_picker, self._school),
            ('永久選手ID（元学校所属）', self.player_picker, self._player),
        ):
            ttk.Label(root, text=label).pack()
            picker.pack(fill='x')
            picker.bind('<<ComboboxSelected>>', handler)
        self.members = ttk.Treeview(root, columns=('team', 'label', 'school', 'player', 'slot'), show='headings')
        for col in self.members['columns']:
            self.members.heading(col, text=col)
        self.members.pack(fill='both', expand=True)

    def _clear(self):
        self.result = self.snapshot = None
        for tree in (self.innings, self.players, self.members):
            tree.delete(*tree.get_children())
        for picker in (self.team_picker, self.school_picker, self.player_picker):
            picker.set('')
            picker['values'] = ()

    def open_saved(self, db_path, year, competition_id, match_id):
        self._clear()
        self.status.config(text='保存済み結果を検証中')
        try:
            reader = RegisteredFullALabReader(db_path)
            reader._scope(year, competition_id)
            snapshot = reader.snapshot()  # Connection is closed before any Tk rendering.
            result = next((r for r in snapshot.results if r.match_id == match_id), None)
            if result is None:
                raise ValueError('saved match not found')
            match = match_input_from_registration(snapshot.registration, snapshot.repo, snapshot.rosters,
                team1_id=result.team1_id, team2_id=result.team2_id, opt_in=True)
            self.show(result, match, snapshot.registration, snapshot.repo, snapshot.rosters)
            self.snapshot = snapshot
            self.team_picker['values'] = (result.team1_id, result.team2_id)
            self.team_picker.set(result.team1_id)
            self._team()
            self.status.config(text=f'保存済み架空試合 {result.team1_score}–{result.team2_score}（再検証済み）')
        except Exception:
            self._clear()
            self.status.config(text='保存済み結果の検証拒否・結果なし')
            raise

    def _team(self, event=None):
        if self.snapshot is None:
            return
        team = next(t for t in self.snapshot.registration.teams if t.team_id == self.team_picker.get())
        self.school_picker['values'] = ('',) + team.school_ids
        self.school_picker.set('')
        self._school()

    def _school(self, event=None):
        if self.snapshot is None:
            return
        team = next(t for t in self.snapshot.registration.teams if t.team_id == self.team_picker.get())
        school = self.school_picker.get()
        people = tuple(p for p in team.players if not school or p.origin_school_id == school)
        self.player_picker['values'] = ('',) + tuple(p.player_id for p in people)
        self.player_picker.set('')
        self._player()

    def _player(self, event=None):
        if self.snapshot is None:
            return
        team = next(t for t in self.snapshot.registration.teams if t.team_id == self.team_picker.get())
        school, player = self.school_picker.get(), self.player_picker.get()
        for tree in (self.players, self.members):
            tree.delete(*tree.get_children())
        for p in team.players:
            if (not school or p.origin_school_id == school) and (not player or p.player_id == player):
                self.members.insert('', 'end', values=(team.team_id, team.label, p.origin_school_id, p.player_id, p.team_slot))
        for kind, rows in (('打撃', self.result.batter_stats), ('投手', self.result.pitcher_stats)):
            from dataclasses import asdict
            for row in rows:
                if row.team_id == team.team_id and (not school or row.origin_school_id == school) and (not player or row.player_id == player):
                    stats = {k:v for k,v in asdict(row).items() if k not in
                        ('year','competition_id','match_id','team_id','origin_school_id','player_id')}
                    self.players.insert('', 'end', values=(row.team_id,row.origin_school_id,row.player_id,kind,str(stats)))
