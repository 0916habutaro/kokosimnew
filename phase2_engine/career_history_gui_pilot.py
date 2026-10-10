"""Stage43G-16 standalone Tkinter history navigation PILOT.

Run: python -m phase2_engine.career_history_gui_pilot
       --data-root data --slot <SAVE_ROOT>/<SLOT_ID>

This is not the finished game GUI; it reads only career A archives and the
registered school master, and is intentionally isolated from 2026 BrowseDB.
"""
from __future__ import annotations

import argparse
import json
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path

from .career_history_browse_model import (
    CareerHistoryBrowseModel, CareerHistoryNavigator, HistoryRoute, RANKABLE,
    SOURCE,
)

APP_NAME = "ココシミュNew｜歴代記録ビュー（試験版・閲覧専用）"
METRICS = {
    "通算安打": "batting_hits", "通算本塁打": "batting_home_runs",
    "通算打点": "batting_rbi", "通算盗塁": "batting_stolen_bases",
    "通算奪三振": "pitching_strikeouts",
    "通算投球アウト": "pitching_outs",
}


class CareerHistoryGuiPilot:
    def __init__(self, root: tk.Tk, model: CareerHistoryBrowseModel):
        self.root = root
        self.model = model
        years = model.years()
        if not years:
            raise ValueError("キャリア年度のA方式履歴がありません")
        self.navigator = CareerHistoryNavigator(model, year=years[-1]["year"])
        self.year_var = tk.StringVar(value=str(years[-1]["year"]))
        self.search_var = tk.StringVar()
        self.metric_var = tk.StringVar(value="通算安打")
        self.status_var = tk.StringVar(value="ゲーム内記録のみ / 正式GUIではない")
        self.links: dict[str, HistoryRoute] = {}
        self.root.title(APP_NAME)
        self.root.geometry("1200x780")
        self.root.minsize(960, 620)
        self._layout()
        self._render(self.navigator.render())

    def _layout(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="戻る", command=self._back).pack(side="left")
        ttk.Button(bar, text="前ページ", command=lambda: self._change_page(-1)).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="次ページ", command=lambda: self._change_page(1)).pack(side="left")
        ttk.Label(bar, text="年度").pack(side="left", padx=(16, 4))
        box = ttk.Combobox(
            bar, textvariable=self.year_var, state="readonly", width=9,
            values=[str(y["year"]) for y in self.model.years()],
        )
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", self._change_year)
        ttk.Button(bar, text="年度一覧", command=self._years).pack(side="left", padx=6)
        ttk.Label(bar, text="学校名または学校ID").pack(side="left", padx=(12, 3))
        entry = ttk.Entry(bar, textvariable=self.search_var, width=23)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._search())
        ttk.Button(bar, text="学校検索", command=self._search).pack(side="left", padx=4)
        ttk.Combobox(
            bar, textvariable=self.metric_var, state="readonly",
            values=list(METRICS), width=12,
        ).pack(side="left", padx=6)
        ttk.Button(bar, text="この学校の歴代記録",
                   command=self._leaders).pack(side="left")
        body = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        table_frame = ttk.Frame(body)
        body.add(table_frame, weight=3)
        self.table = ttk.Treeview(
            table_frame, columns=("name", "value", "description"),
            show="headings", selectmode="browse",
        )
        for col, label, width in (
            ("name", "項目／ID", 260),
            ("value", "値／学校", 280),
            ("description", "内容・試合", 470),
        ):
            self.table.heading(col, text=label)
            self.table.column(col, width=width, minwidth=110)
        self.table.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.table.yview,
        )
        tree_scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=tree_scroll.set)
        self.table.bind("<Double-1>", self._open_selection)
        bottom = ttk.Frame(body)
        body.add(bottom, weight=2)
        self.details = tk.Text(
            bottom, wrap="word", state="disabled", height=12,
            font=("Yu Gothic UI", 10),
        )
        self.details.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            bottom, orient="vertical", command=self.details.yview,
        )
        scroll.pack(side="right", fill="y")
        self.details.configure(yscrollcommand=scroll.set)
        ttk.Label(
            self.root, textvariable=self.status_var, anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 6))

    def _year(self) -> int:
        return int(self.year_var.get())

    def _open(self, route: HistoryRoute) -> None:
        try:
            page = self.navigator.open(route)
            self.year_var.set(str(route.year))
            self._render(page)
        except (ValueError, KeyError, OSError) as exc:
            messagebox.showwarning("閲覧できません", str(exc))

    def _years(self) -> None:
        self._open(HistoryRoute("years", self._year()))

    def _change_year(self, _event=None) -> None:
        # Explicit year change clears contextual school/game selection.
        self._open(HistoryRoute("years", self._year()))

    def _back(self) -> None:
        try:
            data = self.navigator.back()
            self.year_var.set(str(self.navigator.current.year))
            self._render(data)
        except (ValueError, OSError) as exc:
            messagebox.showwarning("戻り先を開けません", str(exc))

    def _search(self) -> None:
        try:
            schools = self.model.find_schools(self.search_var.get())
        except ValueError as exc:
            messagebox.showwarning("検索条件", str(exc))
            return
        self._clear()
        self._detail({
            "scope": "保存済みゲーム年度のキャリア記録のみ",
            "matched": len(schools),
            "help": "学校をダブルクリックすると、その学校の戦績と歴代選手を開きます",
        })
        for i, row in enumerate(schools):
            iid = f"search_{i}"
            self.table.insert(
                "", "end", iid=iid,
                values=(row["school_id"], row["school_name"],
                        row["prefecture_code"]),
            )
            self.links[iid] = HistoryRoute(
                "school", self._year(), school_id=row["school_id"],
            )
        self.status_var.set(f"学校検索 {len(schools)}件（最大30件）")

    def _leaders(self) -> None:
        current = self.navigator.current
        if not current.school_id:
            messagebox.showinfo(
                "学校未選択", "学校ページで学校を選んでください"
            )
            return
        metric = METRICS[self.metric_var.get()]
        self._open(HistoryRoute(
            "leaders", self._year(),
            school_id=current.school_id, metric=metric,
        ))

    def _change_page(self, delta: int) -> None:
        route = self.navigator.current
        if route.screen not in ("school", "competition"):
            return
        size = 30 if route.screen == "school" else 50
        next_offset = max(0, route.offset + delta * size)
        if next_offset == route.offset:
            return
        self._open(HistoryRoute(
            route.screen, route.year,
            school_id=route.school_id,
            player_id=route.player_id,
            competition_id=route.competition_id,
            match_id=route.match_id,
            start_year=route.start_year,
            offset=next_offset, metric=route.metric,
        ))

    def _open_selection(self, _event=None) -> None:
        selection = self.table.selection()
        if selection and selection[0] in self.links:
            self._open(self.links[selection[0]])

    def _clear(self) -> None:
        for iid in self.table.get_children():
            self.table.delete(iid)
        self.links.clear()

    def _item(self, label: object, value: object, detail: object,
              route: HistoryRoute | None = None) -> None:
        iid = f"row_{len(self.table.get_children())}"
        self.table.insert("", "end", iid=iid,
                          values=(str(label), str(value), str(detail)))
        if route:
            self.links[iid] = route

    def _detail(self, payload: dict) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert(
            "end", json.dumps(payload, ensure_ascii=False, indent=2),
        )
        self.details.configure(state="disabled")

    def _render(self, page: dict) -> None:
        self._clear()
        screen = page["screen"]
        year = page["year"]
        if screen == "years":
            for y in page["years"]:
                self._item(
                    y["year"], y["state"], f"記録試合数 {y['archived_match_count']}",
                    HistoryRoute("years", y["year"]),
                )
            self._detail({"source": SOURCE, "years": len(page["years"]),
                          "notice": "学校検索または大会IDから記録を表示します"})
        elif screen == "school":
            for rec in page["year_results"]["records"]:
                self._item(
                    f"{rec['year']} / {rec['competition_id']}",
                    f"{rec['wins']}勝 {rec['losses']}敗",
                    f"得点 {rec['runs_for']} / 失点 {rec['runs_against']}",
                    HistoryRoute(
                        "competition", rec["year"],
                        competition_id=rec["competition_id"],
                    ),
                )
            for player in page["historical_players"]["players"]:
                self._item(
                    player["player_id"], player["display_name"],
                    f"入学 {player['entry_year']} / {player['latest_roster_status']}",
                    HistoryRoute("player", year, player_id=player["player_id"]),
                )
            self._detail({
                "school_id": page["school_id"],
                "school_name": page["school_name"],
                "results_total": page["year_results"]["total_groups"],
                "historical_players_total": page["historical_players"]["total"],
                "note": "直近所属なし＝必ずしも卒業ではありません",
                "source": SOURCE,
            })
        elif screen == "player":
            for rec in page["membership"]:
                self._item(
                    rec["year"], rec["display_name"],
                    f"学年 {rec['academic_year']} / 背番号 {rec['roster_no']}",
                    HistoryRoute("school", rec["year"],
                                 school_id=rec["school_id"]),
                )
            self._detail({
                "player_id": page["player_id"],
                "name": page["display_name"],
                "career_stats": page["career_stats"],
                "season_stats": page["season_stats"],
                "missing_box_score_games": page["missing_box_score_games"],
                "source_validation": page["source_validation"],
                "source_payloads_rechecked_on_read":
                    page["source_payloads_rechecked_on_read"],
                "cached_year_count": page["cached_year_count"],
                "raw_year_count": page["raw_year_count"],
                "source": SOURCE,
            })
        elif screen == "competition":
            for g in page["matches"]["rows"]:
                self._item(
                    g["match_date"], g["match_id"],
                    f"{g['team1_id']} {g['team1_score']} - "
                    f"{g['team2_score']} {g['team2_id']}",
                    HistoryRoute("match", year,
                                 competition_id=g["competition_id"],
                                 match_id=g["match_id"]),
                )
            self._detail({
                "competition_id": page["competition_id"],
                "game_count": page["matches"]["total"],
                "bracket_champion_verified": False,
                "note": "試合履歴だけで大会優勝校や進出権を確定しません",
            })
        elif screen == "match":
            g = page["game"]
            for school in (g["team1_id"], g["team2_id"]):
                self._item(
                    "学校を開く", school, "",
                    HistoryRoute("school", year, school_id=school),
                )
            for kind in ("batter_stats", "pitcher_stats"):
                for r in g.get(kind) or []:
                    if "player_id" in r:
                        self._item(
                            "打者" if kind == "batter_stats" else "投手",
                            r["player_id"], r.get("school_id", ""),
                            HistoryRoute("player", year,
                                         player_id=r["player_id"]),
                        )
            self._detail({
                "year": year, "competition_id": page["competition_id"],
                "match_id": page["match_id"],
                "game": g,
                "inning_score_status": page["inning_score_status"],
                "box_score_status": page["box_score_status"],
                "plate_appearance_events_archived": False,
                "source": SOURCE,
            })
        elif screen == "leaders":
            for rec in page["records"]["rows"]:
                self._item(
                    rec["player_id"], rec["stat_value"], page["category"],
                    HistoryRoute("player", year,
                                 player_id=rec["player_id"]),
                )
            self._detail({
                "school_id": page["school_id"],
                "category": page["category"],
                "candidate_count": page["records"]["candidate_count"],
                "missing_box_score_games": page["records"]["missing_box_score_games"],
                "source_validation": page["source_validation"],
                "source_payloads_rechecked_on_read":
                    page["source_payloads_rechecked_on_read"],
                "cached_year_count": page["cached_year_count"],
                "raw_year_count": page["raw_year_count"],
                "source": SOURCE,
            })
        self.status_var.set(
            f"{screen} / {year}年度 / ゲーム内sandbox記録（正式GUIではありません）"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Career A-history Tk pilot")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--slot", required=True,
                        help="Directory containing historical_matches.sqlite3")
    args = parser.parse_args()
    model = CareerHistoryBrowseModel(
        Path(args.data_root), Path(args.slot),
    )
    root = tk.Tk()
    CareerHistoryGuiPilot(root, model)
    root.mainloop()


if __name__ == "__main__":
    main()
