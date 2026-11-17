"""進行中の年度の状態（LiveSeasonDependencyRuntimeState）をそのまま書き出す・戻す。

セーブの読込で試合を最初から計算し直さないため（game_definition.md §6）。
データ（DataRepository）・試合の進め方（engine）・大会の入力をつくる部品は
書き出さず、読込時に今のものをつなぎ直す。

pickle を使うので、読み込むのは自分のゲームが書いたセーブだけにする。
"""
from __future__ import annotations

import copyreg
import io
import pickle
import zlib

from .engine import TournamentEngine
from .repository import DataRepository
from .season import StructuralAnnualInputFactory


# 2：外に置く部品を型ごとの置き換えで書く（前は persistent_id）
SNAPSHOT_FORMAT = b"KOKOSIM-RUNTIME-2\n"

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


def _external_ref(name):
    """書き出さない部品の目印。読込では ``_Unpickler.find_class`` が今の部品に差し替える。"""
    raise RuntimeSnapshotError(f"external reference outside a snapshot load: {name}")


class _Pickler(pickle.Pickler):
    """書き出さない部品（データ・engine など）を、型ごとの置き換えで目印にする。

    ``persistent_id`` は状態の中のすべてのオブジェクト（約160万個）で呼ばれて遅いので
    使わない。置き換えは ``dispatch_table``（型 → 書き出し方）で、その型のときだけ呼ばれる。
    """

    def __init__(self, stream, seasons):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        external = {
            id(value): f"{year}:{name}"
            for year, season in seasons.items()
            for name, value in _engine_parts(season.engine).items()
            if value is not None
        }
        protocol = pickle.HIGHEST_PROTOCOL

        def by_identity(obj):
            name = external.get(id(obj))
            if name is not None:
                return _external_ref, (name,)
            return obj.__reduce_ex__(protocol)

        def by_type(obj):
            return _external_ref, (_REPO if isinstance(obj, DataRepository) else _FACTORY,)

        table = dict(copyreg.dispatch_table)
        for season in seasons.values():
            for value in _engine_parts(season.engine).values():
                if value is not None:
                    table[type(value)] = by_identity
        for kind in (DataRepository, StructuralAnnualInputFactory, *(
            type(repo) for repo in (
                getattr(season, "repo", None) for season in seasons.values()
            ) if isinstance(repo, DataRepository)
        )):
            table[kind] = by_type
        self.dispatch_table = table


class _Unpickler(pickle.Unpickler):
    def __init__(self, stream, external):
        super().__init__(stream)
        self._external = external

    def find_class(self, module, name):
        if (module, name) == (__name__, _external_ref.__name__):
            return self.external
        return super().find_class(module, name)

    def external(self, name):
        try:
            return self._external[name]
        except KeyError as exc:
            raise pickle.UnpicklingError(
                f"unknown external reference: {name}"
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


class _ReadOnlyUnpickler(_Unpickler):
    """閉じた年度を見るだけのとき。試合の進め方（engine）はつながない。"""

    def external(self, name):
        if name in self._external:
            return self._external[name]
        if ":" in str(name):
            return None
        return super().external(name)


def load_closed_season(data: bytes, repo, data_dir, rng_seed: int):
    """閉じた年度の状態（``dump_runtime_state`` で書いたもの）を、見るだけの形で戻す。"""
    if not data.startswith(SNAPSHOT_FORMAT):
        raise RuntimeSnapshotError("unknown runtime snapshot format")
    try:
        raw = zlib.decompress(data[len(SNAPSHOT_FORMAT):])
        external = {
            _REPO: repo,
            _FACTORY: StructuralAnnualInputFactory(repo, data_dir, rng_seed),
        }
        return _ReadOnlyUnpickler(io.BytesIO(raw), external).load()
    except (zlib.error, pickle.UnpicklingError, EOFError) as exc:
        raise RuntimeSnapshotError(
            f"cannot restore closed season: {exc}"
        ) from exc
