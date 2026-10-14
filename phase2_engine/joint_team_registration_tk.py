"""Detached Stage104 registry viewer, never attached to product history/save UI."""
from tkinter import ttk
from .joint_team_registration_lab import validate_registration


class JointRegistrationTk:
    def __init__(self, root, registration, repo, rosters):
        validate_registration(registration, repo, rosters)
        self.model = registration
        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)
        self.status = ttk.Label(self.frame, text="自己生成登録簿／試合結果は未対応／保存未対応")
        self.status.pack()
        self.teams = ttk.Treeview(self.frame, columns=("label", "team"), show="headings")
        self.teams.heading("label", text="大会チーム")
        self.teams.heading("team", text="年大会チームID")
        self.teams.pack(fill="both", expand=True)
        for team in registration.teams:
            self.teams.insert("", "end", iid=team.team_id, values=(team.label, team.team_id))
        self.schools = ttk.Treeview(self.frame, columns=("school",), show="headings")
        self.schools.heading("school", text="構成学校ID（選択して登録選手を絞込）")
        self.schools.pack(fill="both", expand=True)
        self.players = ttk.Treeview(self.frame,
            columns=("slot", "school", "player", "grade", "entry", "position"), show="headings")
        for key, title in (("slot", "登録番号"), ("school", "元学校ID"), ("player", "永久選手ID"),
                           ("grade", "学年"), ("entry", "入学年"), ("position", "position")):
            self.players.heading(key, text=title)
        self.players.pack(fill="both", expand=True)
        self.page = None
        self.teams.bind("<<TreeviewSelect>>", self.select_team)
        self.schools.bind("<<TreeviewSelect>>", self.select_school)

    def _clear(self):
        self.page = None
        self.schools.delete(*self.schools.get_children())
        self.players.delete(*self.players.get_children())

    def select_team(self, event=None):
        selection = self.teams.selection()
        self._clear()
        if not selection:
            return
        try:
            self.page = self.model.preview(selection[0])
        except ValueError:
            self.status.configure(text="登録簿の参照を拒否／試合結果は未対応")
            return
        self.status.configure(text="自己生成登録簿／試合結果は未対応／保存未対応")
        for sid in self.page["school_ids"]:
            self.schools.insert("", "end", iid=sid, values=(sid,))
        self._players()

    def select_school(self, event=None):
        selection = self.schools.selection()
        if self.page is not None:
            self._players(selection[0] if selection else None)

    def _players(self, school=None):
        self.players.delete(*self.players.get_children())
        for row in self.page["players"]:
            if school is not None and row["origin_school_id"] != school:
                continue
            player = row["player"]
            self.players.insert("", "end", iid=row["player_id"], values=(row["team_slot"],
                row["origin_school_id"], row["player_id"], player["academic_year"],
                player["entry_year"], player["primary_position"]))
