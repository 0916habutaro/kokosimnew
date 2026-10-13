"""Japanese minimal Tk game pilot. Windows personal, generated demo only."""
import argparse
import tkinter as tk
from tkinter import messagebox, ttk

from .live_game_demo_controller import DemoController, demo_read_handles
from .career_history_tk_pilot import CareerHistoryTkPilot


class DemoHistoryTk(CareerHistoryTkPilot):
    """Reuse existing readonly screens with event-scoped demo cleanup."""
    def __init__(self, root, session):
        with demo_read_handles():
            super().__init__(root, session.bridge, slot_session=session)
        # The experiment has one immutable history source, no user entry path.
        self.slot_box.configure(state='disabled')
        self.school_entry.configure(state='disabled')
        self.legacy_games_button.configure(state='disabled')
        self.v2_games_button.configure(state='disabled')

    def _action(self, operation):
        with demo_read_handles():
            super()._action(operation)
        self.legacy_games_button.configure(state='disabled')
        self.v2_games_button.configure(state='disabled')

    def _change_slot(self, _event=None):
        self.slot_var.set(self.slot_session.slot_id)
        self.last_error = 'この試作では固定demo以外を選べません'


class LiveGameTkPilot:
    def __init__(self, root, controller, *, confirm=None):
        self.root, self.controller = root, controller
        self.confirm = confirm or (lambda text: messagebox.askyesno('操作の確認', text, parent=root))
        self.pending = None
        self.closed = False
        self.history_window = None
        self.history_gui = None
        self.last_error = None
        self.buttons = {}
        self.source_var = tk.StringVar(master=root, value='manual')
        self.status_var = tk.StringVar(master=root, value=controller.view.message)
        self.heading_var = tk.StringVar(master=root, value='')
        root.title('ココシミュNew｜8校単大会 操作試作（隔離demo）')
        root.geometry('1080x760')
        root.minsize(820, 600)
        root.protocol('WM_DELETE_WINDOW', self.request_close)
        ttk.Label(root, text='Windows個人用・非配布／2026年度8校限定／既存セーブは利用しません',
                  padding=10).pack(fill='x')
        ttk.Label(root, text='再起動：py -3.12 -m phase2_engine.live_game_tk_pilot --demo-id '
                  + controller.demo_id, padding=(10, 0), wraplength=1000).pack(fill='x')
        bar = ttk.Frame(root, padding=10)
        bar.pack(fill='x')
        for action, caption in [('new','新規ゲーム'),('load','続きから'),('history','過去記録閲覧'),('exit','終了')]:
            self._button(bar, action, caption)
        ttk.Label(bar, text='demo98／保存元').pack(side='left', padx=8)
        self.source_box = ttk.Combobox(bar, state='readonly', width=10,
            textvariable=self.source_var, values=('manual','autosave'))
        self.source_box.pack(side='left')
        ttk.Label(root, text='manual＝手動保存／autosave＝進行後の自動保存。保存元を明示してロードします。',
                  padding=(10,0)).pack(fill='x')
        ttk.Label(root, textvariable=self.heading_var, padding=10).pack(fill='x')
        progress = ttk.Frame(root, padding=10)
        progress.pack(fill='x')
        for action, caption in [('today','当日の試合'),('day','翌日へ'),
                ('next_match','次の試合日まで進む'),('manual','手動保存'),('seal','年度終了・履歴を封印')]:
            self._button(progress, action, caption)
        future = ttk.Frame(root, padding=(10,0))
        future.pack(fill='x')
        for caption in ('翌年度登録','翌年度の大会開始','バックアップ／復元'):
            ttk.Button(future, text=caption, state='disabled').pack(side='left', padx=3)
        ttk.Label(root, text='翌年度登録・翌年度試合・本番バックアップ／復元は未実装です。',
                  padding=10).pack(fill='x')
        self.text = tk.Text(root, wrap='word', height=22)
        self.text.pack(fill='both', expand=True, padx=10)
        ttk.Label(root, textvariable=self.status_var, padding=10, wraplength=1000).pack(fill='x')
        self.render()

    def _button(self, parent, action, caption):
        b = ttk.Button(parent, text=caption, command=lambda:self.dispatch(action))
        b.pack(side='left', padx=3)
        self.buttons[action] = b

    def render(self):
        c = self.controller
        game = c.view.game
        blocked = self.pending is not None or c.history_active
        started = c.verify()['generation'] is not None
        sealed = bool(game and game['sealed'])
        for action, button in self.buttons.items():
            enabled = not blocked
            if action == 'new': enabled = enabled and not started
            elif action in ('load','history'): enabled = enabled and started
            elif action in ('today','day','next_match'): enabled = enabled and bool(game) and not sealed
            elif action == 'manual': enabled = enabled and bool(game)
            elif action == 'seal': enabled = enabled and bool(game) and not sealed and game['summary']['completed_runtime_count'] == 1
            button.configure(state='normal' if enabled else 'disabled')
        self.source_box.configure(state='disabled' if blocked else 'readonly')
        lines = ['新規ゲームは明示開始してください。保存済demoは保存元を選んで続きからを開きます。']
        self.heading_var.set('タイトル／固定隔離スロット：demo98')
        if game:
            s = game['summary']
            self.heading_var.set(f"{s['year']}年度／ゲーム内日付 {s['current_date']}／完了 {s['completed_match_count']}試合")
            lines = ['大会・学校一覧（学校名だけをキーにしません）']
            for competition in game['competitions']:
                lines.append(f"{competition['competition_name']} [{competition['competition_id']}]")
                names = game['school_labels']
                lines.append('学校名：このdemoの2026年度マスター表示名／遷移キーは学校ID')
                lines += [f"  {names.get(sid,sid)} [{sid}]" for sid in game['schools']]
                lines.append('対戦予定・結果（既存カレンダー／runtimeの返却値）')
                for m in competition['matches']:
                    result = (f"{m['team1_score']}－{m['team2_score']}" if m['status']=='completed' else '未実施')
                    lines.append(f"{m['match_date']} {names[m['team1_id']]} 対 {names[m['team2_id']]}：{result}")
            lines.append('当日の試合：' + str(len(game['today'])) + '件')
            lines.append('封印済み・過去記録閲覧が可能です' if sealed else '未封印年度は履歴閲覧できません')
        self.text.configure(state='normal')
        self.text.delete('1.0','end')
        self.text.insert('1.0','\n'.join(lines))
        self.text.configure(state='disabled')

    def dispatch(self, action):
        if self.closed or self.pending is not None or self.controller.history_active:
            return
        if action == 'exit':
            self.request_close()
            return
        if action == 'history':
            self.open_history()
            return
        prompts = {'new':'自己生成8校単大会を新規開始しますか？',
                   'manual':'選択中demoに手動保存しますか？',
                   'seal':'全試合終了後、12月31日へ進めて履歴を封印しますか？翌年度試合は開始しません。'}
        if action in prompts and not self.confirm(prompts[action]):
            return
        try:
            self.pending = self.controller.begin(action,
                source=self.source_var.get() if action == 'load' else None)
            self.status_var.set('処理中です。完了まで操作をお待ちください。')
            # Always observe a submitted child, even if input corruption makes
            # the immediate projection fail before the first poll.
            self.root.after(30, self._poll)
            self.render()
        except (ValueError, OSError) as exc:
            self._error(exc)

    def _poll(self):
        if self.closed: return
        try:
            game = self.controller.poll()
            if game is None:
                self.root.after(30, self._poll)
                return
            self.pending = None
            self.last_error = None
            self.status_var.set(self.controller.view.message)
            self.render()
        except Exception as exc:
            self.pending = None
            self._error(exc)

    def _error(self, exc):
        self.last_error = str(exc)
        self.status_var.set('操作できません：' + str(exc) + '／選択中の保存世代は維持します')
        try:
            self.render()
        except (ValueError, OSError):
            for b in self.buttons.values(): b.configure(state='disabled')
            self.buttons['exit'].configure(state='normal')

    def open_history(self):
        try:
            session = self.controller.open_history()
            self.history_window = tk.Toplevel(self.root)
            self.history_gui = DemoHistoryTk(self.history_window, session)
            self.history_window.protocol('WM_DELETE_WINDOW', self.close_history)
            ttk.Button(self.history_window, text='ゲーム画面へ戻る', command=self.close_history).pack()
            self.render()
        except Exception as exc:
            self.close_history(refresh=False)
            self._error(exc)

    def close_history(self, *, refresh=True):
        if self.history_gui is not None:
            self.history_gui._close_game_windows()
        if self.history_window is not None:
            self.history_window.destroy()
        self.history_window = self.history_gui = None
        self.controller.close_history()
        if not self.closed and refresh:
            self.render()

    def request_close(self):
        if self.pending is not None:
            self.status_var.set('処理完了後に終了してください')
            return
        if self.confirm('画面を終了しますか？保存済demoは表示されたIDで再起動できます。'):
            self.close()

    def close(self):
        if self.closed: return
        if self.pending is not None:
            raise ValueError('処理中は終了できません')
        self.closed = True
        self.close_history()
        self.controller.close()
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo-id', help='以前この試作で生成したdemo IDだけを明示再開')
    args = parser.parse_args(argv)
    controller = DemoController(args.demo_id)
    try:
        root = tk.Tk()
        gui = LiveGameTkPilot(root, controller)
        root.mainloop()
        if not gui.closed:
            gui.close()
    finally:
        controller.close()


if __name__ == '__main__':
    main()
