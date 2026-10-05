from __future__ import annotations

import hashlib
import random
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
