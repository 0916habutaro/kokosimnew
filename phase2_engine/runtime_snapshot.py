"""進行中の年度の状態（LiveSeasonDependencyRuntimeState）をそのまま書き出す・戻す。

セーブの読込で試合を最初から計算し直さないため（game_definition.md §6）。
データ（DataRepository）・試合の進め方（engine）・大会の入力をつくる部品は
書き出さず、読込時に今のものをつなぎ直す。

pickle を使うので、読み込むのは自分のゲームが書いたセーブだけにする。
"""
from __future__ import annotations

import io
import pickle
import zlib

from .engine import TournamentEngine
from .repository import DataRepository
from .season import StructuralAnnualInputFactory


SNAPSHOT_FORMAT = b"KOKOSIM-RUNTIME-1\n"

_REPO = "repo"
_ENGINE = "engine"
_FACTORY = "structural_factory"
# 大会の進行が直接持っている試合の決め方（engine と同じもの）。
_RESOLVERS = ("main_match_resolver", "pre_main_match_resolver")


class RuntimeSnapshotError(ValueError):
    pass


class _Pickler(pickle.Pickler):
    def __init__(self, stream, engine):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        self._engine = engine
        self._resolvers = {
            id(value): name
            for name in _RESOLVERS
            if (value := getattr(engine, name, None)) is not None
        }

    def persistent_id(self, obj):
        if obj is self._engine:
            return _ENGINE
        name = self._resolvers.get(id(obj))
        if name is not None:
            return name
        if isinstance(obj, DataRepository):
            return _REPO
        if isinstance(obj, StructuralAnnualInputFactory):
            return _FACTORY
        return None


class _Unpickler(pickle.Unpickler):
    def __init__(self, stream, external):
        super().__init__(stream)
        self._external = external

    def persistent_load(self, pid):
        try:
            return self._external[pid]
        except KeyError as exc:
            raise pickle.UnpicklingError(
                f"unknown external reference: {pid}"
            ) from exc


def dump_runtime_state(state) -> bytes:
    stream = io.BytesIO()
    _Pickler(stream, state.engine).dump(state)
    return SNAPSHOT_FORMAT + zlib.compress(stream.getvalue(), 1)


def load_runtime_state(data: bytes, plan, *, engine=None):
    if not data.startswith(SNAPSHOT_FORMAT):
        raise RuntimeSnapshotError("unknown runtime snapshot format")
    try:
        raw = zlib.decompress(data[len(SNAPSHOT_FORMAT):])
        engine = (
            engine if engine is not None
            else TournamentEngine(plan.repo)
        )
        external = {
            **{name: getattr(engine, name, None) for name in _RESOLVERS},
            _REPO: plan.repo,
            _ENGINE: engine,
            _FACTORY: StructuralAnnualInputFactory(
                plan.repo, plan.data_dir, plan.rng_seed
            ),
        }
        return _Unpickler(io.BytesIO(raw), external).load()
    except (zlib.error, pickle.UnpicklingError, EOFError) as exc:
        raise RuntimeSnapshotError(
            f"cannot restore runtime snapshot: {exc}"
        ) from exc
