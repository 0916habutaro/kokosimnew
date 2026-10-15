"""GUI-free Stage109 actions. Worker sends messages; only Tk's thread renders."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from queue import Queue, Empty
import threading
from time import perf_counter

from .yamanashi_demo_store import DemoNamespace, DemoStore
from .yamanashi_tournament_lab import checkpoint


@dataclass(frozen=True)
class DemoUpdate:
    snapshot: object = None
    message: str = ''
    done: bool = False
    error: bool = False


class DemoController:
    def __init__(self):
        self.namespace = self.store = self.snapshot = None
        self.busy = self.closed = False
        self._thread = None
        self._queue = Queue()
        self._cancel = threading.Event()

    def _release(self):
        if self.store is not None:
            self.store.close()
        self.store = self.snapshot = None

    def use_namespace(self, path, *, create=False):
        if self.busy or self.closed:
            raise ValueError('処理中または終了済みです')
        self._release()
        self.namespace = None
        ns = DemoNamespace.create(path, opt_in=True) if create else DemoNamespace(path)
        ns.demos()
        self.namespace = ns
        return ns.demos()

    def execute(self, action, *, demo_id=None, cancel=None, progress=None, fault=None):
        if self.closed:
            raise ValueError('デモは終了しています')
        cancel = cancel or threading.Event()
        if self.namespace is None:
            raise ValueError('専用保存先を明示選択してください')
        if action in ('new', 'resume'):
            self._release()
            self.store = (DemoStore.create(self.namespace, opt_in=True) if action == 'new'
                          else DemoStore.resume(self.namespace, demo_id))
            self.snapshot = self.store.snapshot()
        elif action in ('one', 'round'):
            if self.store is None:
                raise ValueError('先に新規デモまたは続きからを選択してください')
            snap = self.store.snapshot()
            if snap.complete:
                raise ValueError('全31試合が完了しています')
            target_round = snap.plan.games[len(snap.results)].round_no
            while not snap.complete:
                self.store.play_next(expected_checkpoint=checkpoint(snap.results), cancel=cancel, fault=fault)
                snap = self.store.snapshot()
                self.snapshot = snap
                if progress:
                    progress(DemoUpdate(snap, f'{len(snap.results)}/31試合 自動保存済み'))
                if action == 'one' or snap.complete or snap.plan.games[len(snap.results)].round_no != target_round:
                    break
        elif action == 'reload':
            if self.store is None:
                raise ValueError('デモを選択してください')
            self.snapshot = self.store.snapshot()
        else:
            raise ValueError('未知の操作です')
        return self.snapshot

    def begin(self, action, *, demo_id=None, fault=None):
        if self.busy or self.closed:
            raise ValueError('処理中または終了済みです')
        self.busy = True
        self.snapshot = None
        self._cancel.clear()
        def work():
            try:
                snap = self.execute(action, demo_id=demo_id, cancel=self._cancel,
                                    progress=self._queue.put, fault=fault)
                self._queue.put(DemoUpdate(snap, f'{len(snap.results)}/31試合 自動保存済み', done=True))
            except InterruptedError:
                # Cancellation has rolled back before commit. Do not project unverified state.
                self._queue.put(DemoUpdate(message='未commitの計算結果は未保存です。commit済みだけ再開できます', done=True))
            except Exception:
                self._release()
                # No private path, raw SHA or arbitrary SQLite error in UI/CI evidence.
                self._queue.put(DemoUpdate(message='検証拒否・保存できません。原本は修復しません。専用デモを選び直してください',
                                           done=True, error=True))
        self._thread = threading.Thread(target=work, name='yamanashi-demo-calculation', daemon=False)
        self._thread.start()

    def poll(self):
        try:
            update = self._queue.get_nowait()
        except Empty:
            return None
        if update.done:
            self._thread.join()
            self._thread = None
            self.busy = False
        return update

    def request_cancel(self):
        self._cancel.set()

    def close(self):
        self.request_cancel()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self.busy = False
        self._release()
        self.closed = True


def main(argv=None):
    parser = argparse.ArgumentParser(description='ゲーム内試験用山梨県夏季大会・専用デモCLI')
    parser.add_argument('--namespace', type=Path, required=True)
    parser.add_argument('--create-namespace', action='store_true')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--new', action='store_true')
    group.add_argument('--demo-id')
    parser.add_argument('--games', type=int, default=0, choices=range(32))
    args = parser.parse_args(argv)
    c = DemoController()
    began = perf_counter()
    try:
        c.use_namespace(args.namespace, create=args.create_namespace)
        snap = c.execute('new' if args.new else 'resume', demo_id=args.demo_id)
        seconds = []
        for _ in range(args.games):
            tick = perf_counter()
            snap = c.execute('one')
            seconds.append(round(perf_counter() - tick, 6))
        print(json.dumps(dict(demo_id=c.store.demo_id, committed=len(snap.results), complete=snap.complete,
            database_bytes=c.store.db_path.stat().st_size, seconds=round(perf_counter()-began, 6),
            game_seconds=seconds), ensure_ascii=False))
    finally:
        c.close()


if __name__ == '__main__':
    main()
