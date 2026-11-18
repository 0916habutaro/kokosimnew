"""名簿づくりの並列化（新規開始・年度替わりの新入部員の能力）。

選手の能力は選手ごとの乱数と入部品質だけで決まる（``roster_book.new_player_state``）。
親のプロセスで学校ごとの顔ぶれと入部品質を求め、能力だけを学校ごとに子のプロセスで計算して、
学校の順に組み立て直す。1プロセスでつくるのと同じ結果になる。値は ``config/runtime/parallel_v1.json``。

Windows（EXE を含む）でも動くよう、子のプロセスは spawn で起こす（入口で
``multiprocessing.freeze_support()`` を呼ぶ）。プロセスを起こせない環境では1プロセスに戻す。
起動の途中の子のプロセスの中（種を並べて進める balance_report など）で起こせないときは、警告を出さずに1プロセスで計算する。
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import sys

CONFIG_PATH = Path("config") / "runtime" / "parallel_v1.json"

_settings: dict | None = None
_worker: tuple | None = None


def settings() -> dict:
    global _settings
    if _settings is None:
        rule = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["roster_build"]
        max_workers, min_schools = int(rule["max_workers"]), int(rule["min_schools"])
        if max_workers < 1 or min_schools < 1:
            raise ValueError("parallel_v1: max_workers and min_schools must be >= 1")
        _settings = {"max_workers": max_workers, "min_schools": min_schools}
    return _settings


def worker_count(schools: int, requested: int | None = None) -> int:
    """プロセスの数。``requested`` を渡すとその数（学校の数を超えない。テスト用）。"""
    if requested is not None:
        return max(1, min(int(requested), schools))
    rule = settings()
    if schools < rule["min_schools"]:
        return 1
    return max(1, min(os.cpu_count() or 1, rule["max_workers"], schools))


def _init(config_dir: str, first_year: int, career_seed: int) -> None:
    global _worker
    from .player_growth import PlayerGrowth
    from .school_intake import SchoolAwarePlayerAbilityGenerator

    generator = SchoolAwarePlayerAbilityGenerator(config_dir)
    pitch_types = list(generator.base_generator.params["pitch_repertoire"]["pitch_types"])
    _worker = (generator, PlayerGrowth(), pitch_types, first_year, career_seed)


def _school(task):
    from .roster_book import new_player_state

    generator, growth, pitch_types, first_year, career_seed = _worker
    year, items = task
    return [
        new_player_state(generator, growth, pitch_types, first_year=first_year,
                         career_seed=career_seed, player=player, year=year,
                         cohort=cohort, profile=profile)
        for player, cohort, profile in items
    ]


def _starting_up(error: BaseException) -> bool:
    """子のプロセスの中で、まだ起動の途中のため孫のプロセスを起こせなかったか（multiprocessing の決まった文言）。"""
    return isinstance(error, RuntimeError) and "bootstrapping phase" in str(error)


def _parallel_ready(book) -> bool:
    """子のプロセスで同じ計算ができるか（決まった生成器・成長の設定だけ）。"""
    from .player_growth import PlayerGrowth
    from .school_intake import SchoolAwarePlayerAbilityGenerator

    generator = book.ability_generator
    if not (type(generator) is SchoolAwarePlayerAbilityGenerator and generator.source is None
            and type(book.growth) is PlayerGrowth):
        return False
    # 子のプロセスは設定のファイルから読み直すので、親で書き換えた設定（テストなど）なら使わない
    fresh = SchoolAwarePlayerAbilityGenerator(generator.config_dir)
    return (fresh.params == generator.params
            and fresh.base_generator.params == generator.base_generator.params
            and PlayerGrowth().config == book.growth.config)


def build_states(book, year: int, jobs) -> tuple[list[list], int]:
    """``jobs`` は (学校, 名簿, 新入部員) の並び。学校ごとの新入部員の状態（同じ順）と、
    使ったプロセスの数を返す。"""
    from .roster_book import _with_cohorts

    pairs = [_with_cohorts(newcomers) for _, _, newcomers in jobs]
    workers = worker_count(len(jobs), getattr(book, "parallel_workers", None))
    if workers > 1 and _parallel_ready(book):
        intake = book.ability_generator.intake_model
        profiles = {}

        def profile(player):
            key = (player.school_id, player.entry_year)
            if key not in profiles:
                profiles[key] = intake.profile(school_id=player.school_id,
                                               entry_year=player.entry_year,
                                               base_seed=book.career_seed)
            return profiles[key]

        tasks = [(year, [(player, tuple(cohort), profile(player)) for player, cohort in school])
                 for school in pairs]
        try:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=workers, mp_context=context, initializer=_init,
                initargs=(str(book.ability_generator.config_dir), book.first_year, book.career_seed),
            ) as pool:
                chunk = max(1, len(tasks) // (workers * 8))
                return list(pool.map(_school, tasks, chunksize=chunk)), workers
        except (OSError, RuntimeError, ImportError, EOFError, AttributeError) as error:
            # プロセスを起こせない環境（凍結された実行ファイルの設定違いなど）は1プロセスで。
            # 起こしている途中のプロセスの中（種を並べて進める balance_report の子のプロセスなど）
            # では子のプロセスを起こせない。そのときは警告を出さない（結果は同じ）
            if not _starting_up(error):
                print(f"名簿づくりを1プロセスに戻しました: {error!r}", file=sys.stderr or sys.__stderr__)
    return [[book._new_state(player, year, cohort) for player, cohort in school]
            for school in pairs], 1
