"""Self-created demo test processes; no user save or external SQLite input."""
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[1]


def run_cli(namespace, *, demo_id=None, games=0, create=False):
    args = [sys.executable, '-m', 'phase2_engine.yamanashi_demo_controller', '--namespace', str(namespace),
            '--games', str(games)]
    if create:
        args += ['--create-namespace']
    args += ['--demo-id', demo_id] if demo_id else ['--new']
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=600)
    if completed.returncode:
        raise AssertionError('独立Pythonプロセスの専用デモ操作に失敗')
    return json.loads(completed.stdout)


def run_gui(namespace, phase, demo_id=None):
    completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(namespace), str(phase), demo_id or ''],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=600,
        env=dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT)))
    if completed.returncode:
        # Only test failure text, never arbitrary paths/digests/payloads.
        raise AssertionError('native mapped Tk別プロセスの操作・終了gateに失敗')
    return json.loads(completed.stdout)


def gui_phase(namespace, phase, demo_id):
    import tkinter as tk
    from phase2_engine.yamanashi_demo_tk import YamanashiDemoTk
    from phase2_engine.yamanashi_demo_store import DemoNamespace, DemoStore
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *args: errors.append('Tk callback failure')
    gui = YamanashiDemoTk(root, namespace_picker=lambda create: namespace, confirm=lambda text: True)
    def pump():
        deadline = monotonic() + 500
        while gui.controller.busy:
            root.update()
            if errors or monotonic() > deadline:
                raise AssertionError('Tk callback/timeout')
            sleep(.01)
        root.update()
        assert not errors and gui.last_error is None
    def click(action):
        assert str(gui.buttons[action]['state']) != 'disabled'
        gui.buttons[action].invoke()
        pump()
    root.update()
    assert root.winfo_ismapped()
    click('namespace_new' if phase == 0 else 'namespace_open')
    if phase:
        gui.demo_box.set(demo_id)
    click('new' if phase == 0 else 'resume')
    start = len(gui.controller.snapshot.results)
    if phase == 0:
        assert start == 0
        assert len(gui.history.pickers['team']['values']) == 32
        assert len(gui.history.tables['plan'].get_children()) == 31
        click('one')
    elif phase == 1:
        assert start == 1
        click('round')
    else:
        assert start == 16
        for _ in range(4):
            click('round')
    snap = gui.controller.snapshot
    assert len(snap.results) == (1, 16, 31)[phase]
    tree = gui.history.tables['plan']
    gui.history.book.select(tree.master); root.update()
    tree.yview_moveto(1); root.update(); assert tree.yview()[0] > 0
    visited = 0
    if phase == 2:
        assert len(gui.history.tables['ranks'].get_children()) == 32
        # All 32 labels and all 660 permanent IDs; school filters retain joint origins.
        for index, team in enumerate(snap.registration.teams):
            gui.history.pickers['team'].current(index)
            gui.history.pickers['team'].event_generate('<<ComboboxSelected>>'); root.update()
            assert team.label in gui.history.pickers['team'].get()
            for school_index, sid in enumerate(team.school_ids, 1):
                gui.history.pickers['school'].current(school_index)
                gui.history.pickers['school'].event_generate('<<ComboboxSelected>>'); root.update()
                ids = gui.history.pickers['player']['values'][1:]
                assert len(ids) == 20
                for pindex, pid in enumerate(ids, 1):
                    gui.history.pickers['player'].current(pindex)
                    gui.history.pickers['player'].event_generate('<<ComboboxSelected>>'); root.update()
                    rows = gui.history.tables['members'].get_children()
                    assert len(rows) == 1
                    values = gui.history.tables['members'].item(rows[0], 'values')
                    assert values[1:3] == (sid, pid)
                    visited += 1
        assert visited == 660 and not errors
        for i in range(len(gui.history.pickers['match']['values'])):
            gui.history.pickers['match'].current(i)
            gui.history.pickers['match'].event_generate('<<ComboboxSelected>>'); root.update()
            assert len(gui.history.tables['innings'].get_children()) == len(gui.history.result.inning_scores)
    result = dict(demo_id=gui.controller.store.demo_id, committed=len(snap.results),
        complete=snap.complete, mapped=True, visited_players=visited)
    gui.buttons['exit'].invoke()
    assert gui.closed and gui.controller.closed and not gui.controller.busy
    # SQLite connections and native delete-sharing pins must all be released.
    ns = DemoNamespace(namespace)
    store = DemoStore.resume(ns, result['demo_id'])
    db = store.db_path
    store.close()
    moved = db.with_suffix('.released')
    db.rename(moved); moved.rename(db)
    store = DemoStore.resume(DemoNamespace(namespace), result['demo_id'])
    assert len(store.snapshot().results) == result['committed']
    store.close()
    return result


if __name__ == '__main__':
    print(json.dumps(gui_phase(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3])))
