from __future__ import annotations

import hashlib
import random
from statistics import NormalDist
from typing import Iterable, List, TypeVar

T = TypeVar("T")


def namespaced_seed(base_seed: int, namespace: str) -> int:
    payload = f"{base_seed}:{namespace}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def rng_for(base_seed: int, namespace: str) -> random.Random:
    return random.Random(namespaced_seed(base_seed, namespace))


def shuffled(items: Iterable[T], base_seed: int, namespace: str) -> List[T]:
    out = list(items)
    rng_for(base_seed, namespace).shuffle(out)
    return out


def uniform_for(base_seed: int, namespace: str) -> float:
    """1回だけ引く 0以上1未満の値。乱数の生成器をつくらず、種と名前空間のハッシュから出す。"""
    return namespaced_seed(base_seed, namespace) / 2.0 ** 64


def gauss_for(base_seed: int, namespace: str, mu: float, sigma: float) -> float:
    """1回だけ引く正規分布の値（``uniform_for`` を逆関数で変換する）。"""
    u = (namespaced_seed(base_seed, namespace) + 0.5) / 2.0 ** 64
    return _NORMAL.inv_cdf(u) * sigma + mu


_NORMAL = NormalDist()
