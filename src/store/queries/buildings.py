"""建物単位の検索・組立 (docs/building-aggregation-design.md §6).

検索の意味論: 部屋条件(required_features / max_walk / max_monthly / 眣 / 面積 等)は
「条件を満たす部屋を 1 つ以上持つ建物」をヒットさせる。判定そのものは
search.py の部屋スコープ WHERE(_search_where + required EXISTS 前段)を
そのまま再利用し、結果を building_id で束ねる(順序 (b) の読み替えどおり)。

units 配列の載せ方(§6.1):
- ``units="all"``      GeoJSON(FE)向け。建物の可視部屋全て(worker が再フィルタ)
- ``units="matching"`` MCP 向け。絞り込み条件+可視性を通過した部屋のみ

建物の並び順は建物キャッシュ列(is_active / min_daily_rent_yen)で Python 側
ソートする(件数は ~4k・SQLite の変数上限に IN 句を依存させない)。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from domain.feature_categories import FEATURE_CATEGORIES
from domain.feature_resolution import satisfiable_codes_from_categories
from store.embeddings import EMBEDDING_MODEL, embed_query_cached, vector_literal
from store.pg import open_connection
from store.queries._common import (
    _CHILD_IN_CHUNK,
    _FEATURES_CHILD_SQL,
    _fetch_child_rows_by_property,
    _property_list_sql,
    _property_row_to_result,
    _repo,
    fetch_standard_child_maps,
    iso_jsonable,
)
from store.queries.search import (
    _MIN_WALK_FILTER,
    _required_feature_clauses,
    _resolve_required_features,
    _search_where,
)

# 辞書の sub='building' 語彙(建物レベル feature 導出のフィルタ・設計 §3-4)
_BUILDING_SUB_CODES: frozenset[str] = frozenset(
    c.code for c in FEATURE_CATEGORIES if getattr(c, "sub", None) == "building"
)

_ROOM_ORDER_BY = (
    "ORDER BY p.is_active DESC, p.catalog_rent_per_day_yen IS NULL, "
    "p.catalog_rent_per_day_yen ASC, p.id ASC"
)


def _building_sort_key(b: dict[str, Any]) -> tuple:
    rent = b.get("min_daily_rent_yen")
    return (
        0 if b.get("is_active") else 1,
        rent is None,
        rent if rent is not None else 0,
        b["id"],
    )


def _matching_room_ids(conn, params: dict[str, Any]) -> list[int]:
    """部屋スコープの条件を通過した部屋 id(可視性込み・§6.1 の判定の正本)。"""
    requirements = _resolve_required_features(params)
    max_walk = params.get("max_walk_minutes")
    max_monthly = params.get("max_monthly_total_yen")

    clauses, qparams = _search_where(params)
    clauses.extend(_required_feature_clauses(requirements, qparams))
    clauses.append("p.building_id IS NOT NULL")

    base_from = (
        "FROM properties p "
        "LEFT JOIN property_shortlists s ON s.property_id = p.id "
        f"WHERE {' AND '.join(clauses)}"
    )
    if max_walk is not None:
        sql = (
            "SELECT id FROM (SELECT p.id,"
            " (SELECT MIN(walk_minutes) FROM property_accesses"
            " WHERE property_id = p.id AND walk_minutes IS NOT NULL) as min_walk"
            f" {base_from}) WHERE {_MIN_WALK_FILTER}"
        )
        qparams = [*qparams, max_walk]
    else:
        sql = f"SELECT p.id {base_from}"
    ids = [int(r["id"]) for r in conn.execute(sql, qparams)]

    if max_monthly is not None:
        # 実効値は Python 集計のため、該当部屋だけ組立して min_plan_total で絞る
        # (search.py の post filter と同一の意味論)
        kept: list[int] = []
        assembled, _ = _assemble_rooms(conn, ids)
        for pid in ids:
            total = assembled[pid].get("min_plan_total") if pid in assembled else None
            if total is not None and total <= max_monthly:
                kept.append(pid)
        ids = kept
    return ids


def _semantic_room_distances(
    conn, room_ids: list[int], query_vec: list[float]
) -> dict[int, float]:
    """部屋 id → embedding コサイン距離(model 一致のみ・未カバーは不在)。

    HNSW 不採用(計画の設計判断): 8k 行規模は seq scan 距離計算で数十 ms・
    recall 100%。チャンク分割 IN は _room_building_map と同パターン。
    """
    out: dict[int, float] = {}
    for start in range(0, len(room_ids), _CHILD_IN_CHUNK):
        chunk = room_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        for row in conn.execute(
            "SELECT property_id, embedding <=> %s AS dist"
            " FROM property_embeddings"
            f" WHERE property_id IN ({ph}) AND model = %s",
            [vector_literal(query_vec), *chunk, EMBEDDING_MODEL],
        ):
            out[int(row["property_id"])] = float(row["dist"])
    return out


def _room_building_map(conn, room_ids: list[int]) -> dict[int, int]:
    """部屋 id → building_id を chunked IN で取得(変数上限に依存しない)。"""
    out: dict[int, int] = {}
    for start in range(0, len(room_ids), _CHILD_IN_CHUNK):
        chunk = room_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        for row in conn.execute(
            f"SELECT id, building_id FROM properties WHERE id IN ({ph})", chunk
        ):
            out[int(row["id"])] = int(row["building_id"])
    return out


def _assemble_rooms(
    conn, room_ids: list[int]
) -> tuple[dict[int, dict[str, Any]], dict[int, list[str]]]:
    """部屋 id 列 → (組み立て済み物件 dict, feature category 列)。検索と同一構成。"""
    results: dict[int, dict[str, Any]] = {}
    categories: dict[int, list[str]] = {}
    for start in range(0, len(room_ids), _CHILD_IN_CHUNK):
        chunk = room_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        rows = [
            dict(r)
            for r in conn.execute(
                _property_list_sql(f"WHERE p.id IN ({ph}) {_ROOM_ORDER_BY}"), chunk
            )
        ]
        maps = fetch_standard_child_maps(conn, chunk)
        feature_map = _fetch_child_rows_by_property(conn, _FEATURES_CHILD_SQL, chunk)
        for row in rows:
            pid = row["id"]
            results[pid] = _property_row_to_result(
                row,
                maps.access.get(pid, []),
                maps.image.get(pid, []),
                maps.plan.get(pid, []),
                maps.campaign.get(pid, []),
            )
            results[pid]["feature_categories"] = satisfiable_codes_from_categories(
                [r["category"] for r in feature_map.get(pid, [])]
            )
            # 設備名要約(重複語除去済み・設計 §6.1 の「部屋単位 PropertyProperties
            # 一式」準拠。B2-α で FE が '' 固定退避していた設備表示の復旧)
            results[pid]["feature_summary"] = ", ".join(
                dict.fromkeys(
                    r["feature_name"] for r in feature_map.get(pid, [])
                )
            )
            categories[pid] = [r["category"] for r in feature_map.get(pid, [])]
    return results, categories


def _visible_room_ids_of_buildings(
    conn, building_ids: list[int]
) -> dict[int, list[int]]:
    """建物ごとの可視部屋 id(可視性は _search_where と同一規則・§8)。"""
    out: dict[int, list[int]] = {}
    for start in range(0, len(building_ids), _CHILD_IN_CHUNK):
        chunk = building_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        sql = _property_list_sql(
            f"WHERE p.building_id IN ({ph}) "
            "AND (p.is_active OR s.status IN ('saved', 'hide', 'reject')) "
            f"{_ROOM_ORDER_BY}"
        )
        for row in conn.execute(sql, chunk):
            out.setdefault(int(row["building_id"]), []).append(int(row["id"]))
    return out


def _campaign_active(cam: dict[str, Any], today: str) -> bool:
    starts = cam.get("starts_on")
    ends = cam.get("ends_on")
    if starts and str(starts) > today:
        return False
    if ends and str(ends) < today:
        return False
    return True


def _building_shortlist_map(
    conn, building_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """建物 id → ショートリスト行 (status/comment/updated_at・未登録は不在)."""
    out: dict[int, dict[str, Any]] = {}
    for start in range(0, len(building_ids), _CHILD_IN_CHUNK):
        chunk = building_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        for row in conn.execute(
            f"SELECT building_id, status, comment, updated_at FROM building_shortlists"
            f" WHERE building_id IN ({ph})",
            chunk,
        ):
            out[int(row["building_id"])] = dict(row)
    return out


def _saved_room_building_ids(conn, room_ids: list[int]) -> set[int]:
    """部屋 id 列のうち saved 部屋の building_id 集合(saved_only 建物判定用)."""
    out: set[int] = set()
    for start in range(0, len(room_ids), _CHILD_IN_CHUNK):
        chunk = room_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        for row in conn.execute(
            f"SELECT DISTINCT p.building_id AS bid FROM properties p"
            f" JOIN property_shortlists s ON s.property_id = p.id"
            f" WHERE p.id IN ({ph}) AND s.status = 'saved'",
            chunk,
        ):
            if row["bid"] is not None:
                out.add(int(row["bid"]))
    return out


def _building_dict(
    building: dict[str, Any],
    names: list[dict[str, Any]],
    unit_results: list[dict[str, Any]],
    unit_categories: dict[int, list[str]],
    shortlist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """buildings 行 + units から配信 dict を組む(§6.1 の契約・§7 の代表値)。"""
    access_seen: list[str] = []
    source_sites: list[str] = []
    lat = building.get("lat")
    lng = building.get("lng")
    min_daily = None
    max_daily = None
    min_total = None
    min_label = None
    min_walk = None
    thumbnail = None
    has_campaign = False
    today = date.today().isoformat()
    building_codes: set[str] = set()

    for unit in unit_results:
        site = unit.get("source_site")
        if site and site not in source_sites:
            source_sites.append(site)
        if lat is None and unit.get("lat") is not None:
            lat, lng = unit["lat"], unit["lng"]
        for a in unit.get("access_summary") or []:
            if a not in access_seen:
                access_seen.append(a)
        d = unit.get("min_daily_rent")
        if d is not None:
            min_daily = d if min_daily is None else min(min_daily, d)
            max_daily = d if max_daily is None else max(max_daily, d)
        w = unit.get("min_walk_minutes")
        if w is not None and (min_walk is None or w < min_walk):
            min_walk = w
        if thumbnail is None and unit.get("thumbnail_url"):
            thumbnail = unit["thumbnail_url"]
        if not has_campaign:
            for cam in unit.get("campaigns") or []:
                if _campaign_active(cam, today):
                    has_campaign = True
                    break
        for code in unit_categories.get(unit["id"], []):
            if code in _BUILDING_SUB_CODES:
                building_codes.add(code)

    # 最安部屋の総額/ラベル(§7: 現行 min 計算式と同一の部屋から)
    for unit in unit_results:
        if min_daily is not None and unit.get("min_daily_rent") == min_daily:
            min_total = unit.get("min_plan_total")
            min_label = unit.get("min_plan_label")
            break

    station_list = []
    for a in access_seen:
        parts = str(a).split(" ")
        if len(parts) > 1:
            station_list.append(parts[1])

    return {
        "id": building["id"],
        "kind": "building",
        "name": building.get("canonical_name"),
        "address": building.get("address"),
        "prefecture_slug": building.get("prefecture_slug"),
        "prefecture_name": building.get("prefecture_name"),
        "municipality": building.get("municipality"),
        "lat": lat,
        "lng": lng,
        "built_year": building.get("built_year"),
        "structure": building.get("structure"),
        "building_floors": building.get("building_floors"),
        "is_active": bool(building.get("is_active", True)),
        "units_count": building.get("units_count"),
        "active_units_count": building.get("active_units_count"),
        "source_sites": source_sites,
        "building_names": [
            {"source_site": n["source_site"], "name": n["name"]} for n in names
        ],
        "feature_categories": satisfiable_codes_from_categories(sorted(building_codes)),
        "min_daily_rent": min_daily,
        "max_daily_rent": max_daily,
        "min_plan_total": min_total,
        "min_plan_label": min_label,
        "min_walk_minutes": min_walk,
        "thumbnail_url": thumbnail,
        "has_campaign": has_campaign,
        "access_summary": access_seen,
        "station_summary": ", ".join(station_list),
        "shortlist_status": (shortlist or {}).get("status"),
        "shortlist_comment": (shortlist or {}).get("comment"),
        "shortlist_updated_at": (shortlist or {}).get("updated_at"),
        "units": unit_results,
    }


def _ordered_building_rows(conn, building_ids: set[int]) -> list[dict[str, Any]]:
    """建物行をキャッシュ列の順序(is_active DESC → 最安日額 ASC → id)で返す。"""
    rows: list[dict[str, Any]] = []
    ids = sorted(building_ids)
    for start in range(0, len(ids), _CHILD_IN_CHUNK):
        chunk = ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        rows.extend(
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM buildings WHERE id IN ({ph})", chunk
            )
        )
    rows.sort(key=_building_sort_key)
    return rows


def _building_name_map(
    conn, building_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for start in range(0, len(building_ids), _CHILD_IN_CHUNK):
        chunk = building_ids[start : start + _CHILD_IN_CHUNK]
        ph = ",".join("%s" for _ in chunk)
        for row in conn.execute(
            f"SELECT building_id, source_site, name FROM building_names"
            f" WHERE building_id IN ({ph}) ORDER BY building_id, source_site",
            chunk,
        ):
            out.setdefault(int(row["building_id"]), []).append(dict(row))
    return out


def _matching_room_map_with_saved_carry(
    conn, params: dict[str, Any]
) -> tuple[dict[int, int], set[int], list[int], dict[int, float] | None]:
    """検索の共通経路: (部屋→建物 map, 建物saved貫通集合, 条件一致部屋 id 列, 意味距離).

    - saved_only の建物意味論: 「建物saved OR 条件一致部屋に saved≥1」(U1)。
      部屋スコープの saved 絞り(_search_where の s.status='saved')は外して
      部屋集合を取り、建物単位で判定し直す(units="matching" には建物saved の
      建物の条件一致部屋も載る)。
    - 建物saved の建物は可視性を貫通して結果に残す(部屋の inactive 可視化
      ルールと対称・U3)。部屋スコープ条件(features/総額等)は建物行に適用
      できないため、県条件のみ buildings 行で照合する。
    - natural_query(PG移行 Phase 7): クエリ embedding を RETRIEVAL_QUERY で
      取得し、部屋単位の意味距離を計算。embedding 未カバー(model 不一致含む)
      の部屋は結果から除外する(スコア計算不能のため)。距離は建物代表選択と
      ソート(iter_search_buildings)で消費する。
    """
    saved_only = bool(params.get("saved_only"))
    room_params = dict(params)
    if saved_only:
        room_params["saved_only"] = False
    matching_ids = _matching_room_ids(conn, room_params)
    matching_map = _room_building_map(conn, matching_ids) if matching_ids else {}

    distances: dict[int, float] | None = None
    if params.get("natural_query"):
        query_vec = embed_query_cached(str(params["natural_query"]))
        distances = _semantic_room_distances(conn, matching_ids, query_vec)
        matching_map = {
            pid: bid for pid, bid in matching_map.items() if pid in distances
        }

    pref = params.get("prefecture_name")
    carry_sql = (
        "SELECT b.id FROM buildings b JOIN building_shortlists sl"
        " ON sl.building_id = b.id WHERE sl.status = 'saved'"
    )
    carry_q: list[Any] = []
    if pref:
        carry_sql += " AND b.prefecture_name = %s"
        carry_q.append(pref)
    carry = {
        int(r["id"]) for r in conn.execute(carry_sql, carry_q)
    }

    if saved_only:
        keep = carry | _saved_room_building_ids(conn, matching_ids)
        matching_map = {pid: bid for pid, bid in matching_map.items() if bid in keep}
        carry &= keep
    return matching_map, carry, matching_ids, distances


def iter_search_buildings(
    params: dict[str, Any] | None = None,
    *,
    state: dict[str, Any] | None = None,
    units: str = "all",
):
    """建物単位の検索ジェネレータ(§6.1)。limit の単位は建物数。

    state に走査の終わり方を書き戻す(search と同じ契約・候補単位は建物)。
    """
    if units not in ("all", "matching"):
        raise ValueError(f"unknown units={units!r} (expected 'all' / 'matching')")
    params = params or {}
    limit = int(params.get("limit") or 50)

    with open_connection() as conn:
        matching_map, carry, matching_ids, distances = (
            _matching_room_map_with_saved_carry(conn, params)
        )
        if not matching_map and not carry:
            if state is not None:
                state["candidates_exhausted"] = True
            return

        # 建物順序はキャッシュ列で確定(Python ソート)→ limit は建物数に効く
        ordered = _ordered_building_rows(conn, set(matching_map.values()) | carry)
        if distances:
            # 意味距離ソート(PG移行 Phase 7): 建物代表距離 = 建物内条件一致
            # 部屋の距離最小値(embedding 単位は部屋のため)。建物saved 貫通
            # (carry・embedding 無し)は inf で最後尾へ。タイブレークは
            # 既定の _building_sort_key。
            building_dist: dict[int, float] = {}
            for pid, bid in matching_map.items():
                d = distances[pid]
                if bid not in building_dist or d < building_dist[bid]:
                    building_dist[bid] = d
            ordered.sort(
                key=lambda b: (
                    building_dist.get(int(b["id"]), float("inf")),
                    _building_sort_key(b),
                )
            )
        target_buildings = [b for b in ordered][:limit] if limit else ordered
        exhausted = len(ordered) <= len(target_buildings)
        remaining = [int(b["id"]) for b in target_buildings]

        name_map = _building_name_map(conn, remaining)
        shortlist_map = _building_shortlist_map(conn, remaining)

        # units="matching": 建物ごとの条件一致部屋 / "all": 建物ごとの可視部屋
        if units == "matching":
            per_building: dict[int, list[int]] = {}
            for pid, bid in matching_map.items():
                per_building.setdefault(bid, []).append(pid)
            for bid in per_building:
                per_building[bid].sort()
        else:
            per_building = _visible_room_ids_of_buildings(conn, remaining)

        all_room_ids = sorted({p for v in per_building.values() for p in v})
        assembled, categories = _assemble_rooms(conn, all_room_ids)

        for b in target_buildings:
            bid = int(b["id"])
            room_ids = per_building.get(bid, [])
            if not room_ids and bid not in carry:
                # 可視/条件一致部屋が 1 つも無い建物は出さない
                # (建物saved は可視性を貫通・units=[] で配信)
                continue
            unit_results = [assembled[p] for p in room_ids if p in assembled]
            yield _building_dict(
                b,
                name_map.get(bid, []),
                unit_results,
                categories,
                shortlist=shortlist_map.get(bid),
            )
        if state is not None:
            state["candidates_exhausted"] = exhausted


def search_buildings(
    params: dict[str, Any] | None = None,
    *,
    state: dict[str, Any] | None = None,
    units: str = "all",
) -> list[dict[str, Any]]:
    return list(iter_search_buildings(params, state=state, units=units))


def count_buildings(params: dict[str, Any] | None = None) -> int:
    """検索条件に一致する部屋を持つ建物数(§6.1 meta.total 用).

    建物saved の貫通分(saved_only に関わらず)も含む(iter_search_buildings
    の建物集合と同一の数え方)。
    """
    params = params or {}
    with open_connection() as conn:
        matching_map, carry, _, _ = _matching_room_map_with_saved_carry(conn, params)
        return len(set(matching_map.values()) | carry)


def get_building_detail(building_id: int) -> dict[str, Any] | None:
    """建物 1 件の詳細(get_building_detail MCP ツールの実体)。"""
    with open_connection() as conn:
        row = conn.execute(
            "SELECT * FROM buildings WHERE id = %s", (building_id,)
        ).fetchone()
        if row is None:
            return None
        building = dict(row)
        names = [
            dict(r)
            for r in conn.execute(
                "SELECT source_site, name FROM building_names WHERE building_id = %s"
                " ORDER BY source_site",
                (building_id,),
            )
        ]
        shortlist_map = _building_shortlist_map(conn, [building_id])
        room_map = _visible_room_ids_of_buildings(conn, [building_id])
        room_ids = room_map.get(building_id, [])
        assembled, categories = _assemble_rooms(conn, room_ids)
        return _building_dict(
            building,
            names,
            [assembled[p] for p in room_ids if p in assembled],
            categories,
            shortlist=shortlist_map.get(building_id),
        )


def update_building_shortlist(
    building_id: int,
    status: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """建物ショートリスト状態を更新する(当面 status='saved'/'none' のみ).

    部屋の update_shortlist(store.queries.detail)と対称。buildings.id は
    数値一意のため id 解決は不要(未検出は {"ok": False})。書込本体は
    Repository.update_building_shortlist。
    """
    try:
        bid = int(building_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid building_id"}
    repo = _repo()
    with open_connection() as conn:
        row = conn.execute("SELECT id FROM buildings WHERE id = %s", (bid,)).fetchone()
    if row is None:
        return {"ok": False, "error": "not found"}
    repo.update_building_shortlist(bid, status, comment)
    return {"ok": True, "building_id": bid, "status": status}


def building_geojson_feature(building: dict[str, Any]) -> dict[str, Any] | None:
    """建物 dict → GeoJSON Feature(座標無しはスキップ・部屋と同一規則)。"""
    lat, lng = building.get("lat"), building.get("lng")
    if lat is None or lng is None:
        return None
    props = {k: v for k, v in building.items() if k not in ("lat", "lng")}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": props,
    }


def iter_geojson_building_features(params: dict[str, Any] | None = None):
    """建物 GeoJSON Feature のジェネレータ(/api/buildings/geojson 系の実体)。"""
    for building in iter_search_buildings(params, units="all"):
        feature = building_geojson_feature(building)
        if feature is not None:
            # DB 行由来の datetime/date は isoformat へ(pydantic 非経由の
            # json.dumps 直列化に備えた Phase 6c の窓口)
            yield iso_jsonable(feature)
