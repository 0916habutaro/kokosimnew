"""GUI-independent owned-demo controller; never accepts a user save path."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from time import monotonic
import uuid
from unittest.mock import patch

from .live_game_demo_worker import ROOT, SLOT, SEED, YEAR, CONTRACT
from .career_history_slot_session import CareerHistorySlotSession

VERSION = 'stage98-owned-demo-v1'
DEMO_BASE = Path(tempfile.gettempdir()) / 'kokosim-stage98'
_ID = re.compile(r'[0-9a-f]{32}\Z')
_GEN = re.compile(r'g-[0-9a-f]{32}\Z')
_FILES = {'manual.json', 'autosave.json', 'slot_metadata.json',
          'historical_matches.sqlite3', 'career_rosters.sqlite3'}


def safe_directory(path):
    # Ancestors included: reject POSIX symlinks and Windows junction/reparse paths.
    for entry in (path, *path.parents):
        if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
            raise ValueError('リンク先のdemoは利用できません')
    if not path.is_dir():
        raise ValueError('demoが見つかりません')


def pin(saves):
    safe_directory(saves)
    entries = list(saves.iterdir())
    if len(entries) != 1 or entries[0].name != SLOT:
        raise ValueError('未知のスロットです')
    slot = entries[0]
    safe_directory(slot)
    result = {}
    for p in slot.iterdir():
        if p.is_symlink() or not p.is_file() or p.name not in _FILES or p.stat().st_nlink != 1:
            raise ValueError('未確認の保存ファイルです')
        result[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    if not {'manual.json', 'slot_metadata.json', 'historical_matches.sqlite3'} <= result.keys():
        raise ValueError('保存ファイルが不足しています')
    return result


@contextmanager
def demo_read_handles():
    """Pilot-only, single-threaded Tk event scope; no product lifetime change.

    Legacy read models lack universal close APIs. Capture connections opened
    within an owned demo read, then close even on projection/read exceptions.
    """
    original, handles = sqlite3.connect, []
    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        handles.append(conn)
        return conn
    with patch.object(sqlite3, 'connect', connect):
        try:
            yield
        finally:
            for conn in reversed(handles):
                conn.close()


@dataclass(frozen=True)
class DemoView:
    screen: str = 'title'
    game: dict | None = None
    message: str = '自己生成8校単大会・2026年度の試験です'


class DemoController:
    def __init__(self, demo_id=None, *, _base=None):
        # _base is internal fixture plumbing; no CLI arbitrary-path option.
        self.base = Path(_base) if _base is not None else DEMO_BASE
        self.base.mkdir(parents=True, exist_ok=True)
        safe_directory(self.base)
        self.demo_id = demo_id or uuid.uuid4().hex
        if not isinstance(self.demo_id, str) or not _ID.fullmatch(self.demo_id):
            raise ValueError('demo IDが不正です')
        self.root = self.base / self.demo_id
        if demo_id is None:
            self.root.mkdir()
            self._manifest_write(dict(version=VERSION, slot=SLOT, year=YEAR, seed=SEED,
                contract=CONTRACT, generation=None, files={}))
        safe_directory(self.root)
        self.busy = False
        self.closed = False
        self.history_active = False
        self.view = DemoView()
        self.active_source = None
        self._pending = None
        self._lock = self.root / 'session.lock'
        self._lock_fd = None
        try:
            self._lock_fd = os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            self._manifest = self.verify()
        except BaseException:
            self.close()
            raise

    def _manifest_write(self, value):
        temporary = self.root / ('manifest-' + uuid.uuid4().hex + '.tmp')
        with temporary.open('x', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(temporary, self.root / 'demo.json')

    def verify(self):
        safe_directory(self.root)
        path = self.root / 'demo.json'
        if path.is_symlink():
            raise ValueError('demo設定が不正です')
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or set(data) != {'version','slot','year','seed','contract','generation','files'}
            or any(data[k] != v for k, v in dict(version=VERSION, slot=SLOT, year=YEAR,
                    seed=SEED, contract=CONTRACT).items())):
            raise ValueError('未確認のdemo設定です')
        gen = data['generation']
        if gen is None:
            if data['files'] != {}:
                raise ValueError('demo設定が不正です')
        elif not isinstance(gen, str) or not _GEN.fullmatch(gen) or pin(self.root / gen) != data['files']:
            raise ValueError('保存データが破損または変更されています')
        return data

    @property
    def saves(self):
        data = self.verify()
        if data['generation'] is None:
            raise ValueError('新規ゲームを開始してください')
        return self.root / data['generation']

    @property
    def slot(self):
        return self.saves / SLOT

    def _worker(self, saves, action, source):
        result = subprocess.run([sys.executable, '-m', 'phase2_engine.live_game_demo_worker'],
            input=json.dumps(dict(saves=str(saves), action=action, source=source)),
            cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1'), capture_output=True,
            text=True, encoding='utf-8', timeout=180)
        try:
            response = json.loads(result.stdout)
        except ValueError:
            raise ValueError('ゲーム処理が完了しませんでした') from None
        if result.returncode or not response.get('ok'):
            raise ValueError(response.get('error', 'ゲーム処理が失敗しました'))
        return response['state']

    def _prepare(self, action, slot_id, source):
        if self.closed or self.busy or self.history_active:
            raise ValueError('処理中または終了済みです')
        if slot_id != SLOT or action not in ('new','load','manual','today','day','next_match','seal'):
            raise ValueError('未知のスロットまたは操作です')
        if action == 'load' and source not in ('manual','autosave'):
            raise ValueError('manualかautosaveを明示してください')
        if source is not None and source not in ('manual','autosave'):
            raise ValueError('保存元が不正です')
        if action not in ('new','load') and self.view.game is None:
            raise ValueError('続きからを明示してゲームを開いてください')
        self.busy = True
        temp = None
        try:
            before = self.verify()
            if action == 'new' and before['generation'] is not None:
                raise ValueError('既存demoを上書きできません')
            if action != 'new' and before['generation'] is None:
                raise ValueError('保存済ゲームがありません')
            selected = source if action == 'load' else self.active_source or 'manual'
            if action != 'new' and selected + '.json' not in before['files']:
                raise ValueError('選択した保存元がありません')
            temp = tempfile.TemporaryDirectory(prefix='stage98-work-')
            staged = Path(temp.name) / 'saves'
            if action == 'new':
                staged.mkdir()
            else:
                shutil.copytree(self.root / before['generation'], staged)
            return dict(temp=temp, staged=staged, before=before, action=action, source=selected)
        except BaseException:
            if temp is not None: temp.cleanup()
            self.busy = False
            raise

    def _publish(self, operation, game):
        staged, before = operation['staged'], operation['before']
        files = pin(staged)
        if self.verify() != before:
            raise ValueError('操作中にdemoが変更されました')
        generation = 'g-' + uuid.uuid4().hex
        shutil.copytree(staged, self.root / generation)
        if pin(self.root / generation) != files:
            raise ValueError('保存世代の確認に失敗しました')
        self._manifest_write({**before, 'generation': generation, 'files': files})
        self.active_source = game['active_source']
        self.view = DemoView('game', game, '保存済み：' + self.active_source)
        return game

    def execute(self, action, *, slot_id=SLOT, source=None):
        operation = self._prepare(action, slot_id, source)
        try:
            return self._publish(operation, self._worker(operation['staged'], action, operation['source']))
        finally:
            operation['temp'].cleanup()
            self.busy = False

    def begin(self, action, *, slot_id=SLOT, source=None):
        """Nonblocking GUI adapter. No Python thread can finalize Tk objects."""
        operation = self._prepare(action, slot_id, source)
        try:
            output = Path(operation['temp'].name) / 'response.json'
            with output.open('wb') as out:
                child = subprocess.Popen([sys.executable, '-m', 'phase2_engine.live_game_demo_worker'],
                    stdin=subprocess.PIPE, stdout=out, stderr=out, cwd=ROOT,
                    env=dict(os.environ, PYTHONUTF8='1'))
            operation.update(child=child, output=output, deadline=monotonic()+180)
            self._pending = operation
            child.stdin.write(json.dumps(dict(saves=str(operation['staged']),
                action=action, source=operation['source'])).encode('utf-8'))
            child.stdin.close()
            return operation
        except BaseException:
            self._dispose_pending(operation)
            raise

    def _dispose_pending(self, operation):
        child = operation.get('child')
        if child is not None:
            if child.poll() is None: child.kill()
            child.wait()
            if child.stdin is not None and not child.stdin.closed: child.stdin.close()
        operation['temp'].cleanup()
        self._pending = None
        self.busy = False

    def poll(self):
        operation = self._pending
        if operation is None:
            raise ValueError('実行中の操作がありません')
        child = operation['child']
        if child.poll() is None and monotonic() < operation['deadline']:
            return None
        try:
            if child.poll() is None:
                raise ValueError('ゲーム処理が時間内に完了しませんでした')
            try:
                response = json.loads(operation['output'].read_text(encoding='utf-8'))
            except ValueError:
                raise ValueError('ゲーム処理が完了しませんでした') from None
            if child.returncode or not response.get('ok'):
                raise ValueError(response.get('error', 'ゲーム処理が失敗しました'))
            return self._publish(operation, response['state'])
        finally:
            self._dispose_pending(operation)

    def open_history(self, *, slot_id=SLOT):
        if self.closed or self.busy or self.history_active or slot_id != SLOT:
            raise ValueError('履歴を開けません')
        with demo_read_handles():
            session = CareerHistorySlotSession(self.saves, SLOT)
        self.history_active = True
        return session

    def close_history(self):
        self.history_active = False

    def close(self):
        if self._pending is not None:
            self._dispose_pending(self._pending)
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
            self._lock.unlink()
        self.closed = True
