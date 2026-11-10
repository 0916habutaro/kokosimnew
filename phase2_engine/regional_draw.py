"""地区大会の開催県・出場枠と組み合わせの決まり（game_definition.md §8「地区大会の開催県と組み合わせ」）。

データ（全国共通の仕組み。地区ごとの違いはデータの値だけ）
- ``regional_hosts.csv``：地区大会ごとの開催県の順番（``rotation``。先頭が2026年の実際の開催県）と、
  開催県・次の開催県の追加枠（``host_bonus``・``next_host_bonus``）。2027年以降は順番どおり
  毎年1つずつ進み、最後の次は先頭に戻る（**ゲームの仮の決まり。実際の開催県ではない**）。
  春・秋は別の行。2026年の次の開催県は実際の値（``next_host_2026``）、2027年以降は順番の次
- ``regional_feeder_rules.csv`` の都道府県の枠は開催県でないときの枠。開催県（と次の開催県）は
  その年の追加枠を足す（``apply_host_quotas``）
- ``regional_draw_rules.csv``：組み合わせの決まり

  - ``bye_order``：1回戦免除を先に付ける学校の種類（``;`` 区切りの順。残りは抽選）
  - ``same_prefecture_round``：同じ県の学校が早くても当たる回戦（``QF``・``SF``・``F``・``R2``。空＝決まりなし）
  - ``rank12_round``：同じ県の1位と2位が早くても当たる回戦
  - ``opening_pairs``：1回戦（両方が1回戦から出る試合）は、この組み合わせ（``a-b`` を ``;`` 区切り）だけ
  - ``first_game_forbid``：お互いの初戦で当てない組み合わせ（両方とも初戦の試合。1回戦免除どうしの2回戦も含む）

  学校の種類：``rank1``・``rank2``…（県大会の順位の順に、その県から出る学校の何番目か。選抜の推薦校は
  数えない）、``host``・``nonhost``（開催県かどうか）、``host_rank1``…、``invited``（選抜の推薦校）

組み合わせは、1回戦免除の位置を標準のシード位置に置いてから、決まりを満たすように抽選で埋める
（同じ年度・地区・学校・乱数の種なら同じ組み合わせ）。決まりを満たす組み合わせがないときは、
1回戦の組み合わせ → 初戦で当てない組み合わせ → 同じ県を分ける回戦の順にゆるめる（``relaxed``）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .main_tournament import next_power_of_two, standard_seed_order
from .national_day_plan import round_number
from .randomness import rng_for
from .season_catalog import TEMPLATE_YEAR

HOSTS_FILE = "regional_hosts.csv"
DRAW_RULES_FILE = "regional_draw_rules.csv"
MAX_NODES = 3000   # 1回の探索で試す数（超えたら1回戦免除の学校から引き直す）
ATTEMPTS = 40      # 決まりをゆるめる前に引き直す回数


# ---- 開催県と出場枠 ----

def host_of(row: Mapping[str, str], year: int) -> str:
    """その年度の開催県（2026年は実際の開催県、2027年以降は順番どおり）。"""
    rotation = [code for code in row.get("rotation", "").split(";") if code]
    if not rotation:
        return row.get("host_2026", "")
    if year <= TEMPLATE_YEAR:
        return row.get("host_2026") or rotation[0]
    return rotation[(year - TEMPLATE_YEAR) % len(rotation)]


def next_host_of(row: Mapping[str, str], year: int) -> str:
    """次の年度の開催県（春季東北の次の開催県の枠）。2026年は実際の値。"""
    if year <= TEMPLATE_YEAR and row.get("next_host_2026"):
        return row["next_host_2026"]
    return host_of(row, year + 1)


def host_bonus(row: Mapping[str, str] | None, prefecture: str, year: int) -> int:
    if not row:
        return 0
    bonus = 0
    if prefecture == host_of(row, year):
        bonus += int(row.get("host_bonus") or 0)
    if int(row.get("next_host_bonus") or 0) and prefecture == next_host_of(row, year):
        bonus += int(row["next_host_bonus"])
    return bonus


def apply_host_quotas(rules: Iterable[Mapping[str, str]], host_row: Mapping[str, str] | None,
                      year: int) -> list[dict]:
    """都道府県の枠（開催県でないときの枠）に、その年の開催県の追加枠を足す。"""
    out = []
    for rule in rules:
        rule = dict(rule)
        if (rule.get("source_type") == "prefectural_result"
                and rule.get("qualification_mode", "direct") == "direct"):
            bonus = host_bonus(host_row, rule.get("source_prefecture_code", ""), year)
            if bonus:
                rule["quota"] = str(int(rule.get("quota") or 0) + bonus)
                rule["rank_to"] = str(int(rule.get("rank_to") or rule.get("rank_from") or 1) + bonus)
        out.append(rule)
    return out


# ---- 学校の種類 ----

def entrant_classes(
    entrants: Sequence[str],
    prefecture_of: Mapping[str, str],
    rankings: Mapping[str, Sequence[str]],
    *,
    host: str = "",
    invited: Iterable[str] = (),
) -> dict[str, set[str]]:
    """学校 → 種類。``rankings`` は都道府県 → 県大会の順位の並び。"""
    invited = set(invited)
    entrant_set = set(entrants)
    rank: dict[str, int] = {}
    for prefecture, ranking in rankings.items():
        regular = [s for s in ranking if s in entrant_set and s not in invited
                   and prefecture_of.get(s, prefecture) == prefecture]
        for index, school_id in enumerate(dict.fromkeys(regular), start=1):
            rank.setdefault(school_id, index)
    out: dict[str, set[str]] = {}
    for school_id in entrants:
        classes = {"host" if host and prefecture_of.get(school_id) == host else "nonhost"}
        if school_id in invited:
            classes.add("invited")
        elif school_id in rank:
            classes.add(f"rank{rank[school_id]}")
            if "host" in classes:
                classes.add(f"host_rank{rank[school_id]}")
        out[school_id] = classes
    return out


def _pairs(text: str) -> list[tuple[str, str]]:
    out = []
    for item in [x.strip() for x in (text or "").split(";") if x.strip()]:
        a, _, b = item.partition("-")
        out.append((a, b))
    return out


def _matches(pairs, a: set[str], b: set[str]) -> bool:
    return any((x in a and y in b) or (x in b and y in a) for x, y in pairs)


# ---- 組み合わせ ----

def meet_round(slot_a: int, slot_b: int) -> int:
    """組み合わせ表の位置（0から）の2校が勝ち続けたときに当たる回戦。"""
    return (slot_a ^ slot_b).bit_length()


def first_game_pairs(slots: Sequence[str]) -> list[tuple[str, str]]:
    """お互いの初戦になる試合（1回戦と、1回戦免除どうしの2回戦）。"""
    out = []
    for i in range(0, len(slots), 2):
        if slots[i] and slots[i + 1]:
            out.append((slots[i], slots[i + 1]))
    for i in range(0, len(slots), 4):
        left = [s for s in slots[i:i + 2] if s]
        right = [s for s in slots[i + 2:i + 4] if s]
        if len(left) == 1 and len(right) == 1 and len(slots) >= 4:
            out.append((left[0], right[0]))
    return out


@dataclass
class DrawRule:
    bye_order: tuple[str, ...] = ()
    same_prefecture_round: str = ""
    rank12_round: str = ""
    opening_pairs: tuple[tuple[str, str], ...] = ()
    first_game_forbid: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_row(cls, row: Mapping[str, str]) -> "DrawRule":
        return cls(
            bye_order=tuple(x for x in (row.get("bye_order") or "").split(";") if x),
            same_prefecture_round=row.get("same_prefecture_round", ""),
            rank12_round=row.get("rank12_round", ""),
            opening_pairs=tuple(_pairs(row.get("opening_pairs", ""))),
            first_game_forbid=tuple(_pairs(row.get("first_game_forbid", ""))),
        )


def _bye_recipients(entrants, classes, order, count, rng) -> list[str]:
    chosen: list[str] = []
    for kind in order:
        group = sorted(s for s in entrants if kind in classes[s] and s not in chosen)
        rng.shuffle(group)
        chosen += group[:count - len(chosen)]
        if len(chosen) >= count:
            return chosen
    rest = sorted(s for s in entrants if s not in chosen)
    rng.shuffle(rest)
    return chosen + rest[:count - len(chosen)]


def draw_slots(
    entrants: Sequence[str],
    classes: Mapping[str, set[str]],
    prefecture_of: Mapping[str, str],
    rule: DrawRule,
    *,
    base_seed: int,
    namespace: str,
) -> tuple[list[str], int]:
    """組み合わせ表（2のべき乗の枠。空は1回戦免除）と、ゆるめた段階（0＝全部の決まりどおり）。"""
    entrants = list(dict.fromkeys(entrants))
    size = max(2, next_power_of_two(len(entrants)))
    total = size.bit_length() - 1
    rng = rng_for(base_seed, f"{namespace}:regional_draw")
    byes = size - len(entrants)
    seed_no = standard_seed_order(size)
    bye_slots = {i for i, no in enumerate(seed_no) if no <= byes}
    empty = {i ^ 1 for i in bye_slots}

    def rounds(code: str) -> int:
        return max(1, round_number(code, total)) if code else 1

    same = rounds(rule.same_prefecture_round)
    rank12 = rounds(rule.rank12_round)
    levels = [(rule.opening_pairs, rule.first_game_forbid, same, rank12)]
    levels.append(((), rule.first_game_forbid, same, rank12))
    levels.append(((), (), same, rank12))
    while same > 1 or rank12 > 1:
        same, rank12 = max(1, same - 1), max(1, rank12 - 1)
        levels.append(((), (), same, rank12))
    for relaxed, level in enumerate(levels):
        for _ in range(ATTEMPTS):
            # 1回戦免除の学校も引き直す（同じ順位の中の誰が免除になるかで組めないことがある）
            recipients = _bye_recipients(entrants, classes, rule.bye_order, byes, rng)
            others = [s for s in entrants if s not in set(recipients)]
            slots = _search(size, bye_slots, empty, recipients, others, classes, prefecture_of,
                            level, rng)
            if slots is not None:
                return slots, relaxed
    raise AssertionError("regional draw found no bracket")


def _search(size, bye_slots, empty, recipients, others, classes, prefecture_of, level, rng):
    opening, forbid, same, rank12 = level
    slots = [""] * size
    order = [i for i in range(size) if i not in empty]
    pools = {True: sorted(recipients), False: sorted(others)}
    for pool in pools.values():
        rng.shuffle(pool)
    nodes = 0

    def rank_of(school_id):
        return next((c for c in classes[school_id] if c in ("rank1", "rank2")), "")

    def fits(index: int, school_id: str) -> bool:
        mine = classes[school_id]
        pref = prefecture_of.get(school_id, school_id)
        for other_index, other in enumerate(slots):
            if not other or other_index == index:
                continue
            if prefecture_of.get(other, other) == pref:
                meet = meet_round(index, other_index)
                if meet < same:
                    return False
                if {rank_of(school_id), rank_of(other)} == {"rank1", "rank2"} and meet < rank12:
                    return False
        partner = index ^ 1
        if slots[partner]:
            theirs = classes[slots[partner]]
            if opening and not _matches(opening, mine, theirs):
                return False
            if forbid and _matches(forbid, mine, theirs):
                return False
        elif partner in empty and size >= 4:
            # 1回戦免除どうしの2回戦（お互いの初戦）
            block = index & ~3
            across = [i for i in range(block, block + 4) if i // 2 != index // 2]
            if all(i in empty or i in bye_slots for i in across):
                rival = next((slots[i] for i in across if slots[i]), "")
                if rival and forbid and _matches(forbid, mine, classes[rival]):
                    return False
        return True

    def place(position: int) -> bool:
        nonlocal nodes
        if position == len(order):
            return True
        nodes += 1
        if nodes > MAX_NODES:
            return False
        index = order[position]
        pool = pools[index in bye_slots]
        for school_id in list(pool):
            if fits(index, school_id):
                slots[index] = school_id
                pool.remove(school_id)
                if place(position + 1):
                    return True
                pool.append(school_id)
                slots[index] = ""
        return False

    return list(slots) if place(0) else None


def draw_report(slots: Sequence[str], classes: Mapping[str, set[str]],
                prefecture_of: Mapping[str, str]) -> dict:
    """組み合わせの数：同じ県どうし・県1位どうしの初戦、1回戦免除の校数。"""
    pairs = first_game_pairs(slots)
    byes = sum(1 for i in range(0, len(slots), 2) if bool(slots[i]) != bool(slots[i + 1]))
    return {
        "same_prefecture_first_games": sum(
            1 for a, b in pairs if prefecture_of.get(a, a) == prefecture_of.get(b, b)),
        "rank1_first_games": sum(
            1 for a, b in pairs if "rank1" in classes.get(a, ()) and "rank1" in classes.get(b, ())),
        "byes": byes,
    }
