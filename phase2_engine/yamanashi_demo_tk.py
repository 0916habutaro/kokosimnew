"""Windows personal Tk trial, fictional 2026 Yamanashi; isolated demos only."""
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from dataclasses import asdict
from pathlib import Path

from .yamanashi_demo_controller import DemoController
from .joint_tournament_oracle import player_totals

NOTICE = 'ゲーム内試験用山梨県夏季大会｜2026年・架空選手／架空組合せ／架空結果・Windows個人用／非配布'
HELP = ('固定2026 seed・33校660永久ID／32チーム640登録・5ラウンド31試合。公式大会の結果ではありません。'
        '試合間疲労・怪我・犠打・盗塁・失策等は未実装です。新規は毎回別デモID。'
        '保存は試合ごとに自動commit。処理中終了では未commit結果は未保存。'
        '製品セーブ・旧バックアップの読込／移行／復元、翌年度試合、削除は対象外です。')
STEPS = ('初回：①専用保存先を新規作成（Git・data・save・backup外、未存在の名前）→②新規32チームデモ。'
         '再開：①専用保存先を開く（demo子フォルダーではなく保存ルート）→②下のデモID→③続きから。')


class DemoHistory:
    def __init__(self, parent, *, guard, on_error):
        self.snapshot = self.result = None
        self._stats_context = None
        self.guard, self.on_error = guard, on_error
        self.pickers, self.tables = {}, {}
        self.status = ttk.Label(parent, text='デモを明示開始／再開してください', wraplength=1050)
        self.status.pack(fill='x')
        labels = [('team', '参加チーム（公式表示名との対応・勝敗は架空）'),
                  ('school', '元学校の参加履歴（合同の勝敗は学校単独成績へ複製しません）'),
                  ('player', '永久選手ID・全660人（未登録20人も閲覧可）'), ('match', '保存済み試合')]
        for key, caption in labels:
            frame = ttk.Frame(parent)
            frame.pack(fill='x')
            ttk.Label(frame, text=caption, width=57).pack(side='left')
            box = ttk.Combobox(frame, state='readonly', height=18)
            box.pack(side='left', fill='x', expand=True)
            box.bind('<<ComboboxSelected>>', lambda event, k=key: self.select(k))
            self.pickers[key] = box
        self.book = ttk.Notebook(parent)
        self.book.pack(fill='both', expand=True)
        self.book.bind('<<NotebookTabChanged>>', self._stats_tab)
        specs = [
            ('ranks', 'チーム同順位', ('同順位', '参加チーム', '勝', '敗', '到達ラウンド')),
            ('plan', '31試合の予定・結果', ('順', '回戦', '試合ID', '架空日', '対戦', '得点／未実施')),
            ('members', '登録・元学校', ('チーム', '元学校ID', '永久選手ID', '登録枠')),
            ('scores', '試合スコア', ('試合ID', '先攻', '先攻得点', '後攻', '後攻得点')),
            ('innings', '全イニング', ('試合ID', '回', '表裏', 'チーム', '得点')),
            ('stats', '試合別・通算個人成績', ('試合ID／通算', 'チーム', '元学校ID', '永久選手ID', '種別', '全計数成績')),
        ]
        for key, title, cols in specs:
            frame = ttk.Frame(self.book)
            self.book.add(frame, text=title)
            tree = ttk.Treeview(frame, columns=cols, show='headings', height=12)
            for col in cols:
                tree.heading(col, text=col)
                tree.column(col, width=150, stretch=False)
            ys = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
            xs = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
            tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
            xs.pack(side='bottom', fill='x'); ys.pack(side='right', fill='y')
            tree.pack(fill='both', expand=True)
            self.tables[key] = tree

    def clear(self):
        self.snapshot = self.result = None
        self._stats_context = None
        for box in self.pickers.values():
            box.set(''); box['values'] = ()
        for tree in self.tables.values():
            tree.delete(*tree.get_children())
        self.status.config(text='検証済みの表示なし')

    def _put(self, key, rows):
        tree = self.tables[key]
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert('', 'end', values=row)

    def show(self, snapshot):
        self.clear()
        self.snapshot = snapshot
        self.teams = snapshot.registration.teams
        self.labels = {t.team_id: t.label for t in self.teams}
        self.pickers['team']['values'] = tuple(f'{t.label} [{t.team_id}]' for t in self.teams)
        self.pickers['team'].current(0)
        self._put('ranks', ((r.rank, self.labels[r.team_id], r.wins, r.losses, r.reached_round) for r in snapshot.ranks))
        results = {r.match_id: r for r in snapshot.results}
        def source(value):
            if value.startswith('winner:'):
                r = results.get(value[7:])
                return self.labels[r.winner_id] if r else value[7:] + 'の勝者'
            return self.labels[value]
        self._put('plan', ((g.sequence, g.round_no, g.match_id, g.day,
            source(g.team1_source) + ' 対 ' + source(g.team2_source),
            f'{results[g.match_id].team1_score}－{results[g.match_id].team2_score}' if g.match_id in results else '未実施')
            for g in snapshot.plan.games))
        self.select('team')

    def select(self, key):
        if self.snapshot is None:
            return
        try:
            self.guard()
            snapshot = self.snapshot
            team = self.teams[self.pickers['team'].current()]
            matches = tuple(r for r in snapshot.results if team.team_id in (r.team1_id, r.team2_id))
            if key == 'team':
                self.pickers['school']['values'] = ('全構成学校',) + tuple(
                    f'{snapshot.repo.team(s).display_name} [{s}]' for s in team.school_ids)
                self.pickers['school'].current(0)
                self.pickers['match']['values'] = tuple(r.match_id for r in matches)
                if matches:
                    self.pickers['match'].current(len(matches)-1)
                else:
                    self.pickers['match'].set('')
            selected_school = self.pickers['school'].current()
            schools = team.school_ids if selected_school <= 0 else (team.school_ids[selected_school-1],)
            people = tuple(p for ros in snapshot.rosters if ros.school_id in schools for p in ros.players)
            if key in ('team', 'school'):
                self.pickers['player']['values'] = ('全選手',) + tuple(p.player_id for p in people)
                self.pickers['player'].current(0)
            index = self.pickers['player'].current()
            chosen = people if index <= 0 else (people[index-1],)
            registered = {p.player_id: p for p in team.players}
            self._put('members', ((team.label, p.school_id, p.player_id,
                registered[p.player_id].team_slot if p.player_id in registered else '未登録') for p in chosen))
            mid = self.pickers['match'].get()
            result = next((r for r in matches if r.match_id == mid), None)
            self.result = result
            self._put('scores', [] if result is None else [(result.match_id, self.labels[result.team1_id],
                result.team1_score, self.labels[result.team2_id], result.team2_score)])
            self._put('innings', [] if result is None else ((mid, s.inning,
                '表' if s.half == 'top' else '裏', self.labels[s.team_id], s.runs if s.was_played else 'X')
                for s in result.inning_scores))
            # Only build the expensive counting-stat table when requested.
            # Context belongs to this verified UI selection; never a persisted cache.
            self._stats_context = (snapshot, matches, team, chosen)
            self._put('stats', ())
            self._stats_tab()
            if self.snapshot is None:
                return
            wins = sum(r.winner_id == team.team_id for r in matches)
            rank = next((r.rank for r in snapshot.ranks if r.team_id == team.team_id), None)
            unregistered = sum(p.player_id not in registered for p in chosen)
            appearances = {s.player_id for g in matches for s in g.batter_stats + g.pitcher_stats}
            not_played = sum(p.player_id not in appearances for p in chosen)
            school_names = ', '.join(f'{snapshot.repo.team(s).display_name} [{s}]' for s in schools)
            self.status.config(text=f'{team.label}：{wins}勝{len(matches)-wins}敗・同順位 {rank or "未確定"}。'
                f'元学校 {school_names}（学校単独順位ではありません）。選択{len(chosen)}人：'
                f'未登録{unregistered}人／未出場{not_played}人。IDは「登録・元学校」、成績は「試合別・通算個人成績」タブ。')
        except Exception:
            self.clear()
            self.on_error()

    def _stats_tab(self, event=None):
        if (self._stats_context is None or 'stats' not in self.tables
                or self.book.select() != str(self.tables['stats'].master)):
            return
        try:
            self.guard()
            snapshot, matches, team, chosen = self._stats_context
            ids = {p.player_id for p in chosen}
            registered = {p.player_id for p in team.players}
            ignored = {'year', 'competition_id', 'match_id', 'team_id', 'origin_school_id', 'player_id'}
            rows = []
            for game in matches:
                for kind, stats in (('打撃', game.batter_stats), ('投手', game.pitcher_stats)):
                    for s in stats:
                        if s.team_id == team.team_id and s.player_id in ids:
                            rows.append((game.match_id, team.label, s.origin_school_id, s.player_id, kind,
                                         str({k:v for k,v in asdict(s).items() if k not in ignored})))
            for p in chosen:
                for kind, totals in player_totals(snapshot.results, p.player_id).items():
                    empty = '未登録・未出場' if p.player_id not in registered else '未出場'
                    rows.append(('通算', team.label, p.school_id, p.player_id, kind, str(totals) if totals else empty))
            self._put('stats', rows)
        except Exception:
            self.clear()
            self.on_error()


class YamanashiDemoTk:
    def __init__(self, root, controller=None, *, namespace_picker=None, confirm=None):
        self.root, self.controller = root, controller or DemoController()
        self.namespace_picker = namespace_picker or self._choose_namespace
        self.confirm = confirm or (lambda text: messagebox.askyesno('専用デモの確認', text, parent=root))
        self.closed = self.closing = False
        self.last_error = None
        self.buttons = {}
        self.status_var = tk.StringVar(master=root, value='専用保存先を新規作成、または以前作成した専用保存先を開いてください')
        self.current_var = tk.StringVar(master=root, value='未開始・自動保存0件')
        root.title('ココシミュNew｜山梨夏32チーム 専用デモ')
        root.geometry('1240x900'); root.minsize(900, 700)
        root.protocol('WM_DELETE_WINDOW', self.request_close)
        ttk.Label(root, text=NOTICE, wraplength=1180, padding=8).pack(fill='x')
        ttk.Label(root, text=HELP, wraplength=1180, padding=(8,0)).pack(fill='x')
        ttk.Label(root, text=STEPS, wraplength=1180, padding=(8,4)).pack(fill='x')
        bar = ttk.Frame(root, padding=8); bar.pack(fill='x')
        for key, label in [('namespace_new','専用保存先を新規作成'), ('namespace_open','専用保存先を開く'),
                           ('new','新規32チームデモ'), ('resume','続きから'), ('exit','終了')]:
            self._button(bar, key, label)
        ttk.Label(root, text='再開するデモID（新規は別IDを追加します。再開したいIDを手元に記録してください）',
                  padding=(8,0)).pack(fill='x')
        self.demo_box = ttk.Combobox(root, state='readonly', height=12)
        self.demo_box.pack(fill='x', padx=8)
        progress = ttk.Frame(root, padding=8); progress.pack(fill='x')
        for key, label in [('one','次の1試合'), ('round','このラウンドの残り'), ('cancel','進行を中断'),
                           ('reload','保存内容を再検証・履歴閲覧')]:
            self._button(progress, key, label)
        self.progress = ttk.Progressbar(root, maximum=31, mode='determinate')
        self.progress.pack(fill='x', padx=8)
        ttk.Label(root, textvariable=self.current_var, padding=(8,0), wraplength=1180).pack(fill='x')
        ttk.Label(root, textvariable=self.status_var, padding=8, wraplength=1180).pack(fill='x')
        frame = ttk.Frame(root, padding=8); frame.pack(fill='both', expand=True)
        self.history = DemoHistory(frame, guard=self._guard, on_error=self._navigation_error)
        self._states()

    def _button(self, parent, key, label):
        b = ttk.Button(parent, text=label, command=lambda:self.dispatch(key))
        b.pack(side='left', padx=3)
        self.buttons[key] = b

    def _choose_namespace(self, create):
        parent = filedialog.askdirectory(parent=self.root,
            title='新規専用保存先の親フォルダーを選択' if create else '以前この試作で作成した専用保存先を選択')
        if not parent:
            return None
        if not create:
            return Path(parent)
        name = simpledialog.askstring('新規専用保存先', '未存在の新規フォルダー名',
                                      initialvalue='KokosimYamanashiDemo109', parent=self.root)
        if not name:
            return None
        if name in ('.','..') or any(c in name for c in '/\\:'):
            raise ValueError('新規フォルダー名を指定してください')
        return Path(parent) / name

    def _guard(self):
        if self.controller.store is None:
            raise ValueError('デモがありません')
        self.controller.store.reader._guard()

    def _navigation_error(self):
        self.last_error = '検証拒否'
        self.controller.snapshot = None
        self.current_var.set('検証済みの表示なし')
        self.progress['value'] = 0
        self.status_var.set('読取検証拒否：画面を消去しました。原本は修復しません')
        self._states()

    def _states(self):
        c = self.controller
        for key, button in self.buttons.items():
            enabled = not c.busy and not self.closing
            if key in ('new','resume'):
                enabled = enabled and c.namespace is not None
                if key == 'resume':
                    enabled = enabled and bool(self.demo_box['values'])
            elif key in ('one','round'):
                enabled = enabled and c.snapshot is not None and not c.snapshot.complete
            elif key == 'reload':
                enabled = enabled and c.store is not None
            if key == 'exit':
                enabled = not self.closing
            if key == 'cancel':
                enabled = c.busy and not self.closing
            button.configure(state='normal' if enabled else 'disabled')
        self.demo_box.configure(state='disabled' if c.busy or self.closing else 'readonly')

    def dispatch(self, action):
        if self.closed or self.closing:
            return
        if action == 'exit':
            self.request_close(); return
        if action == 'cancel' and self.controller.busy:
            self.controller.request_cancel()
            self.status_var.set('中断要求中：まだ完了ではありません。未commit計算結果は未保存。保存済み件数を再検証して表示します')
            self.buttons['cancel'].configure(state='disabled')
            return
        if self.controller.busy:
            return
        try:
            if action.startswith('namespace_'):
                create = action == 'namespace_new'
                path = self.namespace_picker(create)
                if path is None:
                    return
                self.history.clear(); self.current_var.set('未開始・専用デモを選択してください')
                self.progress['value'] = 0
                ids = self.controller.use_namespace(path, create=create)
                self.demo_box['values'] = ids
                self.demo_box.set('')
                if ids:
                    self.demo_box.current(len(ids)-1)
                self.status_var.set('専用保存先を選択しました。新規開始またはデモIDを選んで続きから')
                self._states(); return
            if action == 'new' and not self.confirm('架空32チームの別の新規デモを作成します。専用保存先へ永続保存しますか？'):
                return
            demo_id = self.demo_box.get() if action == 'resume' else None
            self.history.clear()
            committed = len(self.controller.snapshot.results) if self.controller.snapshot is not None else None
            self.current_var.set('検証・計算中（未commit計算結果は未保存）')
            self.controller.begin(action, demo_id=demo_id)
            self.status_var.set('処理中：全保存内容を検証しています。' +
                (f'開始時点の保存済み {committed}/31試合。' if committed is not None else '') +
                '計算中の1試合は未保存です。試合ごとに自動保存し、次戦を更新します')
            self._states()
            self.root.after(30, self._poll)
        except Exception:
            self.controller._release()
            self.controller.namespace = None
            self.demo_box.set(''); self.demo_box['values'] = ()
            self.history.clear()
            self.current_var.set('検証済みの表示なし')
            self.progress['value'] = 0
            self.last_error = '専用保存先・デモの選択を拒否しました'
            self.status_var.set(self.last_error + '。既存フォルダー・製品save・旧backupは使用できません')
            self._states()

    def _poll(self):
        if self.closed:
            return
        update = self.controller.poll()
        if update is not None:
            self.status_var.set(update.message)
            if update.error:
                self.last_error = update.message
                self.history.clear()
                self.current_var.set('検証済みの表示なし')
                self.progress['value'] = 0
            elif update.snapshot is not None:
                snap = update.snapshot
                self.progress['value'] = len(snap.results)
                labels = {t.team_id:t.label for t in snap.registration.teams}
                previous = snap.results[-1] if snap.results else None
                last = (f'前試合：{labels[previous.team1_id]} {previous.team1_score}－{previous.team2_score} '
                        f'{labels[previous.team2_id]}。' if previous else '前試合：まだありません。')
                self.current_var.set(f'{len(snap.results)}/31試合 自動保存済み。' + last + self._next(snap))
                if not update.done:
                    self.status_var.set(('終了要求中：' if self.closing else
                        '中断要求中：' if self.controller._cancel.is_set() else 'ラウンド進行中：') +
                        update.message + '。計算中の次試合は未保存です。終了応答待ちと保存完了は別です')
                if update.done and not self.closing:
                    try:
                        self.history.show(snap)
                        if self.history.snapshot is None:
                            raise ValueError('表示検証拒否')
                        ids = self.controller.namespace.demos()
                        self.demo_box['values'] = ids
                        self.demo_box.set(self.controller.store.demo_id)
                        self.last_error = None
                    except Exception:
                        self.history.clear()
                        self._navigation_error()
            if update.done:
                if self.closing:
                    self.close(); return
                self._states(); return
        self.root.after(30, self._poll)

    def _next(self, snap):
        if snap.complete:
            return '大会完了。同順位・学校参加・全660人の試合別／通算成績を閲覧できます'
        labels = {t.team_id:t.label for t in snap.registration.teams}
        game = snap.plan.games[len(snap.results)]
        winners = {r.match_id:r.winner_id for r in snap.results}
        def name(source):
            return labels[winners[source[7:]]] if source.startswith('winner:') else labels[source]
        remaining = sum(g.round_no == game.round_no for g in snap.plan.games[len(snap.results):])
        return (f'次：第{game.round_no}/5ラウンド（残り{remaining}試合） {game.day} '
                f'{name(game.team1_source)} 対 {name(game.team2_source)}')

    def request_close(self):
        if self.closed or self.closing:
            return
        if not self.confirm('終了しますか？未commitの計算結果は未保存です。commit済みの試合だけ後で再開できます。'):
            return
        self.closing = True
        self.history.clear()
        self.controller.request_cancel()
        self.status_var.set('終了要求中（まだ終了していません）。未commit結果は未保存です。保存済みを確認し接続を閉じてから終了します')
        self._states()
        if not self.controller.busy:
            self.close()

    def close(self):
        if self.closed:
            return
        if self.controller.busy:
            raise ValueError('worker終了を待ってから画面を閉じます')
        self.controller.close()
        # Break GUI callback cycles on Tk's thread before a later worker GC.
        self.history.guard = self.history.on_error = None
        self.namespace_picker = self.confirm = None
        self.closed = True
        self.root.destroy()


def main():
    root = tk.Tk()
    gui = YamanashiDemoTk(root)
    try:
        root.mainloop()
    finally:
        gui.controller.close()


if __name__ == '__main__':
    main()
