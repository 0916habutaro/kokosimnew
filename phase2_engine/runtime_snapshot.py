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
_FACTORY = "structural_factory"
# 年度ごとの試合の進め方。大会の進行が直接持っている試合の決め方も同じ扱い。
_ENGINE_PARTS = ("engine", "main_match_resolver", "pre_main_match_resolver")


class RuntimeSnapshotError(ValueError):
    pass


def _seasons(state) -> dict[int, object]:
    """書き出す年度の状態（年度の重なりなら複数）。"""
    seasons = getattr(state, "__dict__", {}).get("seasons")
    return dict(seasons) if seasons is not None else {state.year: state}


def _engine_parts(engine) -> dict[str, object]:
    parts = {"engine": engine}
    for name in _ENGINE_PARTS[1:]:
        value = getattr(engine, name, None)
        if value is not None:
            parts[name] = value
    return parts


class _Pickler(pickle.Pickler):
    def __init__(self, stream, seasons):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        self._external = {
            id(value): f"{year}:{name}"
            for year, season in seasons.items()
            for name, value in _engine_parts(season.engine).items()
        }

    def persistent_id(self, obj):
        name = self._external.get(id(obj))
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


def snapshot_years(state) -> list[int]:
    return sorted(_seasons(state))


def dump_runtime_state(state) -> bytes:
    stream = io.BytesIO()
    _Pickler(stream, _seasons(state)).dump(state)
    return SNAPSHOT_FORMAT + zlib.compress(stream.getvalue(), 1)


def load_runtime_state(data: bytes, plans: dict, *, engines=None):
    """``plans``・``engines`` は年度ごと。engine がない年度は既定の engine。"""
    if not data.startswith(SNAPSHOT_FORMAT):
        raise RuntimeSnapshotError("unknown runtime snapshot format")
    try:
        raw = zlib.decompress(data[len(SNAPSHOT_FORMAT):])
        plan = next(iter(plans.values()))
        external = {
            _REPO: plan.repo,
            _FACTORY: StructuralAnnualInputFactory(
                plan.repo, plan.data_dir, plan.rng_seed
            ),
        }
        for year, season_plan in plans.items():
            engine = (engines or {}).get(year) or TournamentEngine(
                season_plan.repo
            )
            for name, value in _engine_parts(engine).items():
                external[f"{year}:{name}"] = value
        return _Unpickler(io.BytesIO(raw), external).load()
    except (zlib.error, pickle.UnpicklingError, EOFError) as exc:
        raise RuntimeSnapshotError(
            f"cannot restore runtime snapshot: {exc}"
        ) from exc
