"""記録の画面（大会別ベスト8・複数年度の出場校）の絞り込みと表の行。

季節→大会区分→地域→都道府県→大会名の順に連動させ、選べるものだけを返す。
並び順は配列で返す（JavaScript のオブジェクトは「10」〜「47」を「01」〜「09」より先に並べるため）。
"""
from __future__ import annotations

import re

SEGMENTS = ("spring", "summer", "autumn")
LEVELS = (("national", "全国"), ("regional", "地区"), ("local", "都道府県"))
UNKNOWN_AXIS = "unknown"


def build_catalog(competitions: dict, memberships: list[dict], level_of, name_of) -> list[dict]:
    """大会ごとの季節・区分・地域・出られる都道府県。

    ``prefectures`` は、都道府県の大会ならその都道府県、地区大会なら地区の都道府県（季節ごとの地区割り）、
    全国大会は空（都道府県では絞らない）。"""
    # 1つの都道府県から2つに分かれる大会（夏の北北海道・南北海道・東東京・西東京の地方大会）
    qualifiers: dict[str, int] = {}
    for c in competitions.values():
        if c.get("competition_type") == "summer_local_qualifier" and c.get("qualifying_area_id"):
            qualifiers[c.get("prefecture_code", "")] = qualifiers.get(c.get("prefecture_code", ""), 0) + 1
    catalog = []
    for cid, c in competitions.items():
        pref = c.get("prefecture_code", "")
        segment = c.get("season_segment", "")
        level = level_of(c)
        if c.get("region_id"):
            regions = [c["region_id"]]
            prefectures = sorted({r["prefecture_code"] for r in memberships
                                  if r["region_id"] == c["region_id"] and r["season_segment"] == segment})
        else:
            regions = sorted({r["region_id"] for r in memberships
                              if r["prefecture_code"] == pref and r["season_segment"] == segment})
            # 夏は春・秋で共通の地域区分を候補に使う（東京は両方から選べる）。
            if pref and not regions:
                regions = sorted({r["region_id"] for r in memberships if r["prefecture_code"] == pref})
            prefectures = [pref] if pref else []
        catalog.append({"competition_id": cid, "name": name_of(cid, c.get("competition_name", cid)),
                        "segment": segment, "level": level, "prefecture": pref,
                        "area": c.get("qualifying_area_id", ""),
                        "split": c.get("competition_type") == "summer_local_qualifier"
                        and bool(c.get("qualifying_area_id")) and qualifiers.get(pref, 0) > 1,
                        "regions": regions, "prefectures": prefectures})
    return catalog


def cascade_filters(catalog: list[dict], filters: dict, region_names: dict,
                    prefecture_names: dict) -> tuple[dict, dict, list[dict]]:
    """選べない値は外し（すべてに戻す）、各欄の選択肢と絞り込んだ大会を返す。

    戻り値は（直した条件, 欄ごとの選択肢と使えない欄, 選べる大会）。大会は必ず1つ以上になる。"""
    f = dict(filters)
    if f.get("segment") not in SEGMENTS:
        f["segment"] = ""
    pool = [c for c in catalog if not f["segment"] or c["segment"] == f["segment"]]
    levels = [(key, label) for key, label in LEVELS if any(c["level"] == key for c in pool)]
    if f.get("level") not in {key for key, _ in levels}:
        f["level"] = ""
    pool = [c for c in pool if not f["level"] or c["level"] == f["level"]]
    # 全国大会は地域・都道府県で絞らない
    national = f["level"] == "national"
    regions = [] if national else sorted({r for c in pool for r in c["regions"]})
    if f.get("region") not in regions:
        f["region"] = ""
    # 地図ではマスを押すと地域を外して都道府県を選ぶので、地域で絞る前の都道府県を選べる
    map_prefectures = [] if national else sorted({p for c in pool for p in c["prefectures"]})
    # 地域ごとの都道府県（いまの季節・区分の地区割り。春の関東には東京が入る）。地図で地域を選んだときに
    # 金色にするマス。地図の色分け（秋の地区）とは別
    region_prefectures = {} if national else {
        r: sorted({p for c in pool if r in c["regions"] for p in c["prefectures"]})
        for r in sorted({r for c in pool for r in c["regions"]})}
    pool = [c for c in pool if not f["region"] or f["region"] in c["regions"]]
    prefectures = [] if national else sorted({p for c in pool for p in c["prefectures"]})
    if f.get("prefecture") not in prefectures:
        f["prefecture"] = ""
    pool = [c for c in pool if not f["prefecture"] or f["prefecture"] in c["prefectures"]]
    if f.get("competition_id") not in {c["competition_id"] for c in pool}:
        f["competition_id"] = pool[0]["competition_id"] if pool else ""
    options = {
        "map_area": map_area(catalog, f),
        "level": [list(item) for item in levels],
        "region": [[r, region_names.get(r, r)] for r in regions],
        "prefecture": [[p, prefecture_names.get(p, p)] for p in prefectures],
        "map_prefecture": map_prefectures,
        "region_prefectures": region_prefectures,
        "disabled": {"region": not regions, "prefecture": not prefectures},
    }
    return f, options, pool


def map_area(catalog: list[dict], filters: dict) -> str:
    """地図で片方のマスだけを選んだ色にするときの区分。選んでいる大会が2つに分かれる地方大会で、
    都道府県もそれを選んでいるときだけ（ほかは空＝都道府県の2マスとも）。"""
    entry = next((c for c in catalog if c["competition_id"] == filters.get("competition_id")), None)
    if entry and entry.get("split") and filters.get("prefecture") == entry["prefecture"]:
        return entry["area"]
    return ""


def map_pick(catalog: list[dict], filters: dict, prefecture: str, area: str = "") -> dict:
    """地図のマスを押したときの絞り込み（地域は外して都道府県を選ぶ）。

    2つに分かれる大会を見ているとき（季節が夏か、選んでいる大会が分かれた地方大会）は、押したマスの
    区分の大会を選ぶ。分かれない大会（春・秋の北海道・東京の大会、選抜など）は都道府県全体。"""
    f = {**filters, "region": "", "prefecture": prefecture}
    current = next((c for c in catalog if c["competition_id"] == filters.get("competition_id")), None)
    split = filters.get("segment") == "summer" or bool(current and current.get("split"))
    if split and area:
        entry = next((c for c in catalog if c.get("split") and c.get("area") == area), None)
        if entry:
            f["competition_id"] = entry["competition_id"]
    return f


def entrant_axes(entry: dict | None, level: str, summer: bool, summer_areas: list,
                 prefecture_names: dict) -> list[list[str]]:
    """複数年度の出場校の表の行：夏の甲子園は代表地区、地区大会はその地区の都道府県、
    ほかの全国大会は47都道府県（コード順）。"""
    if summer:
        return [list(area) for area in summer_areas]
    if level == "regional" and entry is not None:
        return [[p, prefecture_names.get(p, p)] for p in entry["prefectures"]]
    return [[code, name] for code, name in sorted(prefecture_names.items())]


def entrant_axis(entrant: dict, summer: bool, axis_ids) -> str:
    """出場校をどの行に置くか（夏は進出元の地方大会、ほかは進出元か所属の都道府県）。"""
    if summer:
        axis = next((r["competition_id"] for r in entrant.get("routes", ())
                     if r["competition_id"] in axis_ids), "")
    else:
        axis = next((r["prefecture_code"] for r in entrant.get("routes", ()) if r.get("prefecture_code")),
                    "") or entrant.get("prefecture_code", "")
    return axis if axis in axis_ids else UNKNOWN_AXIS


def place_entrants(rows: list[dict], axes: list[list[str]], summer: bool,
                   only_entered: bool) -> list[list[str]]:
    """各出場校に行（``axis``）を付け、表に出す行を返す。

    出られる都道府県（代表地区）の行だけを並べ、どこにも置けない学校は「所属・進出元未確認」の行に。
    ``only_entered`` なら出場校のあった行だけ。"""
    ids = {axis_id for axis_id, _ in axes}
    used = set()
    for row in rows:
        for entrant in row.get("entrants", ()):
            entrant["axis"] = entrant_axis(entrant, summer, ids)
            used.add(entrant["axis"])
    shown = [axis for axis in axes if not only_entered or axis[0] in used]
    if UNKNOWN_AXIS in used:
        shown.append([UNKNOWN_AXIS, "所属・進出元未確認"])
    return shown


def best8_years(records, stored: dict | None = None) -> dict[str, set[int]]:
    """学校ID → その大会でベスト8以上になった年度。``records`` は ``best8_record`` の形の行
    （進行中の年度）、``stored`` は閉じた年度の分（``competition_best8_years``）。"""
    out: dict[str, set[int]] = {school_id: set(years) for school_id, years in (stored or {}).items()}
    for record in records:
        for schools in record.get("groups", {}).values():
            for school in schools:
                out.setdefault(school["school_id"], set()).add(int(record["school_year"]))
    return out


def best8_label(years, school_year: int) -> str:
    """「8強以上3回目」：その年度を含めて、ベスト8以上になった回数（ゲーム開始後だけ）。"""
    count = sum(1 for year in years if year <= school_year)
    return f"8強以上{count}回目" if count else ""


def edition(name: str) -> str:
    """大会名の回数（「第109回」）。回数のない大会は空。"""
    match = re.search(r"第[0-9０-９]+回", name or "")
    return match.group(0) if match else ""


def empty_hint(*, rows: int, hidden_upcoming: int, before_start: dict | None, earliest: int,
               axes: int | None = None, only_entered: bool = False) -> str:
    """表に何も出ないとき、どの条件を外せば出るかを1行で。出るものがあれば空。"""
    if rows:
        if axes == 0 and only_entered:
            return "出場校のあった都道府県がまだありません。「出場のあった都道府県だけ」を外すと行が出ます。"
        return ""
    if hidden_upcoming:
        return "この範囲はまだ行われていない年度だけです。「未開催の年度も出す」を入れると出ます。"
    if before_start:
        return f"ゲーム開始前の年度だけです。開始年度を{earliest}年度以降にすると出ます。"
    return "条件に合う大会がありません。季節・大会区分を「すべて」にすると出ます。"


def split_areas(config: dict, areas: list[dict]) -> dict[str, dict]:
    """2マスに分ける都道府県の区分（夏の代表区分）。マスのID（``area_code``）→
    {"prefecture", "area_id", "name"}。``areas`` は ``competition_areas.csv`` の行。"""
    schemes = {scheme: code for code, scheme in config.get("split_schemes", {}).items()}
    out = {}
    for row in sorted(areas, key=lambda r: (r["scheme_id"], int(r.get("sort_order") or 0))):
        code = schemes.get(row["scheme_id"])
        if code:
            out[row["area_code"]] = {"prefecture": code, "area_id": row["area_id"],
                                     "name": row["display_name"] or row["area_name"]}
    return out


def tile_map(config: dict, memberships: list[dict], region_names: dict, prefecture_names: dict,
             areas: list[dict] = ()) -> dict:
    """タイル地図のマス（都道府県コード順。分けた都道府県は区分の順）と地域（地区のID順）。

    北海道・東京は夏の代表区分（``config["split_schemes"]``）で2マスずつに分ける。マスの
    ``code`` はマスのID（分けたマスは区分の ``area_code``、ほかは都道府県コード）、``prefecture``
    はその都道府県コード、``area_id`` は分けたマスの区分（ほかは空）。
    地域は ``config["region_segment"]``（秋）の地区割り。県名は「都・府・県」を除く（北海道はそのまま）。"""
    segment = config.get("region_segment", "autumn")
    region_of = {r["prefecture_code"]: r["region_id"] for r in memberships if r["season_segment"] == segment}
    splits = split_areas(config, list(areas))
    order = {code: i for i, code in enumerate(splits)}
    tiles = []
    for code, (col, row) in config["tiles"].items():
        split = splits.get(code)
        pref = split["prefecture"] if split else code
        name = split["name"] if split else prefecture_names.get(code, code)
        tiles.append({"code": code, "prefecture": pref, "area_id": split["area_id"] if split else "",
                      "name": name if split else (name[:-1] if name.endswith(("都", "府", "県")) else name),
                      "full_name": name, "col": int(col), "row": int(row),
                      "region_id": region_of.get(pref, "")})
    tiles.sort(key=lambda t: (t["prefecture"], order.get(t["code"], 0)))
    regions = [{"region_id": r, "name": region_names.get(r, r)} for r in sorted(set(region_of.values()))]
    return {"tiles": tiles, "regions": regions,
            # 都道府県の一覧（分けたマスをまとめた47）
            "prefectures": [[code, prefecture_names.get(code, code)] for code in sorted({t["prefecture"] for t in tiles})],
            "cols": max(t["col"] for t in tiles) + 1, "rows": max(t["row"] for t in tiles) + 1}
