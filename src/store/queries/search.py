"""物件検索系クエリ: 検索 / 件数 / PK 一括取得."""

from __future__ import annotations

from typing import Any, Sequence

from store.queries._common import (
    _CHILD_IN_CHUNK,
    _fetch_child_rows_by_property,
    _property_list_sql,
    _property_row_to_result,
    _repo,
)


def _search_where(params: dict[str, Any]) -> tuple[list[str], list[Any]]:
    """search_properties / count_properties 共通の WHERE 句を構築する.

    可視性 (is_active / shortlist 状態) と絞り込み条件 (県 / ソース / 面積 /
    saved_only / exclude_hidden) を SQL 句へ変換する。max_walk / required_features /
    max_monthly は Python 側の post filter のためここには含めない。
    """
    prefecture_name = params.get("prefecture_name")
    source_sites = params.get("source_sites")
    if isinstance(source_sites, str):
        source_sites = [s.strip() for s in source_sites.split(",") if s.strip()]
    min_area = params.get("min_area_m2")
    saved_only = params.get("saved_only", False)
    exclude_hidden = params.get("exclude_hidden", True)

    # Shortlisted properties stay visible even when the source site drops
    # them (is_active = 0) — the FE/MCP/AI mark them as inactive instead.
    clauses = ["(p.is_active = 1 OR s.status IN ('saved', 'hide', 'reject'))"]
    qparams: list[Any] = []
    if prefecture_name:
        clauses.append("p.prefecture_name = ?")
        qparams.append(prefecture_name)
    if source_sites:
        ph = ",".join("?" for _ in source_sites)
        clauses.append(f"p.source_site IN ({ph})")
        qparams.extend(source_sites)
    if min_area is not None:
        clauses.append("p.area_m2 >= ?")
        qparams.append(min_area)
    if saved_only:
        clauses.append("s.status = 'saved'")
    elif exclude_hidden:
        clauses.append("(s.status IS NULL OR s.status NOT IN ('hide', 'reject'))")
    return clauses, qparams


def iter_search_properties(params: dict[str, Any] | None = None):
    """search_properties のジェネレータ版。検索結果を 1 物件ずつ yield する.

    WHERE 句 / over-fetch (fetch_limit) / max_walk 事前フィルタ /
    required_features 集合判定 / max_monthly 後フィルタ / limit 到達で停止 /
    ORDER BY / 戻り値の順序と内容は search_properties と完全に同一。
    子テーブルの取得は物件ごとの個別クエリ(N+1)を避けつつメモリと TTFB を
    押さえるため、候補を _CHILD_IN_CHUNK 件ずつのチャンクに分けて IN 一括取得する。
    接続はジェネレータ内で開き、途中で破棄されても finally で閉じる。
    """
    params = params or {}
    max_walk = params.get("max_walk_minutes")
    required_features = params.get("required_features")
    if isinstance(required_features, str):
        required_features = [x.strip() for x in required_features.split(",") if x.strip()]
    limit = int(params.get("limit") or 50)
    max_monthly = params.get("max_monthly_total_yen")

    clauses, where_params = _search_where(params)

    sql = _property_list_sql(f"""
        WHERE {' AND '.join(clauses)}
        ORDER BY p.is_active DESC, p.catalog_rent_per_day_yen IS NULL, p.catalog_rent_per_day_yen ASC
        LIMIT ?
    """)
    # over-fetch for post filters
    fetch_limit = max(limit * 20, 500) if (max_walk or required_features or max_monthly) else limit
    qparams = [*where_params, fetch_limit]

    repo = _repo()
    conn = repo.connect()
    try:
        rows = [dict(r) for r in conn.execute(sql, qparams)]

        # max_walk は SQL 側の min_walk_minutes だけで判定できるため先に絞る
        candidates = [
            row
            for row in rows
            if not (
                max_walk is not None
                and row.get("min_walk_minutes") is not None
                and row["min_walk_minutes"] > max_walk
            )
        ]

        emitted = 0
        # 候補全件分の子テーブルを先に取得するとメモリが膨らむため、
        # チャンクごとに IN 一括取得 → チャンク内の行を順に処理して yield する
        for start in range(0, len(candidates), _CHILD_IN_CHUNK):
            chunk = candidates[start : start + _CHILD_IN_CHUNK]
            pids = [row["id"] for row in chunk]

            access_map = _fetch_child_rows_by_property(
                conn,
                "SELECT property_id, line_name, station_name, walk_minutes "
                "FROM property_accesses WHERE property_id IN ({placeholders}) "
                "ORDER BY property_id, sort_order",
                pids,
            )
            image_map = _fetch_child_rows_by_property(
                conn,
                "SELECT property_id, image_url, image_type, sort_order "
                "FROM property_images WHERE property_id IN ({placeholders}) "
                "ORDER BY property_id, sort_order",
                pids,
            )
            plan_map = _fetch_child_rows_by_property(
                conn,
                "SELECT * FROM price_plans WHERE property_id IN ({placeholders}) "
                "ORDER BY property_id, duration_min_days",
                pids,
            )
            campaign_map = _fetch_child_rows_by_property(
                conn,
                "SELECT * FROM campaigns WHERE property_id IN ({placeholders}) "
                "ORDER BY property_id, id",
                pids,
            )
            feature_map = (
                _fetch_child_rows_by_property(
                    conn,
                    "SELECT property_id, feature_name FROM property_features "
                    "WHERE property_id IN ({placeholders})",
                    pids,
                )
                if required_features
                else {}
            )

            for row in chunk:
                pid = row["id"]
                if required_features:
                    feats = {r["feature_name"] for r in feature_map.get(pid, [])}
                    if not all(f in feats for f in required_features):
                        continue

                result = _property_row_to_result(
                    row,
                    access_map.get(pid, []),
                    image_map.get(pid, []),
                    plan_map.get(pid, []),
                    campaign_map.get(pid, []),
                )
                if (
                    max_monthly is not None
                    and result.get("min_plan_total") is not None
                    and result["min_plan_total"] > max_monthly
                ):
                    continue
                yield result
                emitted += 1
                if emitted >= limit:
                    return
    finally:
        conn.close()


def search_properties(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """検索条件に一致する物件リストを返す (iter_search_properties の全件取得).

    limit の既定差は呼び出し層の契約 (意図的な違い):
    - MCP (mcp_server.search_properties): 既定 50 (エージェント UX 向けの絞り込み一覧)
    - API 全件取得系 (/api/geojson, export_geojson / export_kml の既定): 10000
    本関数自身の既定 (params に limit 無し) は 50。上限値 (10000) は双方共通。
    """
    return list(iter_search_properties(params))


def count_properties(params: dict[str, Any] | None = None) -> int:
    """search_properties と同じ可視性 / 絞り込み条件での物件件数を返す.

    NDJSON ストリーム (/api/geojson/stream) の meta 行で総件数を先に通知するための
    軽量 COUNT。ORDER BY / LIMIT は付けない。max_walk / required_features /
    max_monthly は post filter のため件数に反映されない点に注意。
    """
    params = params or {}
    clauses, qparams = _search_where(params)
    repo = _repo()
    conn = repo.connect()
    try:
        sql = (
            "SELECT COUNT(*) FROM properties p "
            "LEFT JOIN shortlists s ON s.property_id = p.id "
            f"WHERE {' AND '.join(clauses)}"
        )
        row = conn.execute(sql, qparams).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def get_properties_by_ids(ids: Sequence[int]) -> list[dict[str, Any]]:
    """PK id の完全一致で物件を取得する (FEエクスポート用).

    search_properties と異なり is_active や shortlist 状態による可視性の
    絞り込みを行わず、座標の有無に関係なく指定 id をすべて返す。
    戻り値の順序は入力 ids の順を維持する (不明 id はスキップ)。
    """
    seen: set[int] = set()
    unique_ids = [i for i in (int(x) for x in ids) if not (i in seen or seen.add(i))]
    if not unique_ids:
        return []

    repo = _repo()
    conn = repo.connect()
    try:
        rows_by_id: dict[int, dict[str, Any]] = {}
        for start in range(0, len(unique_ids), _CHILD_IN_CHUNK):
            chunk = unique_ids[start : start + _CHILD_IN_CHUNK]
            ph = ",".join("?" for _ in chunk)
            sql = _property_list_sql(f"WHERE p.id IN ({ph})")
            for row in conn.execute(sql, chunk):
                rows_by_id[row["id"]] = dict(row)

        pids = list(rows_by_id.keys())
        access_map = _fetch_child_rows_by_property(
            conn,
            "SELECT property_id, line_name, station_name, walk_minutes "
            "FROM property_accesses WHERE property_id IN ({placeholders}) "
            "ORDER BY property_id, sort_order",
            pids,
        )
        image_map = _fetch_child_rows_by_property(
            conn,
            "SELECT property_id, image_url, image_type, sort_order "
            "FROM property_images WHERE property_id IN ({placeholders}) "
            "ORDER BY property_id, sort_order",
            pids,
        )
        plan_map = _fetch_child_rows_by_property(
            conn,
            "SELECT * FROM price_plans WHERE property_id IN ({placeholders}) "
            "ORDER BY property_id, duration_min_days",
            pids,
        )
        campaign_map = _fetch_child_rows_by_property(
            conn,
            "SELECT * FROM campaigns WHERE property_id IN ({placeholders}) "
            "ORDER BY property_id, id",
            pids,
        )

        results: list[dict[str, Any]] = []
        for pid in unique_ids:
            row = rows_by_id.get(pid)
            if row is None:
                continue
            results.append(
                _property_row_to_result(
                    row,
                    access_map.get(pid, []),
                    image_map.get(pid, []),
                    plan_map.get(pid, []),
                    campaign_map.get(pid, []),
                )
            )
        return results
    finally:
        conn.close()
