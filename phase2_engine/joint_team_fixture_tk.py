"""Read-only small fixture preview, separate from the legacy history GUI."""
from tkinter import ttk


class JointTeamFixtureTk:
    def __init__(self, root, model):
        self.model = model
        self.frame = ttk.Frame(root)
        self.frame.pack(fill="both", expand=True)
        ttk.Label(self.frame, text="自己生成合同チーム検証／試合・保存未対応").pack()
        self.teams = ttk.Treeview(self.frame, columns=("label", "schools"), show="headings")
        self.teams.heading("label", text="大会チーム")
        self.teams.heading("schools", text="元の学校ID")
        self.teams.pack(fill="both", expand=True)
        for entry in model.entries:
            self.teams.insert("", "end", iid=entry.team_id,
                              values=(entry.label, "・".join(entry.school_ids)))
        self.players = ttk.Treeview(self.frame, columns=("school", "player", "grade", "entry"), show="headings")
        for key, title in (("school", "所属学校ID"), ("player", "永久選手ID"), ("grade", "学年"), ("entry", "入学年")):
            self.players.heading(key, text=title)
        self.players.pack(fill="both", expand=True)
        self.teams.bind("<<TreeviewSelect>>", self.select)
        self.page = None

    def select(self, event=None):
        selection = self.teams.selection()
        if not selection:
            return
        self.page = self.model.preview(selection[0])
        self.players.delete(*self.players.get_children())
        for p in self.page["players"]:
            self.players.insert("", "end", iid=p["player_id"], values=(
                p["school_id"], p["player_id"], p["academic_year"], p["entry_year"]))
